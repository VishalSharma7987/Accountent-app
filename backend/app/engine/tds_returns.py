"""Quarterly TDS / TCS return working and certificate data (Phase 4, package D). Pure Python: no DB, web or AI imports.

Takes plain rows (posted deduction items, challans, allocations) and returns the working the accountant checks and exports.
No tax is computed here: tax amounts, rates and sections are copied from the stored deduction items; this module only
groups, adds up and checks (T-30 .. T-34). The form number is chosen from the form rows by the quarter-END date (T-31).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.money import format_inr
from app.engine.tds_types import FormRule

ZERO = Decimal("0.00")
RETURN_KINDS = ("salary", "non_salary_resident", "tcs")
QUARTER_MONTHS = {1: (4, 6), 2: (7, 9), 3: (10, 12), 4: (1, 3)}


def _d(value: date) -> str:
    return value.strftime("%d-%m-%Y")


# ---- quarters and forms --------------------------------------------------------------------------------------------


def quarter_of(on: date) -> tuple[int, int]:
    """(quarter, financial-year start year) of a date. Apr-Jun = 1 ... Jan-Mar = 4."""
    fy_year = on.year if on.month >= 4 else on.year - 1
    quarter = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[on.month]
    return quarter, fy_year


def quarter_period(fy_start: date, quarter: int) -> tuple[date, date]:
    """First and last day of an Indian financial-year quarter."""
    if quarter not in QUARTER_MONTHS:
        raise ValueError("quarter must be 1 to 4")
    first, last = QUARTER_MONTHS[quarter]
    year = fy_start.year + (1 if quarter == 4 else 0)
    end_day = {3: 31, 6: 30, 9: 30, 12: 31}[last]
    return date(year, first, 1), date(year, last, end_day)


def pick_form(forms: list[FormRule], form_key: str, on: date) -> FormRule | None:
    """The form row of `form_key` in force on `on` (the quarter-end date, T-31); None when no row is in force."""
    for f in forms:
        if f.form_key == form_key and f.effective_from <= on and (f.effective_to is None or on <= f.effective_to):
            return f
    return None


# ---- input rows ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemRow:
    """One deduction item of a POSTED, non-reversed voucher, as stored."""

    item_id: str
    voucher_number: str
    deductee_ledger_id: str
    deductee_name: str
    pan: str | None
    pan_status: str
    nature_key: str
    rate_mode: str  # flat | slab_manual
    kind: str  # tds | tcs
    section_ref: str
    payment_code: str | None
    act: str
    event_date: date
    payment_amount: Decimal
    taxable_base: Decimal
    rate_applied: Decimal
    rate_reason: str
    tds_amount: Decimal
    certificate_no: str | None = None


@dataclass(frozen=True)
class ChallanRow:
    challan_id: str
    bsr_code: str
    deposit_date: date
    serial_no: str
    tax: Decimal
    interest: Decimal
    fee: Decimal
    other: Decimal
    total: Decimal
    status: str
    in_quarter: bool  # the challan's own financial year + quarter + kind match this working


@dataclass(frozen=True)
class AllocRow:
    challan_id: str
    item_id: str
    amount: Decimal


def return_kind_of(item: ItemRow) -> str:
    if item.kind == "tcs":
        return "tcs"
    return "salary" if item.rate_mode == "slab_manual" else "non_salary_resident"


@dataclass
class ReturnWorking:
    deductee_rows: list[dict] = field(default_factory=list)
    challan_rows: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


def _allocated(allocs: list[AllocRow]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for a in allocs:
        out[a.item_id] = out.get(a.item_id, ZERO) + a.amount
    return out


# ---- the working (T-30, T-32) --------------------------------------------------------------------------------------


def build_return_working(
    return_kind: str, tan: str | None, items: list[ItemRow], challans: list[ChallanRow], allocs: list[AllocRow]
) -> ReturnWorking:
    w = ReturnWorking()
    if not tan:
        w.errors.append({"rule_id": "T-30", "blocking": True, "message": (
            "The deductor's TAN is not entered for this client; the statement cannot be prepared without it. "
            "Enter the TAN in the TDS profile.")})
    mine = sorted((i for i in items if return_kind_of(i) == return_kind),
                  key=lambda i: (i.deductee_name, i.event_date, i.voucher_number, i.item_id))
    by_item = _allocated(allocs)
    my_ids = {i.item_id for i in mine}
    for n, it in enumerate(mine, 1):
        deposited = by_item.get(it.item_id, ZERO)
        bad_pan = it.pan_status != "valid" or not it.pan
        w.deductee_rows.append({
            "item_id": it.item_id, "voucher_number": it.voucher_number, "deductee_name": it.deductee_name, "pan": it.pan,
            "pan_status": it.pan_status, "section_ref": it.section_ref, "payment_code": it.payment_code,
            "amount_paid": it.payment_amount, "taxable_base": it.taxable_base, "tax_deducted": it.tds_amount,
            "tax_deposited": deposited, "rate": it.rate_applied, "rate_reason": it.rate_reason, "event_date": it.event_date,
            "certificate_no": it.certificate_no, "error_row": bad_pan,
        })
        if bad_pan:
            w.errors.append({"rule_id": "T-30", "line_no": n, "blocking": False, "message": (
                f"Row {n}: {it.deductee_name} has no valid PAN (status {it.pan_status}); tax was deducted at "
                f"{it.rate_applied:.2f}% ({it.rate_reason}). The statement needs a valid PAN or the "
                f"PAN-not-available entry; correct the deductee master first if the PAN is now known.")})
        if it.tds_amount > deposited:
            w.warnings.append({"rule_id": "T-32", "line_no": n, "message": (
                f"Row {n}: {it.deductee_name}, voucher {it.voucher_number} dated {_d(it.event_date)}: tax deducted "
                f"{format_inr(it.tds_amount)} but only {format_inr(deposited)} is allocated to a challan "
                f"(short by {format_inr(it.tds_amount - deposited)}); interest for late deposit may be due.")})

    allocated_challans = {a.challan_id for a in allocs}
    mine_challans = {a.challan_id for a in allocs if a.item_id in my_ids}
    for c in sorted(challans, key=lambda c: (c.deposit_date, c.bsr_code, c.serial_no)):
        unallocated = c.challan_id not in allocated_challans
        if c.challan_id not in mine_challans and not (unallocated and c.in_quarter):
            continue
        w.challan_rows.append({"bsr_code": c.bsr_code, "deposit_date": c.deposit_date, "serial_no": c.serial_no, "tax": c.tax,
                               "interest": c.interest, "fee": c.fee, "other": c.other, "total": c.total, "status": c.status})
        if unallocated:
            w.warnings.append({"rule_id": "T-32", "message": (
                f"Challan {c.bsr_code} / {_d(c.deposit_date)} / {c.serial_no}: tax {format_inr(c.tax)} is not allocated to "
                "any deduction; allocate it in challan matching or it will not show against a deductee.")})

    rows = w.deductee_rows
    ch = w.challan_rows
    deducted = sum((r["tax_deducted"] for r in rows), ZERO)
    deposited_total = sum((r["tax_deposited"] for r in rows), ZERO)
    w.totals = {
        "row_count": len(rows), "amount_paid": sum((r["amount_paid"] for r in rows), ZERO), "tax_deducted": deducted,
        "tax_deposited": deposited_total, "short_deposit": sum((max(r["tax_deducted"] - r["tax_deposited"], ZERO) for r in rows), ZERO),
        "challan_count": len(ch), "challan_tax": sum((c["tax"] for c in ch), ZERO),
        "challan_interest": sum((c["interest"] for c in ch), ZERO), "challan_fee": sum((c["fee"] for c in ch), ZERO),
        "challan_other": sum((c["other"] for c in ch), ZERO), "challan_total": sum((c["total"] for c in ch), ZERO),
    }
    if return_kind == "salary" and rows:
        w.warnings.append({"rule_id": "T-30", "message": (
            "Salary: tax is the amount typed by the accountant on each voucher (no slab computation here); the statement "
            "is employee-wise for the quarter, so check each row against the payroll working.")})
    return w


# ---- certificate data (T-34) ---------------------------------------------------------------------------------------


def build_certificate(
    form: FormRule, deductor: dict, deductee: dict, items: list[ItemRow], challans: list[ChallanRow],
    allocs: list[AllocRow], period: str,
) -> tuple[dict | None, list[dict]]:
    """Certificate data for one deductee. Refused (None + errors) unless the deductor TAN is known and every item with
    tax is fully allocated to challans (T-34). Items without tax are not part of a certificate."""
    errors: list[dict] = []
    if not deductor.get("tan"):
        errors.append({"rule_id": "T-30", "message": "The deductor's TAN is not entered; a certificate cannot be prepared without it."})
        return None, errors
    taxed = sorted((i for i in items if i.tds_amount > 0), key=lambda i: (i.event_date, i.voucher_number, i.item_id))
    if not taxed:
        errors.append({"rule_id": "T-34", "message": (
            f"No tax was deducted from {deductee['name']} in {period}; there is nothing to certify.")})
        return None, errors
    by_item = _allocated([a for a in allocs if a.item_id in {i.item_id for i in taxed}])
    for it in taxed:
        got = by_item.get(it.item_id, ZERO)
        if got < it.tds_amount:
            errors.append({"rule_id": "T-34", "message": (
                f"Voucher {it.voucher_number} dated {_d(it.event_date)}: tax deducted {format_inr(it.tds_amount)} but only "
                f"{format_inr(got)} is deposited (balance {format_inr(it.tds_amount - got)} is not allocated to a challan). "
                "A certificate is issued only for fully deposited tax.")})
    if errors:
        return None, errors
    rows = [{"voucher_number": i.voucher_number, "event_date": i.event_date, "section_ref": i.section_ref,
             "payment_code": i.payment_code, "amount_paid": i.payment_amount, "rate": i.rate_applied,
             "tax_deducted": i.tds_amount, "tax_deposited": by_item[i.item_id]} for i in taxed]
    per_challan: dict[str, Decimal] = {}
    for a in allocs:
        if a.item_id in by_item:
            per_challan[a.challan_id] = per_challan.get(a.challan_id, ZERO) + a.amount
    ch_rows = [{"bsr_code": c.bsr_code, "deposit_date": c.deposit_date, "serial_no": c.serial_no,
                "tax_deposited": per_challan[c.challan_id]}
               for c in sorted(challans, key=lambda c: (c.deposit_date, c.bsr_code, c.serial_no)) if c.challan_id in per_challan]
    data = {
        "form_no": form.form_no, "form_status": form.verification_status, "period": period, "deductor": deductor,
        "deductee": deductee, "items": rows, "challans": ch_rows,
        "total_amount_paid": sum((r["amount_paid"] for r in rows), ZERO),
        "total_deducted": sum((r["tax_deducted"] for r in rows), ZERO),
        "total_deposited": sum((r["tax_deposited"] for r in rows), ZERO),
    }
    return data, []
