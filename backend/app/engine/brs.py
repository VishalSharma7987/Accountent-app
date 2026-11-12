"""Bank Reconciliation Statement as on a date (rule R-05). Pure Python: no database, web or AI.

Signs: balance per books is signed, debit positive (Dr = money at the bank). Balance per bank is the statement's own
balance: opening + deposits - withdrawals, positive = money in the account. Both are therefore on the same scale and
    computed bank balance = books + issued not presented - deposited not cleared
                                  + bank-only credits - bank-only debits
must equal the balance per bank; otherwise the difference (per bank - computed) is shown and ties is False.

A match is "settled" on the date D when every bank line and every book item in it is dated on or before D.
Book items dated on or before D that are not in a settled match are the reconciling items
(Cr = issued not presented, Dr = deposited not cleared); bank lines dated on or before D that are not in a settled
match are bank-only (credit / debit). Items dated after D are ignored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.reconcile import DEPOSIT, BankLine, BookItem, signed_total

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Match:
    bank_ids: tuple
    book_ids: tuple


@dataclass(frozen=True)
class BrsItem:
    date: date
    reference: str | None
    description: str
    amount: Decimal  # positive


@dataclass(frozen=True)
class BrsResult:
    as_on: date
    balance_per_books: Decimal  # signed, Dr positive
    issued_not_presented: list[BrsItem]
    deposited_not_cleared: list[BrsItem]
    bank_only_credits: list[BrsItem]
    bank_only_debits: list[BrsItem]
    computed_bank_balance: Decimal
    balance_per_bank: Decimal
    difference: Decimal  # balance per bank - computed
    ties: bool


def balance_per_books(opening: Decimal, book_items: Sequence[BookItem], as_on: date) -> Decimal:
    """Ledger opening (signed) + voucher lines dated on or before as_on. Opening items are already inside the
    opening balance and are not added again."""
    return opening + signed_total(x for x in book_items if x.kind == "voucher_line" and x.date <= as_on)


def balance_per_bank(opening: Decimal, bank_lines: Sequence[BankLine], as_on: date) -> Decimal:
    """Statement opening balance + deposits - withdrawals of the lines dated on or before as_on."""
    return opening + signed_total(x for x in bank_lines if x.date <= as_on)


def _settled(as_on: date, book_items: Sequence[BookItem], bank_lines: Sequence[BankLine], matches: Sequence[Match]) -> set:
    book_date = {x.id: x.date for x in book_items}
    bank_date = {x.id: x.date for x in bank_lines}
    done: set = set()
    for m in matches:
        dates = [bank_date[i] for i in m.bank_ids if i in bank_date] + [book_date[i] for i in m.book_ids if i in book_date]
        if all(d <= as_on for d in dates):
            done.update(m.bank_ids)
            done.update(m.book_ids)
    return done


def brs(
    as_on: date,
    books_balance: Decimal,
    book_items: Sequence[BookItem],
    bank_lines: Sequence[BankLine],
    matches: Sequence[Match],
    bank_balance: Decimal,
) -> BrsResult:
    settled = _settled(as_on, book_items, bank_lines, matches)

    def book_row(x: BookItem) -> BrsItem:
        return BrsItem(x.date, x.reference_no, x.narration, x.amount)

    def bank_row(x: BankLine) -> BrsItem:
        return BrsItem(x.date, x.reference, x.description, x.amount)

    def rows(items, direction, convert):
        picked = [x for x in items if x.date <= as_on and x.id not in settled and x.direction == direction]
        return [convert(x) for x in sorted(picked, key=lambda x: (x.date, str(x.id)))]

    inp = rows(book_items, "payment", book_row)
    dnc = rows(book_items, DEPOSIT, book_row)
    credits = rows(bank_lines, DEPOSIT, bank_row)
    debits = rows(bank_lines, "payment", bank_row)
    total = lambda xs: sum((x.amount for x in xs), ZERO)
    computed = books_balance + total(inp) - total(dnc) + total(credits) - total(debits)
    difference = bank_balance - computed
    return BrsResult(as_on, books_balance, inp, dnc, credits, debits, computed, bank_balance, difference, difference == 0)
