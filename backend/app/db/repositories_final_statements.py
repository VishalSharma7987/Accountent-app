"""Reads and the one upsert of the Phase 6 statements package (closing stock, ledger roles, closing vouchers, partner shares).
SQL only: no accounting maths. Services never commit."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.final_types import PartnerShare

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ClientProfile:
    name: str
    entity_type: str
    business_type: str


@dataclass(frozen=True)
class ClosingStockRow:
    financial_year_id: Any
    as_on_date: date
    source: str
    inventory_method: str | None
    cost_value: Decimal
    write_down: Decimal
    carrying_value: Decimal
    basis_note: str
    detail: dict
    approved_by: str
    approved_at: datetime


def client_profile(conn: Connection, client_id: object) -> ClientProfile | None:
    row = conn.execute(text("SELECT name, entity_type, business_type FROM clients WHERE id = :c"), {"c": client_id}).first()
    return ClientProfile(*row) if row else None


def closing_voucher_ids(conn: Connection, client_id: object) -> set[object]:
    """Every year-end closing voucher and its reversal (closed or reopened): the statements never count them."""
    rows = conn.execute(text("SELECT voucher_id FROM year_end_close_vouchers WHERE client_id = :c"), {"c": client_id})
    return {r[0] for r in rows}


def ledger_roles(conn: Connection, client_id: object) -> dict[object, str]:
    rows = conn.execute(text("SELECT ledger_id, role FROM final_ledger_roles WHERE client_id = :c"), {"c": client_id})
    return {r[0]: r[1] for r in rows}


def partner_shares(conn: Connection, client_id: object, fy_id: object) -> tuple[PartnerShare, ...]:
    """The partners with a profit share for the year, in the order they were created (the last one takes the rounding remainder)."""
    rows = conn.execute(
        text(
            "SELECT p.id, p.name, COALESCE(p.current_ledger_id, p.capital_ledger_id), t.profit_share_percent "
            "FROM partner_fy_terms t JOIN partners p ON p.id = t.partner_id AND p.client_id = t.client_id "
            "WHERE t.client_id = :c AND t.financial_year_id = :fy ORDER BY p.created_at, p.name"
        ),
        {"c": client_id, "fy": fy_id},
    )
    return tuple(PartnerShare(r[0], r[1], r[2], r[3].quantize(Decimal("0.0001"))) for r in rows)


def get_closing_stock(conn: Connection, client_id: object, fy_id: object) -> ClosingStockRow | None:
    row = conn.execute(
        text(
            "SELECT financial_year_id, as_on_date, source, inventory_method, cost_value, write_down, carrying_value, basis_note, "
            "detail, approved_by, approved_at FROM final_closing_stock WHERE client_id = :c AND financial_year_id = :fy"
        ),
        {"c": client_id, "fy": fy_id},
    ).first()
    if row is None:
        return None
    return ClosingStockRow(row[0], row[1], row[2], row[3], row[4].quantize(CENTS), row[5].quantize(CENTS), row[6].quantize(CENTS),
                           row[7], row[8], row[9], row[10])


def upsert_closing_stock(conn: Connection, client_id: object, fy_id: object, *, as_on: date, source: str, method: str | None,
                         cost: Decimal, write_down: Decimal, carrying: Decimal, basis_note: str, detail: str, actor: str) -> None:
    conn.execute(
        text(
            "INSERT INTO final_closing_stock (client_id, financial_year_id, as_on_date, source, inventory_method, cost_value, write_down, "
            "carrying_value, basis_note, detail, approved_by) VALUES (:c, :fy, :on, :src, :m, :cost, :wd, :cv, :note, CAST(:detail AS jsonb), :by) "
            "ON CONFLICT (client_id, financial_year_id) DO UPDATE SET as_on_date = EXCLUDED.as_on_date, source = EXCLUDED.source, "
            "inventory_method = EXCLUDED.inventory_method, cost_value = EXCLUDED.cost_value, write_down = EXCLUDED.write_down, "
            "carrying_value = EXCLUDED.carrying_value, basis_note = EXCLUDED.basis_note, detail = EXCLUDED.detail, "
            "approved_by = EXCLUDED.approved_by, approved_at = now()"
        ),
        {"c": client_id, "fy": fy_id, "on": as_on, "src": source, "m": method, "cost": cost, "wd": write_down, "cv": carrying,
         "note": basis_note, "detail": detail, "by": actor},
    )
