"""Read-only listings for the API: clients, groups, ledgers with balances, vouchers, opening balances, audit log.

No accounting maths here: balances come from the engine's Trial Balance (via services.reports); this file only
loads and filters. Services take a SQLAlchemy Connection and never commit.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.db import repositories as repo
from app.engine import reports as engine
from app.engine.models import Balance, OpeningBalance
from app.engine.money import parse_amount
from app.services import reports
from app.services.errors import ServiceError

CENTS = Decimal("0.01")
MAX_LIMIT = 500


def require_client(conn: Connection, client_id: object) -> None:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


# ============================================================================================== clients


def list_clients(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, name, legal_name, entity_type, business_type, gst_type, is_active FROM clients "
            "ORDER BY lower(name), created_at"
        )
    )
    keys = ("id", "name", "legal_name", "entity_type", "business_type", "gst_type", "is_active")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def get_client(conn: Connection, client_id: object) -> dict:
    row = conn.execute(
        text(
            "SELECT id, name, legal_name, entity_type, business_type, gst_type, is_active, pan, state_code, "
            "books_begin_date FROM clients WHERE id = :c"
        ),
        {"c": client_id},
    ).first()
    if row is None:
        raise ServiceError("not_found", "Client not found.")
    keys = ("id", "name", "legal_name", "entity_type", "business_type", "gst_type", "is_active", "pan",
            "state_code", "books_begin_date")
    client = dict(zip(keys, row, strict=True))
    years = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c ORDER BY start_date"),
        {"c": client_id},
    )
    client["financial_years"] = [{"id": r[0], "start_date": r[1], "end_date": r[2]} for r in years]
    return client


# =============================================================================================== groups


def groups_tree(conn: Connection, client_id: object) -> list[dict]:
    """System groups plus this client's own groups, nested by parent. Top level in the standard display order."""
    require_client(conn, client_id)
    rows = conn.execute(
        text(
            "SELECT g.code, g.name, g.nature, g.report, g.is_system, p.code FROM account_groups g "
            "LEFT JOIN account_groups p ON p.id = g.parent_id WHERE g.client_id IS NULL OR g.client_id = :c"
        ),
        {"c": client_id},
    )
    nodes = {r[0]: {"code": r[0], "name": r[1], "nature": r[2], "report": r[3], "is_system": r[4], "children": []}
             for r in rows}
    parents = {r_code: None for r_code in nodes}
    for code, parent_code in conn.execute(
        text(
            "SELECT g.code, p.code FROM account_groups g JOIN account_groups p ON p.id = g.parent_id "
            "WHERE g.client_id IS NULL OR g.client_id = :c"
        ),
        {"c": client_id},
    ):
        parents[code] = parent_code
    roots = []
    for code, node in nodes.items():
        parent = parents[code]
        (nodes[parent]["children"] if parent in nodes else roots).append(node)

    def order(node: dict) -> tuple[int, str]:
        if node["code"] in engine.PRIMARY_ORDER:
            return (engine.PRIMARY_ORDER.index(node["code"]), "")
        return (len(engine.PRIMARY_ORDER), node["name"].lower())

    roots.sort(key=order)
    for node in nodes.values():
        node["children"].sort(key=lambda n: n["name"].lower())
    return roots


# ============================================================================================== ledgers


@dataclass(frozen=True)
class LedgerListing:
    id: uuid.UUID
    name: str
    group_code: str
    group_name: str
    group_path: tuple[str, ...]
    is_active: bool
    balance: Balance


def _default_as_on(conn: Connection, client_id: object) -> date:
    today = date.today()
    if repo.financial_year_for_date(conn, client_id, today) is not None:
        return today
    latest = repo.latest_financial_year(conn, client_id)
    if latest is None:
        raise ServiceError("no_financial_year", "This client has no financial year.")
    return latest.end_date


def ledgers_with_balance(conn: Connection, client_id: object, as_on: date | None = None) -> list[LedgerListing]:
    """Every ledger of the client with its group and closing balance as on a date (engine Trial Balance)."""
    require_client(conn, client_id)
    on = as_on or _default_as_on(conn, client_id)
    trial = reports.trial_balance(conn, client_id, on)
    shown = {row.ledger_id: row for section in trial.sections for row in section.rows}
    out = []
    for ledger in repo.ledgers_of_client(conn, client_id):
        row = shown[ledger.id]
        if row.debit > 0:
            balance = Balance(row.debit, "Dr")
        elif row.credit > 0:
            balance = Balance(row.credit, "Cr")
        else:
            balance = Balance(parse_amount("0"), None)
        out.append(LedgerListing(ledger.id, ledger.name, ledger.group_code, row.group_path[-1], row.group_path,
                                 ledger.is_active, balance))
    return sorted(out, key=lambda x: (x.group_path, x.name.lower()))


