"""Invoice-mode vouchers (Phase 3, package B): builds the ledger lines of a draft from its `gst` block, stores and reads
the GST rows, re-checks them at approve / post (G-26, G-23) and previews without saving.

Services take a SQLAlchemy Connection and never commit. The hooks of services/gst_hooks.py call these functions, so
services/vouchers.py needs no GST knowledge. Nothing here imports services.vouchers at module level (it imports the hooks).
"""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories_gst_invoice as repo
from app.engine.gst_invoice import (
    BuildOutcome,
    InvoiceContext,
    build_invoice,
    check_lines_match,
    check_number_length,
)
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import Allocation, ValidationError, VoucherDraft, VoucherLine
from app.services.errors import ServiceError, VoucherRuleError

STATUS_ORDER = {"verified": 0, "secondary_verified": 1, "pending": 2}
NO_GSTIN_CATEGORIES = frozenset({"b2c", "unregistered_supplier", "import_of_service", "export_with_payment", "export_without_payment"})


# ================================================================================================ build


def _supply_date(voucher_type: str, voucher_date: date, inv: InvoiceIn) -> date:
    return voucher_date if voucher_type in ("sales", "credit_note") else inv.invoice_date


def _resolve(inv: InvoiceIn, party) -> tuple[InvoiceIn, str | None]:
    """Fill the buyer / supplier GSTIN from the party when the caller left it out (shown back on the voucher), and
    find the counterparty's state (from the GSTIN, else the party master)."""
    gstin = (inv.counterparty_gstin or "").strip().upper() or None
    if gstin is None and party is not None and party.gstin and inv.supply_category not in NO_GSTIN_CATEGORIES:
        gstin = party.gstin
    state = gstin[:2] if gstin and gstin[:2].isdigit() else (party.state_code if party is not None else None)
    return replace(inv, counterparty_gstin=gstin), state


def build_for_draft(conn: Connection, draft: VoucherDraft) -> tuple[BuildOutcome, InvoiceIn | None, repo.ContextRows | None, str | None]:
    inv = draft.gst
    rows = repo.load_context(
        conn, draft.client_id, inv.gst_registration_id, draft.party_ledger_id, draft.voucher_date, inv.invoice_date
    )
    if rows.registration is None:
        raise ServiceError("not_found", "GST registration not found for this client.")
    resolved, state = _resolve(inv, rows.party)
    ctx = InvoiceContext(
        draft.voucher_type, draft.voucher_date, draft.party_ledger_id, rows.registration, state,
        rows.round_off_invoices, rows.rules,
    )
    return build_invoice(resolved, ctx), resolved, rows, state


def expand_invoice(conn: Connection, draft: VoucherDraft) -> tuple[VoucherDraft, list[ValidationError]]:
    """Replace the lines of a draft that has a `gst` block by the engine's lines. Without `gst` the draft is returned
    unchanged. On rule errors the draft has no lines and the errors are returned."""
    if draft.gst is None:
        return draft, []
    outcome, resolved, rows, _ = build_for_draft(conn, draft)
    if outcome.errors or outcome.result is None:
        return draft, outcome.errors
    result = outcome.result
    party_amount = next(x for x in result.lines if x.role == "party")
    allocations = draft.gst_party_allocations
    if not allocations and rows.party is not None and rows.party.bill_wise and draft.voucher_type in ("sales", "purchase") \
            and (draft.reference_no or "").strip():
        # default (Phase 2 prefill): the party line opens a new bill for the full invoice value under the reference no
        allocations = (Allocation("new_ref", party_amount.debit or party_amount.credit, draft.reference_no.strip()),)
    lines = tuple(
        VoucherLine(_uid(x.ledger_id), x.debit if x.debit > 0 else None, x.credit if x.credit > 0 else None,
                    allocations if x.role == "party" else ())
        for x in result.lines
    )
    return replace(draft, lines=lines, gst=resolved, gst_result=result, party_ledger_id=_uid(draft.party_ledger_id)), []


