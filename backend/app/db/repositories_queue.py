"""SQL of the approval queue and of the narration suggestions (Phase 7 package F). Plain SQL, no rules."""

import json
from typing import Any

from sqlalchemy import Connection, text

_ITEM = ("q.id, q.client_id, q.kind, q.document_id, q.extraction_id, q.tally_import_id, q.source_ref, q.status, q.edited_payload, "
         "q.findings, q.blocking_count, q.warning_count, q.draft_voucher_id, q.reviewer, q.acknowledged, q.accepted_by, q.accepted_at, "
         "q.rejected_by, q.rejected_at, q.reject_reason, q.created_by, q.created_at, d.original_filename, d.doc_type, d.content_type, "
         "d.page_count, e.payload AS extraction_payload, e.source AS extraction_source")
_FROM = ("FROM approval_queue_items q JOIN documents d ON d.id = q.document_id AND d.client_id = q.client_id "
         "LEFT JOIN extractions e ON e.id = q.extraction_id AND e.client_id = q.client_id")


def list_items(conn: Connection, client_id: Any, status: str | None, kind: str | None, has_blocking: bool | None) -> list[dict]:
    rows = conn.execute(
        text(f"SELECT {_ITEM} {_FROM} WHERE q.client_id = :c AND (CAST(:s AS text) IS NULL OR q.status = :s) "
             "AND (CAST(:k AS text) IS NULL OR q.kind = :k) "
             "AND (CAST(:b AS boolean) IS NULL OR (q.blocking_count > 0) = CAST(:b AS boolean)) ORDER BY q.created_at, q.id"),
        {"c": client_id, "s": status, "k": kind, "b": has_blocking}).mappings()
    return [dict(r) for r in rows]


def get_item(conn: Connection, client_id: Any, item_id: Any, *, lock: bool = False) -> dict | None:
    row = conn.execute(
        text(f"SELECT {_ITEM} {_FROM} WHERE q.client_id = :c AND q.id = :i" + (" FOR UPDATE OF q" if lock else "")),
        {"c": client_id, "i": item_id}).mappings().first()
    return None if row is None else dict(row)


def set_edited_payload(conn: Connection, client_id: Any, item_id: Any, payload: dict) -> None:
    conn.execute(text("UPDATE approval_queue_items SET edited_payload = CAST(:p AS jsonb) WHERE client_id = :c AND id = :i"),
                 {"p": json.dumps(payload, default=str), "c": client_id, "i": item_id})


def set_state(conn: Connection, client_id: Any, item_id: Any, *, findings_json: str, blocking: int, warnings: int,
              draft_voucher_id: Any | None) -> None:
    conn.execute(
        text("UPDATE approval_queue_items SET findings = CAST(:f AS jsonb), blocking_count = :b, warning_count = :w, "
             "draft_voucher_id = :d WHERE client_id = :c AND id = :i"),
        {"f": findings_json, "b": blocking, "w": warnings, "d": draft_voucher_id, "c": client_id, "i": item_id})


def set_claim(conn: Connection, client_id: Any, item_id: Any, status: str, reviewer: str | None) -> None:
    conn.execute(text("UPDATE approval_queue_items SET status = :s, reviewer = :r WHERE client_id = :c AND id = :i"),
                 {"s": status, "r": reviewer, "c": client_id, "i": item_id})


def clear_draft(conn: Connection, client_id: Any, item_id: Any) -> None:
    conn.execute(text("UPDATE approval_queue_items SET draft_voucher_id = NULL WHERE client_id = :c AND id = :i"),
                 {"c": client_id, "i": item_id})


def mark_accepted(conn: Connection, client_id: Any, item_id: Any, actor: str, acknowledged: list[dict], findings_json: str,
                  blocking: int, warnings: int) -> None:
    conn.execute(
        text("UPDATE approval_queue_items SET status = 'accepted', accepted_by = :by, accepted_at = now(), "
             "acknowledged = CAST(:a AS jsonb), findings = CAST(:f AS jsonb), blocking_count = :b, warning_count = :w "
             "WHERE client_id = :c AND id = :i"),
        {"by": actor, "a": json.dumps(acknowledged), "f": findings_json, "b": blocking, "w": warnings, "c": client_id, "i": item_id})


