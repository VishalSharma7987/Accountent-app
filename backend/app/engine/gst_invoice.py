"""Invoice mode (Phase 3, step 3.3): turn an InvoiceIn into the voucher lines, the tax lines and the item rows.

Pure Python (no DB / web / AI). The caller never types a tax amount: the engine builds every ledger line (G-13, G-14).
Booking (CLAUDE.md-style, Tally-like):
  Sales        Dr party (invoice value) / Cr sales ledger per item (taxable value) / Cr Output CGST, SGST, IGST, Cess
  Purchase     Dr purchase / expense / asset ledger per item (taxable value, plus the tax when the credit is blocked)
               / Dr Input tax / Cr party. Reverse charge: party gets the taxable value only; the tax is Dr Input tax
               and Cr RCM payable
  Credit Note  the Sales lines with every side swapped;  Debit Note  the Purchase lines with every side swapped
  Round-off    only when the client option is on: the invoice value is rounded to the nearest rupee (half up); the
               difference goes to the round-off ledger, never to a tax ledger (G-16)

Rules built here: G-06 registration period, G-08 ledger roles, G-12 place of supply, G-14 typed tax, G-16 round-off,
G-17 items, G-18 document kind, G-19 supply category / GSTIN, G-20 import of service, G-22 GSTIN, G-23 number length,
G-24 notes, G-25 purchase documents, G-26 booked lines = engine lines, G-30 blocked-credit tags.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from app.engine.gst_tax import (
    ZERO,
    GstRuleError,
    RuleData,
    compute_item,
    fmt_date,
    head_for,
    in_force,
)
from app.engine.gst_types import (
    ENGINE_VERSION,
    GeneratedLine,
    GstRegistration,
    InvoiceIn,
    InvoiceResult,
    TaxLine,
)
from app.engine.models import ValidationError
from app.engine.money import format_inr, round_half_up

GSTIN_FORMAT = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
NUMBER_CHARS = re.compile(r"^[A-Za-z0-9/-]+$")

OUTWARD = ("sales", "credit_note")
INWARD = ("purchase", "debit_note")
PARTY_DEBIT = ("sales", "debit_note")
OUTWARD_CATEGORIES = frozenset({
    "b2b", "b2c", "sez_with_payment", "sez_without_payment", "export_with_payment", "export_without_payment", "deemed_export",
})
INWARD_CATEGORIES = frozenset({"b2b", "unregistered_supplier", "composition_supplier", "import_of_service"})
NEEDS_GSTIN_OUTWARD = frozenset({"b2b", "sez_with_payment", "sez_without_payment", "deemed_export"})
FOREIGN_POS_CATEGORIES = frozenset({"export_with_payment", "export_without_payment", "import_of_service"})
DOCUMENT_KINDS = frozenset({"tax_invoice", "bill_of_supply", "self_invoice"})
# Reasons of a Credit / Debit Note (voucher_gst.note_reason). Document metadata, not law values.
NOTE_REASONS = frozenset({
    "sales_return", "post_sale_discount", "deficiency_in_services", "correction_in_invoice", "change_in_pos",
    "provisional_assessment", "others",
})
NON_TAXABLE = frozenset({"exempt", "nil_rated", "non_gst"})
ROLE_NAMES = {
    "output_cgst": "Output CGST", "output_sgst": "Output SGST", "output_igst": "Output IGST", "output_cess": "Output Cess",
    "input_cgst": "Input CGST", "input_sgst": "Input SGST", "input_igst": "Input IGST", "input_cess": "Input Cess",
    "rcm_cgst": "RCM CGST payable", "rcm_sgst": "RCM SGST payable", "rcm_igst": "RCM IGST payable",
    "rcm_cess": "RCM Cess payable", "round_off": "Round off",
}
HEADS = ("cgst", "sgst", "igst", "cess")
FORBIDDEN_ITEM_KEYS = frozenset({
    "cgst", "sgst", "igst", "cess", "gst_rate", "rate_of_tax", "tax", "tax_amount", "tax_rate", "taxable_value",
    "gross_amount", "gst", "tax_ledger_id",
})


@dataclass(frozen=True)
class InvoiceContext:
    """What the caller knows about the voucher around the invoice."""

    voucher_type: str  # sales | purchase | credit_note | debit_note
    voucher_date: date
    party_ledger_id: object | None
    registration: GstRegistration
    counterparty_state_code: str | None  # state of the buyer (not needed) / the SUPPLIER of a purchase
    round_off_invoices: bool
    rules: RuleData
    gstin_check: Callable[[str], list[str]] | None = None  # G-01/G-02 check of package A: problems as text


@dataclass(frozen=True)
class BuildOutcome:
    result: InvoiceResult | None
    errors: list[ValidationError]


def _err(rule_id: str, message: str, line_no: int | None = None) -> ValidationError:
    return ValidationError(rule_id, message, line_no)


def typed_tax_errors(has_lines: bool, item_extra_keys: Sequence[Iterable[str]]) -> list[ValidationError]:
    """G-14: in invoice mode the caller supplies no ledger lines and no tax amount or rate."""
    errors = []
    if has_lines:
        errors.append(_err(
            "G-14", "In invoice mode the tax and ledger lines are built by the system; remove the lines you typed "
            "and give only the invoice header and item lines."))
    for n, keys in enumerate(item_extra_keys, start=1):
        bad = sorted(k for k in keys if k in FORBIDDEN_ITEM_KEYS)
        if bad:
            errors.append(_err(
                "G-14", f"Item {n}: tax is calculated by the system; remove {', '.join(bad)}.", n))
    return errors


def check_number_length(number: str, max_length: Decimal | int) -> list[ValidationError]:
    """G-23: a GST document number has at most `max_length` characters (rule table) of letters, digits, / and -."""
    limit = int(max_length)
    problems = []
    if len(number) > limit:
        problems.append(f"{number} has {len(number)} characters; at most {limit} are allowed")
    if not NUMBER_CHARS.match(number):
        problems.append(f"{number} may contain only letters, digits, / and -")
    return [_err("G-23", f"Voucher number {p}, so it cannot be posted as a GST document.") for p in problems]


def check_lines_match(result: InvoiceResult, booked: Sequence[tuple[object, Decimal, Decimal]]) -> list[ValidationError]:
    """G-26: the booked voucher lines (ledger, debit, credit, in order) equal what the engine builds."""
    expected = [(str(x.ledger_id), x.debit, x.credit) for x in result.lines]
    booked = [(str(ledger), debit, credit) for ledger, debit, credit in booked]
    if len(expected) != len(booked):
        return [_err("G-26", f"The voucher has {len(booked)} lines but the invoice items produce {len(expected)}; "
                             "the lines were changed after they were built. Rebuild the voucher from its items.")]
    for number, (want, have) in enumerate(zip(expected, booked, strict=True), start=1):
        if tuple(want) != tuple(have):
            return [_err(
                "G-26",
                f"Line {number} was changed after the system built it: expected Debit {format_inr(want[1])} / Credit "
                f"{format_inr(want[2])}, found Debit {format_inr(have[1])} / Credit {format_inr(have[2])}.", number)]
    return []


def _header_errors(inv: InvoiceIn, ctx: InvoiceContext) -> list[ValidationError]:
    errors: list[ValidationError] = []
    vt, cat, reg = ctx.voucher_type, inv.supply_category, ctx.registration
    outward = vt in OUTWARD
    if vt not in OUTWARD + INWARD:
        return [_err("V-08", "Invoice mode is only for Sales, Purchase, Credit Note and Debit Note vouchers.")]
    if ctx.party_ledger_id is None:
        errors.append(_err("V-13", "An invoice needs its party ledger (the customer or supplier)."))
    if not inv.items:
        errors.append(_err("G-17", "An invoice needs at least one item line."))
    if inv.document_kind not in DOCUMENT_KINDS:
        errors.append(_err("G-18", f"Unknown document kind '{inv.document_kind}'."))
    allowed = OUTWARD_CATEGORIES if outward else INWARD_CATEGORIES
    if cat not in allowed:
        errors.append(_err("G-19", f"Supply category '{cat}' cannot be used on a "
                                   f"{'sales' if outward else 'purchase'} document."))

    # G-06: the registration must be in force on the invoice date
    if inv.invoice_date < reg.effective_from or (reg.effective_to is not None and inv.invoice_date > reg.effective_to):
        errors.append(_err(
            "G-06", f"Registration {reg.gstin} is not in force on {fmt_date(inv.invoice_date)}."))

    # G-12 place of supply
    pos = (inv.place_of_supply or "").strip()
    if not pos or pos not in ctx.rules.state_codes:
        errors.append(_err("G-12", f"Place of supply '{pos}' is not a valid state code; choose it explicitly."))
    elif pos == "96" and cat not in FOREIGN_POS_CATEGORIES:
        errors.append(_err("G-19", "Place of supply 96 (foreign country) is only for exports and imports of services."))
    elif pos != "96" and cat in ("export_with_payment", "export_without_payment"):
        errors.append(_err("G-19", "The place of supply of an export is 96 (foreign country)."))

    # dates
    if outward and inv.invoice_date != ctx.voucher_date:
        errors.append(_err(
            "G-12", f"The invoice date {fmt_date(inv.invoice_date)} must equal the voucher date {fmt_date(ctx.voucher_date)}."))
    if not outward and inv.invoice_date > ctx.voucher_date:
        errors.append(_err(
            "G-25", f"The supplier's invoice date {fmt_date(inv.invoice_date)} is after the voucher date "
                    f"{fmt_date(ctx.voucher_date)}."))

    # GSTIN of the other party (G-19, G-22, G-25)
    gstin = (inv.counterparty_gstin or "").strip().upper() or None
    who = "Buyer" if outward else "Supplier"
    if gstin is None:
        if outward and cat in NEEDS_GSTIN_OUTWARD:
            errors.append(_err("G-19", f"A {cat} supply needs the buyer's GSTIN."))
        if not outward and cat == "b2b":
            errors.append(_err("G-25", "A purchase from a registered supplier needs the supplier's GSTIN (for input credit)."))
    else:
        if outward and cat == "b2c":
            errors.append(_err("G-19", "A B2C supply has no buyer GSTIN; use B2B for a registered buyer."))
        if not GSTIN_FORMAT.match(gstin):
            errors.append(_err("G-22", f"{who} GSTIN {gstin} is not in the GSTIN format (15 characters)."))
        elif ctx.gstin_check is not None:
            for problem in ctx.gstin_check(gstin):
                errors.append(_err("G-22", f"{who} GSTIN {gstin}: {problem}"))

    # G-24 notes
    is_note = vt in ("credit_note", "debit_note")
    if is_note:
        if not inv.original_invoice_no or inv.original_invoice_date is None:
            errors.append(_err("G-24", "A Credit / Debit Note needs the original invoice number and date."))
        elif inv.original_invoice_date > inv.invoice_date:
            errors.append(_err(
                "G-24", f"The original invoice date {fmt_date(inv.original_invoice_date)} is after the note date "
                        f"{fmt_date(inv.invoice_date)}."))
        if inv.note_reason not in NOTE_REASONS:
            errors.append(_err("G-24", "A Credit / Debit Note needs a reason from the list "
                                       f"({', '.join(sorted(NOTE_REASONS))})."))
    elif inv.original_invoice_no or inv.original_invoice_date or inv.note_reason:
        errors.append(_err("G-24", "The original invoice reference and reason belong only on a Credit / Debit Note."))

    # G-18 composition client
    if reg.registration_type == "composition":
        if outward and inv.document_kind != "bill_of_supply":
            errors.append(_err("G-18", "A composition dealer cannot raise a tax invoice or charge tax; use a Bill of Supply."))
        if not outward:
            errors.append(_err(
                "G-18", "Purchases of a composition dealer are not supported in invoice mode (no input credit, tax "
                        "goes into cost); enter them as an ordinary voucher."))
    if inv.document_kind == "self_invoice" and outward:
        errors.append(_err("G-18", "A self-invoice is only for reverse-charge purchases."))
    return errors


def _blocked_flag(inv_item, tax: TaxLine, ctx: InvoiceContext, n: int, inward: bool) -> TaxLine:
    key = inv_item.itc_category_key
    if not key:
        if inv_item.itc_exception_claimed:
            raise GstRuleError("G-30", f"Item {n}: an exception can be claimed only on a line tagged with a blocked-credit category.", n)
        return tax
    if not inward:
        raise GstRuleError("G-30", f"Item {n}: blocked-credit tags apply only to purchases and debit notes.", n)
    live = [r for r in ctx.rules.blocked_rules if r.category_key == key and in_force(r, ctx.voucher_date)]
    if not live:
        raise GstRuleError(
            "G-30", f"Item {n}: blocked-credit category '{key}' is not in force on {fmt_date(ctx.voucher_date)} "
                    "(or does not exist).", n)
    if inv_item.itc_exception_claimed:
        if not live[0].has_exception:
            raise GstRuleError("G-30", f"Item {n}: category '{key}' has no exception to claim.", n)
        if not (inv_item.itc_exception_note or "").strip():
            raise GstRuleError("G-30", f"Item {n}: claiming an exception needs a written note.", n)
        return tax
    return replace(tax, tax_in_cost=True)


def build_invoice(inv: InvoiceIn, ctx: InvoiceContext) -> BuildOutcome:
    """All the invoice-mode rules and the generated lines. result is None when there is any error."""
    errors = _header_errors(inv, ctx)
    if errors and (not inv.items or ctx.voucher_type not in OUTWARD + INWARD):
        return BuildOutcome(None, errors)

    vt, cat, reg = ctx.voucher_type, inv.supply_category, ctx.registration
    outward = vt in OUTWARD
    pos = (inv.place_of_supply or "").strip()

    if outward:
        charge = reg.registration_type != "composition"
        supplier_state: str | None = reg.state_code
    else:
        charge = cat not in ("unregistered_supplier", "composition_supplier")
        supplier_state = ctx.counterparty_state_code
    needs_state = not outward and cat != "import_of_service"
    state_missing = needs_state and supplier_state is None and not errors_has(errors, "G-12")
    if state_missing and (charge or any(i.rcm_category_key for i in inv.items)):
        errors.append(_err("G-12", "The supplier's state is not known (give the supplier's GSTIN or state); the tax "
                                   "head (CGST + SGST or IGST) depends on it."))
    head = "inter"
    if supplier_state is not None and pos:
        head = head_for(supplier_state, pos, cat)
    elif cat in ("import_of_service",):
        head = "inter"

    taxes: list[TaxLine] = []
    warnings: list[tuple[str, str, int | None]] = []
    for n, entry in enumerate(inv.items, start=1):
        try:
            if cat == "import_of_service" and not entry.rcm_category_key:
                raise GstRuleError("G-20", f"Item {n}: every item of an import of service is on reverse charge; "
                                           "give the reverse charge category.", n)
            if entry.rcm_category_key and outward:
                raise GstRuleError("G-20", f"Item {n}: reverse charge applies only to purchases.", n)
            tax = compute_item(n, entry, ctx.rules, ctx.voucher_date if outward else inv.invoice_date, head,
                               charge_tax=charge, supply_category=cat)
            tax = _blocked_flag(entry, tax, ctx, n, not outward)
        except GstRuleError as problem:
            errors.append(_err(problem.rule_id, problem.message, problem.item_line_no))
            continue
        if tax.rate_is_default:
            warnings.append((
                "G-10",
                (f"Item {n}: no specific rate rule for {entry.hsn_sac}; the default rate "
                 f"{tax.gst_rate.normalize():f}% was applied. Check the code."),
                n,
            ))
        taxes.append(tax)

    if len(taxes) == len(inv.items):
        errors.extend(_kind_errors(inv, ctx, taxes))
    if errors:
        return BuildOutcome(None, errors)

    result, role_errors = _generate(inv, ctx, taxes, tuple(warnings))
    return BuildOutcome(None if role_errors else result, role_errors)


def errors_has(errors: Sequence[ValidationError], rule_id: str) -> bool:
    return any(e.rule_id == rule_id for e in errors)


def _kind_errors(inv: InvoiceIn, ctx: InvoiceContext, taxes: Sequence[TaxLine]) -> list[ValidationError]:
    """G-18: tax invoice vs bill of supply for a regular client's outward supplies; self-invoice needs reverse charge."""
    out = []
    if ctx.voucher_type in OUTWARD and ctx.registration.registration_type == "regular":
        all_non_taxable = all(t.treatment in NON_TAXABLE for t in taxes)
        if inv.document_kind == "bill_of_supply" and not all_non_taxable:
            out.append(_err("G-18", "A Bill of Supply is only for supplies where every line is exempt, nil-rated or "
                                    "non-GST; raise a tax invoice."))
        if inv.document_kind == "tax_invoice" and all_non_taxable:
            out.append(_err("G-18", "Every line is exempt, nil-rated or non-GST; a regular dealer issues a Bill of Supply."))
    if inv.document_kind == "self_invoice" and ctx.voucher_type in INWARD and not any(t.rcm for t in taxes):
        out.append(_err("G-18", "A self-invoice is only for reverse-charge purchases."))
    return out


