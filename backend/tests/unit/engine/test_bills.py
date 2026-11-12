"""Bill-wise allocation rules B-01 .. B-05, due dates, open bills, mirrored allocations, the opening-bills check.

All expected numbers are hand-calculated and typed literally. Signed amounts: debit +, credit -.
"""

from datetime import date
from decimal import Decimal

from engine_helpers import ids

from app.engine.bills import (
    AllocationRow,
    BillState,
    OpeningBillIn,
    OpeningBillRow,
    PartyInfo,
    default_due_date,
    mirror_allocations,
    open_bills,
    opening_bills_check,
    ref_key,
    resolve_allocations,
    resolve_opening_bills,
    validate_allocations,
    validate_opening_bills,
)
from app.engine.models import Allocation, OpeningBalance, VoucherLine

D = Decimal
DAY = date(2026, 4, 5)
PARTIES = {
    "rahul": PartyInfo("Rahul Enterprises", "debtor", True, 30),
    "sharma": PartyInfo("Sharma Suppliers", "creditor", True, 45),
    "old": PartyInfo("Old Debtor", "debtor", False, 0),
}


def A(kind, amount, ref=None, due=None):
    return Allocation(kind, amount, ref, due)


def L(ledger, dr=None, cr=None, *allocs):
    return VoucherLine(ledger, dr, cr, tuple(allocs))


def inv1(outstanding="100000", origin="Dr"):
    """State of one open bill INV1 of Rahul."""
    return {ref_key("rahul", "INV1"): BillState(D(outstanding), origin)}


def check(lines, state=None, *, used=(), reversal=False, on=DAY):
    return validate_allocations(lines, PARTIES, on, state or {}, used, is_reversal=reversal)


# ==================================================================================================== B-01


def test_B01_full_allocation_of_a_sales_line_is_valid():
    lines = [L("rahul", "100000", None, A("new_ref", "100000", "INV1")), L("sales", None, "100000")]
    assert check(lines) == []


def test_B01_party_line_without_any_allocation_rejected():
    errors = check([L("rahul", "100000"), L("sales", None, "100000")])
    assert ids(errors) == [("B-01", 1)]
    assert "1,00,000.00" in errors[0].message


def test_B01_partial_allocation_rejected_with_amounts():
    lines = [L("rahul", "100000", None, A("new_ref", "60000", "INV1")), L("sales", None, "100000")]
    errors = check(lines)
    assert ids(errors) == [("B-01", 1)]
    assert "60,000.00" in errors[0].message and "1,00,000.00" in errors[0].message and "40,000.00" in errors[0].message


def test_B01_over_allocation_rejected():
    lines = [L("rahul", "100000", None, A("new_ref", "100000.01", "INV1")), L("sales", None, "100000")]
    assert ids(check(lines)) == [("B-01", 1)]


def test_B01_allocation_on_a_non_party_line_rejected():
    lines = [L("rahul", "100000", None, A("new_ref", "100000", "INV1")),
             L("sales", None, "100000", A("on_account", "100000"))]
    assert ids(check(lines)) == [("B-01", 2)]


def test_B01_party_that_is_not_bill_wise_takes_no_allocation():
    lines = [L("old", "500", None, A("on_account", "500")), L("sales", None, "500")]
    assert ids(check(lines)) == [("B-01", 1)]


def test_B01_party_that_is_not_bill_wise_without_allocation_is_fine():
    assert check([L("old", "500"), L("sales", None, "500")]) == []


def test_B01_line_without_parties_row_is_phase_1_behaviour():
    assert check([L("rent", "500"), L("cash", None, "500")]) == []


def test_B01_split_over_several_allocations_adds_up():
    lines = [L("rahul", "100000", None, A("new_ref", "60000", "INV1"), A("new_ref", "40000", "INV2")),
             L("sales", None, "100000")]
    assert check(lines) == []


# ==================================================================================================== B-02


