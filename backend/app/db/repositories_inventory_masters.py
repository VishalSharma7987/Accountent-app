"""SQL for the inventory masters (Phase 5, package A): godowns, stock items, per-year policy, opening stock.
SQL only: no rules, no maths beyond sums. Every function takes a Connection owned by the caller."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Connection, text

QTY = Decimal("0.001")
CENTS = Decimal("0.01")

# =============================================================================================== godowns


@dataclass(frozen=True)
class GodownRow:
    id: uuid.UUID
    name: str
    is_active: bool


def godown_rows(conn: Connection, client_id: object) -> list[GodownRow]:
    rows = conn.execute(text("SELECT id, name, is_active FROM godowns WHERE client_id = :c ORDER BY lower(name)"),
                        {"c": client_id})
    return [GodownRow(*r) for r in rows]


def godown_row(conn: Connection, client_id: object, godown_id: object) -> GodownRow | None:
    row = conn.execute(text("SELECT id, name, is_active FROM godowns WHERE client_id = :c AND id = :id"),
                       {"c": client_id, "id": godown_id}).first()
    return GodownRow(*row) if row else None


def godown_name_taken(conn: Connection, client_id: object, name: str, exclude_id: object | None) -> bool:
    return conn.execute(
        text("SELECT 1 FROM godowns WHERE client_id = :c AND lower(btrim(name)) = lower(btrim(:n)) "
             "AND (CAST(:x AS uuid) IS NULL OR id <> :x)"),
        {"c": client_id, "n": name, "x": exclude_id},
    ).first() is not None


def insert_godown(conn: Connection, client_id: object, godown_id: uuid.UUID, name: str) -> None:
    conn.execute(text("INSERT INTO godowns (id, client_id, name) VALUES (:id, :c, :n)"),
                 {"id": godown_id, "c": client_id, "n": name})


def update_godown(conn: Connection, client_id: object, godown_id: object, name: str, is_active: bool) -> None:
    conn.execute(text("UPDATE godowns SET name = :n, is_active = :a WHERE client_id = :c AND id = :id"),
                 {"id": godown_id, "c": client_id, "n": name, "a": is_active})


def active_items_defaulting_to(conn: Connection, client_id: object, godown_id: object) -> int:
    return conn.execute(
        text("SELECT count(*) FROM stock_items WHERE client_id = :c AND default_godown_id = :g AND is_active"),
        {"c": client_id, "g": godown_id}).scalar_one()


# ===================================================================================== stock held (S-18)


def nonzero_balances(conn: Connection, client_id: object) -> list[tuple[uuid.UUID, uuid.UUID, Decimal]]:
    """(item_id, godown_id, quantity) of every item and godown that holds stock now. 'Now' = for each item, the latest
    financial year that has any opening or movement row: opening + inwards - outwards of that year."""
    rows = conn.execute(
        text(
            "WITH q AS ("
            " SELECT financial_year_id AS fy, item_id, godown_id, quantity AS q FROM stock_opening WHERE client_id = :c"
            " UNION ALL"
            " SELECT financial_year_id, item_id, godown_id, CASE direction WHEN 'in' THEN quantity ELSE -quantity END"
            " FROM stock_movements WHERE client_id = :c), "
            "latest AS (SELECT q.item_id, max(f.start_date) AS sd FROM q JOIN financial_years f ON f.id = q.fy GROUP BY q.item_id), "
            "per AS (SELECT q.item_id, q.godown_id, sum(q.q) AS bal FROM q JOIN financial_years f ON f.id = q.fy "
            " JOIN latest l ON l.item_id = q.item_id AND l.sd = f.start_date GROUP BY q.item_id, q.godown_id) "
            "SELECT item_id, godown_id, bal FROM per WHERE bal <> 0"
        ),
        {"c": client_id},
    )
    return [(r[0], r[1], r[2].quantize(QTY)) for r in rows]


# ============================================================================================ stock items


@dataclass(frozen=True)
class StockItemRow:
    item_id: uuid.UUID
    sku: str
    name: str
    hsn_sac: str
    uqc: str | None
    default_godown_id: uuid.UUID
    default_godown_name: str
    is_active: bool
    has_entries: bool
    opening_qty: Decimal | None = None
    opening_value: Decimal | None = None


_ITEM_SELECT = (
    "SELECT s.item_id, s.sku, g.name, g.hsn_sac, g.uqc, s.default_godown_id, d.name, s.is_active, "
    "(EXISTS (SELECT 1 FROM stock_opening o WHERE o.item_id = s.item_id) "
    " OR EXISTS (SELECT 1 FROM stock_movements m WHERE m.item_id = s.item_id)) AS has_entries, "
    "(SELECT sum(o.quantity) FROM stock_opening o WHERE o.item_id = s.item_id AND o.financial_year_id = :fy), "
    "(SELECT sum(o.value) FROM stock_opening o WHERE o.item_id = s.item_id AND o.financial_year_id = :fy) "
    "FROM stock_items s JOIN gst_items g ON g.id = s.item_id AND g.client_id = s.client_id "
    "JOIN godowns d ON d.id = s.default_godown_id AND d.client_id = s.client_id WHERE s.client_id = :c"
)


def _stock_item(row: tuple, with_opening: bool) -> StockItemRow:
    qty = (row[9] or Decimal(0)).quantize(QTY) if with_opening else None
    value = (row[10] or Decimal(0)).quantize(CENTS) if with_opening else None
    return StockItemRow(*row[:9], qty, value)


def stock_item_rows(conn: Connection, client_id: object, q: str | None, active: bool | None,
                    fy_id: object | None) -> list[StockItemRow]:
    rows = conn.execute(
        text(_ITEM_SELECT + " AND (CAST(:a AS boolean) IS NULL OR s.is_active = :a) "
             "AND (CAST(:q AS text) IS NULL OR lower(g.name) LIKE '%' || lower(:q) || '%' "
             "OR lower(s.sku) LIKE '%' || lower(:q) || '%') ORDER BY lower(g.name)"),
        {"c": client_id, "a": active, "q": q, "fy": fy_id},
    )
    return [_stock_item(tuple(r), fy_id is not None) for r in rows]


def stock_item_row(conn: Connection, client_id: object, item_id: object) -> StockItemRow | None:
    row = conn.execute(text(_ITEM_SELECT + " AND s.item_id = :i"), {"c": client_id, "i": item_id, "fy": None}).first()
    return _stock_item(tuple(row), False) if row else None


def sku_taken(conn: Connection, client_id: object, sku: str, exclude_item_id: object | None) -> bool:
    return conn.execute(
        text("SELECT 1 FROM stock_items WHERE client_id = :c AND lower(btrim(sku)) = lower(btrim(:s)) "
             "AND (CAST(:x AS uuid) IS NULL OR item_id <> :x)"),
        {"c": client_id, "s": sku, "x": exclude_item_id},
    ).first() is not None


def insert_stock_item(conn: Connection, client_id: object, item_id: object, sku: str, godown_id: object,
                      is_active: bool) -> None:
    conn.execute(
        text("INSERT INTO stock_items (item_id, client_id, sku, default_godown_id, is_active) "
             "VALUES (:i, :c, :s, :g, :a)"),
        {"i": item_id, "c": client_id, "s": sku, "g": godown_id, "a": is_active})


def update_stock_item(conn: Connection, client_id: object, item_id: object, sku: str, godown_id: object,
                      is_active: bool) -> None:
    conn.execute(
        text("UPDATE stock_items SET sku = :s, default_godown_id = :g, is_active = :a WHERE client_id = :c AND item_id = :i"),
        {"i": item_id, "c": client_id, "s": sku, "g": godown_id, "a": is_active})


# ===================================================================================================== policy


@dataclass(frozen=True)
class PolicyRow:
    financial_year_id: uuid.UUID
    valuation_method: str
    negative_stock_mode: str
    set_by: str
    set_at: datetime


def policy_row(conn: Connection, client_id: object, fy_id: object) -> PolicyRow | None:
    row = conn.execute(
        text("SELECT financial_year_id, valuation_method, negative_stock_mode, set_by, set_at FROM inventory_settings "
             "WHERE client_id = :c AND financial_year_id = :fy"), {"c": client_id, "fy": fy_id}).first()
    return PolicyRow(*row) if row else None


def insert_policy(conn: Connection, client_id: object, fy_id: object, method: str, mode: str, actor: str) -> None:
    conn.execute(
        text("INSERT INTO inventory_settings (client_id, financial_year_id, valuation_method, negative_stock_mode, set_by) "
             "VALUES (:c, :fy, :m, :n, :by)"), {"c": client_id, "fy": fy_id, "m": method, "n": mode, "by": actor})


def update_policy(conn: Connection, client_id: object, fy_id: object, method: str, mode: str, actor: str) -> None:
    conn.execute(
        text("UPDATE inventory_settings SET valuation_method = :m, negative_stock_mode = :n, set_by = :by, set_at = now() "
             "WHERE client_id = :c AND financial_year_id = :fy"),
        {"c": client_id, "fy": fy_id, "m": method, "n": mode, "by": actor})


def year_has_movements(conn: Connection, client_id: object, fy_id: object) -> bool:
    return conn.execute(
        text("SELECT 1 FROM stock_movements WHERE client_id = :c AND financial_year_id = :fy LIMIT 1"),
        {"c": client_id, "fy": fy_id}).first() is not None


def year_has_locked_period(conn: Connection, client_id: object, fy_id: object) -> bool:
    """S-09: any period of the year is locked."""
    return conn.execute(
        text("SELECT 1 FROM periods WHERE client_id = :c AND financial_year_id = :fy AND status = 'locked' LIMIT 1"),
        {"c": client_id, "fy": fy_id}).first() is not None


# ===================================================================================================== opening


@dataclass(frozen=True)
class OpeningRow:
    item_id: uuid.UUID
    sku: str
    name: str
    godown_id: uuid.UUID
    godown_name: str
    quantity: Decimal
    value: Decimal


def opening_rows(conn: Connection, client_id: object, fy_id: object) -> list[OpeningRow]:
    rows = conn.execute(
        text("SELECT o.item_id, s.sku, g.name, o.godown_id, d.name, o.quantity, o.value FROM stock_opening o "
             "JOIN stock_items s ON s.item_id = o.item_id JOIN gst_items g ON g.id = o.item_id "
             "JOIN godowns d ON d.id = o.godown_id WHERE o.client_id = :c AND o.financial_year_id = :fy "
             "ORDER BY lower(g.name), lower(d.name)"), {"c": client_id, "fy": fy_id})
    return [OpeningRow(r[0], r[1], r[2], r[3], r[4], r[5].quantize(QTY), r[6].quantize(CENTS)) for r in rows]


def replace_opening(conn: Connection, client_id: object, fy_id: object, rows: list[tuple], actor: str) -> None:
    """rows = [(item_id, godown_id, quantity, value)]: the whole opening of the year is replaced."""
    conn.execute(text("DELETE FROM stock_opening WHERE client_id = :c AND financial_year_id = :fy"),
                 {"c": client_id, "fy": fy_id})
    if rows:
        conn.execute(
            text("INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
                 "VALUES (:c, :fy, :i, :g, :q, :v, :by)"),
            [{"c": client_id, "fy": fy_id, "i": i, "g": g, "q": q, "v": v, "by": actor} for i, g, q, v in rows])


def stock_in_hand_opening(conn: Connection, client_id: object, fy_id: object) -> Decimal | None:
    """Debit minus credit of the opening balances of the client's Stock-in-hand ledgers (None = the client has none)."""
    row = conn.execute(
        text("SELECT count(l.id), coalesce(sum(ob.debit - ob.credit), 0) FROM ledgers l "
             "JOIN account_groups ag ON ag.id = l.group_id AND ag.code = 'stock_in_hand' "
             "LEFT JOIN opening_balances ob ON ob.ledger_id = l.id AND ob.financial_year_id = :fy "
             "WHERE l.client_id = :c"), {"c": client_id, "fy": fy_id}).one()
    return None if row[0] == 0 else row[1].quantize(CENTS)
