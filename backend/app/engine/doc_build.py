"""Assembles a GST invoice-mode DRAFT from a validated extraction and the saved mappings (Phase 7 package E; D-20..D-24).

Pure Python: no DB, web or AI imports. The result is plain data (`VoucherDraft` with a `gst` block of item lines); the SERVICE
passes it to the voucher service, which computes every tax amount (G-xx), balances the voucher (V-04) and applies every other
rule. Nothing printed on the document is posted as an amount: only taxable ingredients (quantity, rate, discount), HSN and date go
in. A draft is built only when no `error` or `review` finding exists; unknown party / ledger / place of supply is a finding,
never a guess and never an auto-created master.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.engine.doc_map import (
    LineMap,
    PartyMap,
    normalise_gstin,
    normalise_name,
    resolve_line,
    resolve_party,
)
from app.engine.doc_types import (
    BLOCKING,
    DRAFTABLE_VOUCHER_TYPE,
    DocFinding,
    DocType,
    ExtractedInvoice,
    ExtractedLine,
    ExtractedTotals,
    Field,
    Severity,
    Source,
)
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import VoucherDraft

OUTWARD = ("sales", "credit_note")
LABELS = {"purchase": "Purchase invoice", "sales": "Sales invoice", "credit_note": "Credit note", "debit_note": "Debit note"}
_NUMBER = re.compile(r"^\d+(\.\d+)?$")
_DATE_FORMATS = (
    (re.compile(r"^(\d{2})-(\d{2})-(\d{4})$"), (2, 1, 0)),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"), (2, 1, 0)),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), (0, 1, 2)),
)


@dataclass(frozen=True)
class RegistrationInfo:
    id: object
    gstin: str
    state_code: str
    effective_from: date
    effective_to: date | None = None


@dataclass(frozen=True)
class PartyInfo:
    """What the party master says about a ledger (all optional)."""

    ledger_id: object
    gstin: str | None = None
    state_code: str | None = None
    gst_registration_type: str | None = None


@dataclass(frozen=True)
class ItemInfo:
    id: object
    hsn_sac: str
    uqc: str | None = None


@dataclass(frozen=True)
class BuildContext:
    client_id: object
    doc_type: DocType
    registrations: Sequence[RegistrationInfo]
    party_maps: Sequence[PartyMap]
    line_maps: Sequence[LineMap]
    state_names: Mapping[str, str]                      # state code -> name (rule table gst_state_codes)
    parties: Mapping[str, PartyInfo] = None             # str(ledger id) -> party master facts
    items: Mapping[str, ItemInfo] = None                # str(item id) -> item master facts
    note_reason: str | None = None                      # credit / debit notes: chosen by the accountant, never guessed
    original_invoice_date: date | None = None           # credit / debit notes: not on the extraction schema


@dataclass(frozen=True)
class BuildResult:
    findings: tuple[DocFinding, ...]
    draft: VoucherDraft | None
    party_map_ids: tuple = ()
    line_map_ids: tuple = ()

    @property
    def blocked(self) -> bool:
        return any(f.severity in BLOCKING for f in self.findings)


# ============================================================================================ small parsers


def parse_date(text: str | None) -> date | None:
    shown = (text or "").strip()
    for pattern, (yi, mi, di) in _DATE_FORMATS:
        m = pattern.match(shown)
        if m:
            try:
                return date(int(m.group(yi + 1)), int(m.group(mi + 1)), int(m.group(di + 1)))
            except ValueError:
                return None
    return None


def parse_number(text: str | None) -> Decimal | None:
    """Plain non-negative decimal as printed; Indian commas are stripped. None when it is not a number."""
    shown = (text or "").strip().replace(",", "")
    if not _NUMBER.match(shown):
        return None
    try:
        return Decimal(shown)
    except InvalidOperation:
        return None


def state_code_from_text(text: str | None, state_names: Mapping[str, str]) -> str | None:
    """'29', '29-Karnataka', 'Karnataka (29)' or 'Karnataka' -> '29'. None when it is not exactly one known state."""
    shown = (text or "").strip()
    if not shown:
        return None
    if shown in state_names:
        return shown
    m = re.match(r"^(\d{2})\s*[-:]\s*.+$", shown) or re.match(r"^.+\((\d{2})\)$", shown)
    if m and m.group(1) in state_names:
        return m.group(1)
    wanted = normalise_name(shown)
    found = [code for code, name in state_names.items() if normalise_name(name) == wanted]
    return found[0] if len(found) == 1 else None


def _val(field: Field) -> str | None:
    text = (field.value or "").strip() if field is not None else ""
    return text or None


def _f(rule: str, sev: Severity, message: str, path: str | None = None, printed: str | None = None) -> DocFinding:
    return DocFinding(rule, sev, message, path, printed)


# ============================================================================================ the builder


def build_invoice_draft(inv: ExtractedInvoice, ctx: BuildContext) -> BuildResult:
    findings: list[DocFinding] = []
    voucher_type = DRAFTABLE_VOUCHER_TYPE.get(ctx.doc_type)
    if voucher_type is None:
        return BuildResult((_f("D-09", Severity.ERROR, f"A document of type '{ctx.doc_type.value}' is not an invoice or note and "
                                                      "cannot be drafted as a voucher."),), None)
    outward = voucher_type in OUTWARD
    parties = ctx.parties or {}
    items = ctx.items or {}

    # ---- header: date, number, our registration
    inv_date = parse_date(_val(inv.invoice_date))
    if inv_date is None:
        findings.append(_f("D-06", Severity.ERROR, "The invoice date is missing or not a date (dd-mm-yyyy, dd/mm/yyyy or yyyy-mm-dd).",
                           "invoice_date", _val(inv.invoice_date)))
    invoice_no = _val(inv.invoice_no)
    if invoice_no is None and voucher_type in ("purchase", "debit_note"):
        findings.append(_f("D-05", Severity.ERROR, "The invoice number is missing; a purchase needs the supplier's bill number.",
                           "invoice_no"))
    client_gstin = normalise_gstin(_val(inv.supplier_gstin if outward else inv.buyer_gstin))
    registration = None
    if inv_date is not None:
        in_force = [r for r in ctx.registrations if client_gstin is not None and r.gstin == client_gstin
                    and r.effective_from <= inv_date and (r.effective_to is None or inv_date <= r.effective_to)]
        registration = in_force[0] if in_force else None
    if registration is None and inv_date is not None:
        side = "supplier" if outward else "buyer"
        findings.append(_f("D-08", Severity.ERROR,
                           f"The {side} GSTIN {client_gstin or '(not printed)'} is not a GST registration of this client in force "
                           "on the invoice date.", "supplier_gstin" if outward else "buyer_gstin", client_gstin))

    # ---- the other party
    if outward:
        label, p_name, p_gstin, p_path = "Buyer", inv.buyer_name, inv.buyer_gstin, "buyer_name"
    else:
        label, p_name, p_gstin, p_path = "Supplier", inv.supplier_name, inv.supplier_gstin, "supplier_name"
    counterparty_gstin = normalise_gstin(_val(p_gstin))
    pres = resolve_party(label=label, gstin=counterparty_gstin, name=_val(p_name), maps=ctx.party_maps, field_path=p_path)
    if pres.finding:
        findings.append(pres.finding)
    party = parties.get(str(pres.ledger_id)) if pres.ledger_id is not None else None
    if party is not None and party.gstin and counterparty_gstin and party.gstin != counterparty_gstin:
        findings.append(_f("D-22", Severity.ERROR,
                           f"{label} GSTIN {counterparty_gstin} on the document differs from GSTIN {party.gstin} saved on the mapped "
                           "party ledger. Correct the document data or the party master.", p_path.replace("name", "gstin"),
                           counterparty_gstin))

    # ---- place of supply (D-23): printed, else derived from the document; never guessed
    pos = None
    printed_pos = _val(inv.place_of_supply)
    if printed_pos is not None:
        pos = state_code_from_text(printed_pos, ctx.state_names)
        if pos is None:
            findings.append(_f("D-23", Severity.REVIEW, f"The place of supply '{printed_pos}' is not a known state. Choose it.",
                               "place_of_supply", printed_pos))
    else:
        if outward:
            pos = counterparty_gstin[:2] if counterparty_gstin else (party.state_code if party is not None else None)
        elif registration is not None:
            pos = registration.state_code
        if pos is None or pos not in ctx.state_names:
            pos = None
            findings.append(_f("D-23", Severity.REVIEW, "The place of supply is not printed and cannot be worked out from the "
                                                       "GSTINs or the party master. Choose it.", "place_of_supply"))

    # ---- credit / debit notes need facts the extraction does not carry: chosen by a person
    is_note = voucher_type in ("credit_note", "debit_note")
    original_no = _val(inv.original_invoice_no)
    if is_note:
        if original_no is None or ctx.original_invoice_date is None:
            findings.append(_f("D-25", Severity.REVIEW, "[G-24] A credit / debit note needs the original invoice number and date. "
                               "Enter the missing one.", "original_invoice_no", original_no))
        if ctx.note_reason is None:
            findings.append(_f("D-25", Severity.REVIEW, "[G-24] A credit / debit note needs a reason; choose it.", "note_reason"))

    # ---- lines
    item_lines: list[ItemLineIn] = []
    line_map_ids: list = []
    if not inv.lines:
        findings.append(_f("D-05", Severity.ERROR, "The document has no item lines.", "lines"))
    for n, line in enumerate(inv.lines, start=1):
        base = f"lines[{n - 1}]"
        desc, hsn = _val(line.description), _val(line.hsn_sac)
        qty, rate = parse_number(_val(line.quantity)), parse_number(_val(line.unit_rate))
        discount = parse_number(_val(line.discount)) if _val(line.discount) else Decimal(0)
        for value, name, text in ((qty, "quantity", _val(line.quantity)), (rate, "rate", _val(line.unit_rate)),
                                  (discount, "discount", _val(line.discount))):
            if value is None:
                findings.append(_f("D-05" if text is None else "D-06", Severity.ERROR,
                                   f"Line {n}: {name} is missing." if text is None else f"Line {n}: {name} '{text}' is not a number.",
                                   f"{base}.{'unit_rate' if name == 'rate' else name}", text))
        res = resolve_line(n=n, description=desc, hsn_sac=hsn, party_ledger_id=pres.ledger_id, maps=ctx.line_maps)
        if res.finding:
            findings.append(res.finding)
        line_map_ids.extend(res.map_ids)
        item = items.get(str(res.item_id)) if res.item_id is not None else None
        use_hsn = hsn or (item.hsn_sac if item is not None else None)
        if use_hsn is None:
            findings.append(_f("D-16", Severity.REVIEW, f"Line {n}: no HSN / SAC on the document and no item master to take it from.",
                               f"{base}.hsn_sac"))
        if desc is None and item is None:
            findings.append(_f("D-05", Severity.ERROR, f"Line {n}: the description is missing.", f"{base}.description"))
        if None not in (qty, rate, discount) and res.ledger_id is not None and use_hsn is not None:
            item_lines.append(ItemLineIn(
                desc or "", use_hsn, qty, rate, discount, str(res.ledger_id),
                None if res.item_id is None else str(res.item_id), item.uqc if item is not None else None))

    blocked = any(f.severity in BLOCKING for f in findings)
    if blocked or inv_date is None or registration is None or pos is None or pres.ledger_id is None:
        return BuildResult(tuple(findings), None, tuple(pres.map_ids), tuple(line_map_ids))

    # ---- supply category (never RCM / composition guessed beyond the party master)
    if counterparty_gstin is not None:
        category = "b2b"
    elif outward:
        category = "b2c"
    else:
        category = "composition_supplier" if party is not None and party.gst_registration_type == "composition" else "unregistered_supplier"
    gst = InvoiceIn(
        str(registration.id), "tax_invoice", category, pos, inv_date, tuple(item_lines), counterparty_gstin,
        original_no if is_note else None, ctx.original_invoice_date if is_note else None, ctx.note_reason if is_note else None,
    )
    shown_name = _val(p_name) or ""
    narration = f"{LABELS[voucher_type]} {invoice_no or ''} dated {inv_date.strftime('%d-%m-%Y')} {shown_name} (from document)".replace("  ", " ")
    reference = invoice_no if (invoice_no or voucher_type in ("purchase", "debit_note")) else None
    draft = VoucherDraft(ctx.client_id, voucher_type, inv_date, narration, reference, pres.ledger_id, (), gst=gst)
    return BuildResult(tuple(findings), draft, tuple(pres.map_ids), tuple(line_map_ids))


# ============================================================================================ payload -> engine data


def _field(raw: object) -> Field:
    """One `{value, page, bbox, confidence}` object of the stored extraction payload (a missing key is 'not found')."""
    if not isinstance(raw, dict):
        return Field(None)
    page, box, conf = raw.get("page"), raw.get("bbox"), raw.get("confidence")
    source = None
    if isinstance(page, int):
        source = Source(page, None if not box else tuple(Decimal(str(x)) for x in box))
    value = raw.get("value")
    return Field(None if value is None else str(value), source, None if conf in (None, "") else Decimal(str(conf)))


def invoice_from_payload(payload: Mapping) -> ExtractedInvoice:
    """The stored extraction payload (docs/PHASE7_API_CONTRACT.md) as the engine's ExtractedInvoice. Package D's schema module
    produces the same thing; this plain-dict reader lets the builder work on a stored (or accountant-edited) payload."""
    line_keys = ("description", "hsn_sac", "quantity", "unit", "unit_rate", "discount", "taxable_value", "gst_rate", "cgst", "sgst",
                 "igst", "cess")
    total_keys = ("taxable_total", "cgst_total", "sgst_total", "igst_total", "cess_total", "round_off", "grand_total")
    lines = tuple(ExtractedLine(*(_field(ln.get(k)) for k in line_keys)) for ln in payload.get("lines") or [])
    totals = payload.get("totals") or {}
    return ExtractedInvoice(
        *(_field(payload.get(k)) for k in ("document_kind", "supplier_name", "supplier_gstin", "buyer_name", "buyer_gstin",
                                           "invoice_no", "invoice_date", "place_of_supply", "original_invoice_no")),
        lines, ExtractedTotals(*(_field(totals.get(k)) for k in total_keys)),
        str(payload.get("currency") or "INR"), tuple(str(x) for x in payload.get("notes") or []),
    )
