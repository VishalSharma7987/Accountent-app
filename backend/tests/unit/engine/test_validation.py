"""validate_voucher: one passing and one failing test per rule, plus the Step 1.2 scenarios.

Expected rule IDs, line numbers and key messages are typed literally.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from engine_helpers import (
    GROUPS,
    LEDGERS,
    april_locked,
    draft,
    ids,
    line,
    no_periods,
    only,
    run,
)

from app.engine.validation import group_chain, validate_voucher

# ============================================================================================ valid vouchers


def test_valid_owner_invests_1_lakh_cash_in_the_business():
    d = draft("receipt", [line("cash", dr="100000"), line("capital", cr="100000")], narration="Capital introduced")
    assert run(d) == []


def test_valid_voucher_of_every_type():
    cases = [
        draft("contra", [line("cash", cr="5000"), line("hdfc", dr="5000")]),
        draft("payment", [line("rent", dr="10000"), line("cash", cr="10000")]),
        draft("receipt", [line("hdfc", dr="30000"), line("rahul", cr="30000")], party="rahul"),
        draft("sales", [line("rahul", dr="80000"), line("sales", cr="80000")], party="rahul"),
        draft("purchase", [line("purchases", dr="50000"), line("sharma", cr="50000")], party="sharma", reference_no="B-77"),
        draft("credit_note", [line("sales", dr="2000"), line("rahul", cr="2000")], party="rahul"),
        draft("debit_note", [line("sharma", dr="1500"), line("purchases", cr="1500")], party="sharma", reference_no="B-77"),
        draft("journal", [line("rent", dr="8000"), line("outstanding_rent", cr="8000")]),
    ]
    assert [run(d) for d in cases] == [[]] * 8


def test_all_errors_are_returned_together_not_just_the_first():
    d = draft("sales", [line("rahul", dr="100")], on=date(2027, 4, 1), narration="")
    assert ids(run(d)) == [("V-01", None), ("V-06", None), ("V-09", None)]


# ===================================================================================================== V-01


def test_V01_two_lines_is_enough():
    assert only(run(draft("journal", [line("rent", dr="1"), line("outstanding_rent", cr="1")])), "V-01") == []


@pytest.mark.parametrize(("lines", "count"), [([], 0), ([line("rent", dr="100")], 1)])
def test_V01_fewer_than_two_lines_rejected(lines, count):
    errors = only(run(draft("journal", lines)), "V-01")
    assert [(e.rule_id, e.line_no, e.message) for e in errors] == [
        ("V-01", None, f"A voucher needs at least 2 lines; this one has {count}.")
    ]


# ===================================================================================================== V-02


def test_V02_exactly_one_side_per_line_passes():
    assert only(run(draft("journal", [line("rent", dr="10"), line("outstanding_rent", cr="10")])), "V-02") == []


def test_V02_line_with_both_debit_and_credit_rejected():
    d = draft("journal", [line("rent", dr="100", cr="50"), line("outstanding_rent", cr="50")])
    errors = only(run(d), "V-02")
    assert [(e.line_no, e.message) for e in errors] == [
        (1, "Line 1: enter either a Debit or a Credit amount, not both.")
    ]


@pytest.mark.parametrize("empty", [(None, None), ("", ""), ("0", "0"), ("0.00", None), (" ", "0")])
def test_V02_line_with_no_amount_rejected(empty):
    d = draft("journal", [line("rent", dr="100"), line("outstanding_rent", cr="100"), line("sharma", *empty)])
    errors = only(run(d), "V-02")
    assert [(e.line_no, e.message) for e in errors] == [
        (3, "Line 3: enter a Debit or a Credit amount; both are empty or zero.")
    ]


def test_V02_is_not_reported_for_a_line_whose_amount_is_unreadable():
    d = draft("journal", [line("rent", dr="10.005", cr="5"), line("outstanding_rent", cr="5")])
    assert ids(run(d)) == [("V-03", 1)]


# ===================================================================================================== V-03


@pytest.mark.parametrize(
    ("amount", "message"),
    [
        ("10.005", "Line 1: amount 10.005 has more than 2 decimal places."),
        ("-5", "Line 1: amount -5 is negative."),
        ("abc", "Line 1: amount 'abc' is not a valid number."),
        ("1,000.00", "Line 1: amount '1,000.00' is not a valid number."),
        (10.5, "Line 1: amount 10.5 is given as a floating-point number; amounts must be text or Decimal."),
    ],
)
def test_V03_bad_amounts_rejected_with_the_line_number(amount, message):
    d = draft("journal", [line("rent", dr=amount), line("outstanding_rent", cr="100")])
    assert [(e.rule_id, e.line_no, e.message) for e in only(run(d), "V-03")] == [("V-03", 1, message)]


def test_V03_amount_on_the_credit_side_is_checked_too():
    d = draft("journal", [line("rent", dr="100"), line("outstanding_rent", cr="100.001")])
    assert [(e.line_no, e.message) for e in only(run(d), "V-03")] == [
        (2, "Line 2: amount 100.001 has more than 2 decimal places.")
    ]


def test_V03_two_decimals_and_whole_numbers_pass():
    d = draft("journal", [line("rent", dr="10.50"), line("outstanding_rent", cr=Decimal("10.5"))])
    assert run(d) == []


def test_V03_when_an_amount_is_unreadable_the_balance_is_not_judged():
    d = draft("journal", [line("rent", dr="10.005"), line("outstanding_rent", cr="500")])
    assert ids(run(d)) == [("V-03", 1)]  # no V-04 about a total that cannot be trusted


# ===================================================================================================== V-04


def test_V04_balanced_voucher_passes():
    d = draft("payment", [line("rent", dr="10000"), line("cash", cr="10000")])
    assert only(run(d), "V-04") == []


def test_V04_rent_10000_against_cash_9000_rejected_with_amounts_and_difference():
    d = draft("payment", [line("rent", dr="10000"), line("cash", cr="9000")])
    errors = only(run(d), "V-04")
    assert [(e.line_no, e.message) for e in errors] == [
        (None, "Debit 10,000.00 and Credit 9,000.00 are not equal (difference 1,000.00)")
    ]


def test_V04_amounts_in_the_message_use_lakhs_and_crores():
    d = draft("payment", [line("rent", dr="100000"), line("cash", cr="99000")])
    assert only(run(d), "V-04")[0].message == (
        "Debit 1,00,000.00 and Credit 99,000.00 are not equal (difference 1,000.00)"
    )


def test_V04_one_paisa_difference_is_caught():
    d = draft("payment", [line("rent", dr="100.01"), line("cash", cr="100.00")])
    assert only(run(d), "V-04")[0].message == "Debit 100.01 and Credit 100.00 are not equal (difference 0.01)"


def test_V04_several_lines_are_summed_exactly():
    d = draft(
        "journal",
        [line("rent", dr="0.10"), line("freight", dr="0.20"), line("outstanding_rent", cr="0.30")],
    )
    assert only(run(d), "V-04") == []


# ===================================================================================================== V-05


def test_V05_active_ledgers_of_the_same_client_pass():
    assert only(run(draft("payment", [line("rent", dr="1"), line("cash", cr="1")])), "V-05") == []


def test_V05_unknown_ledger_rejected():
    d = draft("payment", [line("rent", dr="1"), line("no-such-ledger", cr="1")])
    assert [(e.line_no, e.message) for e in only(run(d), "V-05")] == [(2, "Line 2: this ledger does not exist.")]


def test_V05_ledger_of_another_client_rejected():
    d = draft("payment", [line("rent", dr="1"), line("foreign_cash", cr="1")])
    assert [(e.line_no, e.message) for e in only(run(d), "V-05")] == [
        (2, "Line 2: ledger 'Cash' belongs to another client.")
    ]


def test_V05_inactive_ledger_rejected():
    d = draft("payment", [line("retired", dr="1"), line("cash", cr="1")])
    assert [(e.line_no, e.message) for e in only(run(d), "V-05")] == [
        (1, "Line 1: ledger 'Old Expense' is inactive.")
    ]


def test_V05_party_ledger_is_checked_too_and_has_no_line_number():
    d = draft("sales", [line("rahul", dr="1"), line("sales", cr="1")], party="ghost")
    assert [(e.line_no, e.message) for e in only(run(d), "V-05")] == [(None, "The party ledger does not exist.")]


def test_V05_inactive_party_ledger_rejected():
    d = draft("payment", [line("retired", dr="1"), line("cash", cr="1")], party="retired")
    messages = [e.message for e in only(run(d), "V-05")]
    assert messages == ["Line 1: ledger 'Old Expense' is inactive.", "The party ledger 'Old Expense' is inactive."]


def test_V05_reversal_may_use_a_ledger_deactivated_after_the_original_was_posted():
    d = draft("payment", [line("retired", cr="1"), line("cash", dr="1")], party="retired")
    assert only(run(d), "V-05") != []
    assert only(run(d, is_reversal=True), "V-05") == []


def test_V05_reversal_still_rejects_a_missing_or_foreign_ledger():
    d = draft("payment", [line("ghost", cr="1"), line("cash", dr="1")])
    assert [e.message for e in only(run(d, is_reversal=True), "V-05")] == ["Line 1: this ledger does not exist."]


# ===================================================================================================== V-06


@pytest.mark.parametrize("on", [date(2026, 4, 1), date(2027, 3, 31), date(2026, 9, 15)])
def test_V06_date_inside_the_financial_year_passes(on):
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=on)
    assert only(run(d), "V-06") == []


@pytest.mark.parametrize(
    ("on", "shown"), [(date(2026, 3, 31), "31-03-2026"), (date(2027, 4, 1), "01-04-2027"), (date(2030, 4, 15), "15-04-2030")]
)
def test_V06_date_outside_every_financial_year_rejected(on, shown):
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=on)
    errors = only(run(d), "V-06")
    assert [(e.line_no, e.message) for e in errors] == [
        (None, f"Voucher date {shown} is not inside any financial year of this client.")
    ]


def test_V06_second_financial_year_is_found():
    fy = [(date(2025, 4, 1), date(2026, 3, 31)), (date(2026, 4, 1), date(2027, 3, 31))]
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=date(2025, 12, 1))
    assert only(run(d, fy=fy, periods=lambda on: None), "V-06") == []


# ===================================================================================================== V-07


def test_V07_open_period_passes():
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=date(2026, 5, 10))
    assert only(run(d, periods=april_locked), "V-07") == []


def test_V07_date_in_a_locked_period_rejected():
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=date(2026, 4, 5))
    errors = only(run(d, periods=april_locked), "V-07")
    assert [(e.line_no, e.message) for e in errors] == [(None, "The period 01-04-2026 to 30-04-2026 is locked.")]


def test_V07_date_with_no_period_defined_rejected():
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=date(2026, 5, 10))
    errors = only(run(d, periods=no_periods), "V-07")
    assert [(e.line_no, e.message) for e in errors] == [
        (None, "No period is defined for 10-05-2026; create the period before entering this voucher.")
    ]


def test_V07_is_not_checked_when_the_date_is_outside_the_financial_year():
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], on=date(2027, 4, 1))
    errors = run(d, periods=april_locked)
    assert ids(errors) == [("V-06", None)]


# ===================================================================================================== V-08


def v08(d):
    return [(e.line_no, e.message) for e in only(run(d), "V-08")]


def test_V08_contra_between_cash_and_bank_passes_even_through_a_client_sub_group():
    assert v08(draft("contra", [line("cash", cr="100"), line("petty", dr="100")])) == []


def test_V08_contra_with_a_non_cash_bank_ledger_rejected():
    d = draft("contra", [line("cash", cr="100"), line("rahul", dr="100")])
    assert v08(d) == [(2, "Line 2: a Contra voucher can only use Cash and Bank ledgers, but 'Rahul Enterprises' is under Sundry Debtors.")]


def test_V08_contra_with_a_party_ledger_rejected():
    d = draft("contra", [line("cash", cr="100"), line("hdfc", dr="100")], party="hdfc")
    assert v08(d) == [(None, "A Contra voucher moves money between Cash and Bank; it cannot have a party ledger.")]


def test_V08_payment_with_a_credit_to_cash_or_bank_passes():
    assert v08(draft("payment", [line("sharma", dr="100"), line("hdfc", cr="100")])) == []


def test_V08_payment_with_cash_on_both_sides_must_be_a_contra():
    d = draft("payment", [line("cash", dr="100"), line("hdfc", cr="100")])
    assert v08(d) == [(None, "Every line of this Payment is a Cash or Bank ledger; money moving between them is a Contra voucher.")]


def test_V08_payment_without_a_credit_to_cash_or_bank_rejected():
    d = draft("payment", [line("rent", dr="100"), line("sharma", cr="100")])
    assert v08(d) == [(None, "A Payment voucher needs at least one Credit line to a Cash or Bank ledger.")]


def test_V08_payment_with_cash_only_on_the_debit_side_rejected():
    d = draft("payment", [line("cash", dr="100"), line("rent", cr="100")])
    assert v08(d) == [(None, "A Payment voucher needs at least one Credit line to a Cash or Bank ledger.")]


def test_V08_receipt_with_a_debit_to_cash_or_bank_passes():
    assert v08(draft("receipt", [line("cash", dr="100"), line("rahul", cr="100")])) == []


def test_V08_receipt_with_cash_on_both_sides_must_be_a_contra():
    d = draft("receipt", [line("cash", dr="100"), line("hdfc", cr="100")])
    assert v08(d) == [(None, "Every line of this Receipt is a Cash or Bank ledger; money moving between them is a Contra voucher.")]


def test_V08_receipt_without_a_debit_to_cash_or_bank_rejected():
    d = draft("receipt", [line("rahul", dr="100"), line("sales", cr="100")])
    assert v08(d) == [(None, "A Receipt voucher needs at least one Debit line to a Cash or Bank ledger.")]


def test_V08_sales_with_a_credit_to_sales_accounts_passes():
    assert v08(draft("sales", [line("cash", dr="100"), line("sales", cr="100")])) == []


def test_V08_sales_voucher_without_a_sales_accounts_line_rejected():
    d = draft("sales", [line("rahul", dr="100"), line("rent", cr="100")])
    assert v08(d) == [(None, "A Sales voucher needs at least one Credit line to a Sales Accounts ledger.")]


def test_V08_sales_account_on_the_debit_side_does_not_count():
    d = draft("sales", [line("sales", dr="100"), line("rahul", cr="100")])
    assert v08(d) == [(None, "A Sales voucher needs at least one Credit line to a Sales Accounts ledger.")]


@pytest.mark.parametrize("debit_ledger", ["purchases", "plant", "freight", "rent"])
def test_V08_purchase_with_a_debit_to_a_purchase_asset_or_expense_ledger_passes(debit_ledger):
    d = draft("purchase", [line(debit_ledger, dr="100"), line("sharma", cr="100")], reference_no="B-1")
    assert v08(d) == []


def test_V08_purchase_without_such_a_debit_line_rejected():
    d = draft("purchase", [line("cash", dr="100"), line("capital", cr="100")], reference_no="B-1")
    assert v08(d) == [(None, "A Purchase voucher needs at least one Debit line to a Purchase Accounts, Fixed Assets, Direct Expenses or Indirect Expenses ledger.")]


def test_V08_credit_note_needs_a_debit_to_sales_accounts():
    assert v08(draft("credit_note", [line("sales", dr="100"), line("rahul", cr="100")])) == []
    d = draft("credit_note", [line("purchases", dr="100"), line("rahul", cr="100")])
    assert v08(d) == [(None, "A Credit Note needs at least one Debit line to a Sales Accounts ledger (the sales return).")]


def test_V08_debit_note_needs_a_credit_to_purchase_accounts():
    assert v08(draft("debit_note", [line("sharma", dr="100"), line("purchases", cr="100")], reference_no="B-1")) == []
    d = draft("debit_note", [line("sharma", dr="100"), line("sales", cr="100")], reference_no="B-1")
    assert v08(d) == [(None, "A Debit Note needs at least one Credit line to a Purchase Accounts ledger (the purchase return).")]


def test_V08_journal_without_cash_or_bank_passes():
    assert v08(draft("journal", [line("rent", dr="100"), line("outstanding_rent", cr="100")])) == []


def test_V08_journal_touching_bank_rejected():
    d = draft("journal", [line("rent", dr="100"), line("hdfc", cr="100")])
    assert v08(d) == [(2, "Line 2: a Journal cannot use Cash or Bank ledgers ('HDFC Bank'); use a Payment, Receipt or Contra voucher.")]


def test_V08_journal_touching_cash_rejected():
    d = draft("journal", [line("cash", dr="100"), line("outstanding_rent", cr="100")])
    assert v08(d) == [(1, "Line 1: a Journal cannot use Cash or Bank ledgers ('Cash'); use a Payment, Receipt or Contra voucher.")]


def test_V08_is_not_judged_when_a_ledger_is_unknown():
    d = draft("payment", [line("rent", dr="100"), line("no-such-ledger", cr="100")])
    assert ids(run(d)) == [("V-05", 2)]


def test_V08_is_not_judged_when_a_line_has_no_valid_amount():
    d = draft("payment", [line("rent", dr="100"), line("cash")])
    assert ids(run(d)) == [("V-02", 2)]


def test_group_chain_walks_up_the_parent_groups():
    assert group_chain("petty_bank", GROUPS) == ["petty_bank", "bank_accounts", "current_assets"]
    assert group_chain("sundry_debtors", GROUPS) == ["sundry_debtors", "current_assets"]
    assert group_chain("sales_accounts", GROUPS) == ["sales_accounts"]
    assert group_chain("unknown_code", GROUPS) == ["unknown_code"]


def test_group_chain_survives_a_cycle_in_the_data():
    from app.engine.models import Group

    loop = {"a": Group("a", "A", "asset", "balance_sheet", "b"), "b": Group("b", "B", "asset", "balance_sheet", "a")}
    assert group_chain("a", loop) == ["a", "b"]


# ===================================================================================================== V-09


def test_V09_narration_present_passes():
    assert only(run(draft("payment", [line("rent", dr="1"), line("cash", cr="1")])), "V-09") == []


@pytest.mark.parametrize("narration", [None, "", "   ", "\t\n"])
def test_V09_missing_narration_rejected(narration):
    d = draft("payment", [line("rent", dr="1"), line("cash", cr="1")], narration=narration)
    assert [(e.line_no, e.message) for e in only(run(d), "V-09")] == [(None, "Narration is required.")]


# ===================================================================================================== V-13


def test_V13_party_ledger_that_appears_in_the_lines_passes():
    d = draft("sales", [line("rahul", dr="100"), line("sales", cr="100")], party="rahul")
    assert only(run(d), "V-13") == []


def test_V13_party_ledger_missing_from_the_lines_rejected():
    d = draft("sales", [line("cash", dr="100"), line("sales", cr="100")], party="rahul")
    assert [(e.line_no, e.message) for e in only(run(d), "V-13")] == [
        (None, "Party ledger 'Rahul Enterprises' is not in the voucher's lines.")
    ]


def test_V13_no_party_ledger_means_nothing_to_check():
    d = draft("sales", [line("cash", dr="100"), line("sales", cr="100")])
    assert only(run(d), "V-13") == []


def test_V13_unknown_party_ledger_is_reported_by_V05_only():
    d = draft("sales", [line("cash", dr="100"), line("sales", cr="100")], party="ghost")
    assert ids(run(d)) == [("V-05", None)]


# ===================================================================================================== V-14


@pytest.mark.parametrize("vtype", ["purchase", "debit_note"])
def test_V14_reference_present_passes(vtype):
    lines = {
        "purchase": [line("purchases", dr="100"), line("sharma", cr="100")],
        "debit_note": [line("sharma", dr="100"), line("purchases", cr="100")],
    }[vtype]
    assert only(run(draft(vtype, lines, reference_no="SUP/889")), "V-14") == []


@pytest.mark.parametrize("reference", [None, "", "   "])
def test_V14_purchase_without_a_bill_number_rejected(reference):
    d = draft("purchase", [line("purchases", dr="100"), line("sharma", cr="100")], reference_no=reference)
    assert [(e.line_no, e.message) for e in only(run(d), "V-14")] == [
        (None, "A Purchase voucher needs the supplier's bill number in Reference No.")
    ]


def test_V14_debit_note_without_the_original_reference_rejected():
    d = draft("debit_note", [line("sharma", dr="100"), line("purchases", cr="100")], reference_no=" ")
    assert [(e.line_no, e.message) for e in only(run(d), "V-14")] == [
        (None, "A Debit Note needs the original bill or debit note reference in Reference No.")
    ]


@pytest.mark.parametrize("vtype", ["sales", "credit_note", "payment", "receipt", "contra", "journal"])
def test_V14_other_voucher_types_do_not_need_a_reference(vtype):
    lines = {
        "sales": [line("rahul", dr="1"), line("sales", cr="1")],
        "credit_note": [line("sales", dr="1"), line("rahul", cr="1")],
        "payment": [line("rent", dr="1"), line("cash", cr="1")],
        "receipt": [line("cash", dr="1"), line("rahul", cr="1")],
        "contra": [line("cash", dr="1"), line("hdfc", cr="1")],
        "journal": [line("rent", dr="1"), line("outstanding_rent", cr="1")],
    }[vtype]
    assert only(run(draft(vtype, lines)), "V-14") == []


# ===================================================================================================== V-15


def _purchase_with_grd(grd, vtype="purchase"):
    lines = [line("purchases", dr="100"), line("sharma", cr="100")] if vtype == "purchase" else [
        line("rahul", dr="100"), line("sales", cr="100")]
    return replace(draft(vtype, lines, reference_no="SUP/1"), goods_received_date=grd)


def test_V15_goods_received_date_before_or_after_the_bill_date_passes():
    assert only(run(_purchase_with_grd(date(2026, 4, 1))), "V-15") == []  # before the bill date 05-04-2026
    assert only(run(_purchase_with_grd(date(2026, 4, 20))), "V-15") == []  # after
    assert only(run(_purchase_with_grd(None)), "V-15") == []


def test_V15_exactly_365_days_away_passes_366_rejected():
    assert only(run(_purchase_with_grd(date(2027, 4, 5))), "V-15") == []  # 05-04-2026 + 365 = 05-04-2027
    errors = only(run(_purchase_with_grd(date(2027, 4, 6))), "V-15")
    assert [(e.line_no, e.message) for e in errors] == [(
        None,
        "Goods received date 06-04-2027 is more than 365 days away from the voucher date 05-04-2026; check the date.",
    )]
    assert only(run(_purchase_with_grd(date(2025, 4, 5))), "V-15") == []  # 05-04-2025 is 365 days before
    assert only(run(_purchase_with_grd(date(2025, 4, 4))), "V-15") != []


def test_V15_goods_received_date_only_on_a_purchase_voucher():
    errors = only(run(_purchase_with_grd(date(2026, 4, 1), "sales")), "V-15")
    assert [e.message for e in errors] == ["Goods received date can be entered only on a Purchase voucher."]


# ===================================================================================================== misc


def test_unknown_voucher_type_is_a_programming_error():
    d = draft("expense", [line("rent", dr="1"), line("cash", cr="1")])
    with pytest.raises(ValueError, match="expense"):
        run(d)


def test_errors_are_ordered_by_rule_then_line():
    d = draft("journal", [line("rent", dr="10.005"), line("hdfc", dr="5"), line("cash")], narration="")
    assert ids(run(d)) == [("V-02", 3), ("V-03", 1), ("V-09", None)]


def test_validate_voucher_does_not_modify_its_inputs():
    ledgers = dict(LEDGERS)
    d = draft("payment", [line("rent", dr="100"), line("cash", cr="100")])
    validate_voucher(d, ledgers, GROUPS, [(date(2026, 4, 1), date(2027, 3, 31))], lambda on: None)
    assert ledgers == LEDGERS


# ============================================================================================ reversal vouchers


def test_a_reversal_mirrors_the_original_so_the_type_rules_are_not_applied():
    """A reversed Payment has a DEBIT to cash: without is_reversal the Payment rule (V-08) would reject it."""
    reversed_payment = draft("payment", [line("rent", cr="10000"), line("cash", dr="10000")])
    assert ids(run(reversed_payment)) == [("V-08", None)]
    assert run(reversed_payment, is_reversal=True) == []


def test_a_reversed_sale_and_purchase_pass_as_reversals():
    sale = draft("sales", [line("rahul", cr="500"), line("sales", dr="500")], party="rahul")
    purchase = draft("purchase", [line("purchases", cr="700"), line("sharma", dr="700")], party="sharma", reference_no="B-9")
    assert ids(run(sale)) == [("V-08", None)] and run(sale, is_reversal=True) == []
    assert ids(run(purchase)) == [("V-08", None)] and run(purchase, is_reversal=True) == []


def test_a_reversal_is_still_checked_for_everything_else():
    d = draft("payment", [line("rent", cr="100"), line("cash", dr="90")], on=date(2027, 4, 1), narration="")
    assert ids(run(d, is_reversal=True)) == [("V-04", None), ("V-06", None), ("V-09", None)]
    locked = draft("payment", [line("rent", cr="1"), line("cash", dr="1")], on=date(2026, 4, 5))
    assert ids(run(locked, is_reversal=True, periods=april_locked)) == [("V-07", None)]


def test_a_reversal_of_a_purchase_still_needs_the_reference():
    d = draft("purchase", [line("purchases", cr="700"), line("sharma", dr="700")], party="sharma")
    assert ids(run(d, is_reversal=True)) == [("V-14", None)]
