"""Step 2.7: Bank Reconciliation Statement (R-05). Pure engine; every number below was worked out by hand.

Convention: balance per books is signed (Dr positive = money at the bank); balance per bank is the statement balance
(opening + deposits - withdrawals; positive = money in the account). computed bank balance =
books + issued-not-presented - deposited-not-cleared + bank-only credits - bank-only debits.
"""

from datetime import date
from decimal import Decimal

from app.engine.brs import Match, balance_per_bank, balance_per_books, brs
from app.engine.reconcile import BankLine, BookItem

AS_ON = date(2026, 4, 30)


def D(x: str) -> Decimal:
    return Decimal(x)


def bank(i, on, amount, direction, ref=None, desc=""):
    return BankLine(i, on, D(amount), direction, ref, desc)


def book(i, on, amount, direction, ref=None, narration="", kind="voucher_line"):
    return BookItem(i, on, D(amount), direction, ref, narration, kind)


def test_R05_all_matched_ties():
    # opening 1,00,000.00; deposit 30,000.00 (10-04) and cheque 15,000.00 (12-04, cleared 13-04)
    books = [book("K1", date(2026, 4, 10), "30000.00", "deposit"), book("K2", date(2026, 4, 12), "15000.00", "payment")]
    lines = [bank("B1", date(2026, 4, 10), "30000.00", "deposit"), bank("B2", date(2026, 4, 13), "15000.00", "payment")]
    in_books = balance_per_books(D("100000.00"), books, AS_ON)
    in_bank = balance_per_bank(D("100000.00"), lines, AS_ON)
    assert in_books == D("115000.00") and in_bank == D("115000.00")
    r = brs(AS_ON, in_books, books, lines, [Match(("B1",), ("K1",)), Match(("B2",), ("K2",))], in_bank)
    assert r.issued_not_presented == [] and r.deposited_not_cleared == []
    assert r.bank_only_credits == [] and r.bank_only_debits == []
    assert r.computed_bank_balance == D("115000.00")
    assert r.difference == D("0.00") and r.ties is True


def scenario_two():
    books = [
        book("K1", date(2026, 4, 28), "30000.00", "deposit", narration="Deposit of cheques"),  # cleared 02-05
        book("K2", date(2026, 4, 12), "15000.00", "payment", ref="000123", narration="Rent cheque"),  # not presented
        book("K3", date(2026, 4, 15), "5000.00", "payment"),  # cleared 16-04
        book("K4", date(2026, 4, 5), "20000.00", "deposit"),  # cleared 10-04
    ]
    lines = [
        bank("B1", date(2026, 4, 10), "20000.00", "deposit"),
        bank("B2", date(2026, 4, 16), "5000.00", "payment"),
        bank("B3", date(2026, 4, 30), "350.00", "payment", desc="SMS CHARGES"),  # only in the bank
        bank("B4", date(2026, 5, 2), "30000.00", "deposit"),  # after the date
    ]
    matches = [Match(("B1",), ("K4",)), Match(("B2",), ("K3",)), Match(("B4",), ("K1",))]
    return books, lines, matches


def test_R05_cheque_not_presented_deposit_not_cleared_and_bank_charge_ties():
    books, lines, matches = scenario_two()
    in_books = balance_per_books(D("100000.00"), books, AS_ON)
    in_bank = balance_per_bank(D("100000.00"), lines, AS_ON)
    # books: 1,00,000 + 30,000 - 15,000 - 5,000 + 20,000 = 1,30,000 ; bank: 1,00,000 + 20,000 - 5,000 - 350 = 1,14,650
    assert in_books == D("130000.00")
    assert in_bank == D("114650.00")
    r = brs(AS_ON, in_books, books, lines, matches, in_bank)
    assert [(i.date, i.reference, i.amount) for i in r.issued_not_presented] == [(date(2026, 4, 12), "000123", D("15000.00"))]
    assert [(i.date, i.amount) for i in r.deposited_not_cleared] == [(date(2026, 4, 28), D("30000.00"))]
    assert r.bank_only_credits == []
    assert [(i.description, i.amount) for i in r.bank_only_debits] == [("SMS CHARGES", D("350.00"))]
    # 1,30,000 + 15,000 - 30,000 + 0 - 350 = 1,14,650
    assert r.computed_bank_balance == D("114650.00")
    assert r.difference == D("0.00") and r.ties is True