def _generate(
    inv: InvoiceIn, ctx: InvoiceContext, taxes: Sequence[TaxLine], warnings: tuple[tuple[str, str, int | None], ...]
) -> tuple[InvoiceResult, list[ValidationError]]:
    vt, reg = ctx.voucher_type, ctx.registration
    outward = vt in OUTWARD
    party_dr = vt in PARTY_DEBIT
    prefix = "output" if outward else "input"
    errors: list[ValidationError] = []

    def ledger(role: str) -> object | None:
        found = reg.ledger_roles.get(role)
        if found is None:
            errors.append(_err(
                "G-08", f"Registration {reg.gstin} has no ledger mapped for '{ROLE_NAMES[role]}'; map the GST ledger "
                        "roles before using invoice mode."))
        return found

    direct = {h: ZERO for h in HEADS}  # tax booked on Input / Output ledgers (everything not in cost)
    rcm_pay = {h: ZERO for h in HEADS}
    party_amount = ZERO
    item_lines: list[tuple[object, Decimal, int]] = []
    for t, entry in zip(taxes, inv.items, strict=True):
        total_tax = t.cgst + t.sgst + t.igst + t.cess
        amount = t.taxable_value + (total_tax if t.tax_in_cost else ZERO)
        party_amount += t.taxable_value + (ZERO if t.rcm else total_tax)
        for h in HEADS:
            value = getattr(t, h)
            if not t.tax_in_cost:
                direct[h] += value
            if t.rcm:
                rcm_pay[h] += value
        if amount > 0:
            item_lines.append((entry.ledger_id, amount, t.item_line_no))

    def side(amount: Decimal, debit: bool) -> tuple[Decimal, Decimal]:
        return (amount, ZERO) if debit else (ZERO, amount)

    other_dr = not party_dr
    lines: list[GeneratedLine] = []
    rounded = party_amount
    round_off = ZERO
    if ctx.round_off_invoices:
        rounded = round_half_up(party_amount, 0)
        round_off = rounded - party_amount
    if rounded > 0:
        lines.append(GeneratedLine(ctx.party_ledger_id, *side(rounded, party_dr), "party"))
    for ledger_id, amount, item_no in item_lines:
        lines.append(GeneratedLine(ledger_id, *side(amount, other_dr), "taxable", item_no))
    for h in HEADS:
        if direct[h] > 0:
            ledger_id = ledger(f"{prefix}_{h}")
            lines.append(GeneratedLine(ledger_id, *side(direct[h], other_dr), f"tax_{h}"))
    for h in HEADS:
        if rcm_pay[h] > 0:
            ledger_id = ledger(f"rcm_{h}")
            lines.append(GeneratedLine(ledger_id, *side(rcm_pay[h], party_dr), f"rcm_{h}"))
    if round_off != 0:
        ledger_id = ledger("round_off")
        on_party_side = round_off < 0
        lines.append(GeneratedLine(ledger_id, *side(abs(round_off), party_dr if on_party_side else other_dr), "round_off"))

    result = InvoiceResult(
        items=tuple(taxes), lines=tuple(lines), invoice_value=rounded, invoice_round_off=round_off,
        has_rcm=any(t.rcm for t in taxes), engine_version=ENGINE_VERSION, warnings=warnings,
    )
    return result, errors
