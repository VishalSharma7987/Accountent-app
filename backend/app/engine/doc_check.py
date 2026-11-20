"""Engine checks of an extracted invoice (Phase 7, package D; rules D-03, D-05 .. D-17). Pure Python: no DB, web, LLM or OCR imports.

AI reads, Python calculates (CLAUDE.md 2.1): the extraction carries only what is PRINTED, as text. This module turns the text into
Decimal (more than 2 places is rejected, never rounded: D-06), RECOMPUTES every line with the existing GST engine
(`gst_tax.compute_item`: taxable value from quantity x rate - discount, tax from the rate table by HSN and date, ROUND_HALF_UP in the one
shared helper) and the totals from those lines, and reports every difference from the printed values as a finding. Nothing printed is
ever copied into `recomputed`; the draft builder (package E) uses only `recomputed`.

Severity: error (data wrong, edit it), review (the system will not guess), warning (acknowledge), info. Differences up to
`ctx.tolerance` (default `ROUND_TOLERANCE`, 1.00) are a warning, larger ones an error (D-10, D-11, D-13). Printed tax that is absent is
read as 0.00 (an inter-state invoice prints no CGST).
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.doc_types import (
    ROUND_TOLERANCE,
    DocFinding,
    DocType,
    ExtractedInvoice,
    Field,
    Severity,
)
from app.engine.gst_tax import GstRuleError, RuleData, compute_item, head_for, in_force
from app.engine.gst_types import GstRegistration, ItemLineIn, StateCode
from app.engine.gstin import GSTIN_RE, validate_gstin
from app.engine.money import MoneyError, format_inr, parse_amount

ZERO = Decimal("0.00")

# document types by the side the client stands on: the client is the BUYER of a purchase side document, the SUPPLIER of a sale side one.
# (a credit note here is a sales return, a debit note a purchase return, as in the voucher types)
PURCHASE_SIDE = frozenset({DocType.PURCHASE_INVOICE, DocType.DEBIT_NOTE, DocType.EXPENSE_BILL})
SALE_SIDE = frozenset({DocType.SALES_INVOICE, DocType.CREDIT_NOTE})

_LABELS = {
    "supplier_name": "Supplier name", "supplier_gstin": "Supplier GSTIN", "buyer_name": "Buyer name", "buyer_gstin": "Buyer GSTIN",
    "invoice_no": "Invoice number", "invoice_date": "Invoice date", "place_of_supply": "Place of supply",
    "description": "Description", "hsn_sac": "HSN / SAC", "quantity": "Quantity", "unit_rate": "Rate", "discount": "Discount",
    "taxable_value": "Taxable value", "gst_rate": "GST rate", "cgst": "CGST", "sgst": "SGST", "igst": "IGST", "cess": "Cess",
    "taxable_total": "Taxable total", "cgst_total": "CGST total", "sgst_total": "SGST total", "igst_total": "IGST total",
    "cess_total": "Cess total", "round_off": "Round-off", "grand_total": "Grand total", "currency": "Currency",
}


def label(path: str) -> str:
    """'lines[1].taxable_value' -> 'Line 2 taxable value'; 'totals.grand_total' -> 'Grand total'."""
    m = re.match(r"^lines\[(\d+)\]\.(\w+)$", path)
    if m:
        return f"Line {int(m.group(1)) + 1} {_LABELS.get(m.group(2), m.group(2)).lower()}"
    return _LABELS.get(path.split(".")[-1], path)


# ============================================================================================ context and result


@dataclass(frozen=True)
class DuplicateCandidate:
    """An earlier document / voucher the service found for this client (D-03): where it is and what identifies it."""

    source: str                   # "voucher" | "extraction"
    ref: str                      # voucher number / reference, or a text naming the other extraction
    supplier_gstin: str | None
    supplier_name: str | None
    invoice_no: str


@dataclass(frozen=True)
class DocCheckContext:
    registrations: tuple[GstRegistration, ...]            # the client's GST registrations (all periods)
    rules: RuleData                                       # GST rate rules, slabs ... as loaded by the caller (any date)
    state_codes: tuple[StateCode, ...]
    today: date
    doc_type: DocType | None = None                       # chosen at upload
    financial_years: tuple[tuple[date, date], ...] = ()   # (start, end) of the client's years; empty = not checked here
    locked_periods: tuple[tuple[date, date], ...] = ()
    min_confidence: Decimal = Decimal("0.85")
    tolerance: Decimal = ROUND_TOLERANCE
    require_source: bool = True                           # False for an extraction typed by the accountant (no page / confidence)
    page_count: int | None = None
    place_of_supply_override: str | None = None           # state code from the party master (package E), used when none is printed
    duplicates: tuple[DuplicateCandidate, ...] = ()


@dataclass(frozen=True)
class RecomputedLine:
    taxable_value: Decimal
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal


@dataclass(frozen=True)
class DocCheckResult:
    findings: tuple[DocFinding, ...]
    lines: tuple[RecomputedLine | None, ...] = ()         # None = this line could not be recomputed (see its finding)
    totals: dict = field(default_factory=dict)            # {} unless EVERY line was recomputed
    direction: str | None = None                          # "purchase" | "sale" | None (undecided)
    place_of_supply: str | None = None                    # state code
    invoice_date: date | None = None

    @property
    def blocking(self) -> list[DocFinding]:
        return [f for f in self.findings if f.severity in (Severity.ERROR, Severity.REVIEW)]


# ============================================================================================ parsing of printed text


def blank(value: str | None) -> bool:
    return value is None or not value.strip()


def parse_amount_text(text: str, *, signed: bool = False) -> Decimal:
    """Printed amount -> Decimal with 2 places. Indian grouping commas and spaces are removed first; more than 2 decimals, text, an
    exponent or (unless `signed`) a minus sign raise MoneyError (D-06)."""
    cleaned = re.sub(r"[,\s]", "", text)
    if signed and cleaned[:1] in "+-":
        sign, cleaned = cleaned[0], cleaned[1:]
        value = parse_amount(cleaned)
        return -value if sign == "-" and value != 0 else value
    return parse_amount(cleaned)


_DATE_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_DATE_YMD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date_text(text: str) -> date:
    """dd-mm-yyyy, dd/mm/yyyy, dd.mm.yyyy or yyyy-mm-dd. Raises ValueError."""
    t = text.strip()
    m = _DATE_DMY.match(t)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = _DATE_YMD.match(t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise ValueError(t)


_QTY = re.compile(r"^\d+(\.\d{1,3})?$")
_RATE = re.compile(r"^\d+(\.\d{1,4})?$")


class Collector:
    def __init__(self) -> None:
        self.items: list[DocFinding] = []

    def add(self, rule_id: str, severity: Severity, message: str, path: str | None = None,
            printed: str | None = None, computed: str | None = None) -> None:
        self.items.append(DocFinding(rule_id, severity, message, path, printed, computed))

    def amount(self, f: Field, path: str, *, signed: bool = False) -> Decimal | None:
        """Printed amount or None (not printed, or refused with a D-06 finding)."""
        if blank(f.value):
            return None
        try:
            return parse_amount_text(f.value, signed=signed)
        except MoneyError as error:
            self.add("D-06", Severity.ERROR, f"{label(path)} '{f.value.strip()}' cannot be used: {error} (amounts are rejected, never rounded).", path)
            return None

    def number(self, f: Field, path: str, pattern: re.Pattern, places: int, *, positive: bool) -> Decimal | None:
        if blank(f.value):
            return None
        cleaned = re.sub(r"[,\s]", "", f.value).removesuffix("%")
        if not pattern.match(cleaned):
            self.add("D-06", Severity.ERROR,
                     f"{label(path)} '{f.value.strip()}' is not a plain number with at most {places} decimal places.", path)
            return None
        value = Decimal(cleaned)
        if positive and value == 0:
            self.add("D-06", Severity.ERROR, f"{label(path)} must be greater than zero.", path)
            return None
        return value

    def compare(self, rule_id: str, path: str, what: str, printed: Decimal, computed: Decimal, tol: Decimal, *, hint: str = "") -> bool:
        """Printed against recomputed: equal -> nothing; within `tol` -> warning; more -> error. True when a finding was added."""
        diff = abs(printed - computed)
        if diff == 0:
            return False
        severity = Severity.WARNING if diff <= tol else Severity.ERROR
        self.add(rule_id, severity,
                 f"{what}: printed {format_inr(printed)} but recomputed {format_inr(computed)} (difference {format_inr(diff)}).{hint}",
                 path, f"{printed:.2f}", f"{computed:.2f}")
        return True


def _key_no(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def _key_name(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _norm_gstin(text: str | None) -> str | None:
    return None if blank(text) else re.sub(r"\s+", "", text).upper()


# ============================================================================================ field-level checks (D-05)


def _walk_fields(inv: ExtractedInvoice):
    for name in ("document_kind", "supplier_name", "supplier_gstin", "buyer_name", "buyer_gstin", "invoice_no", "invoice_date",
                 "place_of_supply", "original_invoice_no"):
        yield name, getattr(inv, name)
    for i, line in enumerate(inv.lines):
        for name in ("description", "hsn_sac", "quantity", "unit", "unit_rate", "discount", "taxable_value", "gst_rate",
                     "cgst", "sgst", "igst", "cess"):
            yield f"lines[{i}].{name}", getattr(line, name)
    for name in ("taxable_total", "cgst_total", "sgst_total", "igst_total", "cess_total", "round_off", "grand_total"):
        yield f"totals.{name}", getattr(inv.totals, name)


def source_checks_for(fields, require_source: bool, min_confidence: Decimal, page_count: int | None, out: Collector) -> None:
    """D-05 on (path, Field) pairs: a value needs a page and a confidence (unless typed by hand) and a confidence at the minimum."""
    for path, f in fields:
        if blank(f.value):
            continue
        if require_source:
            if f.source is None or f.confidence is None:
                missing = "page / position" if f.source is None else "confidence"
                out.add("D-05", Severity.WARNING,
                        f"{label(path)} '{f.value.strip()}' has no {missing}: it cannot be checked against the document image.", path)
                continue
            if page_count is not None and f.source.page > page_count:
                out.add("D-05", Severity.WARNING,
                        f"{label(path)} says page {f.source.page} but the document has {page_count} page(s).", path)
        if f.confidence is not None and f.confidence < min_confidence:
            out.add("D-05", Severity.WARNING,
                    f"{label(path)} '{f.value.strip()}' was read with confidence {f.confidence:.2f}, below the minimum "
                    f"{min_confidence:.2f}: check it against the document.", path)


def _required(inv: ExtractedInvoice, out: Collector) -> None:
    for name in ("supplier_name", "buyer_name", "invoice_no", "invoice_date"):
        if blank(getattr(inv, name).value):
            out.add("D-05", Severity.ERROR, f"{label(name)} was not found on the document: enter it.", name)
    if not inv.lines:
        out.add("D-05", Severity.ERROR, "No line items were found on the document: enter them.", "lines")
    for i, line in enumerate(inv.lines):
        if blank(line.description.value):
            out.add("D-05", Severity.ERROR, f"Line {i + 1}: description was not found: enter it.", f"lines[{i}].description")
        if blank(line.taxable_value.value) and (blank(line.quantity.value) or blank(line.unit_rate.value)):
            out.add("D-05", Severity.ERROR,
                    f"Line {i + 1}: neither the taxable value nor quantity and rate were found: enter them.",
                    f"lines[{i}].taxable_value")
    if blank(inv.totals.grand_total.value):
        out.add("D-05", Severity.ERROR, "Grand total was not found on the document: enter it.", "totals.grand_total")


# ============================================================================================ direction, registration, place of supply


def _registrations_on(ctx: DocCheckContext, on: date) -> list[GstRegistration]:
    return [r for r in ctx.registrations if r.is_active and r.effective_from <= on and (r.effective_to is None or on <= r.effective_to)]


def _direction(inv: ExtractedInvoice, ctx: DocCheckContext, on: date, sup: str | None, buy: str | None,
               out: Collector) -> str | None:
    regs = _registrations_on(ctx, on)
    expected = "purchase" if ctx.doc_type in PURCHASE_SIDE else "sale" if ctx.doc_type in SALE_SIDE else None
    if not regs:
        out.add("D-08", Severity.INFO,
                "The client has no GST registration in force on the invoice date: the registration checks were skipped.")
        return expected
    mine = {r.gstin for r in regs}
    sup_is, buy_is = sup in mine, buy in mine
    if sup_is and buy_is:
        out.add("D-09", Severity.REVIEW,
                "The client's GSTIN appears as both supplier and buyer: the direction of this document cannot be decided.")
        return None
    if expected == "purchase" and not buy_is:
        out.add("D-08", Severity.ERROR,
                f"This is a purchase document, but the buyer GSTIN {buy or '(not found)'} is not one of the client's registrations.",
                "buyer_gstin")
    elif expected == "sale" and not sup_is:
        out.add("D-08", Severity.ERROR,
                f"This is a sales document, but the supplier GSTIN {sup or '(not found)'} is not one of the client's registrations.",
                "supplier_gstin")
    detected = "purchase" if buy_is else "sale" if sup_is else None
    if detected is None:
        if expected is None:
            out.add("D-09", Severity.REVIEW,
                    "The client's GSTIN is on neither side of this document and no document type was chosen: decide the direction.")
        return None
    if expected is not None and expected != detected:
        out.add("D-09", Severity.REVIEW,
                f"The client's GSTIN shows this document as a {detected}, but it was uploaded as a {expected} document: check the type.")
    return detected


def _state_code_of(text: str | None, ctx: DocCheckContext) -> str | None:
    """'27', '27-Maharashtra', 'Maharashtra (27)' or a state name -> a code of the state table, else None."""
    if blank(text):
        return None
    t = text.strip()
    known = {s.code: s.name for s in ctx.state_codes}
    m = re.match(r"^(\d{2})\b", t) or re.search(r"\((\d{2})\)", t)
    if m and m.group(1) in known:
        return m.group(1)
    low = t.lower()
    best = None
    for s in ctx.state_codes:
        if s.name.lower() in low and (best is None or len(s.name) > len(best.name)):
            best = s
    return best.code if best else None


# ============================================================================================ the check


def check_invoice(inv: ExtractedInvoice, ctx: DocCheckContext) -> DocCheckResult:
    out = Collector()
    _required(inv, out)
    source_checks_for(_walk_fields(inv), ctx.require_source, ctx.min_confidence, ctx.page_count, out)

    if inv.currency.strip().upper() != "INR":
        out.add("D-06", Severity.ERROR, f"Currency '{inv.currency}' is not accepted: only INR documents can be booked.", "currency")

    # ---- date (D-06, D-14)
    on: date | None = None
    if not blank(inv.invoice_date.value):
        try:
            on = parse_date_text(inv.invoice_date.value)
        except ValueError:
            out.add("D-06", Severity.ERROR,
                    f"Invoice date '{inv.invoice_date.value.strip()}' is not a valid date (use dd-mm-yyyy).", "invoice_date")
    if on is not None:
        _date_range(on, ctx, out)

    # ---- GSTIN (D-07)
    sup = _norm_gstin(inv.supplier_gstin.value)
    buy = _norm_gstin(inv.buyer_gstin.value)
    for path, g in (("supplier_gstin", sup), ("buyer_gstin", buy)):
        if g is None:
            continue
        errors = validate_gstin(g, ctx.state_codes, on or ctx.today)
        for e in errors:
            out.add("D-07", Severity.ERROR, e.message, path)

    if on is None:
        # nothing that depends on the date (rate table, registrations in force) can be decided
        _duplicates(inv, ctx, sup, out)
        return DocCheckResult(tuple(out.items))

    direction = _direction(inv, ctx, on, sup, buy, out)

    # ---- place of supply and tax head
    supplier_state = sup[:2] if sup and GSTIN_RE.match(sup) else None
    pos = _place_of_supply(inv, ctx, buy if buy and GSTIN_RE.match(buy) else None, out)
    registered_supplier = sup is not None and bool(GSTIN_RE.match(sup))
    charge_tax = registered_supplier
    if direction == "sale":
        comp = [r for r in _registrations_on(ctx, on) if r.gstin == sup and r.registration_type == "composition"]
        if comp:
            charge_tax = False
    head = None            # None = cannot be decided (the place of supply was reported above): no line is recomputed
    if not charge_tax:
        head = "intra"     # no tax is charged, so the head does not matter
    elif supplier_state is not None and pos is not None:
        head = head_for(supplier_state, pos, "b2b")

    # ---- lines
    tax_note = "" if registered_supplier else " The supplier GSTIN is missing or invalid, so the supplier is treated as unregistered (no tax can be charged); if the supplier is registered, enter the GSTIN."
    recomputed = [_check_line(i, line, ctx, on, head, charge_tax, tax_note, out) for i, line in enumerate(inv.lines)]
    # printed per-line taxable values (for D-17), parsed quietly: failures were reported by _check_line
    quiet = Collector()
    printed_taxable = [quiet.amount(line.taxable_value, f"lines[{i}].taxable_value") for i, line in enumerate(inv.lines)]

    totals = _check_totals(inv, ctx, recomputed, printed_taxable, out)
    _duplicates(inv, ctx, sup, out)
    return DocCheckResult(tuple(out.items), tuple(recomputed), totals, direction, pos, on)


def _date_range(on: date, ctx: DocCheckContext, out: Collector) -> None:
    when = on.strftime("%d-%m-%Y")
    if on > ctx.today:
        out.add("D-14", Severity.ERROR, f"Invoice date {when} is in the future.", "invoice_date")
        return
    if ctx.financial_years and not any(a <= on <= b for a, b in ctx.financial_years):
        out.add("D-14", Severity.ERROR, f"Invoice date {when} is outside the client's financial years.", "invoice_date")
        return
    if any(a <= on <= b for a, b in ctx.locked_periods):
        out.add("D-14", Severity.ERROR, f"Invoice date {when} is in a locked period: it cannot be booked there.", "invoice_date")


def _place_of_supply(inv: ExtractedInvoice, ctx: DocCheckContext, buyer_gstin: str | None, out: Collector) -> str | None:
    printed = inv.place_of_supply.value
    if not blank(printed):
        code = _state_code_of(printed, ctx)
        if code is None:
            out.add("D-12", Severity.REVIEW,
                    f"Place of supply '{printed.strip()}' is not a state or code of the state table: correct it.", "place_of_supply")
        return code
    if ctx.place_of_supply_override is not None:
        return ctx.place_of_supply_override
    if buyer_gstin is not None:
        out.add("D-12", Severity.INFO,
                f"Place of supply is not printed: the buyer's state ({buyer_gstin[:2]}, from the buyer GSTIN) is used.", "place_of_supply")
        return buyer_gstin[:2]
    out.add("D-12", Severity.REVIEW, "Place of supply is not printed and cannot be taken from a buyer GSTIN: enter it.", "place_of_supply")
    return None


def _check_line(i: int, line, ctx: DocCheckContext, on: date, head: str | None, charge_tax: bool, tax_note: str,
                out: Collector) -> RecomputedLine | None:
    p = f"lines[{i}]"
    n = i + 1
    start = len(out.items)
    qty = out.number(line.quantity, f"{p}.quantity", _QTY, 3, positive=True)
    rate = out.amount(line.unit_rate, f"{p}.unit_rate")
    disc = out.amount(line.discount, f"{p}.discount")
    p_taxable = out.amount(line.taxable_value, f"{p}.taxable_value")
    p_rate = out.number(line.gst_rate, f"{p}.gst_rate", _RATE, 4, positive=False)
    printed = {h: out.amount(getattr(line, h), f"{p}.{h}") for h in ("cgst", "sgst", "igst", "cess")}

    hsn = None if blank(line.hsn_sac.value) else re.sub(r"\s+", "", line.hsn_sac.value)
    if hsn is None or not hsn.isdigit():
        shown = "was not found" if hsn is None else f"'{hsn}' is not numeric"
        out.add("D-16", Severity.REVIEW, f"Line {n}: the HSN / SAC code {shown}: the tax rate cannot be decided without it.", f"{p}.hsn_sac")
        return None
    if any(f.severity == Severity.ERROR for f in out.items[start:]) or head is None:
        return None
    if blank(line.taxable_value.value) and (qty is None or rate is None):
        return None   # already an error (D-05)

    # the basis of the recomputation: quantity x rate - discount, or the printed taxable value when they are not printed
    from_printed = qty is None or rate is None
    if from_printed:
        if p_taxable is None:
            return None
        q, r, d = Decimal(1), p_taxable, ZERO
        out.add("D-10", Severity.WARNING,
                f"Line {n}: quantity or rate was not found, so the taxable value could not be recomputed; the printed "
                f"{format_inr(p_taxable)} is used.", f"{p}.quantity")
    else:
        q, r, d = qty, rate, disc if disc is not None else ZERO
    uqc = None if blank(line.unit.value) else line.unit.value.strip().upper()
    item = ItemLineIn(line.description.value or "", hsn, q, r, d, "-", uqc=uqc)
    try:
        tl = compute_item(n, item, ctx.rules, on, head, charge_tax=charge_tax, supply_category="b2b")
    except GstRuleError as error:
        if error.rule_id in ("G-10", "G-11"):
            out.add("D-15", Severity.REVIEW,
                    f"{error.message} The rate table has a gap (pending): add the rule; nothing is filled in.", f"{p}.hsn_sac")
        elif error.rule_id == "G-17":
            out.add("D-06", Severity.ERROR, error.message, f"{p}.quantity")
        else:
            out.add("D-11", Severity.ERROR, error.message, f"{p}.hsn_sac")
        return None

    rec = RecomputedLine(tl.taxable_value, tl.gst_rate, tl.cgst, tl.sgst, tl.igst, tl.cess)

    # D-10 taxable value
    if not from_printed and p_taxable is not None:
        out.compare("D-10", f"{p}.taxable_value", f"Line {n} taxable value", p_taxable, tl.taxable_value, ctx.tolerance,
                    hint=" (quantity x rate - discount)")

    # rate (D-15 slab, D-11 table)
    skip_tax = False
    if p_rate is not None:
        if tl.treatment == "taxable":
            slab = any(s.rate == p_rate and in_force(s, on) for s in ctx.rules.slabs)
            if not slab:
                out.add("D-15", Severity.ERROR,
                        f"Line {n}: the printed GST rate {p_rate}% is not a GST rate in force on {on.strftime('%d-%m-%Y')}.",
                        f"{p}.gst_rate", str(p_rate), str(tl.gst_rate))
                skip_tax = True
            elif p_rate != tl.gst_rate:
                out.add("D-11", Severity.ERROR,
                        f"Line {n}: the printed GST rate {p_rate}% differs from the rate table ({tl.gst_rate.normalize():f}% for {hsn})." + tax_note,
                        f"{p}.gst_rate", str(p_rate), str(tl.gst_rate))
                skip_tax = True
        elif p_rate != 0:
            out.add("D-11", Severity.ERROR,
                    f"Line {n}: a GST rate of {p_rate}% is printed, but no tax is chargeable on {hsn} on this date (rate table: {tl.treatment}).",
                    f"{p}.gst_rate", str(p_rate), "0")
            skip_tax = True

    # tax type against the place of supply (D-12)
    if not skip_tax and tl.treatment == "taxable" and charge_tax:
        if head == "intra" and (printed["igst"] or ZERO) > 0:
            out.add("D-12", Severity.ERROR,
                    f"Line {n}: IGST is printed, but supplier and place of supply are in the same state, so CGST + SGST apply.",
                    f"{p}.igst", f"{printed['igst']:.2f}", "0.00")
            skip_tax = True
        elif head == "inter":
            bad = next((h for h in ("cgst", "sgst") if (printed[h] or ZERO) > 0), None)
            if bad:
                out.add("D-12", Severity.ERROR,
                        f"Line {n}: {bad.upper()} is printed, but the supply is to another state, so IGST applies.",
                        f"{p}.{bad}", f"{printed[bad]:.2f}", "0.00")
                skip_tax = True

    # tax amounts (D-11)
    if not skip_tax:
        for h, value in (("cgst", tl.cgst), ("sgst", tl.sgst), ("igst", tl.igst), ("cess", tl.cess)):
            out.compare("D-11", f"{p}.{h}", f"Line {n} {h.upper() if h != 'cess' else 'cess'}", printed[h] or ZERO, value,
                        ctx.tolerance, hint=tax_note if (printed[h] or ZERO) > 0 and not charge_tax else "")
    return rec


def _check_totals(inv: ExtractedInvoice, ctx: DocCheckContext, rec: list[RecomputedLine | None],
                  printed_taxable: list[Decimal | None], out: Collector) -> dict:
    t = inv.totals
    p = {name: out.amount(getattr(t, name), f"totals.{name}", signed=(name == "round_off"))
         for name in ("taxable_total", "cgst_total", "sgst_total", "igst_total", "cess_total", "round_off", "grand_total")}

    # D-17: the printed lines must add up to the printed taxable total (otherwise a line was probably missed)
    d17 = False
    if inv.lines and p["taxable_total"] is not None and all(v is not None for v in printed_taxable):
        d17 = out.compare("D-17", "totals.taxable_total", "Printed taxable total against the printed lines",
                          p["taxable_total"], sum(printed_taxable, ZERO), ctx.tolerance,
                          hint=" The lines read from the document do not add up to its total: a line may have been missed.")

    if not rec or any(r is None for r in rec):
        return {}
    ro = p["round_off"] if p["round_off"] is not None else ZERO
    sums = {
        "taxable_total": sum((r.taxable_value for r in rec), ZERO), "cgst_total": sum((r.cgst for r in rec), ZERO),
        "sgst_total": sum((r.sgst for r in rec), ZERO), "igst_total": sum((r.igst for r in rec), ZERO),
        "cess_total": sum((r.cess for r in rec), ZERO),
    }
    grand = sum(sums.values(), ZERO) + ro
    totals = {**sums, "round_off": ro, "grand_total": grand}

    if abs(ro) > ctx.tolerance:
        out.add("D-13", Severity.ERROR,
                f"Round-off {format_inr(ro)} is more than {format_inr(ctx.tolerance)}: it cannot explain the difference to the lines.",
                "totals.round_off", f"{ro:.2f}", None)
    for name in ("taxable_total", "cgst_total", "sgst_total", "igst_total", "cess_total"):
        if p[name] is None or (name == "taxable_total" and d17):
            continue
        out.compare("D-13", f"totals.{name}", _LABELS[name], p[name], sums[name], ctx.tolerance)
    if p["grand_total"] is not None and abs(ro) <= ctx.tolerance:
        out.compare("D-13", "totals.grand_total", "Grand total", p["grand_total"], grand, ctx.tolerance,
                    hint=" (lines + taxes + round-off)")
    return totals


def _duplicates(inv: ExtractedInvoice, ctx: DocCheckContext, supplier_gstin: str | None, out: Collector) -> None:
    if blank(inv.invoice_no.value):
        return
    no = _key_no(inv.invoice_no.value)
    name = None if blank(inv.supplier_name.value) else _key_name(inv.supplier_name.value)
    for c in ctx.duplicates:
        if _key_no(c.invoice_no) != no:
            continue
        if supplier_gstin and c.supplier_gstin:
            same = supplier_gstin == c.supplier_gstin.upper()
        elif name and c.supplier_name:
            same = name == _key_name(c.supplier_name)
        else:
            same = False
        if same:
            out.add("D-03", Severity.WARNING,
                    f"Invoice {inv.invoice_no.value.strip()} of this supplier may already be entered ({c.source}: {c.ref}).", "invoice_no")
