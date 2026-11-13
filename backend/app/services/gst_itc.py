"""ITC register use-cases (Phase 3, package C): entries from posted purchases, evidence, 2B effect, 180-day reversal drafts.

All arithmetic and every rule is in `engine/gst_itc.py`; this file loads data, writes the result, logs it. Services take a
Connection and never commit; checks run before the first write. The tool never posts a voucher: reversals and re-claims are
DRAFT journals made through `services.vouchers.create_draft` and posted by the accountant.

Hooks (called by `services.gst_hooks`, wired once by the voucher service):
  on_post(conn, client_id, voucher_id, actor)                          posted purchase / debit note -> ITC entries;
                                                                       posted ITC reversal / re-claim journal -> reversal rows
  on_reverse(conn, client_id, original_id, reversal_id, actor)         entries of a reversed voucher -> reversed
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_bills as repo_b
from app.db import repositories_gst_itc as repo
from app.engine import gst_itc as engine
from app.engine.gst_itc import Amounts
from app.engine.models import VoucherDraft, VoucherLine
from app.engine.money import format_inr
from app.services import audit, bills, queries, reports
from app.services import vouchers as voucher_service
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

HEADS = repo.HEADS
TWO = Decimal("0.01")
ACTIVE_REVERSAL = ("drafted", "reversed", "reclaim_drafted", "reclaimed")  # a reversal that counts against the entry
POSTED_REVERSAL = ("reversed", "reclaim_drafted", "reclaimed")
DOC_TYPES = {"purchase": "invoice", "debit_note": "debit_note"}


def _d(value: object) -> Decimal:
    return Decimal(str(value)).quantize(TWO)


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _amounts(row: dict[str, Any], prefix: str = "") -> Amounts:
    return Amounts(*(_d(row[prefix + h]) for h in HEADS))


def _as_dict(a: Amounts) -> dict[str, str]:
    return {h: format(getattr(a, h), "f") for h in HEADS}


def _require_entry(conn: Connection, client_id: object, entry_id: object, *, lock: bool = False) -> dict[str, Any]:
    e = repo.get_entry(conn, client_id, entry_id, lock=lock)
    if e is None:
        raise ServiceError("not_found", "ITC entry not found.")
    return e


def _facts(e: dict[str, Any], **override: Any) -> engine.ItcFacts:
    ims = {"ims_pending": "pending", "ims_rejected": "rejected"}.get(e.get("pending_reason") or "")
    values = {
        "source": e["source"], "doc_type": e["doc_type"], "invoice_date": e["supplier_invoice_date"],
        "itc_category_key": e["itc_category_key"], "itc_exception_claimed": e["itc_exception_claimed"],
        "itc_exception_note": e["itc_exception_note"], "tax_document_held": e["tax_document_held"],
        "goods_services_received": e["goods_services_received"], "received_date": e["received_date"],
        "supplier_tax_paid": e["supplier_tax_paid"], "ims_status": ims,
    }
    values.update(override)
    return engine.ItcFacts(**values)


def _snapshot(e: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status", "pending_reason", "blocked_category_key", "tax_document_held", "goods_services_received", "received_date",
        "supplier_tax_paid", "evidence_note", "claimed_in_period",
    )
    return {k: e[k] for k in keys}


def _apply(
    conn: Connection, e: dict[str, Any], cls: engine.Classification, actor: str, reason: str, *, via: str,
    changes: dict[str, Any] | None = None, action: str = "itc_status_change",
) -> dict[str, Any]:
    """Write the classification and the evidence changes, append the event and the audit row; return the fresh entry."""
    problem = engine.transition_error(e["status"], cls.status, via=via)
    if problem:
        raise ServiceError("itc_invalid_transition", problem)
    new = {
        **(changes or {}), "status": cls.status, "pending_reason": cls.pending_reason,
        "blocked_category_key": cls.blocked_category_key,
    }
    repo.update_entry(conn, e["id"], new)
    repo.insert_event(conn, e["client_id"], e["id"], e["status"], cls.status, reason, actor)
    fresh = repo.get_entry(conn, e["client_id"], e["id"])
    audit.log(conn, AuditEntry(e["client_id"], actor, action, "itc_entry", e["id"], old=_snapshot(e), new=_snapshot(fresh)))
    return fresh


# ===================================================================================== hooks


def on_post(conn: Connection, client_id: object, voucher_id: object, actor: str) -> None:
    head = repo.voucher_header(conn, voucher_id)
    if head is None:
        return
    if head["voucher_type"] == "journal":
        _journal_posted(conn, client_id, head, actor)
    elif head["voucher_type"] in DOC_TYPES and head["gst_registration_id"] is not None:
        _create_entries(conn, client_id, head, actor)


def _create_entries(conn: Connection, client_id: object, head: dict[str, Any], actor: str) -> None:
    items = repo.taxed_item_lines(conn, head["id"])
    if not items:
        return
    rules = repo.blocked_rules(conn)
    deadline = engine.claim_deadline(head["invoice_date"], repo.itc_condition(conn, "claim_time_limit", head["invoice_date"]))
    for item in items:
        facts = engine.ItcFacts(
            "rcm" if item["rcm"] else "regular", DOC_TYPES[head["voucher_type"]], head["invoice_date"], item["itc_category_key"],
            item["itc_exception_claimed"], item["itc_exception_note"], False, False, None, "unknown",
        )
        cls = engine.classify(facts, rules)
        entry_id = repo.insert_entry(
            conn,
            {
                "client_id": client_id, "gst_registration_id": head["gst_registration_id"], "voucher_id": head["id"],
                "item_line_no": item["item_line_no"], "doc_type": facts.doc_type, "source": facts.source,
                "supplier_ledger_id": head["party_ledger_id"], "supplier_gstin": head["counterparty_gstin"],
                "supplier_invoice_no": head["reference_no"], "supplier_invoice_date": head["invoice_date"],
                **{h: _d(item[h]) for h in HEADS}, "status": cls.status, "pending_reason": cls.pending_reason,
                "blocked_category_key": cls.blocked_category_key, "claim_deadline": deadline,
            },
        )
        if entry_id is None:  # already there (posting hook run twice): never overwrite
            continue
        repo.insert_event(conn, client_id, entry_id, None, cls.status, f"Created on posting. {cls.reason}", actor)
        audit.log(
            conn,
            AuditEntry(
                client_id, actor, "itc_create", "itc_entry", entry_id,
                new={"voucher_id": head["id"], "item_line_no": item["item_line_no"], "status": cls.status, **_as_dict(_amounts(item))},
            ),
        )


def on_reverse(conn: Connection, client_id: object, original_id: object, reversal_id: object, actor: str) -> None:
    actor = require_actor(actor)
    for e in repo.entries_of_voucher(conn, original_id):
        if e["status"] == "reversed":
            continue
        repo.update_entry(conn, e["id"], {"status": "reversed", "pending_reason": None})
        repo.insert_event(conn, client_id, e["id"], e["status"], "reversed", f"The voucher was reversed (reversal voucher {reversal_id}).", actor)
        audit.log(conn, AuditEntry(client_id, actor, "itc_reverse", "itc_entry", e["id"], old={"status": e["status"]}, new={"status": "reversed"}))
    rev = repo.reversal_by_voucher(conn, original_id)
    if rev is None:
        return
    if rev["reversal_voucher_id"] == original_id:
        repo.update_reversal(conn, rev["id"], {"status": "cancelled"})
    else:  # a re-claim journal was reversed: the shares are reversed again
        _undo_reclaim(conn, rev, original_id)
    audit.log(conn, AuditEntry(client_id, actor, "itc_reversal_voucher_reversed", "itc_reversal", rev["id"], old={"status": rev["status"]}))
    _refresh_entry(conn, client_id, rev["itc_entry_id"], actor, f"Journal {original_id} was reversed.")


def _input_amounts(conn: Connection, client_id: object, registration_id: object, voucher_id: object) -> Amounts:
    roles = repo.ledger_roles(conn, client_id, registration_id)
    debits = repo.voucher_debit_by_ledger(conn, voucher_id)
    return Amounts(*(debits.get(roles.get(f"input_{h}"), Decimal("0.00")) for h in HEADS))


def _journal_posted(conn: Connection, client_id: object, head: dict[str, Any], actor: str) -> None:
    rev = repo.reversal_by_voucher(conn, head["id"])
    if rev is None:
        return
    if rev["reversal_voucher_id"] == head["id"] and rev["status"] == "drafted":
        repo.update_reversal(conn, rev["id"], {"status": "reversed"})
    elif rev["reclaim_voucher_id"] == head["id"] and rev["status"] == "reclaim_drafted":
        entry = _require_entry(conn, client_id, rev["itc_entry_id"])
        got = _input_amounts(conn, client_id, entry["gst_registration_id"], head["id"])
        total = Amounts(*(_d(rev["reclaimed_" + h]) + getattr(got, h) for h in HEADS))
        full = all(getattr(total, h) == _d(rev[h]) for h in HEADS)
        repo.update_reversal(
            conn, rev["id"],
            {"status": "reclaimed" if full else "reversed", "reclaimed_on": head["voucher_date"], **{"reclaimed_" + h: getattr(total, h) for h in HEADS}},
        )
    else:
        return
    audit.log(conn, AuditEntry(client_id, actor, "itc_reversal_posted", "itc_reversal", rev["id"], old={"status": rev["status"]}))
    _refresh_entry(conn, client_id, rev["itc_entry_id"], actor, f"Journal {head['id']} was posted.")


def _undo_reclaim(conn: Connection, rev: dict[str, Any], voucher_id: object) -> None:
    entry = _require_entry(conn, rev["client_id"], rev["itc_entry_id"])
    got = _input_amounts(conn, rev["client_id"], entry["gst_registration_id"], voucher_id)
    left = {"reclaimed_" + h: max(_d(rev["reclaimed_" + h]) - getattr(got, h), Decimal("0.00")) for h in HEADS}
    repo.update_reversal(conn, rev["id"], {"status": "reversed", **left})


def _refresh_entry(conn: Connection, client_id: object, entry_id: object, actor: str, why: str) -> None:
    """After a reversal / re-claim journal changed: the entry is 'reversed' exactly while the net reversed amount covers it."""
    e = repo.get_entry(conn, client_id, entry_id, lock=True)
    if e is None or e["voucher_status"] == "reversed":
        return
    net = _net_reversed(conn, entry_id, POSTED_REVERSAL)
    total = _amounts(e)
    covers = not total.is_zero() and all(getattr(net, h) >= getattr(total, h) for h in HEADS)
    if covers and e["status"] != "reversed":
        repo.update_entry(conn, entry_id, {"status": "reversed", "pending_reason": None})
        repo.insert_event(conn, client_id, entry_id, e["status"], "reversed", f"Credit reversed in the books. {why}", actor)
    elif not covers and e["status"] == "reversed":
        cls = engine.classify(_facts(e), repo.blocked_rules(conn))
        _apply(conn, e, cls, actor, f"Credit re-claimed. {why}", via="reclaim")


def _net_reversed(conn: Connection, entry_id: object, statuses: tuple[str, ...]) -> Amounts:
    rows = [r for r in repo.reversals_of_entry(conn, entry_id) if r["status"] in statuses]
    return Amounts(*(sum((_d(r[h]) - _d(r["reclaimed_" + h]) for r in rows), Decimal("0.00")) for h in HEADS))


# ===================================================================================== register


def _view(e: dict[str, Any], as_on: date, share: dict | None = None) -> dict[str, Any]:
    return {
        "id": e["id"], "voucher_id": e["voucher_id"], "voucher_number": e["voucher_number"], "item_line_no": e["item_line_no"],
        "doc_type": e["doc_type"], "source": e["source"], "supplier_ledger_id": e["supplier_ledger_id"],
        "supplier_name": e["supplier_name"], "supplier_gstin": e["supplier_gstin"], "supplier_invoice_no": e["supplier_invoice_no"],
        "supplier_invoice_date": e["supplier_invoice_date"], **{h: _d(e[h]) for h in HEADS}, "status": e["status"],
        "pending_reason": e["pending_reason"], "blocked_category_key": e["blocked_category_key"],
        "tax_document_held": e["tax_document_held"], "goods_services_received": e["goods_services_received"],
        "received_date": e["received_date"], "supplier_tax_paid": e["supplier_tax_paid"], "evidence_note": e["evidence_note"],
        "claim_deadline": e["claim_deadline"], "claimed_in_period": e["claimed_in_period"],
        "deadline_passed": e["claimed_in_period"] is None and engine.deadline_passed(e["claim_deadline"], as_on),
        "days_since_invoice": engine.days_since(e["supplier_invoice_date"], as_on), "unpaid_share": share,
    }


def list_register(
    conn: Connection, client_id: object, *, registration_id=None, status=None, period=None, supplier_ledger_id=None,
    as_on: date | None = None,
) -> dict[str, Any]:
    queries.require_client(conn, client_id)
    today = as_on or date.today()
    entries = repo.list_entries(
        conn, client_id, registration_id=registration_id, status=status, period=period, supplier_ledger_id=supplier_ledger_id
    )
    totals = {s: Amounts.zero() for s in ("eligible", "blocked", "pending", "reversed")}
    for e in entries:
        a = _amounts(e)
        t = totals[e["status"]]
        sign = -1 if e["doc_type"] == "debit_note" else 1  # a debit note reduces the credit
        totals[e["status"]] = Amounts(*(getattr(t, h) + sign * getattr(a, h) for h in HEADS))
    return {"entries": [_view(e, today) for e in entries], "totals": {s: _as_dict(a) for s, a in totals.items()}}


def get_entry(conn: Connection, client_id: object, entry_id: object, as_on: date | None = None) -> dict[str, Any]:
    return _view(_require_entry(conn, client_id, entry_id), as_on or date.today())


def events(conn: Connection, client_id: object, entry_id: object) -> list[dict[str, Any]]:
    _require_entry(conn, client_id, entry_id)
    return repo.events_of(conn, client_id, entry_id)


def _require_unclaimed(e: dict[str, Any]) -> None:
    if e["claimed_in_period"] is not None:
        raise ServiceError("itc_invalid_transition", "This credit is already claimed in a return; its evidence can no longer be changed.")


def update_evidence(
    conn: Connection, client_id: object, entry_id: object, *, tax_document_held: bool, goods_services_received: bool,
    received_date: date | None = None, supplier_tax_paid: str | None = None, evidence_note: str | None = None, actor: str,
) -> dict[str, Any]:
    """G-31 / G-37: record the Section 16(2) evidence, re-classify, append an event."""
    actor = require_actor(actor)
    e = _require_entry(conn, client_id, entry_id, lock=True)
    _require_unclaimed(e)
    note = (evidence_note or "").strip() or None
    changes: dict[str, Any] = {
        "tax_document_held": tax_document_held, "goods_services_received": goods_services_received,
        "received_date": received_date, "evidence_by": actor, "evidence_at": _now(),
    }
    if note is not None:
        changes["evidence_note"] = note
    override: dict[str, Any] = {
        "tax_document_held": tax_document_held, "goods_services_received": goods_services_received, "received_date": received_date,
    }
    if supplier_tax_paid is not None:
        if supplier_tax_paid != "manual_confirmed":
            raise ServiceError("invalid_supplier_tax_paid", "Only a manual confirmation can be recorded here; the 2B result is applied by the 2B reconciliation.")
        if note is None:
            raise ServiceError("reason_required", "A manual confirmation that the supplier paid the tax needs a written note (G-32).")
        changes["supplier_tax_paid"] = supplier_tax_paid
        override.update(supplier_tax_paid=supplier_tax_paid, ims_status=None)
    cls = engine.classify(_facts(e, **override), repo.blocked_rules(conn))
    fresh = _apply(conn, e, cls, actor, f"Evidence recorded. {cls.reason}", via="evidence", changes=changes, action="itc_evidence")
    return _view(fresh, date.today())


def confirm(conn: Connection, client_id: object, entry_id: object, *, reason: str, actor: str) -> dict[str, Any]:
    """G-32: the accountant confirms, with a reason, that the supplier's tax is paid although 2B does not show it yet."""
    actor = require_actor(actor)
    text_ = (reason or "").strip()
    if not text_:
        raise ServiceError("reason_required", "A reason is required to confirm a credit that is not in GSTR-2B (G-32).")
    e = _require_entry(conn, client_id, entry_id, lock=True)
    _require_unclaimed(e)
    if e["status"] != "pending" or e["pending_reason"] not in ("not_in_2b", "ims_pending"):
        raise ServiceError(
            "itc_invalid_transition",
            "Manual confirmation applies only to a credit that is pending because it is not (yet) in GSTR-2B or is pending in IMS.",
        )
    cls = engine.classify(_facts(e, supplier_tax_paid="manual_confirmed", ims_status=None), repo.blocked_rules(conn))
    fresh = _apply(
        conn, e, cls, actor, f"Manual confirmation: {text_}", via="confirm",
        changes={"supplier_tax_paid": "manual_confirmed", "evidence_note": text_, "evidence_by": actor, "evidence_at": _now()},
        action="itc_confirm",
    )
    return _view(fresh, date.today())


