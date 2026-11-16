"""SQL for stock movements written by vouchers (Phase 5, package C). SQL only: no rules, no costing.

Ids leave this module as strings (the engines compare ids as plain values). `load_movements` and `load_opening` are also
used read-only by the reports (package E) and the stock journals (package D).
Every function takes a Connection owned by the caller.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    MovementKind,
    NegativeStockMode,
    OpeningStock,
    ValuationMethod,
)
from app.engine.inventory_voucher import ItemFacts, LineFacts, OriginalFacts, StockLineIn

QTY = Decimal("0.001")
CENTS = Decimal("0.01")


def _ids(values) -> list[uuid.UUID]:
    return [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in values]


# ============================================================================================ year and policy


@dataclass(frozen=True)
class YearPolicy:
    financial_year_id: str
    start_date: date
    end_date: date
    policy: InventoryPolicy | None  # None = the client never set the inventory policy for this year (S-04)


def year_policy_on(conn: Connection, client_id: object, on: date) -> YearPolicy | None:
    """The financial year holding `on` with its inventory policy; None when no year holds the date."""
    row = conn.execute(
        text("SELECT f.id, f.start_date, f.end_date, s.valuation_method, s.negative_stock_mode FROM financial_years f "
             "LEFT JOIN inventory_settings s ON s.financial_year_id = f.id AND s.client_id = f.client_id "
             "WHERE f.client_id = :c AND :d BETWEEN f.start_date AND f.end_date"),
        {"c": client_id, "d": on},
    ).first()
    return None if row is None else _year_policy(row)


def year_policy(conn: Connection, client_id: object, fy_id: object) -> YearPolicy | None:
    row = conn.execute(
        text("SELECT f.id, f.start_date, f.end_date, s.valuation_method, s.negative_stock_mode FROM financial_years f "
             "LEFT JOIN inventory_settings s ON s.financial_year_id = f.id AND s.client_id = f.client_id "
             "WHERE f.client_id = :c AND f.id = :fy"),
        {"c": client_id, "fy": fy_id},
    ).first()
    return None if row is None else _year_policy(row)


def _year_policy(row) -> YearPolicy:
    policy = None if row[3] is None else InventoryPolicy(ValuationMethod(row[3]), NegativeStockMode(row[4]))
    return YearPolicy(str(row[0]), row[1], row[2], policy)


# ================================================================================================== masters


def stock_item_facts(conn: Connection, client_id: object, item_ids: list) -> dict[str, ItemFacts]:
    """Items among `item_ids` that have a stock_items row (others are not stock items)."""
    if not item_ids:
        return {}
    rows = conn.execute(
        text("SELECT s.item_id, g.name, s.is_active, g.is_active, g.uqc, g.hsn_sac, s.default_godown_id "
             "FROM stock_items s JOIN gst_items g ON g.id = s.item_id AND g.client_id = s.client_id "
             "WHERE s.client_id = :c AND s.item_id = ANY(:ids)"),
        {"c": client_id, "ids": _ids(item_ids)},
    )
    return {str(r[0]): ItemFacts(r[1], r[2], r[3], r[4], r[5], str(r[6])) for r in rows}


def godowns_of(conn: Connection, client_id: object) -> dict[str, tuple[str, bool]]:
    """godown id -> (name, is_active)."""
    rows = conn.execute(text("SELECT id, name, is_active FROM godowns WHERE client_id = :c"), {"c": client_id})
    return {str(r[0]): (r[1], r[2]) for r in rows}


def lock_items(conn: Connection, client_id: object, item_ids: list) -> None:
    """Serialise stock postings of the same items: two vouchers cannot both pass S-01 on the same stock."""
    if item_ids:
        conn.execute(
            text("SELECT 1 FROM stock_items WHERE client_id = :c AND item_id = ANY(:ids) ORDER BY item_id FOR UPDATE"),
            {"c": client_id, "ids": _ids(item_ids)},
        ).fetchall()


# ============================================================================================ voucher rows


@dataclass(frozen=True)
class VoucherFacts:
    voucher_type: str
    voucher_date: date
    financial_year_id: str
    status: str
    reverses_voucher_id: str | None


def voucher_facts(conn: Connection, client_id: object, voucher_id: object) -> VoucherFacts | None:
    row = conn.execute(
        text("SELECT voucher_type, voucher_date, financial_year_id, status, reverses_voucher_id FROM vouchers "
             "WHERE id = :v AND client_id = :c"),
        {"v": voucher_id, "c": client_id},
    ).first()
    return None if row is None else VoucherFacts(row[0], row[1], str(row[2]), row[3], None if row[4] is None else str(row[4]))


def stored_item_lines(conn: Connection, voucher_id: object) -> list[LineFacts]:
    rows = conn.execute(
        text("SELECT item_line_no, item_id, quantity, uqc, hsn_sac, taxable_value, cgst, sgst, igst, cess, tax_in_cost "
             "FROM voucher_item_lines WHERE voucher_id = :v AND item_id IS NOT NULL ORDER BY item_line_no"),
        {"v": voucher_id},
    )
    return [LineFacts(r[0], str(r[1]), Decimal(r[2]).quantize(QTY), r[3], r[4], Decimal(r[5]).quantize(CENTS),
                      Decimal(r[6]).quantize(CENTS), Decimal(r[7]).quantize(CENTS), Decimal(r[8]).quantize(CENTS),
                      Decimal(r[9]).quantize(CENTS), r[10]) for r in rows]


def stored_stock_lines(conn: Connection, voucher_id: object) -> dict[int, StockLineIn]:
    rows = conn.execute(
        text("SELECT item_line_no, godown_id, original_movement_id FROM voucher_stock_lines WHERE voucher_id = :v"),
        {"v": voucher_id},
    )
    return {r[0]: StockLineIn(r[0], str(r[1]), None if r[2] is None else str(r[2])) for r in rows}


def replace_stock_lines(conn: Connection, client_id: object, voucher_id: object, rows: list[tuple[int, object, object]]) -> None:
    """rows = (item_line_no, godown_id, original_movement_id). Draft vouchers only (the database refuses otherwise)."""
    conn.execute(text("DELETE FROM voucher_stock_lines WHERE voucher_id = :v"), {"v": voucher_id})
    if rows:
        conn.execute(
            text("INSERT INTO voucher_stock_lines (voucher_id, client_id, item_line_no, godown_id, original_movement_id) "
                 "VALUES (:v, :c, :n, :g, :o)"),
            [{"v": voucher_id, "c": client_id, "n": n, "g": g, "o": o} for n, g, o in rows],
        )


# =============================================================================================== movements


def _movement(r) -> Movement:
    return Movement(str(r[0]), r[1], r[2], str(r[3]), str(r[4]), MovementKind(r[5]), Decimal(r[6]).quantize(QTY),
                    None if r[7] is None else Decimal(r[7]).quantize(CENTS), None if r[8] is None else str(r[8]))


def load_movements(conn: Connection, client_id: object, fy_id: object, to_date: date | None = None,
                   item_ids: list | None = None) -> list[Movement]:
    """Posted movements of the year in (date, seq) order; optionally up to a date and for some items only."""
    rows = conn.execute(
        text("SELECT id, seq, movement_date, item_id, godown_id, kind, quantity, value, ref_movement_id FROM stock_movements "
             "WHERE client_id = :c AND financial_year_id = :fy AND (CAST(:to AS date) IS NULL OR movement_date <= CAST(:to AS date)) "
             "AND (CAST(:ids AS uuid[]) IS NULL OR item_id = ANY(CAST(:ids AS uuid[]))) ORDER BY movement_date, seq"),
        {"c": client_id, "fy": fy_id, "to": to_date, "ids": None if item_ids is None else _ids(item_ids)},
    )
    return [_movement(r) for r in rows]


def load_opening(conn: Connection, client_id: object, fy_id: object, item_ids: list | None = None) -> list[OpeningStock]:
    rows = conn.execute(
        text("SELECT item_id, godown_id, quantity, value FROM stock_opening WHERE client_id = :c AND financial_year_id = :fy "
             "AND (CAST(:ids AS uuid[]) IS NULL OR item_id = ANY(CAST(:ids AS uuid[])))"),
        {"c": client_id, "fy": fy_id, "ids": None if item_ids is None else _ids(item_ids)},
    )
    return [OpeningStock(str(r[0]), str(r[1]), Decimal(r[2]).quantize(QTY), Decimal(r[3]).quantize(CENTS)) for r in rows]


def max_seq(conn: Connection) -> int:
    return conn.execute(text("SELECT coalesce(max(seq), 0) FROM stock_movements")).scalar_one()


def original_facts(conn: Connection, client_id: object, movement_ids: list) -> dict[str, OriginalFacts]:
    """Sale / purchase movements named by returns, with what was returned so far (reversed returns do not count)."""
    ids = []
    for m in movement_ids:
        try:
            ids.append(uuid.UUID(str(m)))
        except ValueError:  # a malformed id is simply "not found"
            continue
    if not ids:
        return {}
    rows = conn.execute(
        text("SELECT m.id, m.item_id, m.kind, m.quantity, m.godown_id, "
             "EXISTS (SELECT 1 FROM stock_movements x WHERE x.ref_movement_id = m.id AND x.kind IN ('reversal_in', 'reversal_out')), "
             "(SELECT coalesce(sum(r.quantity), 0) FROM stock_movements r WHERE r.ref_movement_id = m.id "
             " AND r.kind IN ('sales_return', 'purchase_return') AND NOT EXISTS ("
             "  SELECT 1 FROM stock_movements x WHERE x.ref_movement_id = r.id AND x.kind IN ('reversal_in', 'reversal_out'))) "
             "FROM stock_movements m WHERE m.client_id = :c AND m.id = ANY(:ids)"),
        {"c": client_id, "ids": ids},
    )
    return {str(r[0]): OriginalFacts(str(r[0]), str(r[1]), MovementKind(r[2]), Decimal(r[3]).quantize(QTY), str(r[4]), r[5],
                                     Decimal(r[6]).quantize(QTY)) for r in rows}


def insert_movements(conn: Connection, rows: list[dict]) -> None:
    """rows: id, client_id, financial_year_id, item_id, godown_id, movement_date, kind, direction, quantity, value,
    voucher_id, item_line_no, ref_movement_id, created_by. Written in the order given (seq follows)."""
    for row in rows:  # one by one: the identity column `seq` must follow the order of the list
        conn.execute(
            text("INSERT INTO stock_movements (id, client_id, financial_year_id, item_id, godown_id, movement_date, kind, "
                 "direction, quantity, value, voucher_id, item_line_no, ref_movement_id, created_by) "
                 "VALUES (:id, :client_id, :financial_year_id, :item_id, :godown_id, :movement_date, :kind, :direction, "
                 ":quantity, :value, :voucher_id, :item_line_no, :ref_movement_id, :created_by)"),
            row,
        )


def voucher_movements(conn: Connection, voucher_id: object) -> list[dict]:
    """Movements of a voucher's item lines, in line order (id, item, godown, kind, direction, quantity, date, line, ref)."""
    rows = conn.execute(
        text("SELECT m.id, m.item_id, m.godown_id, g.name, m.kind, m.direction, m.quantity, m.movement_date, m.item_line_no, "
             "m.ref_movement_id, m.financial_year_id FROM stock_movements m JOIN godowns g ON g.id = m.godown_id "
             "WHERE m.voucher_id = :v AND m.item_line_no IS NOT NULL ORDER BY m.item_line_no"),
        {"v": voucher_id},
    )
    keys = ("id", "item_id", "godown_id", "godown_name", "kind", "direction", "quantity", "date", "item_line_no",
            "ref_movement_id", "financial_year_id")
    return [{**dict(zip(keys, r, strict=True)), "quantity": Decimal(r[6]).quantize(QTY)} for r in rows]


