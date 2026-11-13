"""Input tax credit (ITC) rules, Phase 3 package C: eligibility, claim deadline, 180-day share, reversal arithmetic.

Pure Python: no DB, web or AI imports. Rule rows come in as the frozen dataclasses of `gst_types.py`; every amount is a
Decimal and every rounding goes through `round_half_up`. Law is data: the Section 17(5) categories, the Section 16(4)
deadline and the 180 days are rule rows chosen by date; nothing in this file knows a category or a number of days.

Rule ids: G-30 blocked credit, G-31 evidence, G-32 2B / IMS, G-33 claim deadline, G-34 180 days, G-35 re-claim,
G-36 no double reversal, G-37 status changes.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.engine.gst_types import BlockedRule, ItcCondition
from app.engine.money import round_half_up

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Amounts:
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal

    @staticmethod
    def zero() -> "Amounts":
        return Amounts(ZERO, ZERO, ZERO, ZERO)

    def is_zero(self) -> bool:
        return not (self.igst or self.cgst or self.sgst or self.cess)

    def total(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess


def _each(a: Amounts, b: Amounts, fn) -> Amounts:
    return Amounts(*(round_half_up(fn(x, y)) for x, y in ((a.igst, b.igst), (a.cgst, b.cgst), (a.sgst, b.sgst), (a.cess, b.cess))))


def _in_force(rule, on: date) -> bool:
    return rule.effective_from <= on and (rule.effective_to is None or on <= rule.effective_to)


# ---- G-30 .. G-32 classification ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItcFacts:
    source: str  # regular | rcm
    doc_type: str  # invoice | debit_note | credit_note
    invoice_date: date  # the rule date: blocked categories are picked by it
    itc_category_key: str | None
    itc_exception_claimed: bool
    itc_exception_note: str | None
    tax_document_held: bool
    goods_services_received: bool
    received_date: date | None
    supplier_tax_paid: str  # unknown | in_2b | not_in_2b | manual_confirmed
    ims_status: str | None = None  # None | pending | rejected (set by the 2B reconciliation)


@dataclass(frozen=True)
class Classification:
    status: str  # eligible | blocked | pending
    pending_reason: str | None
    blocked_category_key: str | None
    reason: str  # plain language, stored on the status event


def classify(facts: ItcFacts, blocked_rules: list[BlockedRule]) -> Classification:
    """Status of one ITC entry (never 'reversed': that comes only from a reversal)."""
    key = facts.itc_category_key
    if key is not None:
        rule = next((r for r in blocked_rules if r.category_key == key and _in_force(r, facts.invoice_date)), None)
        if rule is None:
            return Classification(
                "pending", "evidence_missing", None,
                f"The Section 17(5) category '{key}' is not a rule in force on {facts.invoice_date:%d-%m-%Y}; "
                "choose a valid category or clear the tag.",
            )
        note = (facts.itc_exception_note or "").strip()
        if rule.has_exception and facts.itc_exception_claimed and note:
            pass  # exception claimed with a written note: judged on the ordinary evidence below
        else:
            return Classification("blocked", None, key, f"Blocked credit, {rule.clause_ref}: the tax is part of the cost.")
    if not facts.tax_document_held:
        return Classification("pending", "evidence_missing", None, "The tax invoice / debit note is not recorded as held (Section 16(2)(a)).")
    if not facts.goods_services_received or facts.received_date is None:
        return Classification("pending", "evidence_missing", None, "Receipt of the goods or services (with the date) is not recorded (Section 16(2)(b)).")
    if facts.source != "rcm":
        if facts.supplier_tax_paid == "in_2b" and facts.ims_status in ("pending", "rejected"):
            return Classification("pending", f"ims_{facts.ims_status}", None, f"The supplier's document is {facts.ims_status} in IMS.")
        if facts.supplier_tax_paid not in ("in_2b", "manual_confirmed"):
            return Classification("pending", "not_in_2b", None, "The supplier's document is not found in GSTR-2B (Section 16(2)(c)).")
    return Classification("eligible", None, None, "All recorded conditions are met.")


# ---- G-33 claim deadline -----------------------------------------------------------------------------------


def claim_deadline(invoice_date: date, condition: ItcCondition | None) -> date | None:
    """The date after which the credit cannot be claimed: month/day of the rule in the year in which the financial year
    of the invoice ends. None when no rule row is in force on the invoice date (never a guess)."""
    if condition is None or not _in_force(condition, invoice_date) or condition.deadline_month is None or condition.deadline_day is None:
        return None
    fy_end_year = invoice_date.year + 1 if invoice_date.month >= 4 else invoice_date.year
    return date(fy_end_year, condition.deadline_month, condition.deadline_day)


def deadline_passed(deadline: date | None, on: date) -> bool:
    return deadline is not None and on > deadline


# ---- G-34 .. G-36 180-day rule -------------------------------------------------------------------------------


def days_since(invoice_date: date, as_on: date) -> int:
    return (as_on - invoice_date).days


def payment_due_date(invoice_date: date, days: int) -> date:
    return invoice_date + timedelta(days=days)


@dataclass(frozen=True)
class UnpaidShare:
    fraction: Decimal  # outstanding / original, 4 decimals, for display
    amounts: Amounts


def unpaid_share(tax: Amounts, original: Decimal, outstanding: Decimal) -> UnpaidShare:
    """The unpaid part of the tax: tax x outstanding / original, half-up per head. Outstanding above the original is capped
    (the whole tax); original must be positive."""
    if original <= 0:
        raise ValueError("the original bill amount must be above zero")
    out = min(max(outstanding, ZERO), original)
    exact = out / original

    def part(x: Decimal) -> Decimal:
        return round_half_up(x * out / original)

    return UnpaidShare(round_half_up(exact, 4), Amounts(part(tax.igst), part(tax.cgst), part(tax.sgst), part(tax.cess)))


def reversal_amounts(share: Amounts, net_reversed: Amounts) -> Amounts:
    """G-36: what still has to be reversed = unpaid share - already reversed (net of re-claims), never negative."""
    return _each(share, net_reversed, lambda s, r: max(s - r, ZERO))


def reclaim_amounts(reversed_: Amounts, reclaimed: Amounts, unpaid_now: Amounts) -> Amounts:
    """G-35: the share paid since = net reversed - unpaid share today, never negative, never above what is left of the reversal."""
    left = _each(reversed_, reclaimed, lambda r, c: r - c)
    return _each(left, unpaid_now, lambda a, u: min(max(a - u, ZERO), a))


# ---- G-37 status changes ---------------------------------------------------------------------------------


def transition_error(from_status: str, to_status: str, *, via: str) -> str | None:
    """None when the change is allowed, else a plain-language reason. via: evidence | confirm | tag | reversal | reclaim."""
    if from_status == to_status and from_status != "reversed":
        return None
    if from_status == "reversed":
        if via == "reclaim" and to_status in ("eligible", "pending"):
            return None
        return "A reversed credit cannot be changed; it comes back only through the re-claim of a paid share (G-35, G-36)."
    if via == "reversal":
        return None if to_status == "reversed" else "A reversal marks the entry reversed."
    if via == "tag":
        return None if to_status in ("blocked", "reversed") else "Tagging a blocked category blocks the entry."
    if from_status == "blocked":
        return "A blocked credit is not made eligible by evidence or confirmation; correct the category tag on the invoice instead."
    if via in ("evidence", "confirm") and to_status in ("eligible", "pending"):
        return None
    return f"A {from_status} credit cannot move to {to_status} this way."
