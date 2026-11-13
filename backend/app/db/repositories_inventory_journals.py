"""SQL for stock journals (Phase 5, package D): journals, lines, gapless numbers, and the movements a journal appends.
SQL only: no rules. Every function takes a Connection owned by the caller. (Movements and opening are read here for the
S-01 chain check of a journal; the reports package has its own readers.)"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.inventory_types import Movement, MovementKind, OpeningStock

QTY = Decimal("0.001")
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class JournalRow:
    id: uuid.UUID
    client_id: uuid.UUID
    financial_year_id: uuid.UUID
    journal_type: str
    journal_number: str | None
    journal_date: date
    narration: str
    reason_code: str | None
    reason_note: str | None
    status: str
    created_by: str
    approved_by: str | None
    posted_by: str | None
    reversed_by: str | None
    reverse_reason: str | None
    reversed_at: datetime | None = None


@dataclass(frozen=True)
class JournalLineRow:
    journal_id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_name: str
    from_godown_id: uuid.UUID
    to_godown_id: uuid.UUID | None
    quantity: Decimal


_COLUMNS = ("id, client_id, financial_year_id, journal_type, journal_number, journal_date, narration, reason_code, reason_note, "
            "status, created_by, approved_by, posted_by, reversed_by, reverse_reason, reversed_at")


def get_journal(conn: Connection, client_id: object, journal_id: object, *, lock: bool = False) -> JournalRow | None:
    try:
        uuid.UUID(str(journal_id))
    except ValueError:
        return None
    row = conn.execute(
        text(f"SELECT {_COLUMNS} FROM stock_journals WHERE id = :id AND client_id = :c" + (" FOR UPDATE" if lock else "")),
        {"id": journal_id, "c": client_id}).first()
    return JournalRow(*row) if row else None


def list_journals(conn: Connection, client_id: object, fy_id: object | None, journal_type: str | None, status: str | None,
                  from_date: date | None, to_date: date | None) -> list[JournalRow]:
    rows = conn.execute(
        text(f"SELECT {_COLUMNS} FROM stock_journals WHERE client_id = :c "
             "AND (CAST(:fy AS uuid) IS NULL OR financial_year_id = :fy) AND (CAST(:t AS text) IS NULL OR journal_type = :t) "
             "AND (CAST(:s AS text) IS NULL OR status = :s) AND (CAST(:f AS date) IS NULL OR journal_date >= :f) "
             "AND (CAST(:to AS date) IS NULL OR journal_date <= :to) ORDER BY journal_date, created_at, id"),
        {"c": client_id, "fy": fy_id, "t": journal_type, "s": status, "f": from_date, "to": to_date})
    return [JournalRow(*r) for r in rows]


def lines_of(conn: Connection, client_id: object, journal_ids: list[object]) -> dict[object, list[JournalLineRow]]:
    out: dict[object, list[JournalLineRow]] = {j: [] for j in journal_ids}
    if not journal_ids:
        return out
    rows = conn.execute(
        text("SELECT l.journal_id, l.line_no, l.item_id, g.name, l.from_godown_id, l.to_godown_id, l.quantity "
             "FROM stock_journal_lines l JOIN gst_items g ON g.id = l.item_id AND g.client_id = l.client_id "
             "WHERE l.client_id = :c AND l.journal_id = ANY(CAST(:ids AS uuid[])) ORDER BY l.journal_id, l.line_no"),
        {"c": client_id, "ids": [str(j) for j in journal_ids]})
    for r in rows:
        out[r[0]].append(JournalLineRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6].quantize(QTY)))
    return out


def insert_journal(conn: Connection, client_id: object, journal_id: uuid.UUID, fy_id: object, journal_type: str, on: date,
                   narration: str, reason_code: str | None, reason_note: str | None, actor: str) -> None:
    conn.execute(
        text("INSERT INTO stock_journals (id, client_id, financial_year_id, journal_type, journal_date, narration, reason_code, "
             "reason_note, created_by) VALUES (:id, :c, :fy, :t, :d, :n, :rc, :rn, :by)"),
        {"id": journal_id, "c": client_id, "fy": fy_id, "t": journal_type, "d": on, "n": narration, "rc": reason_code,
         "rn": reason_note, "by": actor})


def update_header(conn: Connection, journal_id: object, on: date, narration: str, reason_code: str | None,
                  reason_note: str | None) -> None:
    conn.execute(
        text("UPDATE stock_journals SET journal_date = :d, narration = :n, reason_code = :rc, reason_note = :rn WHERE id = :id"),
        {"id": journal_id, "d": on, "n": narration, "rc": reason_code, "rn": reason_note})


def replace_lines(conn: Connection, client_id: object, journal_id: object, lines: list) -> None:
    """Delete and insert the lines of a DRAFT journal (the database refuses this for any other status)."""
    conn.execute(text("DELETE FROM stock_journal_lines WHERE journal_id = :id"), {"id": journal_id})
    for line in lines:
        conn.execute(
            text("INSERT INTO stock_journal_lines (journal_id, client_id, line_no, item_id, from_godown_id, to_godown_id, quantity) "
                 "VALUES (:j, :c, :n, :i, :f, :t, :q)"),
            {"j": journal_id, "c": client_id, "n": line.line_no, "i": line.item_id, "f": line.from_godown_id,
             "t": line.to_godown_id, "q": line.quantity})


def delete_journal(conn: Connection, journal_id: object) -> None:
    conn.execute(text("DELETE FROM stock_journals WHERE id = :id"), {"id": journal_id})  # lines cascade (draft only)


def mark_approved(conn: Connection, journal_id: object, actor: str) -> None:
    conn.execute(text("UPDATE stock_journals SET status = 'approved', approved_by = :by, approved_at = now() WHERE id = :id"),
                 {"id": journal_id, "by": actor})


def mark_posted(conn: Connection, journal_id: object, number: str, actor: str) -> None:
    conn.execute(
        text("UPDATE stock_journals SET status = 'posted', journal_number = :n, posted_by = :by, posted_at = now() WHERE id = :id"),
        {"id": journal_id, "n": number, "by": actor})


def mark_reversed(conn: Connection, journal_id: object, reason: str, actor: str) -> None:
    conn.execute(
        text("UPDATE stock_journals SET status = 'reversed', reversed_by = :by, reversed_at = now(), reverse_reason = :r "
             "WHERE id = :id"), {"id": journal_id, "by": actor, "r": reason})


def next_number(conn: Connection, client_id: object, fy_id: object) -> int:
    """Gapless: one upsert under the row lock; a rollback gives the number back."""
    return conn.execute(
        text("INSERT INTO stock_journal_sequences (client_id, financial_year_id, last_number) VALUES (:c, :fy, 1) "
             "ON CONFLICT (client_id, financial_year_id) DO UPDATE SET last_number = stock_journal_sequences.last_number + 1 "
             "RETURNING last_number"), {"c": client_id, "fy": fy_id}).scalar_one()


def lock_stock_chain(conn: Connection, client_id: object) -> None:
    """Serialise writers of one client's stock chronology so two postings cannot each pass S-01 on the same stock."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"stock-chain:{client_id}"})


