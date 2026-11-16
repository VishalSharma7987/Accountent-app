"""SQL for the inventory reports and NRV entries (Phase 5, package E). Read-only except the NRV table.
SQL only: no rules, no maths. Every function takes a Connection owned by the caller."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.inventory_types import Movement, MovementKind, OpeningStock

QTY = Decimal("0.001")
CENTS = Decimal("0.01")


def load_opening(conn: Connection, client_id: object, fy_id: object) -> list[OpeningStock]:
    rows = conn.execute(
        text("SELECT item_id, godown_id, quantity, value FROM stock_opening WHERE client_id = :c AND financial_year_id = :fy"),
        {"c": client_id, "fy": fy_id})
    return [OpeningStock(r[0], r[1], r[2].quantize(QTY), r[3].quantize(CENTS)) for r in rows]


def load_movements(conn: Connection, client_id: object, fy_id: object) -> tuple[list[Movement], dict]:
    """Every movement of the year (the engine checks S-01 over the whole chronology) and a map movement id -> the number
    of its voucher or journal."""
    rows = conn.execute(
        text("SELECT m.id, m.seq, m.movement_date, m.item_id, m.godown_id, m.kind, m.quantity, m.value, m.ref_movement_id, "
             "coalesce(v.voucher_number, j.journal_number) FROM stock_movements m "
             "LEFT JOIN vouchers v ON v.id = m.voucher_id LEFT JOIN stock_journals j ON j.id = m.journal_id "
             "WHERE m.client_id = :c AND m.financial_year_id = :fy ORDER BY m.movement_date, m.seq"),
        {"c": client_id, "fy": fy_id})
    movements, numbers = [], {}
    for r in rows:
        movements.append(Movement(r[0], r[1], r[2], r[3], r[4], MovementKind(r[5]), r[6].quantize(QTY),
                                  None if r[7] is None else r[7].quantize(CENTS), r[8]))
        numbers[r[0]] = r[9]
    return movements, numbers


@dataclass(frozen=True)
class ItemInfo:
    item_id: uuid.UUID
    sku: str
    name: str
    uqc: str | None


def stock_item_infos(conn: Connection, client_id: object) -> list[ItemInfo]:
    rows = conn.execute(
        text("SELECT s.item_id, s.sku, g.name, g.uqc FROM stock_items s JOIN gst_items g ON g.id = s.item_id "
             "WHERE s.client_id = :c"), {"c": client_id})
    return [ItemInfo(*r) for r in rows]


def godown_names(conn: Connection, client_id: object) -> dict[uuid.UUID, str]:
    rows = conn.execute(text("SELECT id, name FROM godowns WHERE client_id = :c"), {"c": client_id})
    return {r[0]: r[1] for r in rows}


# ======================================================================================================= NRV


@dataclass(frozen=True)
class NrvRow:
    id: uuid.UUID
    item_id: uuid.UUID
    name: str
    as_on_date: date
    nrv_per_unit: Decimal
    basis_note: str
    entered_by: str
    entered_at: datetime


def nrv_rows(conn: Connection, client_id: object, fy_id: object, as_on: date | None) -> list[NrvRow]:
    rows = conn.execute(
        text("SELECT n.id, n.item_id, g.name, n.as_on_date, n.nrv_per_unit, n.basis_note, n.entered_by, n.entered_at "
             "FROM stock_nrv_entries n JOIN gst_items g ON g.id = n.item_id "
             "WHERE n.client_id = :c AND n.financial_year_id = :fy AND (CAST(:d AS date) IS NULL OR n.as_on_date = :d) "
             "ORDER BY n.as_on_date, lower(g.name)"), {"c": client_id, "fy": fy_id, "d": as_on})
    return [NrvRow(r[0], r[1], r[2], r[3], r[4].quantize(CENTS), r[5], r[6], r[7]) for r in rows]


def nrv_row(conn: Connection, client_id: object, item_id: object, as_on: date) -> NrvRow | None:
    row = conn.execute(
        text("SELECT n.id, n.item_id, g.name, n.as_on_date, n.nrv_per_unit, n.basis_note, n.entered_by, n.entered_at "
             "FROM stock_nrv_entries n JOIN gst_items g ON g.id = n.item_id "
             "WHERE n.client_id = :c AND n.item_id = :i AND n.as_on_date = :d"), {"c": client_id, "i": item_id, "d": as_on}).first()
    return None if row is None else NrvRow(row[0], row[1], row[2], row[3], row[4].quantize(CENTS), row[5], row[6], row[7])


def insert_nrv(conn: Connection, nrv_id: uuid.UUID, client_id: object, fy_id: object, item_id: object, as_on: date,
               nrv: Decimal, note: str, actor: str) -> None:
    conn.execute(
        text("INSERT INTO stock_nrv_entries (id, client_id, financial_year_id, item_id, as_on_date, nrv_per_unit, basis_note, "
             "entered_by) VALUES (:id, :c, :fy, :i, :d, :n, :b, :by)"),
        {"id": nrv_id, "c": client_id, "fy": fy_id, "i": item_id, "d": as_on, "n": nrv, "b": note, "by": actor})


def update_nrv(conn: Connection, nrv_id: object, nrv: Decimal, note: str, actor: str) -> None:
    conn.execute(
        text("UPDATE stock_nrv_entries SET nrv_per_unit = :n, basis_note = :b, entered_by = :by, entered_at = now() WHERE id = :id"),
        {"id": nrv_id, "n": nrv, "b": note, "by": actor})


def delete_nrv(conn: Connection, nrv_id: object) -> None:
    conn.execute(text("DELETE FROM stock_nrv_entries WHERE id = :id"), {"id": nrv_id})


def year_has_locked_period(conn: Connection, client_id: object, fy_id: object) -> bool:
    return conn.execute(
        text("SELECT 1 FROM periods WHERE client_id = :c AND financial_year_id = :fy AND status = 'locked' LIMIT 1"),
        {"c": client_id, "fy": fy_id}).first() is not None
