"""TDS / TCS challans, allocation, matching, due dates and interest (Phase 4, package C). Pure Python: no DB, web or AI imports.

Rules (docs/PHASE4_PLAN.md): T-20 challan fields, T-21 item must be in a posted voucher of the same kind, T-22 quarter / year / month,
T-23 allocations <= challan tax, T-24 allocations <= item tax, T-26 interest on late deduction, T-27 interest on late deposit,
T-28 due dates and calendar, T-50 rule status. Rates and day numbers come from the rule rows passed in (never hardcoded here).
Dates: the item's `event_date` (earlier of payment and credit date) decides the due date, the quarter and the year (migration 0013).
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.engine.models import ValidationError
from app.engine.money import MoneyError, format_inr, parse_amount, round_half_up
from app.engine.tds_types import DueDateRule, InterestRule

ZERO = Decimal("0.00")
_STATUS_RANK = {"verified": 0, "secondary_verified": 1, "pending": 2}
_BSR = re.compile(r"^[0-9]{7}$")
_SERIAL = re.compile(r"^[0-9]{1,5}$")


class ChallanRuleError(Exception):
    """One or more rules refused the request; `errors` carry rule_id, plain message and line_no."""

    def __init__(self, errors: list[ValidationError]):
        super().__init__("; ".join(e.message for e in errors))
        self.errors = errors


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# ---- calendar helpers ---------------------------------------------------------------------------------------


def quarter_of(d: date) -> int:
    """Indian financial-year quarter: Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar."""
    return (d.month - 4) % 12 // 3 + 1


def fy_start_year_of(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def quarter_end(fy_start_year: int, quarter: int) -> date:
    """Last day of the quarter of the financial year that starts in April of `fy_start_year`."""
    year = fy_start_year + 1 if quarter == 4 else fy_start_year
    month = {1: 6, 2: 9, 3: 12, 4: 3}[quarter]
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def months_between(start: date, end: date) -> int:
    """Months or part of a month from `start` to `end`: 10-04 -> 10-05 is 1, 10-04 -> 11-05 is 2; no delay (end <= start) is 0."""
    if end <= start:
        return 0
    whole = (end.year - start.year) * 12 + (end.month - start.month)
    return whole + (1 if end.day > start.day else 0)


def _in_force(r, on: date) -> bool:
    return r.effective_from <= on and (r.effective_to is None or r.effective_to >= on)


# ---- rule status (T-50) -------------------------------------------------------------------------------------


def rule_status(used: list[tuple[str, str, str]]) -> dict:
    """`used` = (table, verification_status, source_reference) of every rule row an answer relied on."""
    tables: dict[str, str] = {}
    pending: list[str] = []
    for table, status, source in used:
        current = tables.get(table)
        if current is None or _STATUS_RANK[status] > _STATUS_RANK[current]:
            tables[table] = status
        if status == "pending" and source not in pending:
            pending.append(source)
    worst = max(tables.values(), key=lambda s: _STATUS_RANK[s]) if tables else "verified"
    return {"worst": worst, "tables": tables, "pending_sources": sorted(pending)}


# ---- due dates (T-28) ---------------------------------------------------------------------------------------


def deposit_due_date(event_date: date, kind: str, rules: list[DueDateRule]) -> tuple[date, DueDateRule]:
    """Due date of the deposit of tax deducted / collected on `event_date`: month-specific rule (March) before the general one."""
    hits = [r for r in rules if r.event == "challan" and r.kind == kind and _in_force(r, event_date)]
    pick = [r for r in hits if r.month_of_year == event_date.month] or [r for r in hits if r.month_of_year is None]
    if not pick:
        raise ChallanRuleError([ValidationError("T-02", f"No due-date rule for the deposit of {kind.upper()} deducted on {_fmt(event_date)}.")])
    rule = pick[0]
    year, month = add_months(event_date.year, event_date.month, rule.month_offset or 0)
    return _clamped(year, month, rule.due_day or 1), rule


def return_due_date(fy_start_year: int, quarter: int, kind: str, rules: list[DueDateRule]) -> tuple[date, DueDateRule]:
    qe = quarter_end(fy_start_year, quarter)
    hits = [r for r in rules if r.event == "return" and r.kind == kind and r.quarter == quarter and _in_force(r, qe)]
    if not hits:
        raise ChallanRuleError([ValidationError("T-02", f"No due-date rule for the {kind.upper()} statement of quarter {quarter} ending {_fmt(qe)}.")])
    rule = hits[0]
    year, month = add_months(qe.year, qe.month, rule.month_offset or 0)
    return _clamped(year, month, rule.due_day or 1), rule


def certificate_due_date(
    fy_start_year: int, quarter: int | None, kind: str, rules: list[DueDateRule]
) -> tuple[date, DueDateRule]:
    """Quarterly certificate = statement due date + days; quarter None = the annual salary certificate (day / month offset from year end)."""
    if quarter is None:
        year_end = date(fy_start_year + 1, 3, 31)
        hits = [r for r in rules if r.event == "certificate" and r.kind == kind and r.quarter is None and _in_force(r, year_end)]
        if not hits:
            raise ChallanRuleError([ValidationError("T-02", f"No due-date rule for the annual {kind.upper()} certificate of the year ending {_fmt(year_end)}.")])
        rule = hits[0]
        year, month = add_months(year_end.year, year_end.month, rule.month_offset or 0)
        return _clamped(year, month, rule.due_day or 1), rule
    qe = quarter_end(fy_start_year, quarter)
    hits = [r for r in rules if r.event == "certificate" and r.kind == kind and r.quarter == quarter and _in_force(r, qe)]
    if not hits:
        raise ChallanRuleError([ValidationError("T-02", f"No due-date rule for the {kind.upper()} certificate of quarter {quarter} ending {_fmt(qe)}.")])
    rule = hits[0]
    due_return, _ = return_due_date(fy_start_year, quarter, kind, rules)
    return due_return + timedelta(days=rule.days_after_return or 0), rule


@dataclass(frozen=True)
class CalendarRow:
    event: str  # text for the screen
    kind: str  # tds | tcs
    quarter: int | None
    period: str
    due_date: date
    status: str  # done | due | overdue
    amount_due: Decimal | None
    rules_used: tuple[DueDateRule, ...] = field(default=(), compare=False)


def _status(done: bool, due: date, as_on: date) -> str:
    if done:
        return "done"
    return "due" if as_on <= due else "overdue"


def due_calendar(
    fy_start_year: int,
    kinds: list[str],
    rules: list[DueDateRule],
    tax_by_month: dict[tuple[str, int, int], tuple[Decimal, Decimal]],
    returns_filed: set[tuple[str, int]],
    certificates_issued: set[tuple[str, int | None]],
    as_on: date,
) -> list[CalendarRow]:
    """Challan (per month), statement and certificate dates of one financial year.

    tax_by_month[(kind, year, month)] = (tax deducted, tax deposited); a month with nothing to deposit is `done` with amount 0.
    returns_filed {(kind, quarter)}; certificates_issued {(kind, quarter | None)} (None = salary certificate).
    """
    rows: list[CalendarRow] = []
    for kind in kinds:
        label = kind.upper()
        for i in range(12):
            year, month = add_months(fy_start_year, 4, i)
            due, rule = deposit_due_date(date(year, month, 1), kind, rules)
            deducted, deposited = tax_by_month.get((kind, year, month), (ZERO, ZERO))
            left = max(deducted - deposited, ZERO)
            rows.append(CalendarRow(
                f"Deposit of {label} deducted in {calendar.month_name[month]} {year}", kind, quarter_of(date(year, month, 1)),
                f"{calendar.month_abbr[month]} {year}", due, _status(left == 0, due, as_on), left, (rule,),
            ))
        for q in (1, 2, 3, 4):
            due, rule = return_due_date(fy_start_year, q, kind, rules)
            rows.append(CalendarRow(
                f"{label} statement, quarter {q}", kind, q, f"Q{q} {fy_start_year}-{str(fy_start_year + 1)[2:]}", due,
                _status((kind, q) in returns_filed, due, as_on), None, (rule,),
            ))
            cdue, crule = certificate_due_date(fy_start_year, q, kind, rules)
            rows.append(CalendarRow(
                f"{label} certificates, quarter {q}", kind, q, f"Q{q} {fy_start_year}-{str(fy_start_year + 1)[2:]}", cdue,
                _status((kind, q) in certificates_issued, cdue, as_on), None, (crule,),
            ))
        if kind == "tds":
            sdue, srule = certificate_due_date(fy_start_year, None, kind, rules)
            rows.append(CalendarRow(
                f"{label} salary certificates, year {fy_start_year}-{str(fy_start_year + 1)[2:]}", kind, None,
                f"FY {fy_start_year}-{str(fy_start_year + 1)[2:]}", sdue, _status((kind, None) in certificates_issued, sdue, as_on), None, (srule,),
            ))
    rows.sort(key=lambda r: (r.due_date, r.kind, r.event))
    return rows


# ---- challan fields (T-20) ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChallanIn:
    kind: str
    quarter: int
    bsr_code: str
    deposit_date: date | None
    challan_serial_no: str
    tax_amount: Decimal
    interest_amount: Decimal = ZERO
    fee_amount: Decimal = ZERO
    other_amount: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.tax_amount + self.interest_amount + self.fee_amount + self.other_amount


def parse_challan_amounts(raw: dict[str, object]) -> tuple[dict[str, Decimal], list[ValidationError]]:
    """Each amount as typed -> Decimal with 2 places; more than 2 places or a negative amount is refused, never rounded."""
    labels = {"tax_amount": "Tax", "interest_amount": "Interest", "fee_amount": "Fee", "other_amount": "Other amount"}
    out: dict[str, Decimal] = {}
    errors: list[ValidationError] = []
    for key, label in labels.items():
        value = raw.get(key)
        if value is None or value == "":
            if key == "tax_amount":
                errors.append(ValidationError("T-20", "Tax amount of the challan is required."))
            out[key] = ZERO
            continue
        try:
            out[key] = parse_amount(value)
        except MoneyError as exc:
            errors.append(ValidationError("T-20", f"{label}: {exc}."))
            out[key] = ZERO
    return out, errors


def validate_challan(c: ChallanIn) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if c.kind not in ("tds", "tcs"):
        errors.append(ValidationError("T-20", f"Challan kind '{c.kind}' is not TDS or TCS."))
    if not _BSR.match(c.bsr_code or ""):
        errors.append(ValidationError("T-20", f"BSR code '{c.bsr_code}' must be exactly 7 digits."))
    if not _SERIAL.match(c.challan_serial_no or ""):
        errors.append(ValidationError("T-20", f"Challan serial number '{c.challan_serial_no}' must be 1 to 5 digits."))
    if c.deposit_date is None:
        errors.append(ValidationError("T-20", "Deposit date of the challan is required."))
    if c.quarter not in (1, 2, 3, 4):
        errors.append(ValidationError("T-22", f"Quarter {c.quarter} is not valid; use 1 to 4."))
    if c.total <= 0:
        errors.append(ValidationError("T-20", f"Challan total {format_inr(c.total)} must be above zero."))
    return errors


# ---- allocation (T-21 .. T-24) ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemFacts:
    item_id: str
    kind: str
    deductee_name: str
    section_ref: str
    tds_amount: Decimal
    financial_year_id: str
    event_date: date
    voucher_date: date
    voucher_status: str  # posted | reversed | ...
    voucher_number: str | None = None


@dataclass(frozen=True)
class ChallanFacts:
    challan_id: str | None
    kind: str
    financial_year_id: str
    quarter: int
    deposit_date: date
    tax_amount: Decimal


def _label(item: ItemFacts) -> str:
    return f"{item.deductee_name} {item.section_ref} dated {_fmt(item.event_date)}"


def validate_allocations(
    challan: ChallanFacts,
    allocations: list[tuple[str, Decimal]],
    items: dict[str, ItemFacts],
    allocated_elsewhere: dict[str, Decimal],
) -> list[ValidationError]:
    """`allocated_elsewhere[item_id]` = what OTHER challans already cover of the item. line_no = position in `allocations` (1-based)."""
    errors: list[ValidationError] = []
    seen: set[str] = set()
    total = ZERO
    per_item: dict[str, Decimal] = {}
    for no, (item_id, amount) in enumerate(allocations, start=1):
        item = items.get(item_id)
        if item is None:
            errors.append(ValidationError("T-21", "A deduction in the allocation was not found for this client.", no))
            continue
        if item_id in seen:
            errors.append(ValidationError("T-21", f"{_label(item)} is listed twice; give one amount per deduction.", no))
            continue
        seen.add(item_id)
        if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            errors.append(ValidationError("T-24", f"Allocated amount {amount} for {_label(item)} must be above zero with at most 2 decimals.", no))
            continue
        total += amount
        per_item[item_id] = amount
        if item.voucher_status != "posted":
            errors.append(ValidationError("T-21", f"{_label(item)} is in a voucher that is not posted (or was reversed); only posted vouchers can be paid by a challan.", no))
        if item.kind != challan.kind:
            errors.append(ValidationError("T-21", f"{_label(item)} is {item.kind.upper()} but the challan is {challan.kind.upper()}.", no))
        if item.financial_year_id != challan.financial_year_id:
            errors.append(ValidationError("T-22", f"{_label(item)} belongs to another financial year than the challan.", no))
        elif quarter_of(item.event_date) != challan.quarter:
            errors.append(ValidationError("T-22", f"{_label(item)} falls in quarter {quarter_of(item.event_date)} but the challan is for quarter {challan.quarter}.", no))
        if challan.deposit_date < date(item.event_date.year, item.event_date.month, 1):
            errors.append(ValidationError("T-22", f"Challan deposit date {_fmt(challan.deposit_date)} is before the month of deduction of {_label(item)}.", no))
        room = item.tds_amount - allocated_elsewhere.get(item_id, ZERO)
        if amount > room:
            errors.append(ValidationError(
                "T-24", f"Allocation {format_inr(amount)} to {_label(item)} is more than its balance {format_inr(max(room, ZERO))} (tax {format_inr(item.tds_amount)}).", no))
    if total > challan.tax_amount:
        errors.append(ValidationError(
            "T-23", f"Allocated {format_inr(total)} is more than the tax of the challan {format_inr(challan.tax_amount)} (difference {format_inr(total - challan.tax_amount)})."))
    return errors


@dataclass(frozen=True)
class OpenItem:
    item_id: str
    kind: str
    financial_year_id: str
    event_date: date
    voucher_date: date
    balance: Decimal


@dataclass(frozen=True)
class OpenChallan:
    challan_id: str
    kind: str
    financial_year_id: str
    quarter: int
    deposit_date: date
    challan_serial_no: str
    unallocated: Decimal


def propose_allocations(items: list[OpenItem], challans: list[OpenChallan]) -> list[tuple[str, str, Decimal]]:
    """Proposal only: oldest item first, oldest eligible challan first; same kind, year and quarter; the challan must not precede the
    month of deduction; never more than an item's balance or a challan's unallocated tax."""
    left = {c.challan_id: c.unallocated for c in challans}
    ordered_challans = sorted(challans, key=lambda c: (c.deposit_date, c.challan_serial_no, c.challan_id))
    out: list[tuple[str, str, Decimal]] = []
    for item in sorted(items, key=lambda i: (i.event_date, i.voucher_date, i.item_id)):
        need = item.balance
        for c in ordered_challans:
            if need <= 0:
                break
            if (c.kind, c.financial_year_id, c.quarter) != (item.kind, item.financial_year_id, quarter_of(item.event_date)):
                continue
            if c.deposit_date < date(item.event_date.year, item.event_date.month, 1) or left[c.challan_id] <= 0:
                continue
            take = min(need, left[c.challan_id])
            out.append((item.item_id, c.challan_id, take))
            left[c.challan_id] -= take
            need -= take
    return out


# ---- item deposit status and interest (T-26, T-27) ----------------------------------------------------------


@dataclass(frozen=True)
class ItemStatus:
    allocated: Decimal
    balance: Decimal
    deposited_on: date | None  # last deposit date once fully deposited
    due_date: date
    days_late: int | None  # 0 = on time; None = not deposited and not yet due


def item_status(tds_amount: Decimal, deposits: list[tuple[date, Decimal]], due: date, as_on: date) -> ItemStatus:
    allocated = sum((a for _, a in deposits), ZERO)
    balance = tds_amount - allocated
    if balance <= 0 and deposits:
        last = max(d for d, _ in deposits)
        return ItemStatus(allocated, ZERO, last, due, max((last - due).days, 0))
    late = (as_on - due).days
    return ItemStatus(allocated, balance, None, due, late if late > 0 else None)


def pick_interest_rule(rules: list[InterestRule], key: str, on: date) -> InterestRule:
    hits = [r for r in rules if r.interest_key == key and _in_force(r, on)]
    if not hits:
        label = "late deduction" if key == "late_deduction" else "late deposit"
        raise ChallanRuleError([ValidationError("T-02", f"No interest rule for {label} in force on {_fmt(on)}.")])
    return hits[0]


@dataclass(frozen=True)
class ItemInterest:
    deductible_on: date
    deducted_on: date
    months_late_deduction: int
    interest_late_deduction: Decimal
    deposited_on: date | None
    due_date: date
    months_late_deposit: int
    interest_late_deposit: Decimal
    rules_used: tuple[InterestRule, ...] = field(default=(), compare=False)


def _rupees(value: Decimal) -> Decimal:
    return round_half_up(value, 0).quantize(Decimal("0.01"))


def item_interest(
    tds_amount: Decimal,
    event_date: date,
    voucher_date: date,
    deposits: list[tuple[date, Decimal]],
    due: date,
    as_on: date,
    rules: list[InterestRule],
) -> ItemInterest:
    """Interest shown (never posted) for one deduction, whole rupees (half up).

    Late deduction: tax x monthly rate x months from the date the tax was deductible (event date) to the date it was booked
    (voucher date). Late deposit: for every part deposited after the due date, part x monthly rate x months from the deduction date
    (the later of event date and voucher date) to its deposit date; an undeposited balance runs to `as_on` once `as_on` is past the due date.
    The rule rows in force on the event date / deduction date are used; part of a month counts as a full month when the rule says so.
    """
    ded_rule = pick_interest_rule(rules, "late_deduction", event_date)
    deducted_on = max(event_date, voucher_date)
    dep_rule = pick_interest_rule(rules, "late_deposit", deducted_on)

    def months(start: date, end: date, rule: InterestRule) -> int:
        if rule.part_month_counts_full or end <= start:
            return months_between(start, end)
        return (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)  # whole months only

    m_ded = months(event_date, deducted_on, ded_rule)
    interest_ded = _rupees(tds_amount * ded_rule.monthly_rate / 100 * m_ded)

    raw = Decimal(0)
    worst_months = 0
    for dep_date, amount in deposits:
        if dep_date > due:
            m = months(deducted_on, dep_date, dep_rule)
            raw += amount * dep_rule.monthly_rate / 100 * m
            worst_months = max(worst_months, m)
    remaining = tds_amount - sum((a for _, a in deposits), ZERO)
    if remaining > 0 and as_on > due:
        m = months(deducted_on, as_on, dep_rule)
        raw += remaining * dep_rule.monthly_rate / 100 * m
        worst_months = max(worst_months, m)
    fully = remaining <= 0 and deposits
    return ItemInterest(
        event_date, deducted_on, m_ded, interest_ded, max(d for d, _ in deposits) if fully else None, due, worst_months,
        _rupees(raw), (ded_rule, dep_rule),
    )
