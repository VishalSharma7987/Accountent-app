"""GSTR-3B working (Phase 3, package E). Pure Python: no DB, web or AI imports.

Figures: 3.1 outward and RCM (from the same posted documents as GSTR-1), 3.2 inter-state supplies to unregistered /
composition / UIN parties, 4 ITC (from the ITC register, by status), 5 inward exempt / nil / non-GST, 6.1 liability.
Differences with the books are shown by the tie-out, never forced (G-52). Table numbering and the utilisation order of
Section 49 are NOT hardcoded as law: utilisation is reported as "not_computed" until the CA confirms the order.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.gstr1 import (
    EXPORT_CATEGORIES,
    HEADS,
    NIL_TREATMENTS,
    SEZ_CATEGORIES,
    ZERO,
    DocRow,
    ItemRow,
)

TAX_HEADS = ("igst", "cgst", "sgst", "cess")
REDUCING_DOC_TYPES = ("debit_note", "credit_note")  # a note on a purchase takes credit away


@dataclass(frozen=True)
class ItcRow:
    """One ITC register entry. `claim_date` is the date used to place it in a return period."""

    entry_id: str
    source: str  # regular | rcm
    doc_type: str  # invoice | debit_note | credit_note
    status: str  # eligible | blocked | pending | reversed
    claim_date: date
    supply_category: str | None
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal


@dataclass(frozen=True)
class ReversalRow:
    """A posted ITC-reversal journal (180-day or blocked-late): amounts reversed, on its voucher date."""

    reversal_id: str
    on_date: date
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal


@dataclass
class Gstr3bResult:
    tables: dict
    warnings: list[str] = field(default_factory=list)


def _sign(doc: DocRow) -> Decimal:
    return Decimal(-1 if doc.voucher_type in ("credit_note", "debit_note") else 1)


def _bucket() -> dict[str, Decimal]:
    return {"taxable_value": ZERO, **{h: ZERO for h in HEADS}}


def _add(b: dict[str, Decimal], it: ItemRow, sign: Decimal) -> None:
    b["taxable_value"] += sign * it.taxable_value
    for h in HEADS:
        b[h] += sign * getattr(it, h)


def _heads() -> dict[str, Decimal]:
    return {h: ZERO for h in TAX_HEADS}


def _sum_heads(*parts: dict[str, Decimal]) -> dict[str, Decimal]:
    return {h: sum((p[h] for p in parts), ZERO) for h in TAX_HEADS}


def build_gstr3b(
    out_docs: list[DocRow],
    in_docs: list[DocRow],
    itc_rows: list[ItcRow],
    reversals: list[ReversalRow],
    reg_state: str,
    period_start: date,
    period_end_: date,
) -> Gstr3bResult:
    warnings: list[str] = []
    a, b, c, d, e = _bucket(), _bucket(), _bucket(), _bucket(), _bucket()
    unreg: dict[str, dict] = {}
    comp: dict[str, dict] = {}
    uin: dict[str, dict] = {}

    for doc in out_docs:
        sign = _sign(doc)
        zero_rated_doc = doc.supply_category in EXPORT_CATEGORIES + SEZ_CATEGORIES
        for it in doc.items:
            if it.treatment == "exempt" or it.treatment == "nil_rated":
                _add(c, it, sign)
            elif it.treatment == "non_gst":
                _add(e, it, sign)
            elif zero_rated_doc or it.treatment == "zero_rated":
                _add(b, it, sign)
            else:
                _add(a, it, sign)
                if doc.place_of_supply != reg_state and doc.supply_category != "deemed_export":
                    gtype = doc.party_gst_type
                    target = (comp if gtype == "composition" else uin if gtype == "uin_holder"
                              else unreg if not doc.party_gstin else None)
                    if target is not None:
                        row = target.setdefault(doc.place_of_supply, {"place_of_supply": doc.place_of_supply,
                                                                       "taxable_value": ZERO, "igst": ZERO})
                        row["taxable_value"] += sign * it.taxable_value
                        row["igst"] += sign * it.igst
        if doc.supply_category == "deemed_export":
            warnings.append(
                f"{doc.number}: a deemed export is reported in 3.1(a) here; confirm with the CA whether it belongs in 3.1(b).")

    # inward: RCM (3.1(d)) and exempt / nil / non-GST inward supplies (table 5)
    t5 = {k: {"taxable_value": ZERO} for k in
          ("inter_composition_exempt", "intra_composition_exempt", "inter_nil", "intra_nil", "non_gst")}
    for doc in in_docs:
        sign = _sign(doc)
        inter = doc.place_of_supply != reg_state
        for it in doc.items:
            if it.rcm:
                _add(d, it, sign)
            if it.treatment == "non_gst":
                t5["non_gst"]["taxable_value"] += sign * it.taxable_value
            elif doc.supply_category == "composition_supplier":
                t5["inter_composition_exempt" if inter else "intra_composition_exempt"]["taxable_value"] += sign * it.taxable_value
            elif it.treatment in NIL_TREATMENTS:
                t5["inter_nil" if inter else "intra_nil"]["taxable_value"] += sign * it.taxable_value

    # table 4: ITC
    in_period = [r for r in itc_rows if period_start <= r.claim_date <= period_end_]
    a4 = {k: _heads() for k in ("import_goods", "import_services", "inward_rcm", "isd", "all_other_itc")}
    ineligible = _heads()
    for r in in_period:
        s = Decimal(-1 if r.doc_type in REDUCING_DOC_TYPES else 1)
        if r.status == "eligible":
            key = ("inward_rcm" if r.source == "rcm" else
                   "import_services" if r.supply_category == "import_of_service" else "all_other_itc")
            for h in TAX_HEADS:
                a4[key][h] += s * getattr(r, h)
        elif r.status in ("blocked", "pending"):
            for h in TAX_HEADS:
                ineligible[h] += s * getattr(r, h)
    b_others = _heads()
    for rv in reversals:
        if period_start <= rv.on_date <= period_end_:
            for h in TAX_HEADS:
                b_others[h] += getattr(rv, h)
    a_total = _sum_heads(*a4.values())
    b_rule = _heads()
    b_total = _sum_heads(b_rule, b_others)
    c_net = {h: a_total[h] - b_total[h] for h in TAX_HEADS}

    # 6.1: liability per head; no automatic offset (Section 49 order is for the CA to confirm)
    payable = {h: a[h] + b[h] for h in HEADS}
    rcm_payable = {h: d[h] for h in HEADS}
    t6 = {
        "tax_payable": {h: payable[h] for h in TAX_HEADS},
        "rcm_payable_in_cash": {h: rcm_payable[h] for h in TAX_HEADS},
        "itc_available": c_net,
        "utilisation": "not_computed",
        "itc_utilised": None,
        "cash": None,
        "notes": [("ITC utilisation order (Section 49) is not computed: confirm the order with the CA. "
                  "Shown: liability and ITC available per head.")],
    }
    outward_total = {k: a[k] + b[k] + c[k] + e[k] for k in a}
    tables = {
        "t3_1": {"a_outward_taxable": a, "b_zero_rated": b, "c_nil_exempt": c, "d_inward_rcm": d, "e_non_gst": e},
        "t3_2": {k: [v[p] for p in sorted(v)] for k, v in (("unregistered", unreg), ("composition", comp), ("uin", uin))},
        "t4": {
            "a": {**a4, "total": a_total},
            "b": {"rule_38_42_43_and_17_5": b_rule, "others": b_others, "total": b_total},
            "c_net": c_net,
            "d_ineligible": ineligible,
        },
        "t5": t5,
        "t6_1": t6,
        "outward_total": outward_total,
    }
    return Gstr3bResult(tables=tables, warnings=warnings)