def apply_2b_to_entry(
    conn: Connection, client_id: object, entry_id: object, *, supplier_tax_paid: str, ims_status: str | None = None,
    actor: str, reason: str,
) -> tuple[str, str]:
    """One entry. supplier_tax_paid: in_2b | not_in_2b; ims_status: None | pending | rejected.
    Returns (from_status, to_status). Never makes a line eligible without the evidence of G-31 (classify decides); a claimed or
    reversed entry is left unchanged; a manual confirmation is kept unless the document is now in 2B."""
    actor = require_actor(actor)
    if supplier_tax_paid not in ("in_2b", "not_in_2b") or ims_status not in (None, "pending", "rejected"):
        raise ServiceError("invalid_2b_result", "supplier_tax_paid must be in_2b or not_in_2b and ims_status pending or rejected.")
    e = _require_entry(conn, client_id, entry_id, lock=True)
    if e["claimed_in_period"] is not None or e["status"] in ("reversed", "blocked"):
        return e["status"], e["status"]
    if e["supplier_tax_paid"] == "manual_confirmed" and supplier_tax_paid == "not_in_2b":
        supplier_tax_paid = "manual_confirmed"
    cls = engine.classify(_facts(e, supplier_tax_paid=supplier_tax_paid, ims_status=ims_status), repo.blocked_rules(conn))
    fresh = _apply(
        conn, e, cls, actor, f"GSTR-2B result: {reason}. {cls.reason}", via="evidence",
        changes={"supplier_tax_paid": supplier_tax_paid}, action="itc_2b_result",
    )
    return e["status"], fresh["status"]


