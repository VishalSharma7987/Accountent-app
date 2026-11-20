"""Tally XML import use-cases (Phase 7 package B, D-30..D-37). Services take a Connection and never commit; every change is audited.

Four steps, each started by a person:
  import_xml          parse the file, write the mapping report and SUGGESTIONS (tally_master_map). Creates no ledger, no voucher.
  set_master_decision the accountant confirms / chooses create / skips one master.
  apply_masters       creates only the ledgers / items marked `create`, through the existing services. Opening balances and bill
                      allocations in the file are REPORTED and never imported (D-33).
  queue_vouchers      one approval-queue item per Tally voucher; a DRAFT voucher through the voucher service when every ledger is
                      mapped and the voucher service accepts it. Nothing is approved or posted here.

The file's bytes are passed in by the caller (the API reads them from the private document store), so this module has no
dependency on the documents package.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo_main
from app.db import repositories_tally as repo
from app.engine.doc_types import DocFinding, QueueKind, Severity
from app.engine.models import VoucherDraft, VoucherLine
from app.engine.money import format_inr
from app.engine.tally_map import (
    GroupSuggestion,
    name_key,
    resolve_group,
    skip_reason,
    source_refs,
    suggest_ledger,
    to_lines,
    voucher_type,
)
from app.importers.tally_xml import TallyFile, TallyParseError, TallyVoucher, parse_tally_xml
from app.services import ai_hooks, audit, client_setup, gst_items, vouchers
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

DECISIONS = ("confirmed", "create", "skip")
TAX_GROUP = "duties_taxes"


@dataclass(frozen=True)
class ImportResult:
    import_id: Any
    company_name: str | None
    report: dict


@dataclass
class QueueResult:
    queued: int = 0
    drafted: int = 0
    needs_review: int = 0
    skipped: list[dict] = field(default_factory=list)


def _parse(xml_bytes: bytes) -> TallyFile:
    try:
        return parse_tally_xml(xml_bytes)
    except TallyParseError as exc:
        raise ServiceError("invalid_tally_file", exc.message, {"rule_id": exc.rule_id}) from None


def _voucher_total(v: TallyVoucher) -> Decimal:
    return sum((-e.amount for e in v.entries if e.deemed_positive and e.amount < 0), Decimal("0.00"))


def _refs(v: TallyVoucher) -> tuple[str, str]:
    return source_refs(v.guid, v.voucher_type, v.voucher_date, v.number, v.party_ledger, _voucher_total(v))


def _label(v: TallyVoucher) -> dict:
    return {"type": v.voucher_type, "date": v.voucher_date.isoformat(), "number": v.number}


# ================================================================================================== import_xml


def import_xml(conn: Connection, client_id: Any, document_id: Any, xml_bytes: bytes, *, actor: str) -> ImportResult:
    actor = require_actor(actor)
    if not repo_main.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    doc = repo.document_row(conn, client_id, document_id)
    if doc is None:
        raise ServiceError("not_found", "Document not found for this client.")
    if doc["doc_type"] != "tally_xml":
        raise ServiceError("invalid_document_type", "The document was not uploaded as a Tally XML file (doc_type tally_xml).")
    earlier = repo.import_for_document(conn, client_id, document_id)
    if earlier is not None:
        raise ServiceError("import_exists", "This file was already imported; open that import instead.", {"import_id": earlier})
    tally = _parse(xml_bytes)

    groups_by_code = repo.system_groups(conn)
    code_by_id = {v: k for k, v in groups_by_code.items()}
    ledgers = repo.ledgers_by_name(conn, client_id)
    items = repo.items_by_name(conn, client_id)
    stored = {(r["kind"], r["source_name_key"]): r for r in repo.master_rows(conn, client_id)}
    defined = {name_key(g.name): g.parent for g in tally.groups}
    confirmed_groups = {key: code_by_id[r["target_group_id"]] for (kind, key), r in stored.items()
                        if kind == "group" and r["decision"] == "confirmed" and r["target_group_id"] in code_by_id}

    import_id = repo.insert_import(conn, client_id, document_id, tally.company_name, {}, {}, actor)  # counts and report are set below

    def save(kind: str, name: str, parent: str | None, group_code: str | None, ledger_id: Any, item_id: Any, reason: str) -> dict:
        key = name_key(name)
        group_id = groups_by_code.get(group_code) if group_code else None
        row = stored.get((kind, key))
        if row is None:
            repo.insert_master(conn, client_id, import_id, kind, name, key, parent, group_id, ledger_id, item_id, reason)
            return {"decision": "suggested", "reason": reason, "group_code": group_code}
        if row["decision"] == "suggested":
            repo.refresh_suggested_master(conn, row["id"], import_id, parent, group_id, ledger_id, item_id, reason)
            return {"decision": "suggested", "reason": reason, "group_code": group_code}
        repo.touch_decided_master(conn, row["id"], import_id, parent)  # an accountant's decision is never overwritten
        return {"decision": row["decision"], "reason": row["reason"], "group_code": code_by_id.get(row["target_group_id"], group_code)}

    group_report = []
    for g in tally.groups:
        s = resolve_group(g.name, defined, confirmed_groups)
        saved = save("group", g.name, g.parent, s.code, None, None,
                     f"{s.reason} Confirm to map ledgers of this group into '{s.code}'." if s.code else s.reason)
        group_report.append({"name": g.name, "parent": g.parent, "suggested_group_code": saved["group_code"], "decision": saved["decision"],
                             "reason": saved["reason"]})
    predefined_seen = sorted({x for lg in tally.ledgers if lg.parent for x in [lg.parent]
                              if resolve_group(lg.parent, defined, confirmed_groups).predefined})

    ledger_report = []
    used_only = sorted({e.ledger_name for v in tally.vouchers for e in v.entries} - {lg.name for lg in tally.ledgers}, key=str.lower)
    for name, parent, opening, is_master in [(lg.name, lg.parent, lg.opening_balance, True) for lg in tally.ledgers] + [
            (n, None, None, False) for n in used_only]:
        existing = ledgers.get(name.lower())
        if not is_master and existing is not None:
            group = GroupSuggestion(existing.group_code, False, (), "The ledger is used in vouchers but is not a master in the file; its group is taken from the existing ledger.")
        elif not is_master:
            group = GroupSuggestion(None, False, (), "The ledger is used in vouchers but is not a master in the file; choose its group.")
        else:
            group = resolve_group(parent, defined, confirmed_groups)
        s = suggest_ledger(name, group, None if existing is None else existing.id, None if existing is None else existing.group_code,
                           None if existing is None else existing.group_name)
        saved = save("ledger", name, parent, s.target_group_code, s.existing_ledger_id, None, s.reason)
        ledger_report.append({
            "name": name, "parent_group": parent, "suggested_group_code": saved["group_code"],
            "existing_ledger_id": None if existing is None else str(existing.id), "decision": saved["decision"],
            "reason": saved["reason"], "rule_id": s.rule_id, "opening_balance_reported": opening,
        })

    item_report = []
    for it in tally.stock_items:
        existing_id = items.get(it.name.lower())
        if existing_id is not None:
            reason = "An item with this name exists. Confirm to use it."
        elif not it.hsn:
            reason = "No HSN code in the file: it cannot be created automatically. Map it to an existing item or skip it."
        else:
            reason = "No item with this name yet. Choose create to add it as goods with the HSN from the file."
        saved = save("stock_item", it.name, it.parent, None, None, existing_id, reason)
        item_report.append({"name": it.name, "unit": it.unit, "hsn": it.hsn, "existing_item_id": None if existing_id is None else str(existing_id),
                            "decision": saved["decision"], "reason": saved["reason"]})

    live, live_fallback = repo.live_refs(conn, client_id)
    by_type: dict[str, int] = {}
    skipped: list[dict] = []
    drafted_later = 0
    allocations = inventory = 0
    for v in tally.vouchers:
        by_type[v.voucher_type] = by_type.get(v.voucher_type, 0) + 1
        allocations += sum(e.bill_allocations for e in v.entries)
        inventory += v.inventory_lines
        why = skip_reason(v.voucher_type, v.is_cancelled, v.is_optional, v.is_postdated)
        ref, fallback = _refs(v)
        if why is None and (ref in live or fallback in live_fallback):
            why = ("D-37", "Already queued from an earlier import.")
        if why is not None:
            skipped.append({**_label(v), "reason_rule": why[0], "reason": why[1]})
        else:
            drafted_later += 1

    counts = {"groups": len(tally.groups), "ledgers": len(ledger_report), "stock_items": len(tally.stock_items), "vouchers": len(tally.vouchers)}
    report = {
        "counts": counts, "groups": group_report, "standard_groups_used": predefined_seen, "ledgers": ledger_report, "stock_items": item_report,
        "vouchers": {"by_type": by_type, "drafted_later": drafted_later, "skipped": skipped},
        "opening_balances_not_applied": True,
        "bill_allocations_not_imported": allocations, "stock_lines_not_imported": inventory, "ignored_master_kinds": tally.ignored,
    }
    repo.set_import_report(conn, import_id, counts, report)
    audit.log(conn, AuditEntry(client_id, actor, "tally_import", "tally_import", import_id, None,
                               {"document_id": str(document_id), "company": tally.company_name, **counts}))
    return ImportResult(import_id, tally.company_name, report)


def get_import(conn: Connection, client_id: Any, import_id: Any) -> dict:
    row = repo.get_import(conn, client_id, import_id)
    if row is None:
        raise ServiceError("not_found", "Tally import not found for this client.")
    return row


def list_imports(conn: Connection, client_id: Any) -> list[dict]:
    return repo.list_imports(conn, client_id)


def list_masters(conn: Connection, client_id: Any, kind: str | None = None, decision: str | None = None) -> list[dict]:
    return repo.master_rows(conn, client_id, kind=kind, decision=decision)


# ================================================================================================== decisions


def set_master_decision(
    conn: Connection, client_id: Any, master_id: Any, *, decision: str, target_group_id: Any = None, target_ledger_id: Any = None,
    target_item_id: Any = None, accept_nature_change: bool = False, actor: str,
) -> None:
    actor = require_actor(actor)
    row = repo.master_row(conn, client_id, master_id)
    if row is None:
        raise ServiceError("not_found", "Tally master not found for this client.")
    if decision not in DECISIONS:
        raise ServiceError("invalid_decision", "The decision must be confirmed, create or skip.")
    kind = row["kind"]
    group_id, ledger_id, item_id = row["target_group_id"], row["target_ledger_id"], row["target_item_id"]
    reason = {"skip": "Skipped by the accountant.", "confirmed": "Confirmed by the accountant.", "create": "Marked to be created by the accountant."}[decision]
    if kind == "group":
        if decision == "create":
            raise ServiceError("invalid_decision", "A Tally group is mapped to an existing group, not created: choose confirmed or skip.")
        if decision == "confirmed":
            if target_group_id is None or repo.group_info(conn, client_id, target_group_id) is None:
                raise ServiceError("mapping_missing", "Choose the group (target_group_id) this Tally group maps to.")
            group_id = target_group_id
    elif kind == "ledger":
        if decision == "confirmed":
            info = None if target_ledger_id is None else repo.ledger_info(conn, client_id, target_ledger_id)
            if info is None:
                raise ServiceError("mapping_missing", "Choose the existing ledger (target_ledger_id) this Tally ledger maps to.")
            suggested = None if group_id is None else repo.group_info(conn, client_id, group_id)
            if suggested is not None and suggested["nature"] != info.nature and not accept_nature_change:
                raise ServiceError(
                    "mapping_nature", f"'{info.name}' is in a {info.nature} group but Tally's group suggests {suggested['nature']}. "
                    "Send accept_nature_change = true if that is intended.")
            ledger_id = info.id
        elif decision == "create":
            target = target_group_id if target_group_id is not None else group_id
            if target is None or repo.group_info(conn, client_id, target) is None:
                raise ServiceError("mapping_missing", "Choose the group (target_group_id) the new ledger goes under.")
            if row["source_name_key"] in repo.ledgers_by_name(conn, client_id):
                raise ServiceError("mapping_exists", f"A ledger named '{row['source_name']}' already exists; map to it instead of creating.")
            group_id, ledger_id = target, None
    else:  # stock_item
        if decision == "confirmed":
            if target_item_id is None or not repo.item_exists(conn, client_id, target_item_id):
                raise ServiceError("mapping_missing", "Choose the existing item (target_item_id) this Tally stock item maps to.")
            item_id = target_item_id
    repo.decide_master(conn, master_id, decision=decision, target_group_id=group_id, target_ledger_id=ledger_id, target_item_id=item_id,
                       reason=reason, actor=actor)
    audit.log(conn, AuditEntry(
        client_id, actor, "tally_master_decision", "tally_master", master_id,
        {"decision": row["decision"], "target_group_id": str(row["target_group_id"]), "target_ledger_id": str(row["target_ledger_id"])},
        {"decision": decision, "name": row["source_name"], "kind": kind, "target_group_id": str(group_id), "target_ledger_id": str(ledger_id),
         "target_item_id": str(item_id)}))


def confirm_exact_matches(conn: Connection, client_id: Any, import_id: Any, *, actor: str) -> int:
    """One click by the accountant for the plain cases: a Tally ledger whose name exists in exactly the suggested group."""
    actor = require_actor(actor)
    get_import(conn, client_id, import_id)
    ids = repo.exact_ledger_matches(conn, client_id, import_id)
    for master_id in ids:
        row = repo.master_row(conn, client_id, master_id)
        repo.decide_master(conn, master_id, decision="confirmed", target_group_id=row["target_group_id"], target_ledger_id=row["target_ledger_id"],
                           target_item_id=None, reason="Same name and group as an existing ledger; confirmed by the accountant.", actor=actor)
        audit.log(conn, AuditEntry(client_id, actor, "tally_master_decision", "tally_master", master_id, {"decision": "suggested"},
                                   {"decision": "confirmed", "name": row["source_name"], "kind": "ledger", "bulk": True}))
    return len(ids)


# ================================================================================================== apply_masters


def apply_masters(conn: Connection, client_id: Any, import_id: Any, xml_bytes: bytes, *, actor: str) -> dict:
    """Create the ledgers and items marked `create`. Never touches opening balances (D-33), never overwrites a name."""
    actor = require_actor(actor)
    imp = get_import(conn, client_id, import_id)
    tally = _parse(xml_bytes)
    units = {name_key(i.name): i for i in tally.stock_items}
    created = {"groups": 0, "ledgers": 0, "stock_items": 0}
    skipped: list[dict] = []
    for row in repo.master_rows(conn, client_id, decision="create", import_id=import_id):
        name = row["source_name"]
        if row["kind"] == "ledger" and row["target_ledger_id"] is None:
            group = repo.group_info(conn, client_id, row["target_group_id"])
            if group is None or name_key(name) in repo.ledgers_by_name(conn, client_id):
                skipped.append({"kind": "ledger", "name": name, "reason": "A ledger with this name exists now, or the group is gone; nothing was changed."})
                continue
            ledger_id = client_setup.add_ledger(conn, client_id, name, group["code"], actor=actor)
            repo.set_created_target(conn, row["id"], ledger_id=ledger_id)
            created["ledgers"] += 1
        elif row["kind"] == "stock_item" and row["target_item_id"] is None:
            item = units.get(row["source_name_key"])
            if item is None or not item.hsn:
                skipped.append({"kind": "stock_item", "name": name, "reason": "No HSN code in the file; map it to an existing item instead."})
                continue
            try:
                item_id = gst_items.create_item(conn, client_id, name=name, item_kind="goods", hsn_sac=item.hsn,
                                                uqc=(item.unit or "").upper() or None, actor=actor)
            except (VoucherRuleError, ServiceError) as exc:
                skipped.append({"kind": "stock_item", "name": name, "reason": exc.message})
                continue
            repo.set_created_target(conn, row["id"], item_id=item_id)
            created["stock_items"] += 1
    if imp["status"] == "parsed":
        repo.set_import_status(conn, import_id, "masters_applied")
    audit.log(conn, AuditEntry(client_id, actor, "tally_apply_masters", "tally_import", import_id, None, {"created": created, "skipped": len(skipped)}))
    return {"created": created, "skipped": skipped}


# ================================================================================================== queue_vouchers


def _finding(rule: str, severity: Severity, message: str) -> DocFinding:
    return DocFinding(rule, severity, message)


def queue_vouchers(
    conn: Connection, client_id: Any, import_id: Any, xml_bytes: bytes, *, financial_year_id: Any = None, actor: str,
) -> QueueResult:
    actor = require_actor(actor)
    imp = get_import(conn, client_id, import_id)
    tally = _parse(xml_bytes)
    window = None
    if financial_year_id is not None:
        window = repo.financial_year(conn, client_id, financial_year_id)
        if window is None:
            raise ServiceError("not_found", "Financial year not found for this client.")

    rows = {r["source_name_key"]: r for r in repo.master_rows(conn, client_id, kind="ledger")}
    result = QueueResult()
    live, live_fallback = repo.live_refs(conn, client_id)
    plan: list[tuple[TallyVoucher, str, str]] = []
    for v in tally.vouchers:
        why = skip_reason(v.voucher_type, v.is_cancelled, v.is_optional, v.is_postdated)
        ref, fallback = _refs(v)
        if why is None and window is not None and not (window[0] <= v.voucher_date <= window[1]):
            why = ("D-36", "Outside the financial year chosen for this run.")
        if why is None and (ref in live or fallback in live_fallback):
            why = ("D-37", "Already queued; not queued twice.")
        if why is not None:
            result.skipped.append({**_label(v), "reason_rule": why[0], "reason": why[1]})
            continue
        plan.append((v, ref, fallback))

    # every ledger of a voucher we are going to queue needs a decision first (D-31 / D-32)
    undecided = sorted({e.ledger_name for v, _, _ in plan for e in v.entries
                        if (r := rows.get(name_key(e.ledger_name))) is None or r["decision"] == "suggested"
                        or (r["decision"] == "create" and r["target_ledger_id"] is None)}, key=str.lower)
    if undecided:
        raise ServiceError("masters_not_ready",
                           "Decide these ledgers first (confirm, create and apply, or skip): " + ", ".join(undecided), {"ledgers": undecided})

    resolved = {k: r["target_ledger_id"] for k, r in rows.items() if r["decision"] in ("confirmed", "create") and r["target_ledger_id"] is not None}
    group_of = repo.ledger_groups(conn, client_id, list(resolved.values()))

    for v, ref, fallback in plan:
        findings: list[DocFinding] = []
        lines, problems = to_lines([(e.ledger_name, e.amount, e.deemed_positive) for e in v.entries])
        for p in problems:
            findings.append(_finding("D-35", Severity.ERROR if "cannot be decided" in p else Severity.WARNING, p))
        unmapped = sorted({x.ledger_name for x in lines if name_key(x.ledger_name) not in resolved}
                          | ({v.party_ledger} if v.party_ledger and name_key(v.party_ledger) not in resolved else set()), key=str.lower)
        for name in unmapped:
            findings.append(_finding("D-31", Severity.REVIEW, f"Ledger '{name}' was skipped in the mapping; map it to a ledger to continue."))
        allocations = sum(e.bill_allocations for e in v.entries)
        if allocations:
            findings.append(_finding("D-33", Severity.WARNING, f"{allocations} bill-wise allocation(s) in Tally were not imported; they are reported only."))
        if v.inventory_lines:
            findings.append(_finding("D-33", Severity.WARNING, f"{v.inventory_lines} stock line(s) in Tally were not imported; only the accounting entries are."))
        tax_lines = [x.ledger_name for x in lines if group_of.get(resolved.get(name_key(x.ledger_name))) == TAX_GROUP]
        if tax_lines:
            findings.append(_finding(
                "D-35", Severity.WARNING,
                "Tax ledger line(s) (" + ", ".join(sorted(set(tax_lines))) + ") are imported as plain lines. The books balance, but the "
                "voucher is not an invoice for GST: it will not appear in GSTR-1 / GSTR-3B, the ITC register or GST reconciliation, and "
                "no rate, HSN or place-of-supply rule was applied."))

        reference = v.reference or (v.number if voucher_type(v.voucher_type) not in ("purchase", "debit_note") else None)
        draft_id = None
        if not any(f.severity in (Severity.ERROR, Severity.REVIEW) for f in findings):
            draft = VoucherDraft(
                client_id, voucher_type(v.voucher_type), v.voucher_date, v.narration, reference,
                None if not v.party_ledger else resolved[name_key(v.party_ledger)],
                tuple(VoucherLine(resolved[name_key(x.ledger_name)], x.debit if x.debit else None, x.credit if x.credit else None) for x in lines),
            )
            try:
                with conn.begin_nested():
                    made = vouchers.create_draft(conn, draft, actor=actor)
            except ServiceError as exc:
                findings.append(_finding(exc.code, Severity.ERROR, exc.message))
            else:
                if made.voucher_id is not None:
                    draft_id = made.voucher_id
                for e in made.errors:
                    findings.append(DocFinding(e.rule_id, Severity.ERROR, e.message, None if e.line_no is None else f"lines[{e.line_no - 1}]"))
        payload = {
            "source": "tally", "tally_voucher_type": v.voucher_type, "voucher_type": voucher_type(v.voucher_type), "voucher_date": v.voucher_date.isoformat(),
            "number": v.number, "guid": v.guid, "fallback_ref": fallback, "narration": v.narration, "reference_no": reference,
            "party_ledger_name": v.party_ledger, "total": format(_voucher_total(v), ".2f"), "total_display": format_inr(_voucher_total(v)),
            "lines": [{"tally_ledger_name": x.ledger_name, "ledger_id": str(resolved.get(name_key(x.ledger_name)) or ""),
                       "debit": format(x.debit, ".2f"), "credit": format(x.credit, ".2f")} for x in lines],
        }
        ai_hooks.add_queue_item(conn, client_id=client_id, kind=QueueKind.TALLY_VOUCHER, document_id=imp["document_id"], findings=findings,
                                created_by=actor, tally_import_id=import_id, source_ref=ref, draft_voucher_id=draft_id, edited_payload=payload)
        result.queued += 1
        if draft_id is not None:
            result.drafted += 1
        else:
            result.needs_review += 1
    repo.set_import_status(conn, import_id, "vouchers_queued")
    audit.log(conn, AuditEntry(client_id, actor, "tally_queue_vouchers", "tally_import", import_id, None,
                               {"queued": result.queued, "drafted": result.drafted, "needs_review": result.needs_review, "skipped": len(result.skipped)}))
    return result
