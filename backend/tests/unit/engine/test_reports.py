"""Step 1.3: ledger statement and Trial Balance (pure engine).

The mini case is the one in PHASE_PROMPTS.md step 1.3. Every expected number was worked out by hand.

Opening:  Cash 50,000 Dr | Bank 3,00,000 Dr | Stock-in-hand 1,00,000 Dr | Capital 4,50,000 Cr
1) 02-04  Payment   Rent Dr 20,000 / Cash Cr
2) 03-04  Purchase  Purchases Dr 50,000 / Sharma Suppliers Cr
3) 05-04  Sales     Rahul Enterprises Dr 80,000 / Sales Cr
4) 10-04  Receipt   Bank Dr 30,000 / Rahul Cr
5) 12-04  Payment   Sharma Dr 15,000 / Bank Cr
6) 15-04  Contra    Bank Dr 10,000 / Cash Cr
7) 20-04  Payment   Drawings Dr 5,000 / Cash Cr
Closing:  Cash 15,000 Dr | Bank 3,25,000 Dr | Stock 1,00,000 Dr | Rahul 50,000 Dr | Sharma 35,000 Cr |
          Capital 4,50,000 Cr | Drawings 5,000 Dr | Rent 20,000 Dr | Purchases 50,000 Dr | Sales 80,000 Cr
TB totals: Dr 5,65,000 = Cr 5,65,000
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from engine_helpers import GROUPS

from app.engine.models import Balance, Ledger, OpeningBalance, PostedLine
from app.engine.reports import ledger_statement, trial_balance

D = Decimal


def ledger(key, name, group):
    return Ledger(key, name, group, True, "client-1")


LEDGERS = {
    x.id: x
    for x in [
        ledger("cash", "Cash", "cash_in_hand"),
        ledger("bank", "HDFC Bank", "bank_accounts"),
        ledger("stock", "Stock-in-hand", "stock_in_hand"),
        ledger("rahul", "Rahul Enterprises", "sundry_debtors"),
        ledger("sharma", "Sharma Suppliers", "sundry_creditors"),
        ledger("capital", "Owner Capital A/c", "capital_account"),
        ledger("drawings", "Drawings A/c", "capital_account"),
        ledger("rent", "Rent", "indirect_expenses"),
        ledger("purchases", "Purchases", "purchase_accounts"),
        ledger("sales", "Sales", "sales_accounts"),
        ledger("gst", "Output GST", "duties_taxes"),
        ledger("petty", "Petty Bank A/c", "petty_bank"),
    ]
}

OPENINGS = {
    "cash": OpeningBalance(D("50000.00"), D("0.00")),
    "bank": OpeningBalance(D("300000.00"), D("0.00")),
    "stock": OpeningBalance(D("100000.00"), D("0.00")),
    "capital": OpeningBalance(D("0.00"), D("450000.00")),
}


def voucher(vid, number, vtype, on, narration, rows, status="posted"):
    """rows = [(ledger_key, debit, credit)] -> PostedLine list."""
    return [
        PostedLine(vid, number, vtype, on, narration, status, n, key, LEDGERS[key].name, D(dr), D(cr))
        for n, (key, dr, cr) in enumerate(rows, start=1)
    ]


def mini_case(status="posted"):
    lines = []
    lines += voucher("v1", "PAY/2026-27/0001", "payment", date(2026, 4, 2), "April rent", [("rent", "20000", "0"), ("cash", "0", "20000")], status)
    lines += voucher("v2", "PUR/2026-27/0001", "purchase", date(2026, 4, 3), "Goods from Sharma", [("purchases", "50000", "0"), ("sharma", "0", "50000")], status)
    lines += voucher("v3", "SAL/2026-27/0001", "sales", date(2026, 4, 5), "Goods to Rahul", [("rahul", "80000", "0"), ("sales", "0", "80000")], status)
    lines += voucher("v4", "REC/2026-27/0001", "receipt", date(2026, 4, 10), "Received from Rahul", [("bank", "30000", "0"), ("rahul", "0", "30000")], status)
    lines += voucher("v5", "PAY/2026-27/0002", "payment", date(2026, 4, 12), "Paid Sharma", [("sharma", "15000", "0"), ("bank", "0", "15000")], status)
    lines += voucher("v6", "CON/2026-27/0001", "contra", date(2026, 4, 15), "Cash deposited", [("bank", "10000", "0"), ("cash", "0", "10000")], status)
    lines += voucher("v7", "PAY/2026-27/0003", "payment", date(2026, 4, 20), "Owner withdrew cash", [("drawings", "5000", "0"), ("cash", "0", "5000")], status)
    return lines


def tb(lines=None, as_on=date(2026, 4, 30), **kwargs):
    return trial_balance(list(LEDGERS.values()), GROUPS, OPENINGS, mini_case() if lines is None else lines, as_on, **kwargs)


def closing_by_name(result):
    return {
        row.ledger_name: (row.debit, row.credit)
        for section in result.sections
        for row in section.rows
    }


def dr(amount):
    return Balance(D(amount), "Dr")


def cr(amount):
    return Balance(D(amount), "Cr")


NIL = Balance(D("0.00"), None)


# ============================================================================================ Trial Balance


def test_trial_balance_closing_balances_of_the_mini_case():
    result = tb()
    assert closing_by_name(result) == {
        "Cash": (D("15000.00"), D("0.00")),
        "HDFC Bank": (D("325000.00"), D("0.00")),
        "Stock-in-hand": (D("100000.00"), D("0.00")),
        "Rahul Enterprises": (D("50000.00"), D("0.00")),
        "Sharma Suppliers": (D("0.00"), D("35000.00")),
        "Owner Capital A/c": (D("0.00"), D("450000.00")),
        "Drawings A/c": (D("5000.00"), D("0.00")),
        "Rent": (D("20000.00"), D("0.00")),
        "Purchases": (D("50000.00"), D("0.00")),
        "Sales": (D("0.00"), D("80000.00")),
        "Output GST": (D("0.00"), D("0.00")),
        "Petty Bank A/c": (D("0.00"), D("0.00")),
    }


def test_trial_balance_totals_are_5_65_000_on_both_sides_and_balanced():
    result = tb()
    assert (result.total_debit, result.total_credit) == (D("565000.00"), D("565000.00"))
    assert result.difference == NIL
    assert result.is_balanced is True


def test_trial_balance_groups_by_primary_group_with_subtotals_in_display_order():
    result = tb(hide_zero=True)
    assert [(s.group_name, s.debit, s.credit) for s in result.sections] == [
        ("Capital Account", D("5000.00"), D("450000.00")),
        ("Current Liabilities", D("0.00"), D("35000.00")),
        ("Current Assets", D("490000.00"), D("0.00")),
        ("Sales Accounts", D("0.00"), D("80000.00")),
        ("Purchase Accounts", D("50000.00"), D("0.00")),
        ("Indirect Expenses", D("20000.00"), D("0.00")),
    ]


def test_trial_balance_rows_carry_the_group_path_from_the_primary_group_down():
    result = tb(hide_zero=True)
    paths = {row.ledger_name: row.group_path for s in result.sections for row in s.rows}
    assert paths["Rahul Enterprises"] == ("Current Assets", "Sundry Debtors")
    assert paths["Sharma Suppliers"] == ("Current Liabilities", "Sundry Creditors")
    assert paths["Drawings A/c"] == ("Capital Account",)
    assert paths["Sales"] == ("Sales Accounts",)


def test_trial_balance_ledger_in_a_client_sub_group_shows_the_whole_path():
    lines = voucher("vp", "REC/2026-27/0009", "receipt", date(2026, 4, 6), "Deposit", [("petty", "1000", "0"), ("sales", "0", "1000")])
    result = tb(lines)
    petty = next(r for s in result.sections for r in s.rows if r.ledger_name == "Petty Bank A/c")
    assert petty.group_path == ("Current Assets", "Bank Accounts", "Petty Bank")
    assert (petty.debit, petty.credit) == (D("1000.00"), D("0.00"))


def test_trial_balance_rows_inside_a_group_are_sorted_by_path_then_ledger_name():
    result = tb(hide_zero=True)
    current_assets = next(s for s in result.sections if s.group_name == "Current Assets")
    # sorted by group path (Bank Accounts < Cash-in-hand < Stock-in-hand < Sundry Debtors), then ledger name
    assert [r.ledger_name for r in current_assets.rows] == ["HDFC Bank", "Cash", "Stock-in-hand", "Rahul Enterprises"]


def test_trial_balance_shows_nil_ledgers_by_default_and_can_hide_them():
    assert len(closing_by_name(tb())) == 12
    assert len(closing_by_name(tb(hide_zero=True))) == 10


def test_trial_balance_as_on_a_date_counts_only_vouchers_up_to_that_date_inclusive():
    # up to 10-04: vouchers 1-4 only. Cash 50,000-20,000 = 30,000 Dr; Bank 3,00,000+30,000 = 3,30,000 Dr;
    # Rahul 80,000-30,000 = 50,000 Dr; Sharma 50,000 Cr; Rent 20,000; Purchases 50,000; Sales 80,000 Cr
    # Dr: 30,000+3,30,000+1,00,000+50,000+20,000+50,000 = 5,80,000   Cr: 50,000+4,50,000+80,000 = 5,80,000
    result = tb(as_on=date(2026, 4, 10))
    balances = closing_by_name(result)
    assert balances["Cash"] == (D("30000.00"), D("0.00"))
    assert balances["HDFC Bank"] == (D("330000.00"), D("0.00"))
    assert balances["Rahul Enterprises"] == (D("50000.00"), D("0.00"))
    assert balances["Sharma Suppliers"] == (D("0.00"), D("50000.00"))
    assert balances["Drawings A/c"] == (D("0.00"), D("0.00"))  # voucher 7 is later
    assert (result.total_debit, result.total_credit) == (D("580000.00"), D("580000.00"))


def test_trial_balance_before_any_voucher_shows_only_the_opening_balances():
    result = tb(as_on=date(2026, 4, 1))
    assert (result.total_debit, result.total_credit) == (D("450000.00"), D("450000.00"))
    assert closing_by_name(result)["Cash"] == (D("50000.00"), D("0.00"))


@pytest.mark.parametrize("status", ["draft", "approved"])
def test_trial_balance_ignores_draft_and_approved_vouchers(status):
    result = tb(mini_case(status))
    balances = closing_by_name(result)
    assert balances["Cash"] == (D("50000.00"), D("0.00"))  # openings only
    assert balances["Rent"] == (D("0.00"), D("0.00"))
    assert (result.total_debit, result.total_credit) == (D("450000.00"), D("450000.00"))


def test_trial_balance_counts_a_reversed_voucher_and_its_reversal_so_they_cancel_out():
    reversal = voucher("v8", "PAY/2026-27/0004", "payment", date(2026, 4, 25), "Reversal of PAY/2026-27/0001: wrong month",
                       [("rent", "0", "20000"), ("cash", "20000", "0")])
    lines = [replace(x, status="reversed") if x.voucher_id == "v1" else x for x in mini_case()] + reversal
    result = tb(lines)
    balances = closing_by_name(result)
    assert balances["Cash"] == (D("35000.00"), D("0.00"))
    assert balances["Rent"] == (D("0.00"), D("0.00"))
    assert (result.total_debit, result.total_credit) == (D("565000.00"), D("565000.00"))


def test_trial_balance_reports_the_difference_when_it_does_not_balance_never_hides_it():
    openings = {"cash": OpeningBalance(D("100.00"), D("0.00")), "capital": OpeningBalance(D("0.00"), D("60.00"))}
    result = trial_balance(list(LEDGERS.values()), GROUPS, openings, [], date(2026, 4, 30))
    assert (result.total_debit, result.total_credit) == (D("100.00"), D("60.00"))
    assert result.difference == dr("40.00")
    assert result.is_balanced is False


def test_trial_balance_difference_on_the_credit_side():
    openings = {"cash": OpeningBalance(D("10.00"), D("0.00")), "capital": OpeningBalance(D("0.00"), D("60.50"))}
    result = trial_balance(list(LEDGERS.values()), GROUPS, openings, [], date(2026, 4, 30))
    assert result.difference == cr("50.50")


def test_trial_balance_nets_a_ledger_to_a_single_side():
    # Cash opens 50,000 Dr and pays out 80,000: closing 30,000 on the CREDIT side
    lines = voucher("vx", "PAY/2026-27/0099", "payment", date(2026, 4, 3), "Big payment", [("rent", "80000", "0"), ("cash", "0", "80000")])
    assert closing_by_name(tb(lines))["Cash"] == (D("0.00"), D("30000.00"))


def test_trial_balance_line_for_an_unknown_ledger_is_an_error_not_silently_dropped():
    lines = voucher("vz", "JRN/2026-27/0001", "journal", date(2026, 4, 3), "x", [("rent", "5", "0"), ("rent", "0", "5")])
    broken = [replace(lines[0], ledger_id="ghost", ledger_name="Ghost"), lines[1]]
    with pytest.raises(ValueError, match="ghost"):
        tb(broken)


def test_trial_balance_ledger_with_an_unknown_group_is_shown_under_its_own_code():
    odd = Ledger("odd", "Odd Ledger", "mystery_group", True, "client-1")
    result = trial_balance([odd], GROUPS, {"odd": OpeningBalance(D("5.00"), D("0.00"))}, [], date(2026, 4, 30))
    assert [(s.group_name, s.debit) for s in result.sections] == [("mystery_group", D("5.00"))]


# ======================================================================================= Ledger statement


def statement(key, lines=None, start=date(2026, 4, 1), end=date(2026, 4, 30)):
    return ledger_statement(LEDGERS[key], OPENINGS.get(key, OpeningBalance(D("0.00"), D("0.00"))),
                            mini_case() if lines is None else lines, start, end)


def rows_of(result):
    return [(r.kind, r.date, r.voucher_number, r.particulars, r.debit, r.credit, r.balance) for r in result.rows]


def test_cash_statement_running_balance_by_hand():
    result = statement("cash")
    assert rows_of(result) == [
        ("opening", date(2026, 4, 1), None, "Opening Balance", D("50000.00"), D("0.00"), dr("50000.00")),
        ("entry", date(2026, 4, 2), "PAY/2026-27/0001", "By Rent", D("0.00"), D("20000.00"), dr("30000.00")),
        ("entry", date(2026, 4, 15), "CON/2026-27/0001", "By HDFC Bank", D("0.00"), D("10000.00"), dr("20000.00")),
        ("entry", date(2026, 4, 20), "PAY/2026-27/0003", "By Drawings A/c", D("0.00"), D("5000.00"), dr("15000.00")),
        ("closing", date(2026, 4, 30), None, "Closing Balance", D("0.00"), D("0.00"), dr("15000.00")),
    ]
    assert (result.opening, result.closing) == (dr("50000.00"), dr("15000.00"))
    assert (result.total_debit, result.total_credit) == (D("0.00"), D("35000.00"))


def test_bank_statement_uses_to_on_the_debit_side_and_by_on_the_credit_side():
    result = statement("bank")
    assert rows_of(result) == [
        ("opening", date(2026, 4, 1), None, "Opening Balance", D("300000.00"), D("0.00"), dr("300000.00")),
        ("entry", date(2026, 4, 10), "REC/2026-27/0001", "To Rahul Enterprises", D("30000.00"), D("0.00"), dr("330000.00")),
        ("entry", date(2026, 4, 12), "PAY/2026-27/0002", "By Sharma Suppliers", D("0.00"), D("15000.00"), dr("315000.00")),
        ("entry", date(2026, 4, 15), "CON/2026-27/0001", "To Cash", D("10000.00"), D("0.00"), dr("325000.00")),
        ("closing", date(2026, 4, 30), None, "Closing Balance", D("0.00"), D("0.00"), dr("325000.00")),
    ]
    assert (result.total_debit, result.total_credit) == (D("40000.00"), D("15000.00"))


def test_creditor_statement_runs_on_the_credit_side():
    result = statement("sharma")
    assert [r.balance for r in result.rows] == [NIL, cr("50000.00"), cr("35000.00"), cr("35000.00")]
    assert result.closing == cr("35000.00")


def test_statement_from_a_later_date_brings_earlier_postings_into_the_opening_row():
    result = statement("cash", start=date(2026, 4, 10))
    assert result.opening == dr("30000.00")  # 50,000 opening - 20,000 rent paid on 02-04
    assert [(r.kind, r.voucher_number, r.balance) for r in result.rows] == [
        ("opening", None, dr("30000.00")),
        ("entry", "CON/2026-27/0001", dr("20000.00")),
        ("entry", "PAY/2026-27/0003", dr("15000.00")),
        ("closing", None, dr("15000.00")),
    ]


def test_statement_to_an_earlier_date_stops_there_inclusive():
    result = statement("cash", end=date(2026, 4, 15))
    assert [r.voucher_number for r in result.rows if r.kind == "entry"] == ["PAY/2026-27/0001", "CON/2026-27/0001"]
    assert result.closing == dr("20000.00")


def test_statement_period_boundaries_are_inclusive():
    result = statement("cash", start=date(2026, 4, 15), end=date(2026, 4, 15))
    assert [r.voucher_number for r in result.rows if r.kind == "entry"] == ["CON/2026-27/0001"]


def test_statement_of_a_ledger_with_no_postings_shows_opening_and_closing_only():
    result = statement("stock")
    assert [(r.kind, r.balance) for r in result.rows] == [("opening", dr("100000.00")), ("closing", dr("100000.00"))]


def test_statement_of_an_unused_ledger_is_nil():
    result = statement("gst")
    assert (result.opening, result.closing) == (NIL, NIL)
    assert [(r.kind, r.debit, r.credit) for r in result.rows] == [
        ("opening", D("0.00"), D("0.00")), ("closing", D("0.00"), D("0.00"))
    ]


def test_statement_balance_changes_side_when_the_ledger_is_overdrawn():
    lines = voucher("vx", "PAY/2026-27/0099", "payment", date(2026, 4, 3), "Big payment", [("rent", "80000", "0"), ("cash", "0", "80000")])
    result = statement("cash", lines)
    assert [r.balance for r in result.rows] == [dr("50000.00"), cr("30000.00"), cr("30000.00")]


def test_statement_with_several_counter_ledgers_says_as_per_details():
    lines = voucher("vg", "SAL/2026-27/0010", "sales", date(2026, 4, 8), "Sale with GST",
                    [("rahul", "118000", "0"), ("sales", "0", "100000"), ("gst", "0", "18000")])
    entries = [r for r in statement("rahul", lines).rows if r.kind == "entry"]
    assert [(r.particulars, r.debit) for r in entries] == [("(as per details)", D("118000.00"))]
    sales = [r for r in statement("sales", lines).rows if r.kind == "entry"]
    assert [r.particulars for r in sales] == ["(as per details)"]  # Sales sees Rahul and Output GST on the other side


def test_statement_counter_ledger_is_named_when_exactly_one_other_ledger_is_involved():
    lines = voucher("vg", "SAL/2026-27/0010", "sales", date(2026, 4, 8), "Cash sale", [("cash", "500", "0"), ("sales", "0", "500")])
    entries = [r for r in statement("sales", lines).rows if r.kind == "entry"]
    assert [r.particulars for r in entries] == ["By Cash"]


def test_statement_shows_narration_and_voucher_type():
    entry = statement("cash").rows[1]
    assert (entry.voucher_type, entry.narration) == ("payment", "April rent")


@pytest.mark.parametrize("status", ["draft", "approved"])
def test_statement_ignores_draft_and_approved_vouchers(status):
    result = statement("cash", mini_case(status))
    assert [r.kind for r in result.rows] == ["opening", "closing"]
    assert result.closing == dr("50000.00")


def test_statement_counts_a_reversed_voucher_and_its_reversal():
    reversal = voucher("v8", "PAY/2026-27/0004", "payment", date(2026, 4, 25), "Reversal of PAY/2026-27/0001",
                       [("rent", "0", "20000"), ("cash", "20000", "0")])
    lines = [replace(x, status="reversed") if x.voucher_id == "v1" else x for x in mini_case()] + reversal
    result = statement("cash", lines)
    assert [r.voucher_number for r in result.rows if r.kind == "entry"] == [
        "PAY/2026-27/0001", "CON/2026-27/0001", "PAY/2026-27/0003", "PAY/2026-27/0004",
    ]
    assert result.closing == dr("35000.00")


def test_statement_with_to_date_before_from_date_is_an_error():
    with pytest.raises(ValueError, match="to_date"):
        statement("cash", start=date(2026, 4, 30), end=date(2026, 4, 1))


def test_statement_entries_on_the_same_date_are_ordered_by_voucher_number_then_line():
    lines = (
        voucher("b", "PAY/2026-27/0002", "payment", date(2026, 4, 3), "second", [("rent", "2", "0"), ("cash", "0", "2")])
        + voucher("a", "PAY/2026-27/0001", "payment", date(2026, 4, 3), "first", [("rent", "1", "0"), ("cash", "0", "1")])
    )
    result = statement("cash", lines)
    assert [r.voucher_number for r in result.rows if r.kind == "entry"] == ["PAY/2026-27/0001", "PAY/2026-27/0002"]