def apply_2b_result(
    conn: Connection, client_id: object, registration_id: object, period: date, effects: Any, actor: str
) -> list[dict[str, Any]]:
    """Called by the 2B reconciliation (package D) with its ItcEffect list: each effect names a book voucher and what 2B says
    (supplier_tax_paid in_2b | not_in_2b, pending_reason not_in_2b | ims_pending | ims_rejected | None). Only regular-charge entries
    of that registration are touched. Returns [{itc_entry_id, from_status, to_status}] for every entry looked at."""
    actor = require_actor(actor)
    out = []
    for fx in effects:
        ims = {"ims_pending": "pending", "ims_rejected": "rejected"}.get(fx.pending_reason or "")
        for e in repo.entries_of_voucher(conn, fx.voucher_id):
            if e["gst_registration_id"] != registration_id or e["source"] != "regular":
                continue
            before, after = apply_2b_to_entry(
                conn, client_id, e["id"], supplier_tax_paid=fx.supplier_tax_paid, ims_status=ims, actor=actor,
                reason=f"{period:%m-%Y}: {fx.note}",
            )
            out.append({"itc_entry_id": e["id"], "from_status": before, "to_status": after})
    return out


def set_claimed_period(conn: Connection, client_id: object, entry_id: object, period: date, *, actor: str) -> dict[str, Any]:
    """For the GSTR-3B working (package E): record the month a credit is claimed in. G-33: after the claim deadline it is refused."""
    actor = require_actor(actor)
    if period.day != 1:
        raise ServiceError("invalid_period", "The claim period is the first day of a month.")
    e = _require_entry(conn, client_id, entry_id, lock=True)
    if e["status"] != "eligible":
        raise ServiceError("itc_invalid_transition", f"Only an eligible credit can be claimed; this one is {e['status']}.")
    _require_unclaimed(e)
    if engine.deadline_passed(e["claim_deadline"], period):
        raise ServiceError(
            "claim_deadline_passed",
            f"The time limit to claim this credit ended on {_fmt(e['claim_deadline'])} (Section 16(4), rule status "
            "'pending' until the CA confirms); it cannot be claimed in the return for "
            f"{period:%m-%Y}. It stays in the register as a flagged item.",
        )
    repo.update_entry(conn, entry_id, {"claimed_in_period": period})
    repo.insert_event(conn, client_id, entry_id, "eligible", "eligible", f"Claimed in the return of {period:%m-%Y}.", actor)
    audit.log(conn, AuditEntry(client_id, actor, "itc_claim", "itc_entry", entry_id, old={"claimed_in_period": None}, new={"claimed_in_period": period}))
    return _view(repo.get_entry(conn, client_id, entry_id), date.today())


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


