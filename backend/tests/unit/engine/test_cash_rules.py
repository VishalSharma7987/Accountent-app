"""C-01: Cash-in-hand can never be negative on any date (end-of-day balances)."""

from datetime import date
from decimal import Decimal

from app.engine.cash_rules import CashMovement, check_cash_never_negative
from app.engine.models import OpeningBalance

D = Decimal
ZERO = OpeningBalance(D("0.00"), D("0.00"))


def mv(on, dr="0", cr="0"):
    return CashMovement(on, D(dr), D(cr))


def test_C01_payment_from_empty_cash_names_first_date_and_amount():
    err = check_cash_never_negative("Cash", ZERO, [], [mv(date(2026, 4, 5), cr="1200")])
    assert err.rule_id == "C-01" and err.line_no is None
    assert err.message.startswith("Cash would be negative on 05-04-2026: Cr 1,200.00")
    assert "Cash" in err.message


def test_C01_opening_cash_covers_payment():
    opening = OpeningBalance(D("1200.00"), D("0.00"))
    assert check_cash_never_negative("Cash", opening, [], [mv(date(2026, 4, 5), cr="1200")]) is None


def test_C01_same_day_receipt_and_payment_net_off():
    new = [mv(date(2026, 4, 5), cr="1000"), mv(date(2026, 4, 5), dr="1000")]
    assert check_cash_never_negative("Cash", ZERO, [], new) is None


def test_C01_same_day_payment_larger_than_receipt_is_refused():
    err = check_cash_never_negative("Cash", ZERO, [mv(date(2026, 4, 5), dr="300")], [mv(date(2026, 4, 5), cr="500")])
    assert "05-04-2026: Cr 200.00" in err.message


def test_C01_backdated_payment_breaking_a_later_day_is_caught():
    opening = OpeningBalance(D("1000.00"), D("0.00"))
    posted = [mv(date(2026, 4, 2), dr="500"), mv(date(2026, 4, 10), cr="1200")]  # 1,500 then 300
    err = check_cash_never_negative("Cash", opening, posted, [mv(date(2026, 4, 5), cr="1000")])
    assert "Cash would be negative on 10-04-2026: Cr 700.00" in err.message


def test_C01_reversal_of_a_receipt_that_funded_later_payments_is_refused():
    posted = [mv(date(2026, 4, 2), dr="5000"), mv(date(2026, 4, 3), cr="4000")]
    err = check_cash_never_negative("Cash", ZERO, posted, [mv(date(2026, 4, 10), cr="5000")])
    assert "10-04-2026: Cr 4,000.00" in err.message


def test_C01_first_negative_date_is_reported_not_a_later_one():
    new = [mv(date(2026, 4, 9), cr="10"), mv(date(2026, 4, 3), cr="30")]
    err = check_cash_never_negative("Cash", ZERO, [], new)
    assert "03-04-2026: Cr 30.00" in err.message