def test_B02_new_ref_on_the_wrong_side_of_a_debtor_rejected():
    lines = [L("hdfc", "5000"), L("rahul", None, "5000", A("new_ref", "5000", "R1"))]
    assert ids(check(lines)) == [("B-02", 2)]


def test_B02_advance_on_the_natural_side_rejected():
    lines = [L("rahul", "5000", None, A("advance", "5000", "ADV1")), L("sales", None, "5000")]
    assert ids(check(lines)) == [("B-02", 1)]


def test_B02_advance_receipt_from_debtor_is_valid():
    lines = [L("hdfc", "5000"), L("rahul", None, "5000", A("advance", "5000", "ADV1"))]
    assert check(lines) == []


def test_B02_creditor_new_ref_on_credit_side_valid_and_on_debit_side_rejected():
    ok = [L("purchases", "5000"), L("sharma", None, "5000", A("new_ref", "5000", "PB1"))]
    bad = [L("sharma", "5000", None, A("new_ref", "5000", "PB1")), L("hdfc", None, "5000")]
    assert check(ok) == []
    assert ids(check(bad)) == [("B-02", 1)]


def test_B02_against_ref_on_the_same_side_as_the_bill_rejected():
    lines = [L("rahul", "5000", None, A("against_ref", "5000", "INV1")), L("sales", None, "5000")]
    assert ids(check(lines, inv1())) == [("B-02", 1)]


def test_B02_on_account_is_valid_on_either_side():
    assert check([L("rahul", "5000", None, A("on_account", "5000")), L("sales", None, "5000")]) == []
    assert check([L("hdfc", "5000"), L("rahul", None, "5000", A("on_account", "5000"))]) == []


def test_B02_unknown_kind_rejected():
    lines = [L("rahul", "5000", None, A("settle", "5000", "INV1")), L("sales", None, "5000")]
    assert ids(check(lines)) == [("B-02", 1)]


# ==================================================================================================== B-03


def test_B03_new_bill_reference_is_required():
    lines = [L("rahul", "5000", None, A("new_ref", "5000", "  ")), L("sales", None, "5000")]
    assert ids(check(lines)) == [("B-03", 1)]


def test_B03_reference_already_used_by_the_party_rejected_ignoring_case_and_spaces():
    lines = [L("rahul", "5000", None, A("new_ref", "5000", " inv1 ")), L("sales", None, "5000")]
    errors = check(lines, inv1("0"))  # even a fully settled bill keeps its reference
    assert ids(errors) == [("B-03", 1)]
    assert "inv1" in errors[0].message


def test_B03_reference_used_in_another_year_rejected():
    lines = [L("rahul", "5000", None, A("new_ref", "5000", "OLD9")), L("sales", None, "5000")]
    assert ids(check(lines, used={ref_key("rahul", "old9")})) == [("B-03", 1)]


def test_B03_same_reference_twice_in_one_voucher_rejected():
    lines = [L("rahul", "10000", None, A("new_ref", "6000", "INV7"), A("new_ref", "4000", "inv7")),
             L("sales", None, "10000")]
    assert ids(check(lines)) == [("B-03", 1)]


def test_B03_same_reference_for_two_different_parties_is_fine():
    lines = [L("rahul", "5000", None, A("new_ref", "5000", "X1")), L("sharma", None, "5000", A("new_ref", "5000", "X1"))]
    assert check(lines) == []


def test_B03_on_account_must_not_carry_a_reference():
    lines = [L("rahul", "5000", None, A("on_account", "5000", "INV1")), L("sales", None, "5000")]
    assert ids(check(lines)) == [("B-03", 1)]


# ==================================================================================================== B-04


def test_B04_against_unknown_bill_rejected():
    lines = [L("hdfc", "5000"), L("rahul", None, "5000", A("against_ref", "5000", "NOPE"))]
    errors = check(lines, inv1())
    assert ids(errors) == [("B-04", 2)]
    assert "NOPE" in errors[0].message