# ===================================================================================== draft journals


def _draft_journal(
    conn: Connection, client_id: object, registration_id: object, on: date, narration: str, reference: str,
    debit: dict[str, Decimal], credit: dict[str, Decimal], actor: str,
) -> object:
    roles = repo.ledger_roles(conn, client_id, registration_id)
    missing = sorted({r for r in (*debit, *credit) if r not in roles})
    if missing:
        raise ServiceError("ledger_role_missing", f"Map these GST ledger roles on the registration first: {', '.join(missing)}.", {"roles": missing})
    lines = [VoucherLine(roles[r], debit=a, credit=Decimal("0.00")) for r, a in debit.items() if a]
    lines += [VoucherLine(roles[r], debit=Decimal("0.00"), credit=a) for r, a in credit.items() if a]
    draft = VoucherDraft(client_id, "journal", on, narration, reference, None, tuple(lines))
    result = voucher_service.create_draft(conn, draft, actor=actor)
    if result.errors:
        raise VoucherRuleError(result.errors)
    return result.voucher_id


def _reversal_journal(conn, e, amounts: Amounts, on: date, why: str, actor: str) -> object:
    total = amounts.total()
    narration = f"ITC reversal: {why} - {e['supplier_name'] or 'supplier'} bill {e['supplier_invoice_no']} dated {_fmt(e['supplier_invoice_date'])}, tax {format_inr(total)}"
    return _draft_journal(
        conn, e["client_id"], e["gst_registration_id"], on, narration, f"ITCREV {e['supplier_invoice_no']}",
        {"itc_reversal": total}, {f"input_{h}": getattr(amounts, h) for h in HEADS}, actor,
    )