def test_R05_difference_that_does_not_tie_is_shown():
    books, lines, matches = scenario_two()
    r = brs(AS_ON, D("130000.00"), books, lines, matches, D("114000.00"))
    assert r.computed_bank_balance == D("114650.00")
    assert r.balance_per_bank == D("114000.00")
    assert r.difference == D("-650.00")  # balance per bank - computed
    assert r.ties is False


def test_R05_bank_credit_only_in_bank_and_bank_line_matched_to_a_later_voucher():
    # books: opening 10,000.00, no entries up to 30-04; a payment voucher of 700.00 is dated 02-05 but the bank paid it 30-04
    books = [book("K1", date(2026, 5, 2), "700.00", "payment")]
    lines = [bank("B1", date(2026, 4, 30), "700.00", "payment"), bank("B2", date(2026, 4, 29), "1200.00", "deposit", desc="INT.PD")]
    in_books = balance_per_books(D("10000.00"), books, AS_ON)
    in_bank = balance_per_bank(D("10000.00"), lines, AS_ON)
    assert in_books == D("10000.00") and in_bank == D("10500.00")
    r = brs(AS_ON, in_books, books, lines, [Match(("B1",), ("K1",))], in_bank)
    assert [i.amount for i in r.bank_only_credits] == [D("1200.00")]
    assert [i.amount for i in r.bank_only_debits] == [D("700.00")]
    assert r.issued_not_presented == [] and r.deposited_not_cleared == []  # the 02-05 voucher is after the date
    # 10,000 + 1,200 - 700 = 10,500
    assert r.computed_bank_balance == D("10500.00") and r.ties is True


def test_R05_overdraft_books_balance_credit():
    # books: opening 5,000.00 Cr (-5,000.00), cheque 2,000.00 issued 10-04 not presented -> bank shows -5,000.00
    books = [book("K1", date(2026, 4, 10), "2000.00", "payment")]
    in_books = balance_per_books(D("-5000.00"), books, AS_ON)
    assert in_books == D("-7000.00")
    r = brs(AS_ON, in_books, books, [], [], D("-5000.00"))
    assert r.computed_bank_balance == D("-5000.00") and r.ties is True


def test_R05_opening_item_issued_before_the_year_is_not_presented():
    books = [book("O1", date(2026, 3, 28), "4000.00", "payment", ref="000900", kind="opening_item")]
    # the ledger opening (60,000.00) already includes the cheque; opening items are not added to the balance again
    in_books = balance_per_books(D("60000.00"), books, AS_ON)
    assert in_books == D("60000.00")
    r = brs(AS_ON, in_books, books, [], [], D("64000.00"))
    assert [i.amount for i in r.issued_not_presented] == [D("4000.00")]
    assert r.ties is True


def test_R05_matched_to_bank_line_after_the_date_is_still_in_transit_and_items_after_the_date_are_ignored():
    books = [book("K1", date(2026, 4, 20), "800.00", "deposit"), book("K2", date(2026, 5, 3), "900.00", "deposit")]
    lines = [bank("B1", date(2026, 5, 1), "800.00", "deposit")]
    in_books = balance_per_books(D("0.00"), books, AS_ON)
    in_bank = balance_per_bank(D("0.00"), lines, AS_ON)
    assert in_books == D("800.00") and in_bank == D("0.00")
    r = brs(AS_ON, in_books, books, lines, [Match(("B1",), ("K1",))], in_bank)
    assert [i.amount for i in r.deposited_not_cleared] == [D("800.00")]
    assert r.computed_bank_balance == D("0.00") and r.ties is True