def test_B04_partial_then_full_settlement_valid():
    part = [L("hdfc", "30000"), L("rahul", None, "30000", A("against_ref", "30000", "INV1"))]
    full = [L("hdfc", "100000"), L("rahul", None, "100000", A("against_ref", "100000", "INV1"))]
    assert check(part, inv1()) == []
    assert check(full, inv1()) == []


def test_B04_cannot_settle_more_than_outstanding():
    lines = [L("hdfc", "100000"), L("rahul", None, "100000", A("against_ref", "100000", "INV1"))]
    errors = check(lines, inv1("70000"))
    assert ids(errors) == [("B-04", 2)]
    assert "70,000.00" in errors[0].message and "30,000.00" in errors[0].message


def test_B04_two_allocations_in_one_voucher_count_together():
    lines = [L("hdfc", "80000"),
             L("rahul", None, "80000", A("against_ref", "50000", "INV1"), A("against_ref", "30000", "inv1"))]
    assert ids(check(lines, inv1("70000"))) == [("B-04", 2)]


def test_B04_credit_note_against_a_bill_valid():
    lines = [L("sales", "2000"), L("rahul", None, "2000", A("against_ref", "2000", "INV1"))]
    assert check(lines, inv1()) == []


def test_B04_creditor_payment_against_bill():
    state = {ref_key("sharma", "PB1"): BillState(D("-50000"), "Cr")}
    ok = [L("sharma", "15000", None, A("against_ref", "15000", "PB1")), L("hdfc", None, "15000")]
    over = [L("sharma", "50001", None, A("against_ref", "50001", "PB1")), L("hdfc", None, "50001")]
    assert check(ok, state) == []
    assert ids(check(over, state)) == [("B-04", 1)]


def test_B04_advance_then_adjusted_by_a_sales_invoice_in_one_line():
    state = {ref_key("rahul", "ADV1"): BillState(D("-10000"), "Cr")}
    lines = [L("rahul", "25000", None, A("against_ref", "10000", "ADV1"), A("new_ref", "15000", "INV9")),
             L("sales", None, "25000")]
    assert check(lines, state) == []


def test_B04_advance_cannot_be_adjusted_for_more_than_it_holds():
    state = {ref_key("rahul", "ADV1"): BillState(D("-10000"), "Cr")}
    lines = [L("rahul", "12000", None, A("against_ref", "12000", "ADV1")), L("sales", None, "12000")]
    assert ids(check(lines, state)) == [("B-04", 1)]


def test_B04_a_bill_created_in_the_same_voucher_cannot_be_settled_by_it():
    lines = [L("rahul", "5000", None, A("new_ref", "2000", "N1"), A("against_ref", "3000", "N1")),
             L("sales", None, "5000")]
    assert ("B-04", 1) in ids(check(lines))


def test_B04_settlement_dated_before_the_bill_rejected():
    state = {ref_key("rahul", "INV1"): BillState(D("100000"), "Dr", date(2026, 4, 10))}
    lines = [L("hdfc", "5000"), L("rahul", None, "5000", A("against_ref", "5000", "INV1"))]
    errors = check(lines, state)  # voucher dated 05-04-2026, bill dated 10-04-2026
    assert ids(errors) == [("B-04", 2)]
    assert "10-04-2026" in errors[0].message


# ==================================================================================================== B-05


def test_B05_amount_zero_negative_or_three_decimals_rejected():
    for amount in ("0", "-5", "10.005"):
        lines = [L("rahul", "10", None, A("on_account", amount)), L("sales", None, "10")]
        assert ids(check(lines)) == [("B-05", 1)], amount


def test_B05_missing_amount_rejected():
    lines = [L("rahul", "10", None, A("on_account", None)), L("sales", None, "10")]
    assert ids(check(lines)) == [("B-05", 1)]


