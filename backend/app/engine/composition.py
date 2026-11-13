"""Composition scheme quarterly working (CMP-08 figures) (Phase 3, package E, G-54). Pure Python.

Tax = turnover x rate (rule table), split into equal CGST and SGST with the same half-up rule as the invoice tax
(`round(turnover x rate / 200, 2)` each). A composition taxpayer charges no tax on invoices and claims no ITC: any
document with tax on it is listed. The turnover limit is a flag, not a block. The rate and limit come from the rule row
passed in (verification status is shown); nothing is hardcoded here.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.gstr1 import ZERO, DocRow, round_half_up

# turnover_basis values of gst_composition_rules: which supplies count
NON_TAXABLE = ("exempt", "nil_rated", "non_gst")


@dataclass(frozen=True)
class CompositionRule:
    category: str
    rate: Decimal
    turnover_limit: Decimal
    turnover_basis: str  # taxable_turnover | turnover_in_state
    verification_status: str


@dataclass
class CompositionResult:
    working: dict
    warnings: list[str] = field(default_factory=list)


def _turnover(docs: list[DocRow], basis: str, start: date, end: date) -> Decimal:
    total = ZERO
    for doc in docs:
        if not start <= doc.invoice_date <= end:
            continue
        sign = Decimal(-1 if doc.voucher_type == "credit_note" else 1)
        for it in doc.items:
            if basis == "taxable_turnover" and it.treatment in NON_TAXABLE:
                continue
            total += sign * it.taxable_value
    return total


def build_composition(
    rule: CompositionRule, docs: list[DocRow], quarter_start: date, quarter_end: date, fy_start: date
) -> CompositionResult:
    """`docs`: posted sales and credit notes of the registration from the financial-year start to the quarter end."""
    warnings: list[str] = []
    quarter = _turnover(docs, rule.turnover_basis, quarter_start, quarter_end)
    ytd = _turnover(docs, rule.turnover_basis, fy_start, quarter_end)
    half = round_half_up(quarter * rule.rate / Decimal(200), 2)
    crossed = ytd > rule.turnover_limit
    if rule.verification_status == "pending":
        warnings.append("The composition rate and turnover limit are pending verification (see rule status); confirm with the CA.")
    if crossed:
        warnings.append("Turnover for the year is above the composition limit: the registration may have to move to the regular scheme.")
    with_tax = []
    for doc in docs:
        if not quarter_start <= doc.invoice_date <= quarter_end:
            continue
        tax = sum((it.cgst + it.sgst + it.igst + it.cess for it in doc.items), ZERO)
        if tax > 0:
            with_tax.append({"voucher_number": doc.number, "invoice_date": doc.invoice_date, "tax": tax})
            warnings.append(f"{doc.number}: a composition taxpayer must not charge tax on an invoice, but this one carries tax.")
    working = {
        "category": rule.category, "rate": rule.rate, "rate_status": rule.verification_status,
        "quarter_turnover": quarter, "turnover_basis": rule.turnover_basis,
        "tax": {"cgst": half, "sgst": half, "total": half + half},
        "ytd_turnover": ytd, "limit": rule.turnover_limit, "limit_crossed": crossed,
        "invoices_with_tax": with_tax,
    }
    return CompositionResult(working=working, warnings=warnings)
