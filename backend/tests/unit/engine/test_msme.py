"""M-01: MSME payment-due flag. Dates and totals are hand-calculated."""

from datetime import date
from decimal import Decimal

from app.engine.models import OpenBill
from app.engine.msme import MsmeRule, PartyFacts, flag_msme_overdue, rules_status

D = Decimal
SRC_61 = "s.43B(h) source"
SRC_25 = "s.37(2)(g) source"


def rule(key, cat, applies, frm, to=None, src=SRC_61, status="pending"):
    return MsmeRule(
        key, cat, applies, 45 if applies else None, 15 if applies else None, frm, to, src, status,
        ("manufacturing", "services") if applies else (),
    )


RULES = [
    rule("a", "micro", True, date(2024, 4, 1), date(2026, 3, 31)),
    rule("a", "small", True, date(2024, 4, 1), date(2026, 3, 31)),
    rule("a", "medium", False, date(2024, 4, 1), date(2026, 3, 31)),
    rule("b", "micro", True, date(2026, 4, 1), None, SRC_25),
    rule("b", "small", True, date(2026, 4, 1), None, SRC_25),
    rule("b", "medium", False, date(2026, 4, 1), None, SRC_25),
]
UDYAM = date(2020, 1, 1)


def bill(party="p", ref="B1", on=date(2026, 4, 10), out="-10000.00", kind="bill", accepted=None):
    return OpenBill(
        party, "Party " + party, ref, kind, on, None, D(out), D(out),
        accepted or on, "bill date" if accepted is None else "goods received date",
    )


def facts(cat="micro", days=None, agreement=False, activity="manufacturing", udyam=UDYAM):
    return PartyFacts("p", cat, agreement, days, activity, udyam)


def flags(b, f, as_on):
    return flag_msme_overdue([b], {"p": f}, RULES, as_on)


def test_M01_agreement_with_30_days_uses_the_agreed_days():
    # bill 10-04-2026 + 30 = 10-05-2026; on 11-05 it is 1 day overdue
    [x] = flags(bill(), facts(days=30, agreement=True), date(2026, 5, 11))
    assert (x.legal_days, x.legal_due_date, x.days_overdue, x.outstanding) == (30, date(2026, 5, 10), 1, D("10000.00"))
    assert x.rule_status == "pending" and x.rule_source == SRC_25
    assert (x.acceptance_date, x.acceptance_basis) == (date(2026, 4, 10), "bill date")


def test_M01_agreed_days_above_45_are_capped_at_45_by_the_rule():
    # the party master refuses 60 (P-11); the rule cap of 45 still holds if such a row existed: 10-04 + 45 = 25-05-2026
    [x] = flags(bill(), facts(days=60, agreement=True), date(2026, 5, 26))
    assert (x.legal_days, x.legal_due_date, x.days_overdue) == (45, date(2026, 5, 25), 1)


def test_M01_no_agreement_means_15_days():
    # 10-04 + 15 = 25-04-2026
    [x] = flags(bill(), facts(agreement=False), date(2026, 4, 28))
    assert (x.legal_days, x.legal_due_date, x.days_overdue) == (15, date(2026, 4, 25), 3)


def test_M01_agreed_days_without_the_agreement_flag_are_ignored():
    [x] = flags(bill(), facts(days=40, agreement=False), date(2026, 4, 28))
    assert x.legal_days == 15


def test_M01_due_day_is_not_overdue_and_the_next_day_is():
    f = facts(days=30, agreement=True)
    assert flags(bill(), f, date(2026, 5, 10)) == []
    [x] = flags(bill(), f, date(2026, 5, 11))
    assert x.days_overdue == 1


def test_M01_small_is_flagged_medium_and_none_are_not():
    assert flags(bill(), facts("small"), date(2026, 6, 1))
    assert flags(bill(), facts("medium"), date(2026, 6, 1)) == []
    assert flags(bill(), facts("none"), date(2026, 6, 1)) == []


def test_M01_trader_is_excluded_manufacturer_and_service_are_flagged():
    assert flags(bill(), facts(activity="trading"), date(2026, 6, 1)) == []
    assert flags(bill(), facts(activity=None), date(2026, 6, 1)) == []
    assert flags(bill(), facts(activity="manufacturing"), date(2026, 6, 1))
    assert flags(bill(), facts(activity="services"), date(2026, 6, 1))


def test_M01_covered_activities_come_from_the_rule_row():
    only_services = [MsmeRule("c", "micro", True, 45, 15, date(2026, 4, 1), None, "s", "pending", ("services",))]
    assert flag_msme_overdue([bill()], {"p": facts(activity="manufacturing")}, only_services, date(2026, 6, 1)) == []
    assert flag_msme_overdue([bill()], {"p": facts(activity="services")}, only_services, date(2026, 6, 1))


def test_M01_supply_before_the_udyam_registration_date_is_not_flagged():
    f = facts(udyam=date(2026, 4, 11))  # the bill dated 10-04-2026 is one day before the registration
    assert flags(bill(), f, date(2026, 6, 1)) == []
    assert flags(bill(on=date(2026, 4, 11)), f, date(2026, 6, 1))  # on the registration date: covered
    assert flags(bill(), facts(udyam=None), date(2026, 6, 1)) == []