def test_B05_due_date_before_bill_date_rejected():
    lines = [L("rahul", "10", None, A("new_ref", "10", "INV1", date(2026, 4, 4))), L("sales", None, "10")]
    assert ids(check(lines)) == [("B-05", 1)]


def test_B05_due_date_on_the_bill_date_is_fine_and_only_new_ref_has_one():
    ok = [L("rahul", "10", None, A("new_ref", "10", "INV1", DAY)), L("sales", None, "10")]
    bad = [L("hdfc", "10"), L("rahul", None, "10", A("advance", "10", "A1", date(2026, 5, 1)))]
    assert check(ok) == []
    assert ids(check(bad)) == [("B-05", 2)]


# ============================================================================================= reversals


def test_reversal_of_a_sales_voucher_with_nothing_applied_is_valid():
    lines = [L("sales", "100000"), L("rahul", None, "100000", A("against_ref", "100000", "INV1"))]
    assert check(lines, inv1(), reversal=True) == []


def test_B04_reversal_of_a_sales_voucher_with_a_receipt_applied_is_refused():
    # INV1 was 1,00,000.00 Dr, 30,000.00 received: 70,000.00 outstanding; reversing the whole sale overshoots
    lines = [L("sales", "100000"), L("rahul", None, "100000", A("against_ref", "100000", "INV1"))]
    errors = check(lines, inv1("70000"), reversal=True)
    assert ids(errors) == [("B-04", 2)]
    assert "30,000.00" in errors[0].message


def test_reversal_of_the_receipt_goes_on_the_bills_own_side_without_B02():
    # the receipt (Cr 30,000 against INV1) is reversed by a Dr line against INV1: same side as the bill
    lines = [L("rahul", "30000", None, A("against_ref", "30000", "INV1")), L("hdfc", None, "30000")]
    assert check(lines, inv1("70000"), reversal=True) == []
    assert ids(check(lines, inv1("70000"))) == [("B-02", 1)]  # the same voucher as a normal one is refused


def test_reversal_of_an_on_account_receipt_is_on_account_again():
    lines = [L("rahul", "5000", None, A("on_account", "5000")), L("hdfc", None, "5000")]
    assert check(lines, reversal=True) == []


def test_reversal_of_an_advance_cannot_leave_the_advance_on_the_wrong_side():
    state = {ref_key("rahul", "ADV1"): BillState(D("-6000"), "Cr")}  # 10,000 received, 4,000 already adjusted
    lines = [L("rahul", "10000", None, A("against_ref", "10000", "ADV1")), L("hdfc", None, "10000")]
    assert ids(check(lines, state, reversal=True)) == [("B-04", 1)]


# ============================================================================================ mirroring


def test_mirror_allocations_turns_every_reference_into_against_ref():
    original = (A("new_ref", D("60000.00"), "INV1", date(2026, 5, 5)), A("advance", D("1.00"), "ADV2"),
                A("against_ref", D("2.00"), "INV0"), A("on_account", D("3.00")))
    assert mirror_allocations(original) == (
        A("against_ref", D("60000.00"), "INV1"), A("against_ref", D("1.00"), "ADV2"),
        A("against_ref", D("2.00"), "INV0"), A("on_account", D("3.00")),
    )


# ======================================================================================= due dates, resolve


def test_default_due_date_is_bill_date_plus_credit_days_and_explicit_wins():
    assert default_due_date(date(2026, 4, 5), 30, None) == date(2026, 5, 5)
    assert default_due_date(date(2026, 4, 5), 0, None) == date(2026, 4, 5)
    assert default_due_date(date(2026, 1, 31), 45, None) == date(2026, 3, 17)
    assert default_due_date(date(2026, 4, 5), 30, date(2026, 4, 20)) == date(2026, 4, 20)


