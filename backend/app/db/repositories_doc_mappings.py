"""SQL of the saved party / line mappings and of the draft-builder's queue rows (Phase 7 package E). Plain SQL, no rules."""

import uuid
from typing import Any

from sqlalchemy import Connection, text

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def ledger_row(conn: Connection, client_id: Any, ledger_id: Any) -> tuple[str, bool] | None:
    row = conn.execute(text("SELECT name, is_active FROM ledgers WHERE client_id = :c AND id = :l"),
                       {"c": client_id, "l": ledger_id}).first()
    return None if row is None else (row[0], bool(row[1]))


def item_exists(conn: Connection, client_id: Any, item_id: Any) -> bool:
    return conn.execute(text("SELECT 1 FROM gst_items WHERE client_id = :c AND id = :i"), {"c": client_id, "i": item_id}).first() is not None


# ============================================================================================ party mappings

_PARTY_COLS = "m.id, m.match_kind, m.match_key, m.party_ledger_id, l.name, m.use_count"


def party_rows(conn: Connection, client_id: Any, q: str | None = None) -> list[tuple]:
    rows = conn.execute(
        text(f"SELECT {_PARTY_COLS} FROM party_mappings m JOIN ledgers l ON l.id = m.party_ledger_id AND l.client_id = m.client_id "
             "WHERE m.client_id = :c AND (CAST(:q AS text) IS NULL OR m.match_key LIKE '%' || lower(:q) || '%' "
             "OR lower(l.name) LIKE '%' || lower(:q) || '%') ORDER BY m.match_kind, m.match_key"),
        {"c": client_id, "q": q})
    return [tuple(r) for r in rows]


def party_row(conn: Connection, client_id: Any, mapping_id: Any) -> tuple | None:
    row = conn.execute(
        text(f"SELECT {_PARTY_COLS} FROM party_mappings m JOIN ledgers l ON l.id = m.party_ledger_id AND l.client_id = m.client_id "
             "WHERE m.client_id = :c AND m.id = :i"), {"c": client_id, "i": mapping_id}).first()
    return None if row is None else tuple(row)


def party_by_key(conn: Connection, client_id: Any, match_kind: str, match_key: str) -> tuple | None:
    row = conn.execute(
        text(f"SELECT {_PARTY_COLS} FROM party_mappings m JOIN ledgers l ON l.id = m.party_ledger_id AND l.client_id = m.client_id "
             "WHERE m.client_id = :c AND m.match_kind = :k AND m.match_key = :key"),
        {"c": client_id, "k": match_kind, "key": match_key}).first()
    return None if row is None else tuple(row)


def insert_party(conn: Connection, client_id: Any, match_kind: str, match_key: str, ledger_id: Any, actor: str) -> uuid.UUID:
    return conn.execute(
        text("INSERT INTO party_mappings (client_id, match_kind, match_key, party_ledger_id, created_by) "
             "VALUES (:c, :k, :key, :l, :by) RETURNING id"),
        {"c": client_id, "k": match_kind, "key": match_key, "l": ledger_id, "by": actor}).scalar_one()


def set_party_ledger(conn: Connection, client_id: Any, mapping_id: Any, ledger_id: Any) -> None:
    conn.execute(text("UPDATE party_mappings SET party_ledger_id = :l WHERE client_id = :c AND id = :i"),
                 {"l": ledger_id, "c": client_id, "i": mapping_id})


def delete_party(conn: Connection, client_id: Any, mapping_id: Any) -> None:
    conn.execute(text("DELETE FROM party_mappings WHERE client_id = :c AND id = :i"), {"c": client_id, "i": mapping_id})


def touch_party(conn: Connection, client_id: Any, ids: list) -> None:
    if ids:
        conn.execute(text("UPDATE party_mappings SET use_count = use_count + 1, last_used_at = now() "
                          "WHERE client_id = :c AND id = ANY(:ids)"), {"c": client_id, "ids": list(ids)})


# ============================================================================================ line mappings

_LINE_COLS = ("m.id, m.match_kind, m.match_key, m.party_ledger_id, p.name, m.ledger_id, l.name, m.item_id, i.name, m.use_count")
_LINE_FROM = ("FROM line_mappings m JOIN ledgers l ON l.id = m.ledger_id AND l.client_id = m.client_id "
              "LEFT JOIN ledgers p ON p.id = m.party_ledger_id AND p.client_id = m.client_id "
              "LEFT JOIN gst_items i ON i.id = m.item_id AND i.client_id = m.client_id")


def line_rows(conn: Connection, client_id: Any, q: str | None = None) -> list[tuple]:
    rows = conn.execute(
        text(f"SELECT {_LINE_COLS} {_LINE_FROM} WHERE m.client_id = :c AND (CAST(:q AS text) IS NULL "
             "OR m.match_key LIKE '%' || lower(:q) || '%' OR lower(l.name) LIKE '%' || lower(:q) || '%') "
             "ORDER BY m.match_kind, m.match_key"), {"c": client_id, "q": q})
    return [tuple(r) for r in rows]


def line_row(conn: Connection, client_id: Any, mapping_id: Any) -> tuple | None:
    row = conn.execute(text(f"SELECT {_LINE_COLS} {_LINE_FROM} WHERE m.client_id = :c AND m.id = :i"),
                       {"c": client_id, "i": mapping_id}).first()
    return None if row is None else tuple(row)


