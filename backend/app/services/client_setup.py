"""Client setup use-cases: create a client with its year, periods and ledgers; add/deactivate ledgers;
opening balances.

Every function takes a SQLAlchemy Connection and never commits: the caller (API request, CLI, test) owns the
transaction. Each operation runs inside a SAVEPOINT, so a failure undoes the operation's own partial work even
when the caller keeps its transaction open. Rules live in the engine; this file reads, writes and logs.
"""

import calendar
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import Connection, text

from app.db import repositories as repo
from app.engine import reports
from app.engine.coa_templates import BUSINESS_TYPES, ENTITY_TYPES, default_ledgers
from app.engine.models import OpeningBalance
from app.engine.money import MoneyError, format_inr, parse_amount
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

GST_TYPES = ("regular", "composition", "unregistered")
ZERO = parse_amount("0")


@dataclass(frozen=True)
class ClientProfile:
    name: str
    entity_type: str  # proprietorship | partnership | llp | company
    business_type: str  # trading | service | manufacturing
    gst_type: str  # regular | composition | unregistered
    legal_name: str | None = None
    pan: str | None = None
    state_code: str | None = None
    books_begin_date: date | None = None


@dataclass(frozen=True)
class CreatedClient:
    client_id: uuid.UUID
    financial_year_id: uuid.UUID
    ledger_ids: dict[str, uuid.UUID]  # ledger name -> id


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _invalid(message: str, code: str = "invalid_profile") -> ServiceError:
    return ServiceError(code, message)


def _month_periods(fy_start: date) -> list[tuple[date, date]]:
    periods = []
    for i in range(12):
        month = fy_start.month + i
        year = fy_start.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        periods.append((date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])))
    return periods


# =============================================================================================== create_client


def create_client(
    conn: Connection,
    profile: ClientProfile,
    *,
    fy_start: date,
    actor: str,
    proprietor_name: str | None = None,
    partners: Sequence[str] | None = None,
) -> CreatedClient:
    """Create the client, its first financial year, 12 open monthly periods and the template ledgers, with audit
    rows, all-or-nothing."""
    actor = require_actor(actor)
    name = (profile.name or "").strip()
    if not name:
        raise _invalid("The client name is required.")
    if profile.gst_type not in GST_TYPES:
        raise _invalid(f"Unknown GST type {profile.gst_type!r}; use one of {', '.join(GST_TYPES)}.")
    if (fy_start.month, fy_start.day) != (4, 1):
        raise _invalid(f"A financial year must start on 1 April (got {_fmt(fy_start)}).")
    try:
        template = default_ledgers(
            profile.entity_type, profile.business_type, proprietor_name=proprietor_name, partners=partners
        )
    except ValueError as problem:
        raise _invalid(str(problem)) from problem

    client_id, fy_id = uuid.uuid4(), uuid.uuid4()
    fy_end = date(fy_start.year + 1, 3, 31)
    periods = [(uuid.uuid4(), start, end) for start, end in _month_periods(fy_start)]

    with conn.begin_nested():
        group_ids = repo.system_group_ids(conn)
        ledger_ids = {x.name: uuid.uuid4() for x in template}

        conn.execute(
            text(
                "INSERT INTO clients (id, name, legal_name, entity_type, business_type, pan, state_code, gst_type, "
                "books_begin_date) VALUES (:id, :name, :legal_name, :entity_type, :business_type, :pan, "
                ":state_code, :gst_type, :books_begin_date)"
            ),
            {**asdict(profile), "id": client_id, "name": name},
        )
        conn.execute(
            text("INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (:id, :c, :s, :e)"),
            {"id": fy_id, "c": client_id, "s": fy_start, "e": fy_end},
        )
        conn.execute(
            text(
                "INSERT INTO periods (id, client_id, financial_year_id, period_start, period_end) "
                "VALUES (:id, :c, :fy, :s, :e)"
            ),
            [{"id": pid, "c": client_id, "fy": fy_id, "s": s, "e": e} for pid, s, e in periods],
        )
        conn.execute(
            text("INSERT INTO ledgers (id, client_id, group_id, name) VALUES (:id, :c, :g, :n)"),
            [{"id": ledger_ids[x.name], "c": client_id, "g": group_ids[x.group_code], "n": x.name} for x in template],
        )

        entries = [
            AuditEntry(client_id, actor, "create", "client", client_id,
                       new={**asdict(profile), "name": name, "proprietor_name": proprietor_name, "partners": list(partners or [])}),
            AuditEntry(client_id, actor, "create", "financial_year", fy_id, new={"start_date": fy_start, "end_date": fy_end}),
        ]
        entries += [
            AuditEntry(client_id, actor, "create", "period", pid, new={"period_start": s, "period_end": e, "status": "open"})
            for pid, s, e in periods
        ]
        entries += [
            AuditEntry(client_id, actor, "create", "ledger", ledger_ids[x.name], new={"name": x.name, "group_code": x.group_code})
            for x in template
        ]
        audit.log_many(conn, entries)
    return CreatedClient(client_id, fy_id, ledger_ids)


# =================================================================================================== add_ledger