def test_resolve_allocations_fills_due_date_and_sides():
    lines = [L("rahul", "25000", None, A("against_ref", "10000", "ADV1"), A("new_ref", "15000", "INV9")),
             L("sales", None, "25000"),
             L("hdfc", "5000"),
             L("rahul", None, "5000", A("on_account", "5000"))]
    got = resolve_allocations(lines, PARTIES, DAY)
    assert [(r.line_no, r.party_ledger_id, r.kind, r.bill_ref, r.due_date, r.debit, r.credit) for r in got] == [
        (1, "rahul", "against_ref", "ADV1", None, D("10000.00"), D("0.00")),
        (1, "rahul", "new_ref", "INV9", date(2026, 5, 5), D("15000.00"), D("0.00")),
        (4, "rahul", "on_account", None, None, D("0.00"), D("5000.00")),
    ]


def test_resolve_allocations_trims_the_reference_and_keeps_an_explicit_due_date():
    lines = [L("sharma", None, "100", A("new_ref", "100", "  PB-1 ", date(2026, 4, 9))), L("purchases", "100")]
    (r,) = resolve_allocations(lines, PARTIES, DAY)
    assert (r.bill_ref, r.due_date, r.credit) == ("PB-1", date(2026, 4, 9), D("100.00"))


# ============================================================================================= open bills


def test_open_bills_partial_settlement_advance_on_account_and_reversal():
    opening = [OpeningBillRow("rahul", "INV0", date(2026, 3, 1), date(2026, 3, 31), D("50000"))]
    allocs = [
        AllocationRow("rahul", "new_ref", "INV1", date(2026, 4, 5), date(2026, 5, 5), D("100000")),
        AllocationRow("rahul", "against_ref", "INV0", date(2026, 4, 20), None, D("-50000")),   # INV0 fully received
        AllocationRow("rahul", "against_ref", "INV1", date(2026, 4, 20), None, D("-30000")),   # part of INV1
        AllocationRow("rahul", "on_account", None, date(2026, 4, 25), None, D("-5000")),
        AllocationRow("rahul", "new_ref", "INV2", date(2026, 4, 26), date(2026, 5, 26), D("20000")),
        AllocationRow("rahul", "against_ref", "INV2", date(2026, 4, 27), None, D("-20000")),   # INV2 reversed
        AllocationRow("sharma", "new_ref", "PB1", date(2026, 4, 3), date(2026, 5, 18), D("-50000")),
        AllocationRow("sharma", "against_ref", "PB1", date(2026, 4, 12), None, D("15000")),
        AllocationRow("sharma", "advance", "SADV", date(2026, 4, 14), None, D("8000")),
    ]
    names = {"rahul": "Rahul Enterprises", "sharma": "Sharma Suppliers"}
    got = [(b.party_name, b.bill_ref, b.kind, b.bill_date, b.due_date, b.original, b.outstanding)
           for b in open_bills(opening, allocs, names)]
    assert got == [
        ("Rahul Enterprises", "INV1", "bill", date(2026, 4, 5), date(2026, 5, 5), D("100000.00"), D("70000.00")),
        ("Rahul Enterprises", None, "on_account", date(2026, 4, 25), date(2026, 4, 25), D("-5000.00"), D("-5000.00")),
        ("Sharma Suppliers", "PB1", "bill", date(2026, 4, 3), date(2026, 5, 18), D("-50000.00"), D("-35000.00")),
        ("Sharma Suppliers", "SADV", "advance", date(2026, 4, 14), None, D("8000.00"), D("8000.00")),
    ]


def test_open_bills_on_account_netting_to_zero_drops_out():
    allocs = [
        AllocationRow("rahul", "on_account", None, date(2026, 4, 25), None, D("-5000")),
        AllocationRow("rahul", "on_account", None, date(2026, 4, 26), None, D("5000")),
    ]
    assert open_bills([], allocs, {"rahul": "Rahul Enterprises"}) == []


