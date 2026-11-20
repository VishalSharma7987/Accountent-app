"""The approval queue (Phase 7 package F, D-60..D-64): list, claim, edit with the checks re-run, accept, reject.

Items are created by packages D / E (extracted invoices) and B (Tally vouchers) through `ai_hooks.add_queue_item`. Everything after that
is here. The rules, in order of importance:

* Accepting NEVER posts (D-62). It marks the item accepted when, at that moment, the engine and the voucher service find no error and
  no review finding, every warning has been acknowledged by rule id + field path, and the draft exists. The checks are re-run by this
  service (the stored counts are not trusted); the database repeats the same gate (approval_queue_accepted_complete,
  vouchers_ai_queue_guard) as a backstop.
* Every edit is applied to a COPY of the current payload, stored in `edited_payload`; the AI's answer (`extractions.payload`) never
  changes (D-61). Each edit re-runs the checks and rebuilds the draft in place, or removes it when something blocking is left (D-27).
* Reject needs a reason and removes the draft in the safe order: clear the item's draft link, delete the document link, delete the
  draft through the voucher service, then mark the item rejected (D-63).
* Learning (party / line mappings) comes only from the accountant's final values at accept (D-26).
* Every action is written to the audit log with old and new values (D-64).

Expected outcomes of an edit are results (findings), not exceptions; refusals (blocked accept, wrong state) are ServiceErrors.
Services take a Connection and never commit.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_doc_mappings as doc_db
from app.db import repositories_extractions as ext_db
from app.db import repositories_queue as repo
from app.engine import queue_edit
from app.engine.doc_build import invoice_from_payload, normalise_gstin, parse_date
from app.engine.doc_map import MappingKeyError, line_key, party_key
from app.engine.doc_types import (
    BLOCKING,
    DocFinding,
    DocType,
    QueueKind,
    Severity,
    count_findings,
)
from app.engine.models import VoucherDraft, VoucherLine
from app.engine.tally_map import VOUCHER_TYPES
from app.services import audit, doc_drafts, doc_mappings, extractions, vouchers
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

OPEN = ("pending", "in_review")
_AMOUNT = re.compile(r"^\d+(\.\d{1,2})?$")
_TALLY_VOUCHER_TYPES = frozenset(VOUCHER_TYPES.values())
_CARRIED_RULES = ("D-33", "D-35")  # import warnings of a Tally voucher stay on the item after an edit


@dataclass(frozen=True)
class EditResult:
    status: str
    findings: tuple[DocFinding, ...]
    draft_voucher_id: Any | None


@dataclass(frozen=True)
class AcceptResult:
    draft_voucher_id: Any
    learned: dict = field(default_factory=dict)


# ============================================================================================ small helpers


def _findings_json(findings) -> str:
    return json.dumps([f.as_dict() for f in findings])


def _finding_from_dict(d: dict) -> DocFinding:
    return DocFinding(d["rule_id"], Severity(d["severity"]), d["message"], d.get("field_path"), d.get("printed"), d.get("computed"))


def stored_findings(item: dict) -> list[DocFinding]:
    return [_finding_from_dict(d) for d in (item["findings"] or [])]


def _load(conn: Connection, client_id: Any, item_id: Any, *, lock: bool = False) -> dict:
    item = repo.get_item(conn, client_id, item_id, lock=lock)
    if item is None:
        raise ServiceError("not_found", "Queue item not found.")
    return item


def _require_open(item: dict, actor: str) -> None:
    if item["status"] not in OPEN:
        raise ServiceError("queue_state", f"This item is already {item['status']}; it cannot be changed any more.")
    if item["status"] == "in_review" and item["reviewer"] != actor:
        raise ServiceError("queue_state", f"This item is being reviewed by {item['reviewer']}. Ask them to release it first.")


def current_payload(item: dict) -> dict:
    if item["kind"] == QueueKind.TALLY_VOUCHER.value:
        return dict(item["edited_payload"] or {})
    return dict(item["edited_payload"] or item["extraction_payload"] or {})


def original_payload(conn: Connection, item: dict) -> dict:
    """The extraction as read (never changes). A Tally proposal lives in edited_payload from the start; its first version is kept in
    the audit row of the first edit."""
    if item["kind"] == QueueKind.INVOICE.value:
        return dict(item["extraction_payload"] or {})
    first = repo.first_edit_old(conn, item["client_id"], item["id"])
    if first and isinstance(first.get("payload"), dict):
        return first["payload"]
    return dict(item["edited_payload"] or {})


def _field_value(payload: dict, key: str) -> str | None:
    node = payload.get(key)
    value = node.get("value") if isinstance(node, dict) else None
    return None if value is None else str(value)


def summary(item: dict) -> dict:
    p = current_payload(item)
    if item["kind"] == QueueKind.TALLY_VOUCHER.value:
        return {"party": p.get("party_ledger_name"), "reference_no": p.get("reference_no") or p.get("number"),
                "date": p.get("voucher_date"), "total": p.get("total")}
    outward = item["doc_type"] in (DocType.SALES_INVOICE.value, DocType.CREDIT_NOTE.value)
    totals = p.get("totals") if isinstance(p.get("totals"), dict) else {}
    grand = totals.get("grand_total")
    return {"party": _field_value(p, "buyer_name" if outward else "supplier_name"), "reference_no": _field_value(p, "invoice_no"),
            "date": _field_value(p, "invoice_date"), "total": grand.get("value") if isinstance(grand, dict) else None}


# ============================================================================================ reads


def list_items(conn: Connection, client_id: Any, *, status: str | None = None, kind: str | None = None,
               has_blocking: bool | None = None) -> list[dict]:
    if status is not None and status not in ("pending", "in_review", "accepted", "rejected"):
        raise ServiceError("invalid_status", "Status must be pending, in_review, accepted or rejected.")
    if kind is not None and kind not in (k.value for k in QueueKind):
        raise ServiceError("invalid_kind", "Kind must be invoice or tally_voucher.")
    return [{**i, "summary": summary(i)} for i in repo.list_items(conn, client_id, status, kind, has_blocking)]


def get_detail(conn: Connection, client_id: Any, item_id: Any) -> dict:
    item = _load(conn, client_id, item_id)
    draft = None if item["draft_voucher_id"] is None else repo.draft_voucher(conn, client_id, item["draft_voucher_id"])
    return {**item, "summary": summary(item), "original": original_payload(conn, item), "current": current_payload(item),
            "draft_voucher": draft, "history": repo.history(conn, client_id, item_id)}


# ============================================================================================ claim / release


def claim(conn: Connection, client_id: Any, item_id: Any, *, actor: str) -> None:
    actor = require_actor(actor)
    item = _load(conn, client_id, item_id, lock=True)
    if item["status"] not in OPEN:
        raise ServiceError("queue_state", f"This item is already {item['status']}.")
    if item["status"] == "in_review":
        if item["reviewer"] == actor:
            return
        raise ServiceError("queue_state", f"This item is already being reviewed by {item['reviewer']}.")
    repo.set_claim(conn, client_id, item_id, "in_review", actor)
    audit.log(conn, AuditEntry(client_id, actor, "queue_item_claimed", "approval_queue_item", item_id, {"status": "pending"},
                               {"status": "in_review", "reviewer": actor}))


def release(conn: Connection, client_id: Any, item_id: Any, *, actor: str) -> None:
    actor = require_actor(actor)
    item = _load(conn, client_id, item_id, lock=True)
    if item["status"] == "pending":
        return
    if item["status"] != "in_review":
        raise ServiceError("queue_state", f"This item is already {item['status']}.")
    if item["reviewer"] != actor:
        raise ServiceError("queue_state", f"Only {item['reviewer']} can release this item.")
    repo.set_claim(conn, client_id, item_id, "pending", None)
    audit.log(conn, AuditEntry(client_id, actor, "queue_item_released", "approval_queue_item", item_id,
                               {"status": "in_review", "reviewer": actor}, {"status": "pending"}))


# ============================================================================================ recompute (checks + draft)


def _drop_draft(conn: Connection, item: dict, actor: str) -> None:
    """Remove the item's draft in the safe order: the item's own link first (foreign key), then the document link, then the draft."""
    draft_id = item["draft_voucher_id"]
    if draft_id is None:
        return
    repo.clear_draft(conn, item["client_id"], item["id"])
    doc_db.unlink_voucher(conn, item["client_id"], draft_id)
    vouchers.delete_draft(conn, draft_id, actor=actor)


def _store_state(conn: Connection, item: dict, findings: list[DocFinding], draft_id: Any | None) -> None:
    blocking, warnings = count_findings(findings)
    repo.set_state(conn, item["client_id"], item["id"], findings_json=_findings_json(findings), blocking=blocking, warnings=warnings,
                   draft_voucher_id=draft_id)


def _split_note(payload: dict) -> tuple[dict, str | None, date | None]:
    """credit / debit notes: the reason and the original invoice date are not on the extraction schema; they live in `_note`."""
    clean = {k: v for k, v in payload.items() if k != "_note"}
    note = payload.get("_note") if isinstance(payload.get("_note"), dict) else {}
    return clean, (note.get("note_reason") or None), parse_date(note.get("original_invoice_date"))


def _recompute_invoice(conn: Connection, item: dict, payload: dict, actor: str) -> tuple[list[DocFinding], Any | None]:
    clean, reason, original_date = _split_note(payload)
    ext = ext_db.extraction_row(conn, item["client_id"], item["extraction_id"])
    check = extractions.check_payload(conn, item["client_id"], item["document_id"], clean, source=ext.source)
    if any(f.rule_id == "D-04" for f in check.findings):
        findings = list(check.findings)
        _drop_draft(conn, item, actor)
        _store_state(conn, item, findings, None)
        return findings, None
    out = doc_drafts.build_draft(
        conn, client_id=item["client_id"], document_id=item["document_id"], extraction_id=item["extraction_id"],
        extracted=invoice_from_payload(clean), doc_type=DocType(item["doc_type"]), prior_findings=check.findings, actor=actor,
        note_reason=reason, original_invoice_date=original_date)
    return list(out.findings), out.draft_voucher_id


def _amount(raw: Any) -> Decimal | None:
    return Decimal(raw) if isinstance(raw, str) and _AMOUNT.match(raw.strip()) else None


def _uuid(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None


def _recompute_tally(conn: Connection, item: dict, payload: dict, actor: str) -> tuple[list[DocFinding], Any | None]:
    client_id = item["client_id"]
    findings = [f for f in stored_findings(item) if f.severity == Severity.WARNING and f.rule_id in _CARRIED_RULES]
    vtype = payload.get("voucher_type")
    if vtype not in _TALLY_VOUCHER_TYPES:
        findings.append(DocFinding("D-34", Severity.ERROR, "The voucher type is not one that can be drafted.", "voucher_type"))
    try:
        vdate = date.fromisoformat(str(payload.get("voucher_date")))
    except ValueError:
        vdate = None
        findings.append(DocFinding("D-06", Severity.ERROR, "The voucher date is not a date (yyyy-mm-dd).", "voucher_date"))
    lines: list[VoucherLine] = []
    by_name: dict[str, Any] = {}
    for n, raw in enumerate(payload.get("lines") or []):
        base = f"lines[{n}]"
        name = str(raw.get("tally_ledger_name") or "").strip() or f"line {n + 1}"
        ledger = _uuid(raw.get("ledger_id"))
        if ledger is None or not repo.ledger_in_client(conn, client_id, ledger):
            findings.append(DocFinding("D-31", Severity.REVIEW, f"Line {n + 1} ('{name}') has no ledger of this client yet; choose it.",
                                       f"{base}.ledger_id"))
            continue
        debit, credit = _amount(raw.get("debit")), _amount(raw.get("credit"))
        if debit is None or credit is None:
            findings.append(DocFinding("D-06", Severity.ERROR, f"Line {n + 1} ('{name}'): amounts must be plain numbers with at most "
                                       "2 decimal places.", f"{base}.debit"))
            continue
        by_name[name.casefold()] = ledger
        lines.append(VoucherLine(ledger, debit if debit else None, credit if credit else None))
    party_name = str(payload.get("party_ledger_name") or "").strip()
    party = None
    if party_name:
        party = by_name.get(party_name.casefold())
        if party is None:
            findings.append(DocFinding("D-31", Severity.REVIEW, f"The party '{party_name}' is not one of the lines. Add its line or "
                                       "clear the party.", "party_ledger_name"))
    draft_id = item["draft_voucher_id"]
    if any(f.severity in BLOCKING for f in findings) or vdate is None:
        _drop_draft(conn, item, actor)
        _store_state(conn, item, findings, None)
        return findings, None
    draft = VoucherDraft(client_id, vtype, vdate, payload.get("narration"), payload.get("reference_no"), party, tuple(lines))
    made = None
    try:
        with conn.begin_nested():
            made = vouchers.update_draft(conn, draft_id, draft, actor=actor) if draft_id is not None \
                else vouchers.create_draft(conn, draft, actor=actor)
    except ServiceError as exc:
        findings.append(DocFinding(exc.code, Severity.ERROR, exc.message))
    if made is not None:
        for e in made.errors:
            findings.append(DocFinding(e.rule_id, Severity.ERROR, e.message, None if e.line_no is None else f"lines[{e.line_no - 1}]"))
    if made is None or made.errors:
        _drop_draft(conn, item, actor)
        _store_state(conn, item, findings, None)
        return findings, None
    new_id = made.voucher_id
    if draft_id is None:
        doc_db.link_source(conn, client_id, item["document_id"], new_id, actor)
    _store_state(conn, item, findings, new_id)
    return findings, new_id


def _recompute(conn: Connection, item: dict, payload: dict, actor: str) -> tuple[list[DocFinding], Any | None]:
    if item["kind"] == QueueKind.TALLY_VOUCHER.value:
        return _recompute_tally(conn, item, payload, actor)
    return _recompute_invoice(conn, item, payload, actor)


# ============================================================================================ edit (D-61)


def _apply_edits(item: dict, payload: dict, edits: list[tuple[str, Any]]) -> tuple[dict, dict, dict]:
    """(new payload, {path: old value}, {path: new value})."""
    old: dict = {}
    new: dict = {}
    for path, value in edits:
        if path in ("note_reason", "original_invoice_date") and item["kind"] == QueueKind.INVOICE.value:
            note = dict(payload.get("_note") or {})
            old[path] = note.get(path)
            if value is not None and not isinstance(value, str):
                raise ServiceError("invalid_value", f"'{path}' takes text.")
            note[path] = value.strip() if isinstance(value, str) and value.strip() else None
            payload = {**payload, "_note": note}
            new[path] = note[path]
            continue
        try:
            payload, was = queue_edit.set_path(payload, path, value)
        except queue_edit.PathError as exc:
            raise ServiceError("invalid_field_path", str(exc)) from None
        old[path] = was
        new[path] = queue_edit.value_at(payload, path)
    return payload, old, new


def edit_fields(conn: Connection, client_id: Any, item_id: Any, *, edits: list[tuple[str, Any]] | None = None,
                payload: dict | None = None, actor: str) -> EditResult:
    actor = require_actor(actor)
    if (edits is None) == (payload is None):
        raise ServiceError("invalid_request", "Send either a list of edits or a whole payload.")
    item = _load(conn, client_id, item_id, lock=True)
    _require_open(item, actor)
    before = current_payload(item)
    if payload is not None:
        if not isinstance(payload, dict):
            raise ServiceError("invalid_request", "The payload must be an object.")
        if item["kind"] == QueueKind.TALLY_VOUCHER.value and payload.get("source") != "tally":
            raise ServiceError("invalid_request", "A Tally proposal keeps its shape (source = tally).")
        after = payload
        old_log, new_log = {"payload": before}, {"payload": after}
    else:
        after, old, new = _apply_edits(item, before, edits or [])
        if item["kind"] == QueueKind.TALLY_VOUCHER.value:
            old_log, new_log = {"payload": before, "edits": old}, {"payload": after, "edits": new}
        else:
            old_log, new_log = {"edits": old}, {"edits": new}
    repo.set_edited_payload(conn, client_id, item_id, after)
    findings, draft_id = _recompute(conn, item, after, actor)
    blocking, warnings = count_findings(findings)
    audit.log(conn, AuditEntry(client_id, actor, "queue_item_edited", "approval_queue_item", item_id, old_log,
                               {**new_log, "blocking": blocking, "warnings": warnings,
                                "draft_voucher_id": None if draft_id is None else str(draft_id)}))
    return EditResult(item["status"], tuple(findings), draft_id)


# ============================================================================================ accept (D-60, D-62, D-26)


def _ack_key(rule_id: str, field_path: str | None) -> tuple[str, str]:
    return rule_id, field_path or ""


def _learn(conn: Connection, item: dict, payload: dict, actor: str) -> dict:
    """D-26: save party / line mappings from the accountant's FINAL values (the draft the engine just built from them)."""
    from app.engine.doc_build import build_invoice_draft

    clean, reason, original_date = _split_note(payload)
    ctx = doc_drafts.load_context(conn, item["client_id"], DocType(item["doc_type"]), note_reason=reason,
                                  original_invoice_date=original_date)
    inv = invoice_from_payload(clean)
    built = build_invoice_draft(inv, ctx)
    if built.draft is None or built.draft.gst is None:
        return {}
    outward = built.draft.voucher_type in ("sales", "credit_note")
    p_name, p_gstin = (inv.buyer_name, inv.buyer_gstin) if outward else (inv.supplier_name, inv.supplier_gstin)
    party = built.draft.party_ledger_id
    report: dict = {"party": [], "lines": []}
    cid = item["client_id"]

    def party_step(kind: str, raw: str | None) -> None:
        try:
            key = party_key(kind, raw)
        except MappingKeyError:
            return
        found = doc_db.party_by_key(conn, cid, kind, key)
        if found is not None and str(found[3]) == str(party):
            report["party"].append("unchanged")  # already saved: nothing to learn, no extra use count
            return
        report["party"].append(doc_mappings.learn_party_mapping(conn, cid, match_kind=kind, match_key=raw, party_ledger_id=party,
                                                                 actor=actor))

    party_step("gstin", normalise_gstin(p_gstin.value))
    party_step("name", p_name.value)
    for src, built_line in zip(inv.lines, built.draft.gst.items, strict=False):
        ledger = uuid.UUID(str(built_line.ledger_id))
        item_id = None if built_line.item_id is None else uuid.UUID(str(built_line.item_id))
        for kind, raw in (("description", src.description.value), ("hsn_sac", src.hsn_sac.value)):
            try:
                key = line_key(kind, raw)
            except MappingKeyError:
                continue
            general = doc_db.line_by_key(conn, cid, kind, key, None)
            if general is not None and str(general[5]) == str(ledger):
                report["lines"].append("unchanged")  # a general mapping already gives this ledger
                continue
            report["lines"].append(doc_mappings.learn_line_mapping(conn, cid, match_kind=kind, match_key=raw, ledger_id=ledger,
                                                                    party_ledger_id=party, item_id=item_id, actor=actor))
    return report


