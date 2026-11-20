"""Turns a validated extraction into a GST invoice-mode DRAFT voucher through the voucher service (Phase 7 package E).

D-25: the voucher service's own errors (V-xx, G-xx, T-xx, S-xx, B-xx) come back as `error` findings. D-27: while the queue item is
open the draft is rebuilt in place (never duplicated) and removed again if the data becomes blocking. The draft carries a
`source` link to the document. It is only a DRAFT: the database (vouchers_ai_queue_guard) refuses approve / post until the queue
item is accepted. Unknown party / ledger / place of supply is a review finding; nothing is ever created here.

Services take a SQLAlchemy Connection and never commit. Package D's checks arrive as `prior_findings` (injected).
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_doc_mappings as db
from app.engine.doc_build import (
    BuildContext,
    ItemInfo,
    PartyInfo,
    RegistrationInfo,
    build_invoice_draft,
    invoice_from_payload,
)
from app.engine.doc_types import (
    BLOCKING,
    DocFinding,
    DocType,
    ExtractedInvoice,
    QueueKind,
    Severity,
    count_findings,
)
from app.services import (
    ai_hooks,
    audit,
    doc_mappings,
    gst_items,
    gst_registrations,
    parties,
    vouchers,
)
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor


@dataclass(frozen=True)
class DraftOutcome:
    queue_item_id: Any
    status: str
    findings: tuple[DocFinding, ...]
    draft_voucher_id: Any | None
    rebuilt: bool


def load_context(conn: Connection, client_id: Any, doc_type: DocType, *, note_reason: str | None = None,
                 original_invoice_date: date | None = None) -> BuildContext:
    """Everything the pure builder needs, read through the existing Phase 2 / 3 services (read only)."""
    party_maps, line_maps = doc_mappings.load_maps(conn, client_id)
    regs = [RegistrationInfo(r.id, r.gstin, r.state_code, r.effective_from, r.effective_to)
            for r in gst_registrations.list_registrations(conn, client_id) if r.is_active]
    party_info = {str(p.ledger_id): PartyInfo(p.ledger_id, p.gstin, p.state_code, p.gst_registration_type)
                  for p in parties.list_parties(conn, client_id)}
    item_info = {i.id: ItemInfo(i.id, i.hsn_sac, i.uqc) for i in gst_items.list_items(conn, client_id)}
    return BuildContext(client_id, doc_type, regs, party_maps, line_maps, db.state_names(conn, date.today()), party_info, item_info,
                        note_reason, original_invoice_date)


def _service_findings(errors: Sequence) -> list[DocFinding]:
    """D-25: a rule of the voucher service, unchanged, as an error finding."""
    return [DocFinding("D-25", Severity.ERROR, f"[{e.rule_id}] {e.message}") for e in errors]


def _remove_draft(conn: Connection, client_id: Any, voucher_id: Any, actor: str) -> None:
    db.unlink_voucher(conn, client_id, voucher_id)
    vouchers.delete_draft(conn, voucher_id, actor=actor)


def build_draft(
    conn: Connection,
    *,
    client_id: Any,
    document_id: Any,
    extraction_id: Any,
    extracted: ExtractedInvoice,
    doc_type: DocType,
    prior_findings: Sequence[DocFinding] = (),
    actor: str,
    edited_payload: dict | None = None,
    note_reason: str | None = None,
    original_invoice_date: date | None = None,
) -> DraftOutcome:
    """Build (or rebuild in place) the draft and write the queue item. `prior_findings` are the extraction checks (package D).
    A draft exists afterwards only when no error / review finding exists anywhere."""
    actor = require_actor(actor)
    ctx = load_context(conn, client_id, doc_type, note_reason=note_reason, original_invoice_date=original_invoice_date)
    result = build_invoice_draft(extracted, ctx)
    findings = list(prior_findings) + list(result.findings)
    existing = db.live_queue_item(conn, client_id, extraction_id)
    old_draft = None if existing is None else existing[2]

    draft_id = None
    if not any(f.severity in BLOCKING for f in findings) and result.draft is not None:
        if old_draft is not None:
            res = vouchers.update_draft(conn, old_draft, result.draft, actor=actor)
        else:
            res = vouchers.create_draft(conn, result.draft, actor=actor)
        if res.errors:
            findings += _service_findings(res.errors)
        else:
            draft_id = res.voucher_id
    if draft_id is None and old_draft is not None:
        db.update_queue_item(conn, client_id, existing[0], findings_json="[]", blocking=0, warnings=0, draft_voucher_id=None)
        _remove_draft(conn, client_id, old_draft, actor)  # never leave a stale draft behind (D-27)
    if draft_id is not None:
        db.link_source(conn, client_id, document_id, draft_id, actor)
        doc_mappings.touch(conn, client_id, party_map_ids=list(result.party_map_ids), line_map_ids=list(result.line_map_ids))

    blocking, warnings = count_findings(findings)
    if existing is None:
        item_id = ai_hooks.add_queue_item(
            conn, client_id=client_id, kind=QueueKind.INVOICE, document_id=document_id, extraction_id=extraction_id,
            findings=findings, created_by=actor, draft_voucher_id=draft_id, edited_payload=edited_payload)
        status, rebuilt = "pending", False
    else:
        item_id, status, rebuilt = existing[0], existing[1], True
        db.update_queue_item(conn, client_id, item_id, findings_json=json.dumps([f.as_dict() for f in findings]),
                             blocking=blocking, warnings=warnings, draft_voucher_id=draft_id)
        audit.log(conn, AuditEntry(client_id, actor, "queue_item_rebuilt", "approval_queue_item", item_id,
                                   {"draft_voucher_id": None if old_draft is None else str(old_draft)},
                                   {"draft_voucher_id": None if draft_id is None else str(draft_id), "blocking": blocking,
                                    "warnings": warnings}))
    db.mark_document_queued(conn, client_id, document_id)
    return DraftOutcome(item_id, status, tuple(findings), draft_id, rebuilt)


Checker = Callable[[Any, Any, Any, dict], Sequence[DocFinding]]


def _default_checker(conn: Connection, client_id: Any, extraction_id: Any, payload: dict) -> Sequence[DocFinding]:
    """Package D's engine checks of a stored extraction (D-04..D-19). Imported lazily so this package does not depend on it
    being merged; the expected call is `services.extractions.check(conn, client_id, extraction_id, payload)` returning an object
    with `.findings`."""
    try:
        from app.services import extractions
    except ImportError:
        raise ServiceError("checks_unavailable", "The extraction checks are not available in this build.") from None
    return list(extractions.check(conn, client_id, extraction_id, payload).findings)


def build_for_document(conn: Connection, client_id: Any, document_id: Any, extraction_id: Any | None, *, actor: str,
                       checker: Checker | None = None) -> DraftOutcome:
    """The API's entry point: read the extraction (the newest valid one when no id is given), run the checks, build the draft."""
    doc = db.document_row(conn, client_id, document_id)
    if doc is None:
        raise ServiceError("not_found", "Document not found.")
    try:
        doc_type = DocType(doc[1])
    except ValueError:
        raise ServiceError("invalid_document", "Unknown document type.") from None
    ext = db.extraction_row(conn, client_id, document_id, extraction_id)
    if ext is None:
        raise ServiceError("not_found", "No valid extraction found for this document. Extract or enter it first.")
    if ext[1] != "valid":
        raise ServiceError("extraction_invalid", "This extraction is invalid (D-04); no draft can be built from it.")
    live = db.live_queue_item(conn, client_id, ext[0])
    payload = live[3] if live is not None and live[3] else ext[2]  # the accountant's edits, when there are any
    checks = (checker or _default_checker)(conn, client_id, ext[0], payload)
    return build_draft(conn, client_id=client_id, document_id=document_id, extraction_id=ext[0],
                       extracted=invoice_from_payload(payload), doc_type=doc_type, prior_findings=checks, actor=actor,
                       edited_payload=None)