def test_open_bills_opening_bill_keeps_its_own_dates_and_origin_side():
    opening = [OpeningBillRow("sharma", "PB0", date(2026, 2, 1), date(2026, 3, 18), D("-12000"))]
    (b,) = open_bills(opening, [], {"sharma": "Sharma Suppliers"})
    assert (b.bill_ref, b.kind, b.original, b.outstanding) == ("PB0", "bill", D("-12000.00"), D("-12000.00"))


# ============================================================================== opening bills: input + check


def test_B03_opening_bill_references_must_be_unique_and_present():
    bills = [OpeningBillIn("OB1", date(2026, 2, 1), "100", "Dr"), OpeningBillIn(" ob1 ", date(2026, 2, 2), "50", "Dr"),
             OpeningBillIn("", date(2026, 2, 3), "5", "Dr")]
    assert ids(validate_opening_bills(bills)) == [("B-03", 2), ("B-03", 3)]


def test_B05_opening_bill_amount_side_and_due_date_checked():
    bills = [OpeningBillIn("A", date(2026, 2, 1), "0", "Dr"), OpeningBillIn("B", date(2026, 2, 1), "10.001", "Dr"),
             OpeningBillIn("C", date(2026, 2, 1), "10", "X"),
             OpeningBillIn("D", date(2026, 2, 1), "10", "Cr", date(2026, 1, 31))]
    assert ids(validate_opening_bills(bills)) == [("B-05", 1), ("B-05", 2), ("B-05", 3), ("B-05", 4)]


def test_resolve_opening_bills_due_date_and_sign():
    bills = [OpeningBillIn(" OB1 ", date(2026, 3, 1), "100", "Dr"),
             OpeningBillIn("OB2", date(2026, 3, 1), "40.50", "Cr", date(2026, 3, 5))]
    got = resolve_opening_bills("rahul", bills, 30)
    assert got == [
        OpeningBillRow("rahul", "OB1", date(2026, 3, 1), date(2026, 3, 31), D("100.00")),
        OpeningBillRow("rahul", "OB2", date(2026, 3, 1), date(2026, 3, 5), D("-40.50")),
    ]


def test_opening_bills_check_balanced_and_difference():
    ok = opening_bills_check(D("50000.00"), OpeningBalance(D("50000.00"), D("0.00")))
    assert ok.is_balanced and ok.difference.side is None
    short = opening_bills_check(D("50000.00"), OpeningBalance(D("60000.00"), D("0.00")))
    assert not short.is_balanced
    assert (short.difference.amount, short.difference.side) == (D("10000.00"), "Dr")
    assert (short.total.amount, short.total.side, short.ledger.amount, short.ledger.side) == (
        D("50000.00"), "Dr", D("60000.00"), "Dr")
    none = opening_bills_check(D("0"), None)
    assert none.is_balanced
    credit = opening_bills_check(D("-3000.00"), OpeningBalance(D("0.00"), D("1000.00")))
    assert (credit.difference.amount, credit.difference.side) == (D("2000.00"), "Dr")


def test_M01_open_bills_carry_the_acceptance_date_and_basis():
    opening = [OpeningBillRow("sharma", "OB1", date(2026, 3, 20), date(2026, 4, 4), D("-1000"))]
    allocs = [
        AllocationRow("sharma", "new_ref", "PB1", date(2026, 4, 3), date(2026, 5, 18), D("-50000"),
                      date(2026, 4, 10)),
        AllocationRow("sharma", "new_ref", "PB2", date(2026, 4, 4), date(2026, 5, 19), D("-7000")),
    ]
    got = {b.bill_ref: (b.acceptance_date, b.acceptance_basis) for b in open_bills(opening, allocs, {"sharma": "Sharma"})}
    assert got == {
        "OB1": (date(2026, 3, 20), "bill date"),  # an opening bill uses its bill date
        "PB1": (date(2026, 4, 10), "goods received date"),
        "PB2": (date(2026, 4, 4), "bill date"),
    }
