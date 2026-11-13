"""GSTR-1 working (Phase 3, package E). Pure Python: no DB, web or AI imports.

Takes plain outward documents (posted Sales and Credit Note vouchers in invoice mode, already read from the books) and
sorts every item into exactly one GSTR-1 section by fixed rules (G-50), builds the HSN summary (G-51) and the
documents-issued table. Nothing is guessed: a document that fits no section is listed under `unclassified` with a warning.
Law values (the B2C-large limit) are passed in, never hardcoded. Portal table numbers are constants still to be
confirmed against the portal (PHASE3_LEGAL_VALUES.md section 5), so they are reported separately and marked pending.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.engine.money import format_inr, round_half_up

ZERO = Decimal("0.00")
HEADS = ("igst", "cgst", "sgst", "cess")
NIL_TREATMENTS = ("exempt", "nil_rated", "non_gst")
EXPORT_CATEGORIES = ("export_with_payment", "export_without_payment")
SEZ_CATEGORIES = ("sez_with_payment", "sez_without_payment")

# As understood (secondary sources); to be confirmed against the portal before they are called official (G-55).
PORTAL_TABLES = {
    "b2b": "4", "b2cl": "5", "exports": "6A", "sez": "6B", "b2cs": "7", "nil_exempt_non_gst": "8",
    "cdnr": "9B", "cdnur": "9B", "hsn_summary": "12", "documents_issued": "13",
}
PORTAL_TABLES_STATUS = "pending"


@dataclass(frozen=True)
class ItemRow:
    """One item line of an invoice-mode voucher (from voucher_item_lines). Amounts are positive."""

    item_line_no: int
    hsn_sac: str
    description: str
    uqc: str | None
    quantity: Decimal
    taxable_value: Decimal
    treatment: str
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    rcm: bool = False


@dataclass(frozen=True)
class DocRow:
    """One posted invoice-mode voucher. `voucher_type` is sales | credit_note | purchase | debit_note."""

    voucher_id: str
    voucher_type: str
    number: str
    invoice_date: date
    supply_category: str
    place_of_supply: str
    party_gstin: str | None
    party_name: str
    party_gst_type: str | None
    invoice_value: Decimal
    items: tuple[ItemRow, ...]
    original_invoice_no: str | None = None
    original_invoice_date: date | None = None
    note_reason: str | None = None


@dataclass(frozen=True)
class NumberRow:
    """A voucher number consumed in the period (for the documents-issued table)."""

    voucher_type: str
    number: str
    cancelled: bool  # reversed original, or the reversal voucher itself


@dataclass
class Gstr1Result:
    tables: dict
    warnings: list[str] = field(default_factory=list)


def period_end(period_kind: str, period_start: date) -> date:
    """Last day of the month or quarter that starts on `period_start`. Raises ValueError for a start that is not a period start."""
    if period_start.day != 1:
        raise ValueError(f"Period must start on the 1st of a month, not {period_start.strftime('%d-%m-%Y')}.")
    if period_kind == "month":
        months = 1
    elif period_kind == "quarter":
        if period_start.month not in (1, 4, 7, 10):
            raise ValueError("A quarter starts in April, July, October or January.")
        months = 3
    else:
        raise ValueError(f"Period kind must be month or quarter, not {period_kind!r}.")
    month = period_start.month - 1 + months
    nxt = date(period_start.year + month // 12, month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _q(value: Decimal) -> Decimal:
    return round_half_up(value, 2)


def _zero_heads() -> dict[str, Decimal]:
    return {h: ZERO for h in HEADS}


def _sign(doc: DocRow) -> int:
    return -1 if doc.voucher_type in ("credit_note", "debit_note") else 1


def _is_inter(doc: DocRow, reg_state: str) -> bool:
    return doc.place_of_supply != reg_state


def _item_dict(rate: Decimal, rows: list[ItemRow]) -> dict:
    return {
        "rate": rate,
        "taxable_value": sum((r.taxable_value for r in rows), ZERO),
        "igst": sum((r.igst for r in rows), ZERO),
        "cgst": sum((r.cgst for r in rows), ZERO),
        "sgst": sum((r.sgst for r in rows), ZERO),
        "cess": sum((r.cess for r in rows), ZERO),
    }


def _items_by_rate(items: tuple[ItemRow, ...] | list[ItemRow]) -> list[dict]:
    by_rate: dict[Decimal, list[ItemRow]] = {}
    for it in items:
        by_rate.setdefault(it.gst_rate, []).append(it)
    return [_item_dict(rate, by_rate[rate]) for rate in sorted(by_rate)]


def _section_of(doc: DocRow, reg_state: str, b2cl_limit: Decimal) -> str | None:
    """The GSTR-1 section of a document (G-50), or None when the rules cannot place it."""
    cat = doc.supply_category
    if doc.voucher_type == "credit_note":
        if cat in EXPORT_CATEGORIES:
            return "cdnur"
        if cat in ("b2b", "deemed_export") + SEZ_CATEGORIES:
            return "cdnr" if doc.party_gstin else None
        if cat == "b2c":
            return "cdnur"
        return None
    if cat in EXPORT_CATEGORIES:
        return "exports"
    if cat in SEZ_CATEGORIES:
        return "sez" if doc.party_gstin else None
    if cat in ("b2b", "deemed_export"):
        return "b2b" if doc.party_gstin else None
    if cat == "b2c":
        return "b2cl" if _is_inter(doc, reg_state) and doc.invoice_value > b2cl_limit else "b2cs"
    return None


def _supply_type(doc: DocRow) -> str:
    return {
        "deemed_export": "deemed_export", "sez_with_payment": "sez_with_payment",
        "sez_without_payment": "sez_without_payment",
    }.get(doc.supply_category, "regular")


def _invoice_dict(doc: DocRow, items: list[ItemRow]) -> dict:
    return {
        "invoice_no": doc.number, "invoice_date": doc.invoice_date, "invoice_value": doc.invoice_value,
        "place_of_supply": doc.place_of_supply, "reverse_charge": "N", "supply_type": _supply_type(doc),
        "items": _items_by_rate(items),
    }


def _note_dict(doc: DocRow, items: list[ItemRow]) -> dict:
    return {
        "note_no": doc.number, "note_date": doc.invoice_date, "note_type": "C", "note_value": doc.invoice_value,
        "original_invoice_no": doc.original_invoice_no, "original_invoice_date": doc.original_invoice_date,
        "reason": doc.note_reason, "place_of_supply": doc.place_of_supply, "supply_type": _supply_type(doc),
        "items": _items_by_rate(items),
    }


def _nil_bucket(doc: DocRow, reg_state: str) -> str:
    return ("inter" if _is_inter(doc, reg_state) else "intra") + ("_registered" if doc.party_gstin else "_unregistered")


def build_gstr1(
    docs: list[DocRow], numbers: list[NumberRow], reg_state: str, b2cl_limit: Decimal
) -> Gstr1Result:
    """Build every GSTR-1 table from posted outward documents. `docs` holds sales and credit_note vouchers only."""
    warnings: list[str] = []
    b2b: dict[str, dict] = {}
    sez_rows: dict[str, dict] = {}
    exp_rows: dict[str, list[dict]] = {"with_payment": [], "without_payment": []}
    b2cl: dict[str, list[dict]] = {}
    b2cs: dict[tuple[str, Decimal], list[ItemRow]] = {}
    cdnr: dict[str, dict] = {}
    cdnur: list[dict] = []
    nil = {k: {"nil_rated": ZERO, "exempt": ZERO, "non_gst": ZERO}
           for k in ("inter_registered", "intra_registered", "inter_unregistered", "intra_unregistered")}
    unclassified: list[dict] = []
    hsn: dict[tuple[str, str, Decimal], dict] = {}
    totals = {"taxable_value": ZERO, **_zero_heads()}

    for doc in sorted(docs, key=lambda d: (d.invoice_date, d.number)):
        sign = _sign(doc)
        # totals and HSN: every item of every document, credit notes negative (G-51)
        for it in doc.items:
            s = Decimal(sign)
            totals["taxable_value"] += s * it.taxable_value
            for h in HEADS:
                totals[h] += s * getattr(it, h)
            key = (it.hsn_sac, it.uqc or "", it.gst_rate)
            row = hsn.setdefault(key, {
                "hsn_sac": it.hsn_sac, "description": it.description, "uqc": it.uqc, "quantity": Decimal("0.000"),
                "total_value": ZERO, "taxable_value": ZERO, "igst": ZERO, "cgst": ZERO, "sgst": ZERO, "cess": ZERO,
                "rate": it.gst_rate})
            row["quantity"] += s * it.quantity
            row["taxable_value"] += s * it.taxable_value
            for h in HEADS:
                row[h] += s * getattr(it, h)
            row["total_value"] += s * (it.taxable_value + it.igst + it.cgst + it.sgst + it.cess)

        # nil / exempt / non-GST items go to table 8 only
        for it in doc.items:
            if it.treatment in NIL_TREATMENTS:
                nil[_nil_bucket(doc, reg_state)][it.treatment] += sign * it.taxable_value
        rest = [it for it in doc.items if it.treatment not in NIL_TREATMENTS]
        if not rest:
            continue

        section = _section_of(doc, reg_state, b2cl_limit)
        if section is None:
            unclassified.append({"voucher_number": doc.number, "voucher_type": doc.voucher_type,
                                 "supply_category": doc.supply_category})
            warnings.append(
                f"{doc.number} dated {doc.invoice_date.strftime('%d-%m-%Y')} (value {format_inr(doc.invoice_value)}) "
                f"cannot be placed in a GSTR-1 table: supply category '{doc.supply_category}' with "
                f"{'a' if doc.party_gstin else 'no'} party GSTIN. Fix the voucher; it is NOT in any table.")
            continue
        if section == "b2b":
            b2b.setdefault(doc.party_gstin, {"party_gstin": doc.party_gstin, "party_name": doc.party_name, "invoices": []})[
                "invoices"].append(_invoice_dict(doc, rest))
        elif section == "sez":
            sez_rows.setdefault(doc.party_gstin, {"party_gstin": doc.party_gstin, "party_name": doc.party_name, "invoices": []})[
                "invoices"].append(_invoice_dict(doc, rest))
        elif section == "exports":
            kind = "with_payment" if doc.supply_category == "export_with_payment" else "without_payment"
            exp_rows[kind].append(_invoice_dict(doc, rest))
        elif section == "b2cl":
            b2cl.setdefault(doc.place_of_supply, []).append(_invoice_dict(doc, rest))
        elif section == "b2cs":
            for it in rest:
                b2cs.setdefault((doc.place_of_supply, it.gst_rate), []).append(it)
        elif section == "cdnr":
            cdnr.setdefault(doc.party_gstin, {"party_gstin": doc.party_gstin, "party_name": doc.party_name, "notes": []})[
                "notes"].append(_note_dict(doc, rest))
        else:
            note = _note_dict(doc, rest)
            note["unregistered_type"] = ("EXPWP" if doc.supply_category == "export_with_payment" else
                                         "EXPWOP" if doc.supply_category == "export_without_payment" else "B2CL")
            cdnur.append(note)

    b2cs_rows = []
    for (pos, rate) in sorted(b2cs):
        b2cs_rows.append({"place_of_supply": pos, **_item_dict(rate, b2cs[(pos, rate)])})

    documents_issued = _documents_issued(numbers)
    tables = {
        "b2b": sorted(b2b.values(), key=lambda r: r["party_gstin"]),
        "b2cl": [{"place_of_supply": pos, "invoices": b2cl[pos]} for pos in sorted(b2cl)],
        "b2cs": b2cs_rows,
        "cdnr": sorted(cdnr.values(), key=lambda r: r["party_gstin"]),
        "cdnur": cdnur,
        "exports": [{"export_type": k, "invoices": v} for k, v in exp_rows.items() if v],
        "sez": sorted(sez_rows.values(), key=lambda r: r["party_gstin"]),
        "nil_exempt_non_gst": nil,
        "hsn_summary": [hsn[k] for k in sorted(hsn)],
        "documents_issued": documents_issued,
        "unclassified": unclassified,
        "totals": totals,
        "portal_tables": dict(PORTAL_TABLES),
        "portal_tables_status": PORTAL_TABLES_STATUS,
    }
    return Gstr1Result(tables=tables, warnings=warnings)


_NATURE = {"sales": "Invoices for outward supply", "credit_note": "Credit Note"}


def _documents_issued(numbers: list[NumberRow]) -> list[dict]:
    """Per nature: first and last number, how many numbers were used, how many were cancelled (reversed original
    or the reversal voucher itself), and the net issued. Voucher numbers are sequential with no gaps (CLAUDE.md 5)."""
    out = []
    for vtype in ("sales", "credit_note"):
        rows = sorted((n for n in numbers if n.voucher_type == vtype), key=lambda n: n.number)
        if not rows:
            continue
        cancelled = sum(1 for n in rows if n.cancelled)
        out.append({
            "nature": _NATURE[vtype], "from_no": rows[0].number, "to_no": rows[-1].number,
            "total": len(rows), "cancelled": cancelled, "net_issued": len(rows) - cancelled,
        })
    return out