def mark_rejected(conn: Connection, client_id: Any, item_id: Any, actor: str, reason: str) -> None:
    conn.execute(
        text("UPDATE approval_queue_items SET status = 'rejected', rejected_by = :by, rejected_at = now(), reject_reason = :r "
             "WHERE client_id = :c AND id = :i"), {"by": actor, "r": reason, "c": client_id, "i": item_id})


def reopen_document(conn: Connection, client_id: Any, document_id: Any) -> None:
    conn.execute(text("UPDATE documents SET status = 'extracted' WHERE client_id = :c AND id = :d AND status = 'queued'"),
                 {"c": client_id, "d": document_id})


def draft_voucher(conn: Connection, client_id: Any, voucher_id: Any) -> dict | None:
    row = conn.execute(
        text("SELECT id, status, voucher_type, voucher_date, reference_no, narration, voucher_number FROM vouchers "
             "WHERE client_id = :c AND id = :v"), {"c": client_id, "v": voucher_id}).mappings().first()
    if row is None:
        return None
    lines = conn.execute(
        text("SELECT vl.line_no, vl.ledger_id, l.name, vl.debit, vl.credit FROM voucher_lines vl "
             "JOIN ledgers l ON l.id = vl.ledger_id AND l.client_id = :c WHERE vl.voucher_id = :v ORDER BY vl.line_no"),
        {"c": client_id, "v": voucher_id}).mappings()
    return {**dict(row), "lines": [dict(x) for x in lines]}


def history(conn: Connection, client_id: Any, item_id: Any) -> list[dict]:
    rows = conn.execute(
        text("SELECT id, actor, action, old_data, new_data, created_at FROM audit_log WHERE client_id = :c "
             "AND entity = 'approval_queue_item' AND entity_id = :i ORDER BY id"), {"c": client_id, "i": item_id}).mappings()
    return [dict(r) for r in rows]


def first_edit_old(conn: Connection, client_id: Any, item_id: Any) -> dict | None:
    row = conn.execute(
        text("SELECT old_data FROM audit_log WHERE client_id = :c AND entity = 'approval_queue_item' AND entity_id = :i "
             "AND action = 'queue_item_edited' ORDER BY id LIMIT 1"), {"c": client_id, "i": item_id}).first()
    return None if row is None else row[0]


def ledger_in_client(conn: Connection, client_id: Any, ledger_id: Any) -> bool:
    return conn.execute(text("SELECT 1 FROM ledgers WHERE client_id = :c AND id = :l"), {"c": client_id, "l": ledger_id}).first() is not None


# ============================================================================================ narration


def statement_line(conn: Connection, client_id: Any, line_id: Any) -> dict | None:
    row = conn.execute(
        text("SELECT l.id, l.description, l.debit, l.credit, s.bank_ledger_id FROM bank_statement_lines l "
             "JOIN bank_statements s ON s.id = l.statement_id AND s.client_id = l.client_id "
             "WHERE l.client_id = :c AND l.id = :i"), {"c": client_id, "i": line_id}).mappings().first()
    return None if row is None else dict(row)


def rules_for_key(conn: Connection, client_id: Any, direction: str, key: str) -> list[tuple]:
    rows = conn.execute(
        text("SELECT r.ledger_id, r.approved_count, r.is_active, l.name FROM narration_rules r "
             "JOIN ledgers l ON l.id = r.ledger_id AND l.client_id = r.client_id "
             "WHERE r.client_id = :c AND r.direction = :d AND r.narration_key = :k"), {"c": client_id, "d": direction, "k": key})
    return [tuple(r) for r in rows]


def learn_rule(conn: Connection, client_id: Any, direction: str, key: str, ledger_id: Any, actor: str) -> None:
    conn.execute(
        text("INSERT INTO narration_rules (client_id, direction, narration_key, ledger_id, created_by) "
             "VALUES (:c, :d, :k, :l, :by) ON CONFLICT (client_id, direction, narration_key, ledger_id) "
             "DO UPDATE SET approved_count = narration_rules.approved_count + 1, last_approved_at = now()"),
        {"c": client_id, "d": direction, "k": key, "l": ledger_id, "by": actor})