# ------------------------------------------------------------------------------------------- facts for the rules


def item_activity(conn: Connection, client_id: object, item_ids: list[object]) -> dict[object, bool]:
    """item id -> active, for the ids that are stock items of the client (goods item and stock item both active)."""
    rows = conn.execute(
        text("SELECT s.item_id, (s.is_active AND g.is_active) FROM stock_items s JOIN gst_items g ON g.id = s.item_id "
             "AND g.client_id = s.client_id WHERE s.client_id = :c AND s.item_id = ANY(CAST(:ids AS uuid[]))"),
        {"c": client_id, "ids": [str(i) for i in item_ids]})
    return {r[0]: r[1] for r in rows}


def godown_activity(conn: Connection, client_id: object, godown_ids: list[object]) -> dict[object, bool]:
    rows = conn.execute(
        text("SELECT id, is_active FROM godowns WHERE client_id = :c AND id = ANY(CAST(:ids AS uuid[]))"),
        {"c": client_id, "ids": [str(g) for g in godown_ids]})
    return {r[0]: r[1] for r in rows}


def names(conn: Connection, client_id: object, item_ids: list[object], godown_ids: list[object]) -> dict[object, str]:
    out: dict[object, str] = {}
    for r in conn.execute(text("SELECT id, name FROM gst_items WHERE client_id = :c AND id = ANY(CAST(:ids AS uuid[]))"),
                          {"c": client_id, "ids": [str(i) for i in item_ids]}):
        out[r[0]] = r[1]
    for r in conn.execute(text("SELECT id, name FROM godowns WHERE client_id = :c AND id = ANY(CAST(:ids AS uuid[]))"),
                          {"c": client_id, "ids": [str(g) for g in godown_ids]}):
        out[r[0]] = r[1]
    return out


