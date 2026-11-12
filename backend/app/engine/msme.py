"""M-01: MSME payment-due flag (a report, not a block). Pure Python, no database.

Law is data: the days, effective dates, source and verification status come from `msme_payment_rules` rows (see
app/rules/msme.py); nothing is hardcoded here. Design assumptions (docs/PHASE2_PLAN.md): the bill date is the date
of acceptance; only unpaid supplier bills (credit side) of micro/small suppliers are flagged; a bill whose date has
no rule row is not flagged.

Legal days: with a written agreement and credit days above zero -> min(credit days, days_with_agreement of the
rule); otherwise -> days_no_agreement of the rule. Due date = bill date + legal days; a bill is overdue only AFTER
the due date.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.engine.models import OpenBill

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class MsmeRule:
    rule_key: str
    category: str  # micro | small | medium
    applies: bool
    days_with_agreement: int | None
    days_no_agreement: int | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str  # verified | pending


@dataclass(frozen=True)
class PartyFacts:
    ledger_id: object
    msme_category: str  # none | micro | small | medium
    credit_days: int
    msme_written_agreement: bool


@dataclass(frozen=True)
class MsmeFlag:
    party_ledger_id: object
    party_name: str
    bill_ref: str | None
    bill_date: date
    legal_days: int
    legal_due_date: date
    days_overdue: int
    outstanding: Decimal  # positive: what is still owed
    rule_status: str  # verified | pending
    rule_source: str


@dataclass(frozen=True)
class MsmeReport:
    as_on: date
    rule_status: str  # "pending" until every rule row in force on as_on is verified
    rule_source: str
    items: tuple[MsmeFlag, ...]
    total_outstanding: Decimal


def _in_force(rule: MsmeRule, on: date) -> bool:
    return rule.effective_from <= on and (rule.effective_to is None or on <= rule.effective_to)


def pick_rule(rules: Sequence[MsmeRule], category: str, on: date) -> MsmeRule | None:
    """The rule row of the category in force on `on` (the latest start wins if rows overlap), or None."""
    found = [r for r in rules if r.category == category and _in_force(r, on)]
    return max(found, key=lambda r: r.effective_from) if found else None


def rules_status(rules: Sequence[MsmeRule], as_on: date) -> tuple[str, str]:
    """('verified' | 'pending', source text) for the rows in force on as_on. No rows in force = pending."""
    active = [r for r in rules if _in_force(r, as_on)]
    status = "verified" if active and all(r.verification_status == "verified" for r in active) else "pending"
    sources: list[str] = []
    for r in active:
        if r.source_reference not in sources:
            sources.append(r.source_reference)
    return status, "; ".join(sources)


def flag_msme_overdue(
    open_bills: Sequence[OpenBill],
    parties: Mapping[object, PartyFacts],
    rules: Sequence[MsmeRule],
    as_on: date,
) -> list[MsmeFlag]:
    """Open supplier bills of micro/small suppliers whose legal due date is before `as_on`."""
    flags: list[MsmeFlag] = []
    for bill in open_bills:
        facts = parties.get(bill.party_ledger_id)
        if facts is None or facts.msme_category not in ("micro", "small"):
            continue
        if bill.kind != "bill" or bill.bill_date is None or bill.outstanding >= 0:
            continue
        rule = pick_rule(rules, facts.msme_category, bill.bill_date)
        if rule is None or not rule.applies or rule.days_no_agreement is None or rule.days_with_agreement is None:
            continue
        if facts.msme_written_agreement and facts.credit_days > 0:
            legal_days = min(facts.credit_days, rule.days_with_agreement)
        else:
            legal_days = rule.days_no_agreement
        due = bill.bill_date + timedelta(days=legal_days)
        if as_on <= due:
            continue
        flags.append(MsmeFlag(
            bill.party_ledger_id, bill.party_name, bill.bill_ref, bill.bill_date, legal_days, due,
            (as_on - due).days, (-bill.outstanding).quantize(Decimal("0.01")),
            rule.verification_status, rule.source_reference,
        ))
    return sorted(flags, key=lambda f: (f.legal_due_date, f.party_name, f.bill_ref or ""))
