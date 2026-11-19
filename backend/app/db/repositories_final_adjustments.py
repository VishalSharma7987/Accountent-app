"""SQL of the Phase 6 package A: ledger roles, partners, partner deed terms, adjustment entries. Reads and plain writes only;
the rules live in engine/final_adjustments.py and the audit log is written by the service."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.final_adjustments import LedgerInfo

CENTS = Decimal("0.01")


def client_entity(conn: Connection, client_id: Any) -> str | None:
    row = conn.execute(text("SELECT entity_type FROM clients WHERE id = :c"), {"c": client_id}).first()
    return row[0] if row else None


def ledger_infos(conn: Connection, client_id: Any) -> dict[Any, LedgerInfo]:
    rows = conn.execute(
        text(
            "SELECT l.id, l.name, g.code, p.code, g.nature FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
            "LEFT JOIN account_groups p ON p.id = g.parent_id WHERE l.client_id = :c"
        ),
        {"c": client_id},
    )
    return {r[0]: LedgerInfo(r[0], r[1], r[2], r[3], r[4]) for r in rows}


def ledgers_in_group(conn: Connection, client_id: Any, group_code: str) -> list[tuple[Any, str]]:
    rows = conn.execute(
        text(
            "SELECT l.id, l.name FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
            "WHERE l.client_id = :c AND g.code = :g ORDER BY l.name"
        ),
        {"c": client_id, "g": group_code},
    )
    return [(r[0], r[1]) for r in rows]


# ------------------------------------------------------------------------------------------------ ledger roles


def role_rows(conn: Connection, client_id: Any) -> list[tuple[str, Any, str]]:
    rows = conn.execute(
        text(
            "SELECT r.role, r.ledger_id, l.name FROM final_ledger_roles r JOIN ledgers l ON l.id = r.ledger_id "
            "WHERE r.client_id = :c ORDER BY r.role"
        ),
        {"c": client_id},
    )
    return [(r[0], r[1], r[2]) for r in rows]


def role_of_ledger(conn: Connection, client_id: Any, ledger_id: Any) -> str | None:
    row = conn.execute(
        text("SELECT role FROM final_ledger_roles WHERE client_id = :c AND ledger_id = :l"), {"c": client_id, "l": ledger_id}
    ).first()
    return row[0] if row else None


def set_role(conn: Connection, client_id: Any, role: str, ledger_id: Any, actor: str) -> None:
    conn.execute(
        text(
            "INSERT INTO final_ledger_roles (client_id, role, ledger_id, set_by) VALUES (:c, :r, :l, :a) "
            "ON CONFLICT (client_id, role) DO UPDATE SET ledger_id = EXCLUDED.ledger_id, set_by = EXCLUDED.set_by, set_at = now()"
        ),
        {"c": client_id, "r": role, "l": ledger_id, "a": actor},
    )


# ------------------------------------------------------------------------------------------------ partners


def _partner(r) -> dict:
    return {"id": r[0], "name": r[1], "capital_ledger_id": r[2], "current_ledger_id": r[3], "is_active": r[4]}


_PARTNER_COLS = "id, name, capital_ledger_id, current_ledger_id, is_active"


def list_partners(conn: Connection, client_id: Any) -> list[dict]:
    rows = conn.execute(text(f"SELECT {_PARTNER_COLS} FROM partners WHERE client_id = :c ORDER BY lower(name)"), {"c": client_id})
    return [_partner(r) for r in rows]


def get_partner(conn: Connection, client_id: Any, partner_id: Any) -> dict | None:
    row = conn.execute(text(f"SELECT {_PARTNER_COLS} FROM partners WHERE client_id = :c AND id = :p"), {"c": client_id, "p": partner_id}).first()
    return _partner(row) if row else None


def partner_name_taken(conn: Connection, client_id: Any, name: str, except_id: Any = None) -> bool:
    return conn.execute(
        text("SELECT 1 FROM partners WHERE client_id = :c AND lower(btrim(name)) = lower(btrim(:n)) AND id IS DISTINCT FROM :x"),
        {"c": client_id, "n": name, "x": except_id},
    ).first() is not None


def ledger_used_by_partner(conn: Connection, client_id: Any, ledger_id: Any, except_id: Any = None) -> bool:
    return conn.execute(
        text("SELECT 1 FROM partners WHERE client_id = :c AND (capital_ledger_id = :l OR current_ledger_id = :l) AND id IS DISTINCT FROM :x"),
        {"c": client_id, "l": ledger_id, "x": except_id},
    ).first() is not None


def insert_partner(conn: Connection, partner_id: Any, client_id: Any, name: str, capital_ledger_id: Any, current_ledger_id: Any) -> None:
    conn.execute(
        text("INSERT INTO partners (id, client_id, name, capital_ledger_id, current_ledger_id) VALUES (:i, :c, :n, :cap, :cur)"),
        {"i": partner_id, "c": client_id, "n": name, "cap": capital_ledger_id, "cur": current_ledger_id},
    )


def update_partner(conn: Connection, partner_id: Any, name: str, capital_ledger_id: Any, current_ledger_id: Any, is_active: bool) -> None:
    conn.execute(
        text("UPDATE partners SET name = :n, capital_ledger_id = :cap, current_ledger_id = :cur, is_active = :a WHERE id = :i"),
        {"i": partner_id, "n": name, "cap": capital_ledger_id, "cur": current_ledger_id, "a": is_active},
    )


def partner_has_terms(conn: Connection, partner_id: Any) -> bool:
    return conn.execute(text("SELECT 1 FROM partner_fy_terms WHERE partner_id = :p LIMIT 1"), {"p": partner_id}).first() is not None


def partner_has_adjustments(conn: Connection, client_id: Any, partner_id: Any) -> bool:
    return conn.execute(
        text("SELECT 1 FROM adjustment_entries WHERE client_id = :c AND params ->> 'partner_id' = :p LIMIT 1"),
        {"c": client_id, "p": str(partner_id)},
    ).first() is not None


# ------------------------------------------------------------------------------------------------ partner terms


def _terms(r) -> dict:
    return {
        "partner_id": r[0], "profit_share_percent": r[1], "interest_on_capital_rate": r[2], "interest_on_drawings_rate": r[3],
        "remuneration_annual": r[4], "deed_reference": r[5],
    }


def terms_for_year(conn: Connection, client_id: Any, fy_id: Any) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT partner_id, profit_share_percent, interest_on_capital_rate, interest_on_drawings_rate, remuneration_annual, "
            "deed_reference FROM partner_fy_terms WHERE client_id = :c AND financial_year_id = :fy"
        ),
        {"c": client_id, "fy": fy_id},
    )
    return [_terms(r) for r in rows]


def terms_of_partner(conn: Connection, client_id: Any, fy_id: Any, partner_id: Any) -> dict | None:
    for t in terms_for_year(conn, client_id, fy_id):
        if t["partner_id"] == partner_id:
            return t
    return None


def replace_terms(conn: Connection, client_id: Any, fy_id: Any, rows: list[dict], actor: str) -> None:
    conn.execute(text("DELETE FROM partner_fy_terms WHERE client_id = :c AND financial_year_id = :fy"), {"c": client_id, "fy": fy_id})
    if rows:
        conn.execute(
            text(
                "INSERT INTO partner_fy_terms (partner_id, client_id, financial_year_id, profit_share_percent, interest_on_capital_rate, "
                "interest_on_drawings_rate, remuneration_annual, deed_reference, set_by) VALUES (:partner_id, :c, :fy, "
                ":profit_share_percent, :interest_on_capital_rate, :interest_on_drawings_rate, :remuneration_annual, :deed_reference, :a)"
            ),
            [{**r, "c": client_id, "fy": fy_id, "a": actor} for r in rows],
        )


# ------------------------------------------------------------------------------------------------ opening / movements


def opening_signed(conn: Connection, client_id: Any, fy_id: Any, ledger_id: Any) -> Decimal:
    row = conn.execute(
        text("SELECT debit - credit FROM opening_balances WHERE client_id = :c AND financial_year_id = :fy AND ledger_id = :l"),
        {"c": client_id, "fy": fy_id, "l": ledger_id},
    ).first()
    return Decimal(row[0]).quantize(CENTS) if row else Decimal("0.00")


def posted_movements(conn: Connection, client_id: Any, fy_id: Any, ledger_id: Any) -> list[tuple[date, Decimal, Decimal]]:
    """(date, debit, credit) of every posted / reversed line of the ledger in the year, oldest first."""
    rows = conn.execute(
        text(
            "SELECT v.voucher_date, vl.debit, vl.credit FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND vl.ledger_id = :l AND v.status IN ('posted', 'reversed') "
            "ORDER BY v.voucher_date, v.voucher_number, vl.line_no"
        ),
        {"c": client_id, "fy": fy_id, "l": ledger_id},
    )
    return [(r[0], Decimal(r[1]).quantize(CENTS), Decimal(r[2]).quantize(CENTS)) for r in rows]


# ------------------------------------------------------------------------------------------------ adjustment entries


def insert_adjustment(conn: Connection, row: dict) -> None:
    conn.execute(
        text(
            "INSERT INTO adjustment_entries (id, client_id, financial_year_id, adj_type, as_on_date, amount, params, basis_note, "
            "voucher_id, auto_reverse_voucher_id, created_by) VALUES (:id, :client_id, :financial_year_id, :adj_type, :as_on_date, "
            ":amount, CAST(:params AS jsonb), :basis_note, :voucher_id, :auto_reverse_voucher_id, :created_by)"
        ),
        {**row, "params": json.dumps(row["params"], default=str)},
    )


_LIST_SQL = (
    "SELECT a.id, a.financial_year_id, a.adj_type, a.as_on_date, a.amount, a.basis_note, a.params, a.voucher_id, v.status, "
    "v.voucher_number, a.auto_reverse_voucher_id, rv.status FROM adjustment_entries a JOIN vouchers v ON v.id = a.voucher_id "
    "LEFT JOIN vouchers rv ON rv.id = a.auto_reverse_voucher_id WHERE a.client_id = :c"
)


def _adjustment(r) -> dict:
    return {
        "id": r[0], "financial_year_id": r[1], "adj_type": r[2], "as_on_date": r[3], "amount": Decimal(r[4]).quantize(CENTS),
        "basis_note": r[5], "params": r[6], "voucher_id": r[7], "voucher_status": r[8], "voucher_number": r[9],
        "auto_reverse_voucher_id": r[10], "auto_reverse_status": r[11],
    }


def list_adjustments(conn: Connection, client_id: Any, fy_id: Any, adj_type: str | None = None) -> list[dict]:
    sql = _LIST_SQL + " AND a.financial_year_id = :fy AND (CAST(:t AS text) IS NULL OR a.adj_type = :t) ORDER BY a.as_on_date, a.created_at"
    return [_adjustment(r) for r in conn.execute(text(sql), {"c": client_id, "fy": fy_id, "t": adj_type})]


def get_adjustment(conn: Connection, client_id: Any, adjustment_id: Any) -> dict | None:
    row = conn.execute(text(_LIST_SQL + " AND a.id = :a"), {"c": client_id, "a": adjustment_id}).first()
    return _adjustment(row) if row else None


def delete_adjustment(conn: Connection, adjustment_id: Any) -> None:
    conn.execute(text("DELETE FROM adjustment_entries WHERE id = :a"), {"a": adjustment_id})


def unposted_adjustment_count(conn: Connection, client_id: Any, fy_id: Any, adj_type: str) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM adjustment_entries a JOIN vouchers v ON v.id = a.voucher_id WHERE a.client_id = :c "
            "AND a.financial_year_id = :fy AND a.adj_type = :t AND v.status IN ('draft', 'approved')"
        ),
        {"c": client_id, "fy": fy_id, "t": adj_type},
    ).scalar_one()
