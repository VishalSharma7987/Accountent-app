"""Hook points shared by the Phase 7 packages (docs/PHASE7_PLAN.md). The bodies are final (small reads and one insert); packages
A..G call them instead of each writing their own SQL, so no two packages touch the same table logic.

  llm_enabled / require_llm_enabled - D-51: is any model call allowed for this client (client_ai_settings.llm_enabled)?
  add_queue_item                    - D-60/D-64: put one proposal (extracted invoice or Tally voucher) into the approval queue as
                                      'pending' with its findings and optional draft voucher; audit-logged. Packages B and D call it;
                                      package F owns every later queue action (claim, edit, accept, reject).
  guard_voucher_change              - friendly message in front of the database guard vouchers_ai_queue_guard (D-62): refuse to
                                      approve / post a voucher whose queue item is not accepted. Package F wires the call into
                                      services/vouchers.py (approve and post), the database trigger remains the backstop.
"""

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, text

from app.engine.doc_types import DocFinding, QueueKind, count_findings
from app.services import audit
from app.services.errors import ServiceError


def llm_enabled(conn: Connection, client_id: Any) -> bool:
    row = conn.execute(text("SELECT llm_enabled FROM client_ai_settings WHERE client_id = :c"), {"c": client_id}).first()
    return bool(row and row[0])


def require_llm_enabled(conn: Connection, client_id: Any) -> None:
    if not llm_enabled(conn, client_id):
        raise ServiceError(
            "llm_disabled",
            "AI reading is switched off for this client (D-51). Enter the invoice by hand, or switch it on in the client's AI settings "
            "after confirming that only synthetic or anonymised data is used.",
        )


def add_queue_item(
    conn: Connection,
    *,
    client_id: Any,
    kind: QueueKind,
    document_id: Any,
    findings: Sequence[DocFinding],
    created_by: str,
    extraction_id: Any = None,
    tally_import_id: Any = None,
    source_ref: str | None = None,
    draft_voucher_id: Any = None,
    edited_payload: dict | None = None,
) -> Any:
    blocking, warnings = count_findings(findings)
    row = conn.execute(
        text(
            "INSERT INTO approval_queue_items (client_id, kind, document_id, extraction_id, tally_import_id, source_ref, edited_payload, "
            "findings, blocking_count, warning_count, draft_voucher_id, created_by) "
            "VALUES (:client_id, :kind, :document_id, :extraction_id, :tally_import_id, :source_ref, CAST(:edited AS jsonb), "
            "CAST(:findings AS jsonb), :blocking, :warnings, :draft, :by) RETURNING id"
        ),
        {
            "client_id": client_id, "kind": kind.value, "document_id": document_id, "extraction_id": extraction_id,
            "tally_import_id": tally_import_id, "source_ref": source_ref,
            "edited": None if edited_payload is None else json.dumps(edited_payload, default=str),
            "findings": json.dumps([f.as_dict() for f in findings]), "blocking": blocking, "warnings": warnings,
            "draft": draft_voucher_id, "by": created_by,
        },
    ).one()
    audit.log(conn, audit.AuditEntry(client_id, created_by, "queue_item_created", "approval_queue_item", row[0], None,
                                     {"kind": kind.value, "document_id": str(document_id), "blocking": blocking, "warnings": warnings,
                                      "draft_voucher_id": None if draft_voucher_id is None else str(draft_voucher_id)}))
    return row[0]


def guard_voucher_change(conn: Connection, client_id: Any, voucher_id: Any) -> None:
    """Raise ServiceError('queue_not_accepted') if the voucher was drafted by an import / extraction and not accepted yet."""
    row = conn.execute(
        text("SELECT status FROM approval_queue_items WHERE client_id = :c AND draft_voucher_id = :v AND status <> 'accepted'"),
        {"c": client_id, "v": voucher_id},
    ).first()
    if row is not None:
        raise ServiceError(
            "queue_not_accepted",
            "This voucher was drafted from a document or an import and has not been accepted in the approval queue (D-62). "
            "Accept it there first; then approve and post it as usual.",
        )