def _uid(value):
    """Ledger ids are compared for equality by the voucher rules (V-13), so they are all uuid.UUID."""
    return None if value is None else uuid.UUID(str(value))


def counterparty_state(conn: Connection, draft: VoucherDraft) -> str | None:
    """The state code stored with the header (only a code the state table knows, else NULL)."""
    gstin = draft.gst.counterparty_gstin
    return gstin[:2] if gstin and gstin[:2].isdigit() else None


# ================================================================================================ persist


def persist(conn: Connection, client_id: object, voucher_id: object, draft: VoucherDraft) -> None:
    """Write the GST rows of a saved draft (replacing any earlier ones). Call after the voucher lines are inserted."""
    repo.delete_invoice(conn, voucher_id)
    if draft.gst is None or draft.gst_result is None:
        return
    state = counterparty_state(conn, draft)
    repo.insert_invoice(conn, client_id, voucher_id, draft.gst, draft.gst_result, state)


# ================================================================================================ re-check


def _stored_invoice_in(stored: repo.StoredInvoice) -> InvoiceIn:
    h = stored.header
    items = tuple(
        ItemLineIn(
            i["description"], i["hsn_sac"], Decimal(i["quantity"]), Decimal(i["unit_rate"]), Decimal(i["discount"]),
            uuid.UUID(i["ledger_id"]), i["item_id"], i["uqc"], i["rcm_category_key"], i["itc_category_key"],
            i["itc_exception_claimed"], i["itc_exception_note"],
        )
        for i in stored.items
    )
    return InvoiceIn(
        h["gst_registration_id"], h["document_kind"], h["supply_category"], h["place_of_supply"],
        date.fromisoformat(h["invoice_date"]), items, h["counterparty_gstin"], h["original_invoice_no"],
        None if h["original_invoice_date"] is None else date.fromisoformat(h["original_invoice_date"]), h["note_reason"],
    )


def revalidate(conn: Connection, record) -> list[ValidationError]:
    """G-26 at approve / post: rebuild the invoice from the stored item rows and compare with the stored lines."""
    stored = repo.load_stored(conn, record.id)
    if stored is None or record.reverses_voucher_id is not None:
        return []
    inv = _stored_invoice_in(stored)
    rows = repo.load_context(
        conn, record.client_id, inv.gst_registration_id, record.party_ledger_id, record.voucher_date, inv.invoice_date
    )
    if rows.registration is None:
        return [ValidationError("G-26", "The GST registration of this invoice no longer exists.")]
    inv, state = _resolve(inv, rows.party)
    ctx = InvoiceContext(
        record.voucher_type, record.voucher_date, record.party_ledger_id, rows.registration, state,
        rows.round_off_invoices, rows.rules,
    )
    outcome = build_invoice(inv, ctx)
    if outcome.result is None:
        return outcome.errors
    # the stored item rows themselves must equal the engine's figures
    errors = check_lines_match(outcome.result, [(x.ledger_id, x.debit, x.credit) for x in record.lines])
    for tax, row in zip(outcome.result.items, stored.items, strict=False):
        keys = ("taxable_value", "cgst", "sgst", "igst", "cess")
        if any(Decimal(row[k]) != getattr(tax, k) for k in keys):
            errors.append(ValidationError(
                "G-26", f"Item {tax.item_line_no}: the stored tax figures differ from the system's calculation.", tax.item_line_no))
    return errors


def check_number(conn: Connection, record, number: str) -> None:
    """G-23: refuse to post a GST document whose voucher number is too long or has other characters."""
    is_gst, limit = repo.number_limit(conn, record.id, record.voucher_date)
    if not is_gst:
        return
    if limit is None:
        raise ServiceError("rule_missing", "The rule 'invoice_number_max_length' is not in the rule table; cannot post a GST document.")
    errors = check_number_length(number, limit)
    if errors:
        raise VoucherRuleError(errors)