def financial_years(conn: Connection, client_id: object) -> list[tuple[uuid.UUID, date, date]]:
    return [(r[0], r[1], r[2]) for r in conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c ORDER BY start_date"), {"c": client_id})]


def periods(conn: Connection, client_id: object) -> list[tuple[date, date, str]]:
    return [(r[0], r[1], r[2]) for r in conn.execute(
        text("SELECT period_start, period_end, status FROM periods WHERE client_id = :c ORDER BY period_start"), {"c": client_id})]


# --------------------------------------------------------------------------------- opening and movements for S-01


def load_opening(conn: Connection, client_id: object, fy_id: object, item_ids: list[object]) -> list[OpeningStock]:
    rows = conn.execute(
        text("SELECT item_id, godown_id, quantity, value FROM stock_opening WHERE client_id = :c AND financial_year_id = :fy "
             "AND item_id = ANY(CAST(:ids AS uuid[]))"), {"c": client_id, "fy": fy_id, "ids": [str(i) for i in item_ids]})
    return [OpeningStock(r[0], r[1], r[2].quantize(QTY), r[3].quantize(CENTS)) for r in rows]


def load_movements(conn: Connection, client_id: object, fy_id: object, item_ids: list[object]) -> list[Movement]:
    rows = conn.execute(
        text("SELECT id, seq, movement_date, item_id, godown_id, kind, quantity, value, ref_movement_id FROM stock_movements "
             "WHERE client_id = :c AND financial_year_id = :fy AND item_id = ANY(CAST(:ids AS uuid[])) "
             "ORDER BY movement_date, seq"), {"c": client_id, "fy": fy_id, "ids": [str(i) for i in item_ids]})
    return [Movement(r[0], r[1], r[2], r[3], r[4], MovementKind(r[5]), r[6].quantize(QTY),
                     None if r[7] is None else r[7].quantize(CENTS), r[8]) for r in rows]


def max_seq(conn: Connection) -> int:
    return conn.execute(text("SELECT coalesce(max(seq), 0) FROM stock_movements")).scalar_one()


def journal_movements(conn: Connection, client_id: object, journal_id: object) -> list[Movement]:
    """The movements the journal itself appended (not its reversal mirrors), in posting order."""
    rows = conn.execute(
        text("SELECT id, seq, movement_date, item_id, godown_id, kind, quantity, value, ref_movement_id FROM stock_movements "
             "WHERE client_id = :c AND journal_id = :j AND kind IN ('transfer_in', 'transfer_out', 'write_off') ORDER BY seq"),
        {"c": client_id, "j": journal_id})
    return [Movement(r[0], r[1], r[2], r[3], r[4], MovementKind(r[5]), r[6].quantize(QTY), None, r[8]) for r in rows]


def insert_movement(conn: Connection, client_id: object, fy_id: object, journal_id: object, on: date, kind: MovementKind,
                    item_id: object, godown_id: object, quantity: Decimal, journal_line_no: int | None,
                    ref_movement_id: object, actor: str) -> None:
    direction = "in" if kind in (MovementKind.TRANSFER_IN, MovementKind.REVERSAL_IN) else "out"
    conn.execute(
        text("INSERT INTO stock_movements (client_id, financial_year_id, item_id, godown_id, movement_date, kind, direction, "
             "quantity, journal_id, journal_line_no, ref_movement_id, created_by) "
             "VALUES (:c, :fy, :i, :g, :d, :k, :dir, :q, :j, :ln, :ref, :by)"),
        {"c": client_id, "fy": fy_id, "i": item_id, "g": godown_id, "d": on, "k": kind.value, "dir": direction, "q": quantity,
         "j": journal_id, "ln": journal_line_no, "ref": ref_movement_id, "by": actor})
