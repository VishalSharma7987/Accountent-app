"""The runner's reporting helpers (no database)."""

from decimal import Decimal

import pytest
from pack_runner import RunReport, describe_difference, format_report, side

D = Decimal


@pytest.mark.parametrize(
    ("debit", "credit", "text"),
    [
        (D("54200.00"), D("0.00"), "Dr 54,200.00"),
        (D("0.00"), D("1354460.00"), "Cr 13,54,460.00"),
        (D("0.00"), D("0.00"), "nil"),
        (D("5.00"), D("3.00"), "Dr 5.00 and Cr 3.00"),
    ],
)
def test_side_shows_the_balance_the_way_accountants_read_it(debit, credit, text):
    assert side(debit, credit) == text


def test_a_difference_names_the_ledger_both_balances_and_the_gap():
    line = describe_difference("Cash", (D("54200.00"), D("0.00")), (D("54000.00"), D("0.00")))
    assert line == "Cash: expected Dr 54,200.00, tool says Dr 54,000.00 (difference 200.00)"


def test_a_difference_across_sides_adds_up():
    line = describe_difference("Rahul", (D("100.00"), D("0.00")), (D("0.00"), D("50.00")))
    assert line == "Rahul: expected Dr 100.00, tool says Cr 50.00 (difference 150.00)"


def test_the_report_lists_every_difference_and_the_counts():
    report = RunReport("demo-pack", problems=["Cash: x", "Rent: y"], posted=30, reversed=1, wrong_checked=16)
    assert format_report(report) == (
        "Pack 'demo-pack': 2 difference(s)\n  - Cash: x\n  - Rent: y\n"
        "  (30 vouchers posted, 1 reversed, 16 wrong vouchers rejected)"
    )