def _new_reversal(conn, e, amounts: Amounts, reason: str, on: date, note: str, why: str, actor: str) -> dict[str, Any]:
    voucher_id = _reversal_journal(conn, e, amounts, on, why, actor)
    reversal_id = repo.insert_reversal(
        conn,
        {
            "client_id": e["client_id"], "itc_entry_id": e["id"], "reason": reason, "as_on_date": on, "unpaid_fraction_note": note,
            **{h: getattr(amounts, h) for h in HEADS}, "reversal_voucher_id": voucher_id, "created_by": actor,
        },
    )
    audit.log(conn, AuditEntry(e["client_id"], actor, "itc_reversal_draft", "itc_reversal", reversal_id, new={"voucher_id": voucher_id, "reason": reason, **_as_dict(amounts)}))
    return {"reversal_id": reversal_id, "itc_entry_id": e["id"], "voucher_id": voucher_id, **_as_dict(amounts)}


def tag_blocked(
    conn: Connection, client_id: object, entry_id: object, *, category_key: str, note: str, actor: str, as_on: date | None = None
) -> dict[str, Any]:
    """G-30 / G-36: a Section 17(5) category found after posting. Unclaimed: the entry becomes blocked. Already in the books as
    credit and claimed: a DRAFT reversal journal for the whole tax is made (the entry turns 'reversed' when it is posted)."""
    actor = require_actor(actor)
    if not (note or "").strip():
        raise ServiceError("reason_required", "A note saying why the credit is blocked is required.")
    e = _require_entry(conn, client_id, entry_id, lock=True)
    rule = next((r for r in repo.blocked_rules(conn) if r.category_key == category_key and r.effective_from <= e["supplier_invoice_date"]
                 and (r.effective_to is None or e["supplier_invoice_date"] <= r.effective_to)), None)
    if rule is None:
        raise ServiceError("invalid_category", f"'{category_key}' is not a Section 17(5) category in force on {_fmt(e['supplier_invoice_date'])}.")
    problem = engine.transition_error(e["status"], "blocked", via="tag")
    if problem or e["status"] == "blocked":
        raise ServiceError("itc_invalid_transition", problem or "This credit is already blocked.")
    if e["claimed_in_period"] is None:
        cls = engine.Classification("blocked", None, category_key, f"Tagged as blocked credit, {rule.clause_ref}: {note.strip()}")
        fresh = _apply(conn, e, cls, actor, cls.reason, via="tag", action="itc_tag_blocked")
        return _view(fresh, date.today())
    if _net_reversed(conn, entry_id, ACTIVE_REVERSAL).total() > 0:
        raise ServiceError("reversal_exists", "A reversal already exists for this credit.")
    on = as_on or date.today()
    _new_reversal(
        conn, e, _amounts(e), "blocked_identified_late", on, f"category={category_key}; {note.strip()}",
        f"blocked credit {rule.clause_ref} identified late", actor,
    )
    repo.insert_event(conn, client_id, entry_id, e["status"], e["status"], f"Reversal draft made: blocked category {category_key}. {note.strip()}", actor)
    return _view(repo.get_entry(conn, client_id, entry_id), date.today())