# ================================================================================================ read


def _rule_status(rows: repo.ContextRows, inv: InvoiceIn, items: list[dict], on: date) -> dict:
    """G-55: statuses of the rule rows this invoice used."""
    used: dict[str, list[tuple[str, str]]] = {}
    ids = {i["rate_rule_id"] for i in items if i["rate_rule_id"]}
    for r in rows.rules.rate_rules:
        if r.id in ids:
            used.setdefault("rate", []).append((r.verification_status, r.source_reference))
    for i in items:
        if i["treatment"] == "taxable":
            for s in rows.rules.slabs:
                if s.rate == Decimal(i["gst_rate"]) and s.effective_from <= on and (s.effective_to is None or on <= s.effective_to):
                    used.setdefault("slab", []).append((s.verification_status, s.source_reference))
    keys = {i["rcm_category_key"] for i in items if i["rcm_category_key"]}
    for r in rows.rules.rcm_rules:
        if r.category_key in keys:
            used.setdefault("rcm", []).append((r.verification_status, r.source_reference))
    keys = {i["itc_category_key"] for i in items if i["itc_category_key"]}
    for r in rows.rules.blocked_rules:
        if r.category_key in keys:
            used.setdefault("blocked", []).append((r.verification_status, r.source_reference))
    tables = {t: max((s for s, _ in v), key=STATUS_ORDER.get) for t, v in used.items()}
    worst = max(tables.values(), key=STATUS_ORDER.get) if tables else "verified"
    pending = sorted({src for v in used.values() for s, src in v if s == "pending"})
    return {"worst": worst, "tables": tables, "pending_sources": pending}


def _item_out(i: dict) -> dict:
    keys = ("gross_amount", "discount", "taxable_value", "cgst", "sgst", "igst", "cess", "cess_specific_amount")
    out = {k: f"{Decimal(i[k]):.2f}" for k in keys}
    out.update({
        "item_line_no": i["item_line_no"], "item_id": i["item_id"], "description": i["description"], "hsn_sac": i["hsn_sac"],
        "uqc": i["uqc"], "quantity": f"{Decimal(i['quantity']):.3f}", "unit_rate": f"{Decimal(i['unit_rate']):.2f}",
        "ledger_id": i["ledger_id"], "treatment": i["treatment"], "gst_rate": f"{Decimal(i['gst_rate']):.4f}",
        "cess_rate": f"{Decimal(i['cess_rate']):.4f}", "rate_rule_id": i["rate_rule_id"], "rate_is_default": i["rate_is_default"],
        "rcm": i["rcm"], "rcm_category_key": i["rcm_category_key"], "tax_in_cost": i["tax_in_cost"],
        "itc_category_key": i["itc_category_key"], "itc_exception_claimed": i["itc_exception_claimed"],
        "itc_exception_note": i["itc_exception_note"],
    })
    return out


def _warnings(items: list[dict]) -> list[dict]:
    return [
        {"rule_id": "G-10", "item_line_no": i["item_line_no"],
         "message": f"Item {i['item_line_no']}: the default rate {Decimal(i['gst_rate']).normalize():f}% was applied; check the code."}
        for i in items if i["rate_is_default"]
    ]