def add_ledger(conn: Connection, client_id: object, name: str, group_code: str, *, actor: str) -> uuid.UUID:
    actor = require_actor(actor)
    name = (name or "").strip()
    if not name:
        raise ServiceError("invalid_ledger", "The ledger name is required.")
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    with conn.begin_nested():
        group_id = repo.find_group_id(conn, client_id, group_code)
        if group_id is None:
            raise ServiceError("not_found", f"Account group '{group_code}' does not exist for this client.")
        if repo.ledger_name_exists(conn, client_id, name):
            raise ServiceError("duplicate_ledger", f"A ledger named '{name}' already exists for this client.")
        ledger_id = uuid.uuid4()
        conn.execute(
            text("INSERT INTO ledgers (id, client_id, group_id, name) VALUES (:id, :c, :g, :n)"),
            {"id": ledger_id, "c": client_id, "g": group_id, "n": name},
        )
        audit.log(conn, AuditEntry(client_id, actor, "create", "ledger", ledger_id, new={"name": name, "group_code": group_code}))
    return ledger_id


# =========================================================================================== deactivate_ledger


def deactivate_ledger(conn: Connection, client_id: object, ledger_id: object, *, actor: str) -> None:
    """Make a ledger inactive. Refused while it has a closing balance (latest financial year) or is used in a
    draft/approved voucher: history stays readable, nothing is hidden."""
    actor = require_actor(actor)
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    if not ledger.is_active:
        raise ServiceError("ledger_inactive", f"Ledger '{ledger.name}' is already inactive.")

    year = repo.latest_financial_year(conn, client_id)
    if year is not None:
        opening = repo.openings_for_year(conn, client_id, year.id).get(ledger_id, OpeningBalance(ZERO, ZERO))
        lines = repo.lines_touching_ledger(conn, client_id, ledger_id, year.id)
        closing = reports.ledger_statement(ledger, opening, lines, year.start_date, year.end_date).closing
        if closing.side is not None:
            raise ServiceError(
                "ledger_in_use",
                f"Ledger '{ledger.name}' cannot be deactivated: it has a closing balance of "
                f"{format_inr(closing.amount)} {closing.side}.",
            )
    open_vouchers = repo.open_voucher_count_for_ledger(conn, client_id, ledger_id)
    if open_vouchers:
        raise ServiceError(
            "ledger_in_use",
            f"Ledger '{ledger.name}' cannot be deactivated: it is used in {open_vouchers} draft or approved voucher(s).",
        )
    with conn.begin_nested():
        conn.execute(text("UPDATE ledgers SET is_active = false WHERE id = :id"), {"id": ledger_id})
        audit.log(conn, AuditEntry(client_id, actor, "deactivate", "ledger", ledger_id,
                                   old={"name": ledger.name, "is_active": True}, new={"name": ledger.name, "is_active": False}))


# ======================================================================================= set_opening_balance


def _amount_or_zero(raw: object):
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return ZERO
    try:
        return parse_amount(raw)
    except MoneyError as problem:
        raise ServiceError("invalid_amount", f"Opening balance: {problem}.") from problem


def set_opening_balance(
    conn: Connection,
    client_id: object,
    financial_year_id: object,
    ledger_id: object,
    debit: object,
    credit: object,
    *,
    actor: str,
) -> None:
    """Set (replace) a ledger's opening balance for a financial year; both sides empty removes it.

    Allowed only until the first voucher of that year is posted. Total debit vs credit is checked separately
    (opening_balance_difference) and blocks posting until equal.
    """
    actor = require_actor(actor)
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    if repo.get_financial_year(conn, client_id, financial_year_id) is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    new_debit, new_credit = _amount_or_zero(debit), _amount_or_zero(credit)
    if new_debit > 0 and new_credit > 0:
        raise ServiceError("invalid_amount", "Enter either a Debit or a Credit opening balance, not both.")
    if repo.posted_voucher_exists(conn, client_id, financial_year_id):
        raise ServiceError(
            "opening_locked",
            "Opening balances cannot be changed after vouchers have been posted for this financial year.",
        )

    old = repo.openings_for_year(conn, client_id, financial_year_id).get(ledger_id)
    old_data = None if old is None else {"debit": f"{old.debit:.2f}", "credit": f"{old.credit:.2f}"}
    new_data = {"debit": f"{new_debit:.2f}", "credit": f"{new_credit:.2f}"}
    with conn.begin_nested():
        if new_debit == 0 and new_credit == 0:
            conn.execute(
                text("DELETE FROM opening_balances WHERE ledger_id = :l AND financial_year_id = :fy"),
                {"l": ledger_id, "fy": financial_year_id},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) "
                    "VALUES (:c, :l, :fy, :d, :cr) ON CONFLICT (ledger_id, financial_year_id) "
                    "DO UPDATE SET debit = EXCLUDED.debit, credit = EXCLUDED.credit"
                ),
                {"c": client_id, "l": ledger_id, "fy": financial_year_id, "d": new_debit, "cr": new_credit},
            )
        audit.log(conn, AuditEntry(client_id, actor, "set_opening_balance", "opening_balance", ledger_id,
                                   old=old_data, new=new_data))


def opening_balance_difference(conn: Connection, client_id: object, financial_year_id: object) -> reports.OpeningCheck:
    """Total opening debits vs credits of the year. Posting stays blocked until the difference is nil."""
    if repo.get_financial_year(conn, client_id, financial_year_id) is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return reports.check_openings(repo.openings_for_year(conn, client_id, financial_year_id).values())


__all__ = [
    "BUSINESS_TYPES", "ENTITY_TYPES", "ClientProfile", "CreatedClient", "add_ledger", "create_client",
    "deactivate_ledger", "opening_balance_difference", "set_opening_balance",
]