# ===================================================================================== 180 days


def _assess(conn: Connection, client_id: object, registration_id: object | None, as_on: date, only_entry: object | None = None,
    statuses: tuple[str, ...] = ("eligible", "pending"),
):
    """Per credit: unpaid share as on a date. Returns (rows, not_assessable, rule_status)."""
    entries = [
        e for e in repo.list_entries(conn, client_id, registration_id=registration_id, as_on=as_on)
        if e["doc_type"] == "invoice" and e["source"] == "regular" and e["status"] in statuses
        and (only_entry is None or e["id"] == only_entry)
    ]
    if not entries:
        return [], [], "pending"
    party_rows = repo_b.list_party_rows(conn, client_id)
    open_by_ref = {
        (b.party_ledger_id, b.bill_ref): b for b in bills.open_bills(conn, client_id, as_on) if b.kind == "bill" and b.bill_ref
    }
    reversals = repo.reversals_for_entries(conn, [e["id"] for e in entries])
    rows, skipped, statuses = [], [], set()
    for e in entries:
        cond = repo.itc_condition(conn, "payment_within_days", e["supplier_invoice_date"])
        party = party_rows.get(e["supplier_ledger_id"])
        reason = None
        if cond is None or cond.parameter_days is None:
            reason = "No 180-day rule row is in force on the invoice date."
        elif party is None or not party.bill_wise:
            reason = "The supplier is not a bill-wise party, so payments against this bill cannot be traced."
        if reason:
            skipped.append({"itc_entry_id": e["id"], "supplier_invoice_no": e["supplier_invoice_no"], "reason": reason})
            continue
        statuses.add(cond.verification_status)
        bill = open_by_ref.get((e["supplier_ledger_id"], e["supplier_invoice_no"]))
        if bill is None:  # a bill-wise supplier's bill with nothing open: settled
            original, outstanding = None, Decimal("0.00")
        else:
            original, outstanding = abs(_d(bill.original)), abs(_d(bill.outstanding))
        tax = _amounts(e)
        share = engine.unpaid_share(tax, original, outstanding) if original else engine.UnpaidShare(Decimal("0.0000"), Amounts.zero())
        done = Amounts(*(sum((_d(r[h]) - _d(r["reclaimed_" + h]) for r in reversals.get(e["id"], []) if r["status"] in ACTIVE_REVERSAL), Decimal("0.00")) for h in HEADS))
        rows.append({
            "entry": e, "days": engine.days_since(e["supplier_invoice_date"], as_on), "limit": cond.parameter_days,
            "due_on": engine.payment_due_date(e["supplier_invoice_date"], cond.parameter_days), "outstanding": outstanding,
            "share": share, "net_reversed": done, "to_reverse": engine.reversal_amounts(share.amounts, done),
        })
    status = "pending" if "pending" in statuses or not statuses else ("secondary_verified" if "secondary_verified" in statuses else "verified")
    return rows, skipped, status


