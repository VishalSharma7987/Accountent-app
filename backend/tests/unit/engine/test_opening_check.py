from decimal import Decimal

from app.engine.models import Balance, OpeningBalance
from app.engine.reports import check_openings

D = Decimal


def test_no_opening_balances_is_balanced_at_nil():
    result = check_openings([])
    assert (result.total_debit, result.total_credit, result.is_balanced) == (D("0.00"), D("0.00"), True)
    assert result.difference == Balance(D("0.00"), None)


def test_equal_debits_and_credits_balance():
    result = check_openings([
        OpeningBalance(D("50000.00"), D("0.00")),
        OpeningBalance(D("300000.00"), D("0.00")),
        OpeningBalance(D("100000.00"), D("0.00")),
        OpeningBalance(D("0.00"), D("450000.00")),
    ])
    assert (result.total_debit, result.total_credit) == (D("450000.00"), D("450000.00"))
    assert result.is_balanced is True


def test_debit_heavy_openings_report_the_difference_on_the_debit_side():
    result = check_openings([OpeningBalance(D("1000.00"), D("0.00")), OpeningBalance(D("0.00"), D("400.50"))])
    assert result.difference == Balance(D("599.50"), "Dr")
    assert result.is_balanced is False


def test_credit_heavy_openings_report_the_difference_on_the_credit_side():
    result = check_openings([OpeningBalance(D("10.00"), D("0.00")), OpeningBalance(D("0.00"), D("10.01"))])
    assert result.difference == Balance(D("0.01"), "Cr")
    assert result.is_balanced is False