def test_M01_goods_received_date_starts_the_clock_and_is_reported():
    # bill 10-04-2026, goods received 20-04-2026, no agreement: 20-04 + 15 = 05-05-2026
    b = bill(accepted=date(2026, 4, 20))
    assert flags(b, facts(), date(2026, 5, 5)) == []
    [x] = flags(b, facts(), date(2026, 5, 6))
    assert (x.acceptance_date, x.acceptance_basis, x.legal_due_date, x.days_overdue) == (
        date(2026, 4, 20), "goods received date", date(2026, 5, 5), 1)
    assert x.bill_date == date(2026, 4, 10)


def test_M01_bill_without_acceptance_date_falls_back_to_the_bill_date():
    b = OpenBill("p", "Party p", "B1", "bill", date(2026, 4, 10), None, D("-100.00"), D("-100.00"))
    [x] = flags(b, facts(), date(2026, 5, 1))
    assert (x.acceptance_date, x.acceptance_basis, x.legal_due_date) == (date(2026, 4, 10), "bill date", date(2026, 4, 25))


def test_M01_party_without_facts_is_not_flagged():
    assert flag_msme_overdue([bill(party="zz")], {"p": facts()}, RULES, date(2026, 6, 1)) == []


def test_M01_rule_row_is_picked_by_the_bill_date():
    [x] = flags(bill(on=date(2025, 6, 1)), facts(), date(2025, 7, 1))
    assert x.rule_source == SRC_61 and x.legal_due_date == date(2025, 6, 16) and x.days_overdue == 15
    [y] = flags(bill(on=date(2026, 4, 1)), facts(), date(2026, 4, 20))  # first day of the 2026 rule
    assert y.rule_source == SRC_25 and y.legal_due_date == date(2026, 4, 16)


def test_M01_rule_by_date_names_the_1961_and_2025_sections():
    rows = [
        MsmeRule("a", "micro", True, 45, 15, date(2024, 4, 1), date(2026, 3, 31), "Income-tax Act 1961 s.43B(h)",
                 "secondary_verified", ("manufacturing",)),
        MsmeRule("b", "micro", True, 45, 15, date(2026, 4, 1), None, "Income-tax Act 2025 s.37(2)(g)",
                 "secondary_verified", ("manufacturing",)),
    ]
    [x] = flag_msme_overdue([bill(on=date(2026, 3, 31))], {"p": facts()}, rows, date(2026, 6, 1))
    [y] = flag_msme_overdue([bill(on=date(2026, 4, 1))], {"p": facts()}, rows, date(2026, 6, 1))
    assert x.rule_source == "Income-tax Act 1961 s.43B(h)" and y.rule_source == "Income-tax Act 2025 s.37(2)(g)"
    assert (x.rule_status, y.rule_status) == ("secondary_verified", "secondary_verified")


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
    b = OpenBill("p", "Party p", "B1", "bill", date(2026, 4, 10), None, D("-10000.00"), D("-4000.00"),
                 date(2026, 4, 10), "bill date")
    [x] = flag_msme_overdue([b], {"p": facts()}, RULES, date(2026, 6, 1))
    assert x.outstanding == D("4000.00")


def test_M01_results_sorted_by_due_date_then_party():
    f = {"p": facts(), "q": PartyFacts("q", "small", False, None, "services", UDYAM)}
    bills = [bill(party="q", ref="Q1", on=date(2026, 4, 12)), bill(party="p", ref="P1", on=date(2026, 4, 10))]
    assert [x.bill_ref for x in flag_msme_overdue(bills, f, RULES, date(2026, 7, 1))] == ["P1", "Q1"]


def test_M01_rules_status_is_three_valued():
    status, source = rules_status(RULES, date(2026, 6, 1))
    assert status == "pending" and source == SRC_25
    secondary = [rule("b", "micro", True, date(2026, 4, 1), None, SRC_25, "secondary_verified"),
                 rule("b", "medium", False, date(2026, 4, 1), None, SRC_25, "verified")]
    assert rules_status(secondary, date(2026, 6, 1)) == ("secondary_verified", SRC_25)
    mixed = secondary + [rule("b", "small", True, date(2026, 4, 1), None, SRC_25, "pending")]
    assert rules_status(mixed, date(2026, 6, 1))[0] == "pending"
    verified = [rule("b", "micro", True, date(2026, 4, 1), None, SRC_25, "verified")]
    assert rules_status(verified, date(2026, 6, 1)) == ("verified", SRC_25)
    assert rules_status([], date(2026, 6, 1))[0] == "pending"
    # rows outside the date do not count: an old pending row does not hold back the 2025 rows
    old_pending = [rule("a", "micro", True, date(2024, 4, 1), date(2026, 3, 31), SRC_61, "pending")] + secondary
    assert rules_status(old_pending, date(2026, 6, 1))[0] == "secondary_verified"