def exposure_180(conn: Connection, client_id: object, registration_id: object | None, as_on: date) -> dict[str, Any]:
    """G-34: credits whose invoice is older than the rule's days with part of the bill unpaid, plus those within 30 days of it."""
    queries.require_client(conn, client_id)
    rows, skipped, rule_status = _assess(conn, client_id, registration_id, as_on)

    def item(r) -> dict[str, Any]:
        e = r["entry"]
        return {
            "itc_entry_id": e["id"], "voucher_number": e["voucher_number"], "supplier_name": e["supplier_name"],
            "supplier_invoice_no": e["supplier_invoice_no"], "invoice_date": e["supplier_invoice_date"], "days": r["days"],
            "due_on_day": r["due_on"], "outstanding": r["outstanding"], "unpaid_share": {"fraction": r["share"].fraction, **r["share"].amounts.__dict__},
            **r["share"].amounts.__dict__, "already_reversed": r["share"].amounts.total() > 0 and r["to_reverse"].is_zero(),
        }

    due = [r for r in rows if r["days"] > r["limit"] and r["share"].amounts.total() > 0]
    near = [r for r in rows if r["limit"] - 30 <= r["days"] <= r["limit"] and r["share"].amounts.total() > 0]
    total = Amounts(*(sum((getattr(r["share"].amounts, h) for r in due), Decimal("0.00")) for h in HEADS))
    return {
        "as_on": as_on, "rule_status": rule_status, "items": [item(r) for r in due], "approaching": [item(r) for r in near],
        "total": total.__dict__, "not_assessable": skipped,
    }


def create_reversals(
    conn: Connection, client_id: object, registration_id: object, as_on: date, entry_ids: list[object] | None, *, actor: str
) -> list[dict[str, Any]]:
    """G-34 / G-36: one DRAFT journal per credit for the unpaid share not yet reversed. Never posts."""
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    rows, _, _ = _assess(conn, client_id, registration_id, as_on)
    due = [r for r in rows if r["days"] > r["limit"] and r["share"].amounts.total() > 0 and (entry_ids is None or r["entry"]["id"] in entry_ids)]
    if not due:
        raise ServiceError("nothing_to_reverse", "No credit has an unpaid share past the legal number of days on this date.")
    todo = [r for r in due if not r["to_reverse"].is_zero()]
    if not todo:
        raise ServiceError("reversal_exists", "Every due credit already has a reversal for the same amount.")
    created = []
    for r in todo:
        e = r["entry"]
        note = (
            f"Bill unpaid {format_inr(r['outstanding'])} on {_fmt(as_on)}; fraction {r['share'].fraction}; {r['days']} days since the "
            f"invoice date (limit {r['limit']}). Unpaid share of the tax {format_inr(r['share'].amounts.total())}, "
            f"already reversed {format_inr(r['net_reversed'].total())}."
        )
        created.append(_new_reversal(conn, e, r["to_reverse"], "payment_180_days", as_on, note, f"{r['limit']} days passed, bill unpaid", actor))
    return created