def line_by_key(conn: Connection, client_id: Any, match_kind: str, match_key: str, party_ledger_id: Any | None) -> tuple | None:
    row = conn.execute(
        text(f"SELECT {_LINE_COLS} {_LINE_FROM} WHERE m.client_id = :c AND m.match_kind = :k AND m.match_key = :key "
             f"AND coalesce(m.party_ledger_id, CAST('{_ZERO_UUID}' AS uuid)) = coalesce(CAST(:p AS uuid), CAST('{_ZERO_UUID}' AS uuid))"),
        {"c": client_id, "k": match_kind, "key": match_key, "p": party_ledger_id}).first()
    return None if row is None else tuple(row)


def insert_line(conn: Connection, client_id: Any, match_kind: str, match_key: str, party_ledger_id: Any | None, ledger_id: Any,
                item_id: Any | None, actor: str) -> uuid.UUID:
    return conn.execute(
        text("INSERT INTO line_mappings (client_id, match_kind, match_key, party_ledger_id, ledger_id, item_id, created_by) "
             "VALUES (:c, :k, :key, :p, :l, :i, :by) RETURNING id"),
        {"c": client_id, "k": match_kind, "key": match_key, "p": party_ledger_id, "l": ledger_id, "i": item_id, "by": actor}).scalar_one()


def set_line_target(conn: Connection, client_id: Any, mapping_id: Any, ledger_id: Any, item_id: Any | None) -> None:
    conn.execute(text("UPDATE line_mappings SET ledger_id = :l, item_id = :i WHERE client_id = :c AND id = :m"),
                 {"l": ledger_id, "i": item_id, "c": client_id, "m": mapping_id})


def delete_line(conn: Connection, client_id: Any, mapping_id: Any) -> None:
    conn.execute(text("DELETE FROM line_mappings WHERE client_id = :c AND id = :i"), {"c": client_id, "i": mapping_id})


def touch_line(conn: Connection, client_id: Any, ids: list) -> None:
    if ids:
        conn.execute(text("UPDATE line_mappings SET use_count = use_count + 1, last_used_at = now() "
                          "WHERE client_id = :c AND id = ANY(:ids)"), {"c": client_id, "ids": list(ids)})


# ============================================================================================ queue / link rows used by the builder


def live_queue_item(conn: Connection, client_id: Any, extraction_id: Any) -> tuple | None:
    """(id, status, draft_voucher_id, edited_payload) of the open (pending / in review) queue item of an extraction, locked."""
    row = conn.execute(
        text("SELECT id, status, draft_voucher_id, edited_payload FROM approval_queue_items "
             "WHERE client_id = :c AND extraction_id = :e AND status IN ('pending', 'in_review') FOR UPDATE"),
        {"c": client_id, "e": extraction_id}).first()
    return None if row is None else tuple(row)


def update_queue_item(conn: Connection, client_id: Any, item_id: Any, *, findings_json: str, blocking: int, warnings: int,
                      draft_voucher_id: Any | None) -> None:
    conn.execute(
        text("UPDATE approval_queue_items SET findings = CAST(:f AS jsonb), blocking_count = :b, warning_count = :w, "
             "draft_voucher_id = :d WHERE client_id = :c AND id = :i"),
        {"f": findings_json, "b": blocking, "w": warnings, "d": draft_voucher_id, "c": client_id, "i": item_id})


def link_source(conn: Connection, client_id: Any, document_id: Any, voucher_id: Any, actor: str) -> None:
    conn.execute(
        text("INSERT INTO document_vouchers (client_id, document_id, voucher_id, link_kind, linked_by) "
             "VALUES (:c, :d, :v, 'source', :by) ON CONFLICT (document_id, voucher_id) DO NOTHING"),
        {"c": client_id, "d": document_id, "v": voucher_id, "by": actor})


def unlink_voucher(conn: Connection, client_id: Any, voucher_id: Any) -> None:
    conn.execute(text("DELETE FROM document_vouchers WHERE client_id = :c AND voucher_id = :v"), {"c": client_id, "v": voucher_id})


def mark_document_queued(conn: Connection, client_id: Any, document_id: Any) -> None:
    conn.execute(text("UPDATE documents SET status = 'queued' WHERE client_id = :c AND id = :d "
                      "AND status IN ('uploaded', 'text_ready', 'extracted')"), {"c": client_id, "d": document_id})


def document_row(conn: Connection, client_id: Any, document_id: Any) -> tuple | None:
    row = conn.execute(text("SELECT id, doc_type FROM documents WHERE client_id = :c AND id = :d"),
                       {"c": client_id, "d": document_id}).first()
    return None if row is None else tuple(row)


def extraction_row(conn: Connection, client_id: Any, document_id: Any, extraction_id: Any | None) -> tuple | None:
    """(id, status, payload) of the given extraction, or of the newest valid, not superseded one of the document."""
    if extraction_id is not None:
        row = conn.execute(text("SELECT id, status, payload FROM extractions WHERE client_id = :c AND document_id = :d AND id = :e"),
                           {"c": client_id, "d": document_id, "e": extraction_id}).first()
    else:
        row = conn.execute(text("SELECT id, status, payload FROM extractions WHERE client_id = :c AND document_id = :d "
                                "AND status = 'valid' AND superseded_at IS NULL ORDER BY version DESC LIMIT 1"),
                           {"c": client_id, "d": document_id}).first()
    return None if row is None else tuple(row)


def state_names(conn: Connection, on: Any) -> dict[str, str]:
    rows = conn.execute(text("SELECT code, name FROM gst_state_codes WHERE effective_from <= :on AND (effective_to IS NULL OR effective_to >= :on)"),
                        {"on": on})
    return {r[0]: r[1] for r in rows}
