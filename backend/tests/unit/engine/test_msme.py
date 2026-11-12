"""M-01: MSME payment-due flag. Dates and totals are hand-calculated."""

from datetime import date
from decimal import Decimal

from app.engine.models import OpenBill
from app.engine.msme import MsmeRule, PartyFacts, flag_msme_overdue, rules_status

D = Decimal
SRC_61 = "s.43B(h) source"
SRC_25 = "s.37(2)(g) source"


def rule(key, cat, applies, frm, to=None, src=SRC_61, status="pending"):
    return MsmeRule(key, cat, applies, 45 if applies else None, 15 if applies else None, frm, to, src, status)


RULES = [
    rule("a", "micro", True, date(2024, 4, 1), date(2026, 3, 31)),
    rule("a", "small", True, date(2024, 4, 1), date(2026, 3, 31)),
    rule("a", "medium", False, date(2024, 4, 1), date(2026, 3, 31)),
    rule("b", "micro", True, date(2026, 4, 1), None, SRC_25),
    rule("b", "small", True, date(2026, 4, 1), None, SRC_25),
    rule("b", "medium", False, date(2026, 4, 1), None, SRC_25),
]


def bill(party="p", ref="B1", on=date(2026, 4, 10), out="-10000.00", kind="bill"):
    return OpenBill(party, "Party " + party, ref, kind, on, None, D(out), D(out))


def facts(cat="micro", days=0, agreement=False):
    return PartyFacts("p", cat, days, agreement)


def flags(b, f, as_on):
    return flag_msme_overdue([b], {"p": f}, RULES, as_on)


def test_M01_agreement_with_30_days_uses_the_agreed_days():
    # bill 10-04-2026 + 30 = 10-05-2026; on 11-05 it is 1 day overdue
    [x] = flags(bill(), facts(days=30, agreement=True), date(2026, 5, 11))
    assert (x.legal_days, x.legal_due_date, x.days_overdue, x.outstanding) == (30, date(2026, 5, 10), 1, D("10000.00"))
    assert x.rule_status == "pending" and x.rule_source == SRC_25


def test_M01_agreement_longer_than_45_is_capped_at_45():
    # 10-04 + 45 = 25-05-2026
    [x] = flags(bill(), facts(days=60, agreement=True), date(2026, 5, 26))
    assert (x.legal_days, x.legal_due_date, x.days_overdue) == (45, date(2026, 5, 25), 1)


def test_M01_no_agreement_means_15_days_whatever_the_credit_days():
    # 10-04 + 15 = 25-04-2026
    [x] = flags(bill(), facts(days=60, agreement=False), date(2026, 4, 28))
    assert (x.legal_days, x.legal_due_date, x.days_overdue) == (15, date(2026, 4, 25), 3)


def test_M01_agreement_but_zero_credit_days_means_15():
    [x] = flags(bill(), facts(days=0, agreement=True), date(2026, 4, 26))
    assert x.legal_days == 15


def test_M01_due_day_itself_is_not_yet_overdue():
    assert flags(bill(), facts(days=30, agreement=True), date(2026, 5, 10)) == []


def test_M01_small_is_flagged_medium_and_none_are_not():
    assert flags(bill(), facts("small"), date(2026, 6, 1))
    assert flags(bill(), facts("medium"), date(2026, 6, 1)) == []
    assert flags(bill(), facts("none"), date(2026, 6, 1)) == []


def test_M01_party_without_facts_is_not_flagged():
    assert flag_msme_overdue([bill(party="zz")], {"p": facts()}, RULES, date(2026, 6, 1)) == []


def test_M01_rule_row_is_picked_by_the_bill_date():
    [x] = flags(bill(on=date(2025, 6, 1)), facts(), date(2025, 7, 1))
    assert x.rule_source == SRC_61 and x.legal_due_date == date(2025, 6, 16) and x.days_overdue == 15
    [y] = flags(bill(on=date(2026, 4, 1)), facts(), date(2026, 4, 20))  # first day of the 2026 rule
    assert y.rule_source == SRC_25 and y.legal_due_date == date(2026, 4, 16)


def test_M01_bill_before_any_rule_is_not_flagged():
    assert flags(bill(on=date(2023, 12, 1)), facts(), date(2024, 6, 1)) == []


def test_M01_only_unpaid_supplier_bills_are_flagged():
    f = {"p": facts()}
    assert flag_msme_overdue([bill(out="0.00")], f, RULES, date(2026, 6, 1)) == []
    assert flag_msme_overdue([bill(out="5000.00")], f, RULES, date(2026, 6, 1)) == []  # debit = customer side
    assert flag_msme_overdue([bill(kind="advance")], f, RULES, date(2026, 6, 1)) == []
    assert flag_msme_overdue([bill(kind="on_account", ref=None)], f, RULES, date(2026, 6, 1)) == []
    assert flag_msme_overdue([bill(on=None)], f, RULES, date(2026, 6, 1)) == []


def test_M01_partly_paid_bill_shows_the_outstanding_part():
    b = OpenBill("p", "Party p", "B1", "bill", date(2026, 4, 10), None, D("-10000.00"), D("-4000.00"))
    [x] = flag_msme_overdue([b], {"p": facts()}, RULES, date(2026, 6, 1))
    assert x.outstanding == D("4000.00")


def test_M01_results_sorted_by_due_date_then_party():
    f = {"p": facts(), "q": PartyFacts("q", "small", 0, False)}
    bills = [bill(party="q", ref="Q1", on=date(2026, 4, 12)), bill(party="p", ref="P1", on=date(2026, 4, 10))]
    assert [x.bill_ref for x in flag_msme_overdue(bills, f, RULES, date(2026, 7, 1))] == ["P1", "Q1"]


def test_M01_rules_status_pending_until_every_effective_row_is_verified():
    status, source = rules_status(RULES, date(2026, 6, 1))
    assert status == "pending" and source == SRC_25
    verified = [rule("b", "micro", True, date(2026, 4, 1), None, SRC_25, "verified")]
    assert rules_status(verified, date(2026, 6, 1)) == ("verified", SRC_25)
    assert rules_status([], date(2026, 6, 1))[0] == "pending"