def reclaim(conn: Connection, client_id: object, reversal_id: object, as_on: date, *, actor: str) -> dict[str, Any]:
    """G-35: a DRAFT journal that puts back the share of a reversal that has been paid since. Once per payment."""
    actor = require_actor(actor)
    rev = repo.get_reversal(conn, client_id, reversal_id, lock=True)
    if rev is None:
        raise ServiceError("not_found", "ITC reversal not found.")
    if rev["reason"] != "payment_180_days":
        raise ServiceError("itc_invalid_transition", "Only a reversal made for the 180-day rule can be re-claimed on payment.")
    if rev["status"] != "reversed":
        raise ServiceError("itc_invalid_transition", f"A reversal can be re-claimed only after its journal is posted and while no re-claim is pending (status is {rev['status']}).")
    e = _require_entry(conn, client_id, rev["itc_entry_id"], lock=True)
    rows, _, _ = _assess(
        conn, client_id, e["gst_registration_id"], as_on, only_entry=e["id"], statuses=("eligible", "pending", "reversed")
    )
    if not rows:
        raise ServiceError("itc_invalid_transition", f"The payments for this credit cannot be traced as on {_fmt(as_on)}.")
    now = rows[0]["share"].amounts
    others = _net_reversed(conn, e["id"], ACTIVE_REVERSAL)
    this_net = Amounts(*(_d(rev[h]) - _d(rev["reclaimed_" + h]) for h in HEADS))
    other_net = Amounts(*(max(getattr(others, h) - getattr(this_net, h), Decimal("0.00")) for h in HEADS))
    unpaid_for_this = Amounts(*(max(getattr(now, h) - getattr(other_net, h), Decimal("0.00")) for h in HEADS))
    amounts = engine.reclaim_amounts(Amounts(*(_d(rev[h]) for h in HEADS)), Amounts(*(_d(rev["reclaimed_" + h]) for h in HEADS)), unpaid_for_this)
    if amounts.is_zero():
        raise ServiceError("nothing_to_reclaim", "No part of this reversal has been paid since; nothing to re-claim.")
    total = amounts.total()
    voucher_id = _draft_journal(
        conn, client_id, e["gst_registration_id"], as_on,
        f"ITC re-claim on payment - {e['supplier_name'] or 'supplier'} bill {e['supplier_invoice_no']} dated {_fmt(e['supplier_invoice_date'])}, tax {format_inr(total)}",
        f"ITCRECLAIM {e['supplier_invoice_no']}", {f"input_{h}": getattr(amounts, h) for h in HEADS}, {"itc_reversal": total}, actor,
    )
    repo.update_reversal(conn, reversal_id, {"status": "reclaim_drafted", "reclaim_voucher_id": voucher_id})
    audit.log(conn, AuditEntry(client_id, actor, "itc_reclaim_draft", "itc_reversal", reversal_id, old={"status": "reversed"}, new={"status": "reclaim_drafted", "voucher_id": voucher_id, **_as_dict(amounts)}))
    return {"reclaim_voucher_id": voucher_id, **_as_dict(amounts)}


def list_reversals(conn: Connection, client_id: object, status: str | None = None) -> list[dict[str, Any]]:
    queries.require_client(conn, client_id)
    out = []
    for r in repo.list_reversals(conn, client_id, status):
        out.append({
            "id": r["id"], "itc_entry_id": r["itc_entry_id"], "reason": r["reason"], "as_on_date": r["as_on_date"],
            "amounts": {h: _d(r[h]) for h in HEADS}, "reclaimed": {h: _d(r["reclaimed_" + h]) for h in HEADS},
            "reversal_voucher_id": r["reversal_voucher_id"], "reclaim_voucher_id": r["reclaim_voucher_id"], "status": r["status"],
        })
    return out


# ===================================================================================== tie with the Input ledgers


def register_tie(conn: Connection, client_id: object, registration_id: object, as_on: date) -> dict[str, Any]:
    """Input tax ledgers (regular purchases) against the register: eligible + pending credits, debit notes deducted, reversals
    posted in the books deducted. Blocked credits are in the cost, not in the Input ledgers. RCM entries are not compared."""
    queries.require_client(conn, client_id)
    roles = repo.ledger_roles(conn, client_id, registration_id)
    missing = sorted(f"input_{h}" for h in HEADS if f"input_{h}" not in roles)
    if missing:
        raise ServiceError("ledger_role_missing", f"Map these GST ledger roles on the registration first: {', '.join(missing)}.", {"roles": missing})
    trial = reports.trial_balance(conn, client_id, as_on)
    balance = {row.ledger_id: _d(row.debit) - _d(row.credit) for s in trial.sections for row in s.rows}
    entries = repo.register_sums(conn, client_id, registration_id, as_on)
    reversals = repo.reversals_for_entries(conn, [e["id"] for e in entries])
    register = {h: Decimal("0.00") for h in HEADS}
    for e in entries:
        if e["status"] not in ("eligible", "pending"):
            continue
        sign = -1 if e["doc_type"] == "debit_note" else 1
        net = Amounts(*(sum((_d(r[h]) - _d(r["reclaimed_" + h]) for r in reversals.get(e["id"], []) if r["status"] in POSTED_REVERSAL), Decimal("0.00")) for h in HEADS))
        for h in HEADS:
            register[h] += sign * _d(e[h]) - getattr(net, h)

    def bal(x: Decimal) -> dict[str, str]:
        return {"amount": format(abs(x), "f"), "side": "Dr" if x >= 0 else "Cr"}

    books = {h: balance.get(roles[f"input_{h}"], Decimal("0.00")) for h in HEADS}
    diff = {h: books[h] - register[h] for h in HEADS}
    ties = all(v == 0 for v in diff.values())
    notes = [
        "Input ledgers are compared with regular-charge entries only; credits under reverse charge are not compared.",
        "Blocked credits are part of the cost and are not in the Input ledgers.",
    ]
    if not ties:
        notes.append("A difference is shown, not forced: look for draft or unposted vouchers, manual journals on the Input ledgers, or entries dated after the as-on date.")
    return {
        "input_ledgers": {h: bal(books[h]) for h in HEADS}, "itc_register": {h: bal(register[h]) for h in HEADS},
        "difference": {h: bal(diff[h]) for h in HEADS}, "ties": ties, "notes": notes,
    }
