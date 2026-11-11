"""Builders for engine tests: a real chart (seeded group tree + a few ledgers), drafts and period rules."""

import calendar
from datetime import date

from chart_fixture import GROUP_TREE

from app.engine.models import Group, Ledger, PeriodInfo, VoucherDraft, VoucherLine
from app.engine.validation import validate_voucher

CLIENT = "client-1"
OTHER_CLIENT = "client-2"

GROUPS = {
    code: Group(code, name, nature, report, parent)
    for code, (name, parent, nature, report) in GROUP_TREE.items()
}
# a client's own sub-group under Bank Accounts: still counts as a bank ledger through the parent chain
GROUPS["petty_bank"] = Group("petty_bank", "Petty Bank", "asset", "balance_sheet", "bank_accounts")


def _ledger(ledger_id, name, group, *, active=True, client=CLIENT):
    return Ledger(ledger_id, name, group, active, client)


LEDGER_LIST = [
    _ledger("cash", "Cash", "cash_in_hand"),
    _ledger("hdfc", "HDFC Bank", "bank_accounts"),
    _ledger("petty", "Petty Bank A/c", "petty_bank"),
    _ledger("rahul", "Rahul Enterprises", "sundry_debtors"),
    _ledger("sharma", "Sharma Suppliers", "sundry_creditors"),
    _ledger("sales", "Sales", "sales_accounts"),
    _ledger("purchases", "Purchases", "purchase_accounts"),
    _ledger("rent", "Rent", "indirect_expenses"),
    _ledger("freight", "Freight Inward", "direct_expenses"),
    _ledger("plant", "Plant & Machinery", "fixed_assets"),
    _ledger("capital", "Owner Capital A/c", "capital_account"),
    _ledger("outstanding_rent", "Outstanding Rent", "current_liabilities"),
    _ledger("retired", "Old Expense", "indirect_expenses", active=False),
    _ledger("foreign_cash", "Cash", "cash_in_hand", client=OTHER_CLIENT),
]
LEDGERS = {x.id: x for x in LEDGER_LIST}

FY_RANGES = [(date(2026, 4, 1), date(2027, 3, 31))]


def month_period(on: date, status: str = "open") -> PeriodInfo:
    return PeriodInfo(date(on.year, on.month, 1), date(on.year, on.month, calendar.monthrange(on.year, on.month)[1]), status)


def all_open(on: date):
    return month_period(on) if FY_RANGES[0][0] <= on <= FY_RANGES[0][1] else None


def april_locked(on: date):
    if date(2026, 4, 1) <= on <= date(2026, 4, 30):
        return month_period(on, "locked")
    return all_open(on)


def no_periods(on: date):
    return None


def line(ledger, dr=None, cr=None):
    return VoucherLine(ledger, dr, cr)


def draft(vtype, lines, *, on=date(2026, 4, 5), narration="Test narration", reference_no=None, party=None, client=CLIENT):
    return VoucherDraft(client, vtype, on, narration, reference_no, party, tuple(lines))


def run(d, *, ledgers=LEDGERS, fy=FY_RANGES, periods=all_open, is_reversal=False):
    return validate_voucher(d, ledgers, GROUPS, fy, periods, is_reversal=is_reversal)


def ids(errors):
    """[(rule_id, line_no)] in the order returned."""
    return [(e.rule_id, e.line_no) for e in errors]


def only(errors, rule_id):
    return [e for e in errors if e.rule_id == rule_id]