def accept(conn: Connection, client_id: Any, item_id: Any, *, acknowledge: list[dict] | None = None, learn: bool = True,
           actor: str) -> AcceptResult:
    actor = require_actor(actor)
    item = _load(conn, client_id, item_id, lock=True)
    _require_open(item, actor)
    payload = current_payload(item)
    findings, draft_id = _recompute(conn, item, payload, actor)  # never trust the stored counts
    blocking = [f for f in findings if f.severity in BLOCKING]
    if blocking:
        shown = "; ".join(f.message for f in blocking[:3]) + (" ..." if len(blocking) > 3 else "")
        raise ServiceError("queue_blocked", f"{len(blocking)} finding(s) must be fixed before this item can be accepted: {shown}",
                           {"findings": [f.as_dict() for f in blocking]})
    if draft_id is None:
        raise ServiceError("queue_blocked", "There is no draft voucher for this item; fix the findings first.", {"findings": []})
    given = {_ack_key(a.get("rule_id", ""), a.get("field_path")) for a in (acknowledge or [])}
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    missing = [f for f in warnings if _ack_key(f.rule_id, f.field_path) not in given]
    if missing:
        raise ServiceError(
            "queue_blocked", f"{len(missing)} warning(s) must be acknowledged (rule id and field) before this item is accepted: "
            + "; ".join(f"{f.rule_id}: {f.message}" for f in missing[:3]) + (" ..." if len(missing) > 3 else ""),
            {"unacknowledged": [f.as_dict() for f in missing]})
    acks = [{"rule_id": f.rule_id, "field_path": f.field_path, "by": actor} for f in warnings]
    repo.mark_accepted(conn, client_id, item_id, actor, acks, _findings_json(findings), 0, len(warnings))
    doc_db.link_source(conn, client_id, item["document_id"], draft_id, actor)  # ON CONFLICT DO NOTHING (package E)
    learned: dict = {}
    if learn and item["kind"] == QueueKind.INVOICE.value:
        learned = _learn(conn, item, payload, actor)
    audit.log(conn, AuditEntry(client_id, actor, "queue_item_accepted", "approval_queue_item", item_id,
                               {"status": item["status"], "blocking": item["blocking_count"], "warnings": item["warning_count"]},
                               {"status": "accepted", "draft_voucher_id": str(draft_id), "acknowledged": acks, "learned": learned}))
    return AcceptResult(draft_id, learned)