def list_rules(conn: Connection, client_id: Any) -> list[dict]:
    rows = conn.execute(
        text("SELECT r.id, r.direction, r.narration_key, r.ledger_id, l.name AS ledger_name, r.approved_count, r.is_active "
             "FROM narration_rules r JOIN ledgers l ON l.id = r.ledger_id AND l.client_id = r.client_id "
             "WHERE r.client_id = :c ORDER BY r.direction, r.narration_key, l.name"), {"c": client_id}).mappings()
    return [dict(r) for r in rows]


def rule_row(conn: Connection, client_id: Any, rule_id: Any) -> dict | None:
    row = conn.execute(
        text("SELECT r.id, r.direction, r.narration_key, r.ledger_id, l.name AS ledger_name, r.approved_count, r.is_active "
             "FROM narration_rules r JOIN ledgers l ON l.id = r.ledger_id AND l.client_id = r.client_id "
             "WHERE r.client_id = :c AND r.id = :i"), {"c": client_id, "i": rule_id}).mappings().first()
    return None if row is None else dict(row)


def set_rule_active(conn: Connection, client_id: Any, rule_id: Any, active: bool) -> None:
    conn.execute(text("UPDATE narration_rules SET is_active = :a WHERE client_id = :c AND id = :i"),
                 {"a": active, "c": client_id, "i": rule_id})


def option_ledgers(conn: Connection, client_id: Any, exclude_ledger_id: Any) -> list[tuple]:
    """(id, name) of the ledgers a bank entry can be booked to by the model's choice: active, not cash / bank, not the statement's own."""
    rows = conn.execute(
        text("SELECT l.id, l.name FROM ledgers l JOIN account_groups g ON g.id = l.group_id WHERE l.client_id = :c AND l.is_active "
             "AND g.code NOT IN ('bank_accounts', 'cash_in_hand') AND l.id <> :x ORDER BY lower(l.name), l.id"),
        {"c": client_id, "x": exclude_ledger_id})
    return [tuple(r) for r in rows]


_SUG = ("s.id, s.bank_statement_line_id, s.source, s.suggested_ledger_id, l.name AS ledger_name, s.reason, s.confidence, s.llm_call_id, "
        "s.status")


def suggestions_for_line(conn: Connection, client_id: Any, line_id: Any) -> list[dict]:
    rows = conn.execute(
        text(f"SELECT {_SUG} FROM narration_suggestions s JOIN ledgers l ON l.id = s.suggested_ledger_id AND l.client_id = s.client_id "
             "WHERE s.client_id = :c AND s.bank_statement_line_id = :i ORDER BY s.created_at, s.id"), {"c": client_id, "i": line_id}).mappings()
    return [dict(r) for r in rows]


def suggestion_row(conn: Connection, client_id: Any, suggestion_id: Any, *, lock: bool = False) -> dict | None:
    row = conn.execute(
        text(f"SELECT {_SUG}, s.created_by FROM narration_suggestions s JOIN ledgers l ON l.id = s.suggested_ledger_id "
             "AND l.client_id = s.client_id WHERE s.client_id = :c AND s.id = :i" + (" FOR UPDATE OF s" if lock else "")),
        {"c": client_id, "i": suggestion_id}).mappings().first()
    return None if row is None else dict(row)


def insert_suggestion(conn: Connection, client_id: Any, line_id: Any, source: str, ledger_id: Any, reason: str,
                      confidence: Any, llm_call_id: Any, actor: str) -> Any:
    return conn.execute(
        text("INSERT INTO narration_suggestions (client_id, bank_statement_line_id, source, suggested_ledger_id, reason, confidence, "
             "llm_call_id, created_by) VALUES (:c, :l, :s, :g, :r, :f, :k, :by) RETURNING id"),
        {"c": client_id, "l": line_id, "s": source, "g": ledger_id, "r": reason, "f": confidence, "k": llm_call_id,
         "by": actor}).scalar_one()


def decide_suggestion(conn: Connection, client_id: Any, suggestion_id: Any, status: str, actor: str) -> None:
    conn.execute(
        text("UPDATE narration_suggestions SET status = :s, decided_by = :by, decided_at = now() WHERE client_id = :c AND id = :i"),
        {"s": status, "by": actor, "c": client_id, "i": suggestion_id})


def line_description(conn: Connection, client_id: Any, line_id: Any) -> str | None:
    row = conn.execute(text("SELECT description FROM bank_statement_lines WHERE client_id = :c AND id = :i"),
                       {"c": client_id, "i": line_id}).first()
    return None if row is None else row[0]
