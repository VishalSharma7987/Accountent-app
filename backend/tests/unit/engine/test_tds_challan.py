"""Phase 4 package C engine: challan fields, allocation, matching proposal, due dates, interest, calendar (T-20 .. T-28, T-50).

Rule objects are typed literally (no database). Every expected value is hand-calculated and written as a literal.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.tds_challan import (
    CalendarRow,
    ChallanFacts,
    ChallanIn,
    ChallanRuleError,
    ItemFacts,
    OpenChallan,
    OpenItem,
    certificate_due_date,
    deposit_due_date,
    due_calendar,
    item_interest,
    item_status,
    months_between,
    parse_challan_amounts,
    propose_allocations,
    quarter_of,
    return_due_date,
    rule_status,
    validate_allocations,
    validate_challan,
)
from app.engine.tds_types import DueDateRule, InterestRule

D = Decimal
OLD_END = date(2026, 3, 31)
NEW_START = date(2026, 4, 1)
START = date(2025, 4, 1)


def due(key, event, kind, quarter, month, day, offset, days, frm, to, status="pending"):
    return DueDateRule(key, event, kind, quarter, month, day, offset, days, frm, to, status)


def tds_rules(kind="tds"):
    out = []
    for frm, to in ((START, OLD_END), (NEW_START, None)):
        out.append(due(f"{kind}_challan_regular", "challan", kind, None, None, 7, 1, None, frm, to))
        out.append(due(f"{kind}_challan_march", "challan", kind, None, 3, 30, 1, None, frm, to))
        for q, off in ((1, 1), (2, 1), (3, 1), (4, 2)):
            out.append(due(f"{kind}_return_q{q}", "return", kind, q, None, 31, off, None, frm, to))
            out.append(due(f"{kind}_certificate_q{q}", "certificate", kind, q, None, None, None, 15, frm, to))
        if kind == "tds":
            out.append(due("tds_certificate_salary", "certificate", kind, None, None, 15, 3, None, frm, to))
    return out


RATES = [
    InterestRule("late_deduction", D("1"), True, "201(1A)", START, OLD_END, "pending"),
    InterestRule("late_deduction", D("1"), True, "tbc", NEW_START, None, "pending"),
    InterestRule("late_deposit", D("1.5"), True, "201(1A)", START, OLD_END, "pending"),
    InterestRule("late_deposit", D("1.5"), True, "tbc", NEW_START, None, "pending"),
]


# ---- calendar helpers ----------------------------------------------------------------------------------------


def test_T28_quarter_of_indian_financial_year():
    assert [quarter_of(date(2026, 4, 1)), quarter_of(date(2026, 6, 30)), quarter_of(date(2026, 7, 1)),
            quarter_of(date(2026, 12, 31)), quarter_of(date(2027, 1, 1)), quarter_of(date(2027, 3, 31))] == [1, 1, 2, 3, 4, 4]


@pytest.mark.parametrize(
    "start,end,months",
    [
        (date(2026, 4, 10), date(2026, 5, 10), 1),
        (date(2026, 4, 10), date(2026, 5, 11), 2),
        (date(2026, 4, 10), date(2026, 4, 10), 0),
        (date(2026, 4, 10), date(2026, 4, 5), 0),
        (date(2026, 1, 31), date(2026, 2, 28), 1),
        (date(2026, 1, 15), date(2026, 3, 2), 2),
        (date(2026, 11, 20), date(2027, 1, 21), 3),
    ],
)
def test_T26_months_or_part_of_a_month(start, end, months):
    assert months_between(start, end) == months


# ---- due dates -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,expected",
    [
        (date(2026, 5, 10), date(2026, 6, 7)),
        (date(2026, 12, 15), date(2027, 1, 7)),  # year rolls over
        (date(2026, 3, 20), date(2026, 4, 30)),  # March: 30 April (1961-Act row)
        (date(2027, 3, 5), date(2027, 4, 30)),  # March: 30 April (2025-Act row)
        (date(2025, 6, 1), date(2025, 7, 7)),
    ],
)
def test_T28_deposit_due_date_by_pattern(event, expected):
    assert deposit_due_date(event, "tds", tds_rules())[0] == expected


def test_T02_no_due_date_rule_before_the_seeded_period_is_refused():
    with pytest.raises(ChallanRuleError) as e:
        deposit_due_date(date(2025, 3, 31), "tds", tds_rules())
    assert e.value.errors[0].rule_id == "T-02"
    assert e.value.errors[0].message == "No due-date rule for the deposit of TDS deducted on 31-03-2025."


def test_T28_return_and_certificate_due_dates_of_fy_2026_27():
    r = tds_rules()
    got = [return_due_date(2026, q, "tds", r)[0] for q in (1, 2, 3, 4)]
    assert got == [date(2026, 7, 31), date(2026, 10, 31), date(2027, 1, 31), date(2027, 5, 31)]
    certs = [certificate_due_date(2026, q, "tds", r)[0] for q in (1, 2, 3, 4)]
    assert certs == [date(2026, 8, 15), date(2026, 11, 15), date(2027, 2, 15), date(2027, 6, 15)]
    assert certificate_due_date(2026, None, "tds", r)[0] == date(2027, 6, 15)


def test_T28_return_due_date_of_fy_2025_26_uses_the_1961_rows():
    r = tds_rules()
    assert return_due_date(2025, 4, "tds", r)[0] == date(2026, 5, 31)
    assert return_due_date(2025, 1, "tds", r)[0] == date(2025, 7, 31)


def test_T28_calendar_marks_done_due_and_overdue():
    rows = due_calendar(
        2026, ["tds"], tds_rules(),
        tax_by_month={("tds", 2026, 4): (D("1000.00"), D("1000.00")), ("tds", 2026, 5): (D("800.00"), D("300.00")),
                      ("tds", 2026, 6): (D("200.00"), D("0.00"))},
        returns_filed={("tds", 1)}, certificates_issued=set(), as_on=date(2026, 6, 20),
    )
    by_period = {(r.event.split(" deducted")[0], r.period): r for r in rows if r.event.startswith("Deposit")}
    apr = next(r for r in rows if r.period == "Apr 2026" and r.event.startswith("Deposit"))
    may = next(r for r in rows if r.period == "May 2026" and r.event.startswith("Deposit"))
    jun = next(r for r in rows if r.period == "Jun 2026" and r.event.startswith("Deposit"))
    assert (apr.due_date, apr.status, apr.amount_due) == (date(2026, 5, 7), "done", D("0.00"))
    assert (may.due_date, may.status, may.amount_due) == (date(2026, 6, 7), "overdue", D("500.00"))
    assert (jun.due_date, jun.status, jun.amount_due) == (date(2026, 7, 7), "due", D("200.00"))
    q1 = next(r for r in rows if r.event == "TDS statement, quarter 1")
    q2 = next(r for r in rows if r.event == "TDS statement, quarter 2")
    assert (q1.status, q2.status, q1.due_date) == ("done", "due", date(2026, 7, 31))
    assert len(rows) == 12 + 4 + 4 + 1 and by_period
    assert all(isinstance(r, CalendarRow) for r in rows)
    assert [r.due_date for r in rows] == sorted(r.due_date for r in rows)


# ---- T-20 challan fields -------------------------------------------------------------------------------------


def challan(**kw):
    base = {"kind": "tds", "quarter": 1, "bsr_code": "0510308", "deposit_date": date(2026, 6, 5), "challan_serial_no": "00123", "tax_amount": D("1000.00")}
    base.update(kw)
    return ChallanIn(**base)


def test_T20_valid_challan_total_adds_up():
    c = challan(interest_amount=D("45.00"), fee_amount=D("200.00"), other_amount=D("5.00"))
    assert validate_challan(c) == []
    assert c.total == D("1250.00")


@pytest.mark.parametrize("bsr", ["051030", "05103088", "05103a8", ""])
def test_T20_bsr_code_must_be_seven_digits(bsr):
    errors = validate_challan(challan(bsr_code=bsr))
    assert [e.rule_id for e in errors] == ["T-20"]
    assert f"BSR code '{bsr}' must be exactly 7 digits." == errors[0].message


@pytest.mark.parametrize("serial", ["", "123456", "12a"])
def test_T20_serial_must_be_one_to_five_digits(serial):
    assert [e.rule_id for e in validate_challan(challan(challan_serial_no=serial))] == ["T-20"]


def test_T20_total_must_be_above_zero_and_quarter_in_range():
    errors = validate_challan(challan(tax_amount=D("0.00"), quarter=5))
    assert [(e.rule_id, e.message) for e in errors] == [
        ("T-22", "Quarter 5 is not valid; use 1 to 4."), ("T-20", "Challan total 0.00 must be above zero.")]


def test_T20_amounts_with_more_than_two_decimals_or_negative_are_refused_not_rounded():
    amounts, errors = parse_challan_amounts({"tax_amount": "10.005", "interest_amount": "-1", "fee_amount": None})
    assert [e.rule_id for e in errors] == ["T-20", "T-20"]
    assert errors[0].message == "Tax: amount 10.005 has more than 2 decimal places."
    assert errors[1].message == "Interest: amount -1 is negative."
    assert amounts["fee_amount"] == D("0.00")
    ok, errs = parse_challan_amounts({"tax_amount": "1,000"})
    assert errs and "Tax" in errs[0].message and ok["tax_amount"] == D("0.00")


# ---- T-21 .. T-24 allocation ---------------------------------------------------------------------------------


def item(item_id="i1", amount="1000.00", event=date(2026, 5, 10), kind="tds", fy="fy1", status="posted", voucher=None):
    return ItemFacts(item_id, kind, "Raj Contractors", "194C", D(amount), fy, event, voucher or event, status, "PAY/2026-27/0001")


CH = ChallanFacts("c1", "tds", "fy1", 1, date(2026, 6, 5), D("1000.00"))


def test_T21_T24_a_clean_allocation_passes_and_partial_is_allowed():
    assert validate_allocations(CH, [("i1", D("400.00"))], {"i1": item()}, {}) == []
    assert validate_allocations(CH, [("i1", D("600.00"))], {"i1": item()}, {"i1": D("400.00")}) == []


def test_T21_item_in_unposted_or_reversed_voucher_is_refused():
    errors = validate_allocations(CH, [("i1", D("100.00"))], {"i1": item(status="reversed")}, {})
    assert [(e.rule_id, e.line_no) for e in errors] == [("T-21", 1)]
    assert errors[0].message.startswith("Raj Contractors 194C dated 10-05-2026 is in a voucher that is not posted")


def test_T21_unknown_item_duplicate_item_and_kind_mismatch():
    errors = validate_allocations(CH, [("zz", D("1.00")), ("i1", D("1.00")), ("i1", D("1.00")), ("i2", D("1.00"))],
                                  {"i1": item(), "i2": item("i2", kind="tcs")}, {})
    assert [(e.rule_id, e.line_no) for e in errors] == [("T-21", 1), ("T-21", 3), ("T-21", 4)]
    assert errors[2].message == "Raj Contractors 194C dated 10-05-2026 is TCS but the challan is TDS."


def test_T22_quarter_year_and_month_of_deposit():
    q2 = validate_allocations(CH, [("i1", D("10.00"))], {"i1": item(event=date(2026, 7, 10))}, {})
    assert [(e.rule_id, e.message) for e in q2] == [
        ("T-22", "Raj Contractors 194C dated 10-07-2026 falls in quarter 2 but the challan is for quarter 1."),
        ("T-22", "Challan deposit date 05-06-2026 is before the month of deduction of Raj Contractors 194C dated 10-07-2026."),
    ]
    fy = validate_allocations(CH, [("i1", D("10.00"))], {"i1": item(fy="fy0")}, {})
    assert [e.rule_id for e in fy] == ["T-22"]
    early = ChallanFacts("c1", "tds", "fy1", 1, date(2026, 4, 28), D("1000.00"))
    errs = validate_allocations(early, [("i1", D("10.00"))], {"i1": item(event=date(2026, 5, 10))}, {})
    assert [e.message for e in errs] == ["Challan deposit date 28-04-2026 is before the month of deduction of Raj Contractors 194C dated 10-05-2026."]
    same_month = ChallanFacts("c1", "tds", "fy1", 1, date(2026, 5, 2), D("1000.00"))
    assert validate_allocations(same_month, [("i1", D("10.00"))], {"i1": item(event=date(2026, 5, 10))}, {}) == []


def test_T23_allocations_cannot_exceed_challan_tax():
    items = {"i1": item(amount="800.00"), "i2": item("i2", amount="800.00")}
    errors = validate_allocations(CH, [("i1", D("700.00")), ("i2", D("400.00"))], items, {})
    assert [(e.rule_id, e.line_no, e.message) for e in errors] == [(
        "T-23", None, "Allocated 1,100.00 is more than the tax of the challan 1,000.00 (difference 100.00).")]


def test_T24_item_cannot_be_over_allocated_across_challans():
    errors = validate_allocations(CH, [("i1", D("700.00"))], {"i1": item()}, {"i1": D("400.00")})
    assert [(e.rule_id, e.line_no) for e in errors] == [("T-24", 1)]
    assert errors[0].message == "Allocation 700.00 to Raj Contractors 194C dated 10-05-2026 is more than its balance 600.00 (tax 1,000.00)."


def test_T24_zero_negative_or_three_decimal_allocation_refused():
    errors = validate_allocations(CH, [("i1", D("0.00"))], {"i1": item()}, {})
    assert [e.rule_id for e in errors] == ["T-24"]
    assert [e.rule_id for e in validate_allocations(CH, [("i1", D("1.005"))], {"i1": item()}, {})] == ["T-24"]


# ---- matching proposal ---------------------------------------------------------------------------------------


def test_T21_auto_proposal_oldest_item_first_same_quarter_never_over_allocates():
    items = [
        OpenItem("B", "tds", "fy1", date(2026, 4, 20), date(2026, 4, 20), D("500.00")),
        OpenItem("A", "tds", "fy1", date(2026, 4, 10), date(2026, 4, 10), D("1000.00")),
        OpenItem("C", "tds", "fy1", date(2026, 7, 10), date(2026, 7, 10), D("300.00")),  # quarter 2: no quarter-2 challan
        OpenItem("D", "tcs", "fy1", date(2026, 4, 5), date(2026, 4, 5), D("50.00")),  # other kind
    ]
    challans = [
        OpenChallan("Y", "tds", "fy1", 1, date(2026, 5, 7), "00002", D("1000.00")),
        OpenChallan("X", "tds", "fy1", 1, date(2026, 5, 7), "00001", D("1200.00")),
    ]
    # A (oldest) takes X first; X has 200 left for B; B's remaining 300 comes from Y; C (quarter 2) and D (TCS) get nothing
    assert propose_allocations(items, challans) == [("A", "X", D("1000.00")), ("B", "X", D("200.00")), ("B", "Y", D("300.00"))]


def test_T21_proposal_skips_a_challan_that_precedes_the_deduction_month():
    items = [OpenItem("A", "tds", "fy1", date(2026, 5, 10), date(2026, 5, 10), D("100.00"))]
    challans = [OpenChallan("early", "tds", "fy1", 1, date(2026, 4, 30), "1", D("100.00"))]
    assert propose_allocations(items, challans) == []


# ---- item status and interest --------------------------------------------------------------------------------


def test_T27_item_status_deposited_on_time_late_and_open():
    on_time = item_status(D("1000.00"), [(date(2026, 6, 5), D("1000.00"))], date(2026, 6, 7), date(2026, 8, 1))
    assert (on_time.allocated, on_time.balance, on_time.deposited_on, on_time.days_late) == (D("1000.00"), D("0.00"), date(2026, 6, 5), 0)
    late = item_status(D("1000.00"), [(date(2026, 6, 10), D("400.00")), (date(2026, 6, 17), D("600.00"))], date(2026, 6, 7), date(2026, 8, 1))
    assert (late.deposited_on, late.days_late, late.balance) == (date(2026, 6, 17), 10, D("0.00"))
    part = item_status(D("1000.00"), [(date(2026, 6, 5), D("400.00"))], date(2026, 6, 7), date(2026, 6, 20))
    assert (part.deposited_on, part.balance, part.days_late) == (None, D("600.00"), 13)
    not_due = item_status(D("1000.00"), [], date(2026, 6, 7), date(2026, 6, 1))
    assert (not_due.balance, not_due.days_late) == (D("1000.00"), None)


def test_T27_late_deposit_interest_three_months_at_1_5_percent():
    # 1,000.00 deducted 10-05-2026, due 07-06-2026, deposited 20-07-2026: 10-05 -> 20-07 = 3 months (part counts full); 1,000 x 1.5% x 3 = 45
    r = item_interest(D("1000.00"), date(2026, 5, 10), date(2026, 5, 10), [(date(2026, 7, 20), D("1000.00"))], date(2026, 6, 7), date(2026, 9, 1), RATES)
    assert (r.months_late_deposit, r.interest_late_deposit, r.deposited_on) == (3, D("45.00"), date(2026, 7, 20))
    assert (r.months_late_deduction, r.interest_late_deduction) == (0, D("0.00"))


def test_T27_deposit_on_or_before_the_due_date_carries_no_interest():
    r = item_interest(D("1000.00"), date(2026, 5, 10), date(2026, 5, 10), [(date(2026, 6, 7), D("1000.00"))], date(2026, 6, 7), date(2026, 9, 1), RATES)
    assert (r.months_late_deposit, r.interest_late_deposit) == (0, D("0.00"))


def test_T27_interest_rounds_to_the_whole_rupee_half_up():
    # 333.00 x 1.5% x 1 month = 4.995 -> 5.00
    r = item_interest(D("333.00"), date(2026, 5, 10), date(2026, 5, 10), [(date(2026, 6, 10), D("333.00"))], date(2026, 6, 7), date(2026, 9, 1), RATES)
    assert (r.months_late_deposit, r.interest_late_deposit) == (1, D("5.00"))


def test_T27_part_deposited_late_and_balance_running_to_as_on():
    # 400.00 deposited 20-07-2026: 3 months -> 18.00; balance 600.00 open on 31-08-2026: 10-05 -> 31-08 = 4 months -> 36.00; total 54.00
    r = item_interest(D("1000.00"), date(2026, 5, 10), date(2026, 5, 10), [(date(2026, 7, 20), D("400.00"))], date(2026, 6, 7), date(2026, 8, 31), RATES)
    assert (r.interest_late_deposit, r.deposited_on, r.months_late_deposit) == (D("54.00"), None, 4)


def test_T27_undeposited_item_not_yet_due_has_no_interest():
    r = item_interest(D("1000.00"), date(2026, 5, 10), date(2026, 5, 10), [], date(2026, 6, 7), date(2026, 6, 7), RATES)
    assert r.interest_late_deposit == D("0.00")


def test_T26_late_deduction_interest_two_months_at_1_percent():
    # deductible 10-04-2026, booked 05-06-2026: 2 months (part of the second counts) -> 5,000 x 1% x 2 = 100
    r = item_interest(D("5000.00"), date(2026, 4, 10), date(2026, 6, 5), [], date(2026, 5, 7), date(2026, 6, 5), RATES)
    assert (r.months_late_deduction, r.interest_late_deduction, r.deducted_on) == (2, D("100.00"), date(2026, 6, 5))
    # deposit interest then runs from the booking date: 05-06 -> 20-06 = 1 month; 5,000 x 1.5% = 75
    r2 = item_interest(D("5000.00"), date(2026, 4, 10), date(2026, 6, 5), [(date(2026, 6, 20), D("5000.00"))], date(2026, 5, 7), date(2026, 9, 1), RATES)
    assert (r2.months_late_deposit, r2.interest_late_deposit) == (1, D("75.00"))


def test_T26_booking_before_the_event_date_is_not_late():
    r = item_interest(D("5000.00"), date(2026, 4, 10), date(2026, 4, 1), [], date(2026, 5, 7), date(2026, 4, 20), RATES)
    assert (r.months_late_deduction, r.interest_late_deduction) == (0, D("0.00"))


def test_T26_rule_in_force_on_the_event_date_is_used_and_missing_rule_refused():
    rates = [InterestRule("late_deduction", D("2"), True, "x", date(2026, 4, 1), None, "pending"),
             InterestRule("late_deduction", D("1"), True, "y", date(2025, 4, 1), date(2026, 3, 31), "pending"),
             InterestRule("late_deposit", D("1.5"), True, "z", date(2025, 4, 1), None, "pending")]
    old = item_interest(D("1000.00"), date(2026, 3, 10), date(2026, 4, 10), [], date(2026, 4, 7), date(2026, 4, 10), rates)
    assert old.interest_late_deduction == D("10.00")  # 1 month at 1% (rule of the event date), not 2%
    with pytest.raises(ChallanRuleError) as e:
        item_interest(D("1000.00"), date(2025, 1, 10), date(2025, 1, 10), [], date(2025, 2, 7), date(2025, 1, 10), rates)
    assert e.value.errors[0].message == "No interest rule for late deduction in force on 10-01-2025."


def test_T26_part_month_rule_off_counts_whole_months_only():
    rates = [InterestRule("late_deduction", D("1"), False, "x", START, None, "pending"),
             InterestRule("late_deposit", D("1.5"), False, "z", START, None, "pending")]
    r = item_interest(D("1000.00"), date(2026, 4, 10), date(2026, 6, 20), [], date(2026, 5, 7), date(2026, 6, 20), rates)
    assert (r.months_late_deduction, r.interest_late_deduction) == (2, D("20.00"))
    r = item_interest(D("1000.00"), date(2026, 4, 10), date(2026, 6, 5), [], date(2026, 5, 7), date(2026, 6, 5), rates)
    assert r.months_late_deduction == 1


# ---- T-50 ----------------------------------------------------------------------------------------------------


def test_T50_rule_status_lists_worst_status_per_table_and_pending_sources():
    s = rule_status([("due_date", "secondary_verified", "taxheal"), ("due_date", "pending", "Rule 30 recalled"),
                     ("interest", "pending", "cleartax"), ("interest", "pending", "cleartax")])
    assert s == {"worst": "pending", "tables": {"due_date": "pending", "interest": "pending"},
                 "pending_sources": ["Rule 30 recalled", "cleartax"]}
    assert rule_status([("due_date", "secondary_verified", "x")])["worst"] == "secondary_verified"