def accept_clean(conn: Connection, client_id: Any, ids: list[Any], *, actor: str) -> dict:
    """Bulk acceptance of items with no blocking finding and no warning. Each item goes through `accept` in its own savepoint."""
    actor = require_actor(actor)
    accepted: list[str] = []
    refused: list[dict] = []
    for item_id in ids:
        try:
            with conn.begin_nested():
                item = _load(conn, client_id, item_id)
                if item["blocking_count"] or item["warning_count"]:
                    raise ServiceError("queue_blocked", "The item still has findings; open it and resolve or acknowledge them.")
                accept(conn, client_id, item_id, learn=True, actor=actor)
            accepted.append(str(item_id))
        except ServiceError as exc:
            refused.append({"id": str(item_id), "reason": exc.message})
    return {"accepted": accepted, "refused": refused}


# ============================================================================================ reject (D-63)


def reject(conn: Connection, client_id: Any, item_id: Any, *, reason: str, actor: str) -> None:
    actor = require_actor(actor)
    if reason is None or not reason.strip():
        raise ServiceError("reason_required", "A reason is required to reject an item.")
    item = _load(conn, client_id, item_id, lock=True)
    _require_open(item, actor)
    _drop_draft(conn, item, actor)
    repo.mark_rejected(conn, client_id, item_id, actor, reason.strip())
    if item["kind"] == QueueKind.INVOICE.value:
        repo.reopen_document(conn, client_id, item["document_id"])
    audit.log(conn, AuditEntry(client_id, actor, "queue_item_rejected", "approval_queue_item", item_id,
                               {"status": item["status"], "draft_voucher_id": None if item["draft_voucher_id"] is None
                                else str(item["draft_voucher_id"])},
                               {"status": "rejected", "reason": reason.strip(), "draft_voucher_id": None}))