def load(conn: Connection, client_id: object, voucher_id: object, *, voucher=None) -> dict | None:
    """The `gst` block of a voucher response (None when the voucher is not in invoice mode). `line_roles` maps
    voucher line_no -> {gst_role, item_line_no} for the line list."""
    stored = repo.load_stored(conn, voucher_id)
    if stored is None:
        return None
    h = stored.header
    on = date.fromisoformat(h["invoice_date"])
    rows = repo.load_context(conn, client_id, h["gst_registration_id"], None, on, on)
    inv = _stored_invoice_in(stored)
    return {
        "gst_registration_id": h["gst_registration_id"], "document_kind": h["document_kind"],
        "supply_category": h["supply_category"], "place_of_supply": h["place_of_supply"], "invoice_date": h["invoice_date"],
        "counterparty_gstin": h["counterparty_gstin"], "counterparty_state_code": h["counterparty_state_code"],
        "original_invoice_no": h["original_invoice_no"], "original_invoice_date": h["original_invoice_date"],
        "note_reason": h["note_reason"], "invoice_value": f"{Decimal(h['invoice_value']):.2f}",
        "invoice_round_off": f"{Decimal(h['invoice_round_off']):.2f}", "has_rcm": h["has_rcm"],
        "engine_version": h["engine_version"], "warnings": _warnings(stored.items),
        "items": [_item_out(i) for i in stored.items],
        "line_roles": {r["line_no"]: {"gst_role": r["role"], "item_line_no": r["item_line_no"]} for r in stored.roles},
        "rule_status": _rule_status(rows, inv, stored.items, on),
    }


# ================================================================================================ preview


def preview(conn: Connection, draft: VoucherDraft) -> dict:
    """The lines and tax the engine would build, WITHOUT saving anything. Errors come back as a list, never raised."""
    from app.services import (
        vouchers,  # late import: vouchers imports the hooks, which import this module
    )

    expanded, errors = expand_invoice(conn, draft)
    if errors:
        return {"lines": [], "gst": None, "errors": errors}
    errors = vouchers.validate_draft(conn, expanded)
    result = expanded.gst_result
    names = repo.ledger_names(conn, [x.ledger_id for x in result.lines] + [i.ledger_id for i in expanded.gst.items])
    lines = [
        {"ledger_id": str(x.ledger_id), "ledger_name": names.get(str(x.ledger_id), ""), "debit": f"{x.debit:.2f}",
         "credit": f"{x.credit:.2f}", "gst_role": x.role, "item_line_no": x.item_line_no}
        for x in result.lines
    ]
    rows = repo.load_context(
        conn, draft.client_id, expanded.gst.gst_registration_id, draft.party_ledger_id, draft.voucher_date, expanded.gst.invoice_date
    )
    items = [
        {"item_line_no": t.item_line_no, "taxable_value": str(t.taxable_value), "treatment": t.treatment,
         "gst_rate": str(t.gst_rate), "cgst": str(t.cgst), "sgst": str(t.sgst), "igst": str(t.igst), "cess": str(t.cess),
         "rate_rule_id": t.rate_rule_id, "rate_is_default": t.rate_is_default, "rcm": t.rcm,
         "rcm_category_key": e.rcm_category_key, "itc_category_key": e.itc_category_key}
        for t, e in zip(result.items, expanded.gst.items, strict=True)
    ]
    gst = {
        "invoice_value": f"{result.invoice_value:.2f}", "invoice_round_off": f"{result.invoice_round_off:.2f}",
        "has_rcm": result.has_rcm, "engine_version": result.engine_version,
        "warnings": [{"rule_id": w[0], "message": w[1], "item_line_no": w[2]} for w in result.warnings],
        "items": [
            {**_item_out({**i, "gross_amount": str(t.gross_amount), "discount": str(t.discount), "item_id": None,
                          "description": e.description, "hsn_sac": e.hsn_sac, "uqc": e.uqc, "quantity": str(e.quantity),
                          "unit_rate": str(e.unit_rate), "ledger_id": str(e.ledger_id), "cess_rate": str(t.cess_rate),
                          "cess_specific_amount": str(t.cess_specific_amount), "tax_in_cost": t.tax_in_cost,
                          "itc_exception_claimed": e.itc_exception_claimed, "itc_exception_note": e.itc_exception_note})}
            for i, t, e in zip(items, result.items, expanded.gst.items, strict=True)
        ],
        "rule_status": _rule_status(rows, expanded.gst, items, draft.voucher_date),
    }
    return {"lines": lines, "gst": gst, "errors": errors}
