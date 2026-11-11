"""Reads that turn database rows into engine models. SQL only: no accounting rules and no accounting maths here.

Every function takes a SQLAlchemy Connection owned by the caller.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.models import Ledger, OpeningBalance, PostedLine

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class FinancialYearRow:
    id: object
    start_date: date
    end_date: date


def client_exists(conn: Connection, client_id: object) -> bool:
    return conn.execute(text("SELECT 1 FROM clients WHERE id = :c"), {"c": client_id}).first() is not None


def find_group_id(conn: Connection, client_id: object, group_code: str) -> object | None:
    """A system group, or one of this client's own groups, by code."""
    row = conn.execute(
        text("SELECT id FROM account_groups WHERE code = :code AND (client_id IS NULL OR client_id = :c)"),
        {"code": group_code, "c": client_id},
    ).first()
    return row[0] if row else None


def system_group_ids(conn: Connection) -> dict[str, object]:
    return {code: gid for code, gid in conn.execute(text("SELECT code, id FROM account_groups WHERE client_id IS NULL"))}


def get_ledger(conn: Connection, client_id: object, ledger_id: object) -> Ledger | None:
    row = conn.execute(
        text(
            "SELECT l.id, l.name, g.code, l.is_active, l.client_id FROM ledgers l "
            "JOIN account_groups g ON g.id = l.group_id WHERE l.id = :id AND l.client_id = :c"
        ),
        {"id": ledger_id, "c": client_id},
    ).first()
    return Ledger(row[0], row[1], row[2], row[3], row[4]) if row else None


def ledger_name_exists(conn: Connection, client_id: object, name: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM ledgers WHERE client_id = :c AND lower(name) = lower(:n)"), {"c": client_id, "n": name}
    ).first() is not None


def get_financial_year(conn: Connection, client_id: object, fy_id: object) -> FinancialYearRow | None:
    row = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE id = :id AND client_id = :c"),
        {"id": fy_id, "c": client_id},
    ).first()
    return FinancialYearRow(*row) if row else None


def latest_financial_year(conn: Connection, client_id: object) -> FinancialYearRow | None:
    row = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c ORDER BY start_date DESC LIMIT 1"),
        {"c": client_id},
    ).first()
    return FinancialYearRow(*row) if row else None


def openings_for_year(conn: Connection, client_id: object, fy_id: object) -> dict[object, OpeningBalance]:
    rows = conn.execute(
        text("SELECT ledger_id, debit, credit FROM opening_balances WHERE client_id = :c AND financial_year_id = :fy"),
        {"c": client_id, "fy": fy_id},
    )
    return {ledger_id: OpeningBalance(debit.quantize(CENTS), credit.quantize(CENTS)) for ledger_id, debit, credit in rows}


def lines_touching_ledger(conn: Connection, client_id: object, ledger_id: object, fy_id: object) -> list[PostedLine]:
    """Every line of the posted/reversed vouchers of this year that have a line for the ledger (the other lines
    give the counter ledger names on the statement)."""
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_number, v.voucher_type, v.voucher_date, v.narration, v.status, vl.line_no, "
            "vl.ledger_id, l.name, vl.debit, vl.credit "
            "FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id JOIN ledgers l ON l.id = vl.ledger_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND v.status IN ('posted', 'reversed') "
            "AND v.id IN (SELECT voucher_id FROM voucher_lines WHERE ledger_id = :ledger) "
            "ORDER BY v.voucher_date, v.voucher_number, vl.line_no"
        ),
        {"c": client_id, "fy": fy_id, "ledger": ledger_id},
    )
    return [
        PostedLine(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9].quantize(CENTS), r[10].quantize(CENTS))
        for r in rows
    ]


def open_voucher_count_for_ledger(conn: Connection, client_id: object, ledger_id: object) -> int:
    """Draft or approved vouchers that have a line for the ledger."""
    return conn.execute(
        text(
            "SELECT count(DISTINCT v.id) FROM vouchers v JOIN voucher_lines vl ON vl.voucher_id = v.id "
            "WHERE v.client_id = :c AND vl.ledger_id = :ledger AND v.status IN ('draft', 'approved')"
        ),
        {"c": client_id, "ledger": ledger_id},
    ).scalar_one()


def posted_voucher_exists(conn: Connection, client_id: object, fy_id: object) -> bool:
    """True once any voucher of the year is posted or reversed (opening balances are then frozen)."""
    return conn.execute(
        text(
            "SELECT 1 FROM vouchers WHERE client_id = :c AND financial_year_id = :fy "
            "AND status IN ('posted', 'reversed') LIMIT 1"
        ),
        {"c": client_id, "fy": fy_id},
    ).first() is not None