def live_returns_of(conn: Connection, movement_ids: list) -> int:
    """How many non-reversed returns refer to these movements (a sale / purchase with returns cannot be reversed)."""
    return conn.execute(
        text("SELECT count(*) FROM stock_movements r WHERE r.ref_movement_id = ANY(:ids) "
             "AND r.kind IN ('sales_return', 'purchase_return') AND NOT EXISTS ("
             "SELECT 1 FROM stock_movements x WHERE x.ref_movement_id = r.id AND x.kind IN ('reversal_in', 'reversal_out'))"),
        {"ids": _ids(movement_ids)},
    ).scalar_one()


def returnable(conn: Connection, client_id: object, item_id: object, on: date | None) -> list[dict]:
    """Sales and purchases of an item that can be named as the original of a return."""
    rows = conn.execute(
        text("SELECT m.id, m.kind, v.voucher_number, m.movement_date, m.quantity, "
             "(SELECT coalesce(sum(r.quantity), 0) FROM stock_movements r WHERE r.ref_movement_id = m.id "
             " AND r.kind IN ('sales_return', 'purchase_return') AND NOT EXISTS ("
             "  SELECT 1 FROM stock_movements x WHERE x.ref_movement_id = r.id AND x.kind IN ('reversal_in', 'reversal_out'))) "
             "FROM stock_movements m JOIN vouchers v ON v.id = m.voucher_id "
             "WHERE m.client_id = :c AND m.item_id = :i AND m.kind IN ('sale', 'purchase') "
             "AND (CAST(:on AS date) IS NULL OR m.movement_date <= CAST(:on AS date)) "
             "AND NOT EXISTS (SELECT 1 FROM stock_movements x WHERE x.ref_movement_id = m.id AND x.kind IN ('reversal_in', 'reversal_out')) "
             "ORDER BY m.movement_date, m.seq"),
        {"c": client_id, "i": item_id, "on": on},
    )
    out = []
    for r in rows:
        qty, done = Decimal(r[4]).quantize(QTY), Decimal(r[5]).quantize(QTY)
        out.append({"movement_id": r[0], "kind": r[1], "voucher_number": r[2], "date": r[3], "quantity": qty,
                    "already_returned": done, "returnable": qty - done})
    return out