def opening_balances_report(conn: Connection, client_id: object, financial_year_id: object) -> dict:
    if repo.get_financial_year(conn, client_id, financial_year_id) is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    rows = conn.execute(
        text(
            "SELECT o.ledger_id, l.name, o.debit, o.credit FROM opening_balances o JOIN ledgers l ON l.id = o.ledger_id "
            "WHERE o.client_id = :c AND o.financial_year_id = :fy ORDER BY lower(l.name)"
        ),
        {"c": client_id, "fy": financial_year_id},
    ).all()
    check = engine.check_openings(
        OpeningBalance(debit.quantize(CENTS), credit.quantize(CENTS)) for _, _, debit, credit in rows
    )
    return {
        "rows": [
            {"ledger_id": r[0], "ledger_name": r[1], "debit": r[2].quantize(CENTS), "credit": r[3].quantize(CENTS)}
            for r in rows
        ],
        "check": check,
    }


# ============================================================================================== vouchers


def list_vouchers(
    conn: Connection,
    client_id: object,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    voucher_type: str | None = None,
    status: str | None = None,
    ledger_id: object | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """(items, total_count): vouchers of the client, filtered, by date then number. `total` of an item is its total
    debit; date filters are inclusive; ledger_id keeps vouchers that have a line for that ledger."""
    require_client(conn, client_id)
    limit = max(1, min(limit, MAX_LIMIT))
    where = (
        "FROM vouchers v WHERE v.client_id = :c "
        "AND (CAST(:d_from AS date) IS NULL OR v.voucher_date >= :d_from) "
        "AND (CAST(:d_to AS date) IS NULL OR v.voucher_date <= :d_to) "
        "AND (CAST(:vtype AS text) IS NULL OR v.voucher_type = :vtype) "
        "AND (CAST(:status AS text) IS NULL OR v.status = :status) "
        "AND (CAST(:ledger AS uuid) IS NULL OR EXISTS ("
        "SELECT 1 FROM voucher_lines vl WHERE vl.voucher_id = v.id AND vl.ledger_id = :ledger))"
    )
    params = {"c": client_id, "d_from": date_from, "d_to": date_to, "vtype": voucher_type, "status": status,
              "ledger": ledger_id}
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_number, v.voucher_type, v.voucher_date, v.narration, v.reference_no, v.status, "
            "COALESCE((SELECT sum(vl.debit) FROM voucher_lines vl WHERE vl.voucher_id = v.id), 0) " + where +
            " ORDER BY v.voucher_date, v.voucher_number NULLS LAST, v.created_at LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    total = conn.execute(text("SELECT count(*) " + where), params).scalar_one()
    keys = ("id", "voucher_number", "voucher_type", "voucher_date", "narration", "reference_no", "status", "total")
    items = [dict(zip(keys, r, strict=True)) for r in rows]
    for item in items:
        item["total"] = item["total"].quantize(CENTS)
    return items, total


# =============================================================================================== audit log


def audit_entries(
    conn: Connection, client_id: object, *, entity: str | None = None, entity_id: object | None = None, limit: int = 100
) -> list[dict]:
    """Newest first."""
    require_client(conn, client_id)
    limit = max(1, min(limit, MAX_LIMIT))
    rows = conn.execute(
        text(
            "SELECT id, actor, action, entity, entity_id, old_data, new_data, created_at FROM audit_log "
            "WHERE client_id = :c AND (CAST(:entity AS text) IS NULL OR entity = :entity) "
            "AND (CAST(:eid AS uuid) IS NULL OR entity_id = :eid) ORDER BY id DESC LIMIT :limit"
        ),
        {"c": client_id, "entity": entity, "eid": entity_id, "limit": limit},
    )
    keys = ("id", "actor", "action", "entity", "entity_id", "old_data", "new_data", "created_at")
    out = []
    for r in rows:
        item = dict(zip(keys, r, strict=True))
        for k in ("old_data", "new_data"):  # jsonb normally arrives as a dict already
            if isinstance(item[k], str):
                item[k] = json.loads(item[k])
        out.append(item)
    return out
