"""Cash Book / Bank Book of one Cash-in-hand or Bank ledger: day by day receipts (Dr), payments (Cr) and closing
balance. Pure Decimal arithmetic, no database. Same conventions as engine/reports.py: only vouchers with status
'posted' or 'reversed' count (a reversed voucher and its reversal voucher cancel out); debit positive internally.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.models import Balance, Ledger, OpeningBalance, PostedLine
from app.engine.reports import COUNTED_STATUSES

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CashBookEntry:
    voucher_id: object
    voucher_number: str | None
    voucher_type: str
    narration: str
    counter_ledgers: tuple[str, ...]  # the other ledgers of the same voucher, in line order
    receipt: Decimal  # debit to the book ledger
    payment: Decimal  # credit to the book ledger


@dataclass(frozen=True)
class CashBookDay:
    date: date
    receipts: Decimal
    payments: Decimal
    closing: Balance  # balance at the end of the day
    entries: tuple[CashBookEntry, ...]


@dataclass(frozen=True)
class CashBook:
    ledger_id: object
    ledger_name: str
    from_date: date
    to_date: date
    opening: Balance  # on from_date, before the period's entries
    days: tuple[CashBookDay, ...]  # only days that have entries
    total_receipts: Decimal
    total_payments: Decimal
    closing: Balance


def cash_book(
    ledger: Ledger, opening: OpeningBalance, lines: Sequence[PostedLine], from_date: date, to_date: date
) -> CashBook:
    """Book of `ledger` from from_date to to_date (inclusive).

    opening  the ledger's opening balance for the financial year
    lines    every line of the vouchers that touch the ledger (other lines give the counter ledger names);
             entries dated before from_date are folded into the opening balance. Entries of one day keep the
             order of `lines`.
    """
    if to_date < from_date:
        raise ValueError(f"to_date {to_date} is before from_date {from_date}")
    counted = [x for x in lines if x.status in COUNTED_STATUSES]
    counters: dict[object, list[str]] = {}
    for line in sorted((x for x in counted if x.ledger_id != ledger.id), key=lambda x: x.line_no):
        names = counters.setdefault(line.voucher_id, [])
        if line.ledger_name not in names:
            names.append(line.ledger_name)

    own = [x for x in counted if x.ledger_id == ledger.id]
    running = opening.debit - opening.credit + sum((x.debit - x.credit for x in own if x.voucher_date < from_date), ZERO)
    opening_balance = Balance.from_signed(running)

    in_period = sorted((x for x in own if from_date <= x.voucher_date <= to_date), key=lambda x: x.voucher_date)
    days: list[CashBookDay] = []
    total_receipts = total_payments = ZERO
    index = 0
    while index < len(in_period):
        on = in_period[index].voucher_date
        entries: list[CashBookEntry] = []
        receipts = payments = ZERO
        while index < len(in_period) and in_period[index].voucher_date == on:
            line = in_period[index]
            entries.append(CashBookEntry(
                line.voucher_id, line.voucher_number, line.voucher_type, line.narration,
                tuple(counters.get(line.voucher_id, ())), line.debit.quantize(CENTS), line.credit.quantize(CENTS),
            ))
            receipts += line.debit
            payments += line.credit
            index += 1
        running += receipts - payments
        total_receipts += receipts
        total_payments += payments
        days.append(CashBookDay(on, receipts.quantize(CENTS), payments.quantize(CENTS), Balance.from_signed(running), tuple(entries)))

    return CashBook(
        ledger.id, ledger.name, from_date, to_date, opening_balance, tuple(days),
        total_receipts.quantize(CENTS), total_payments.quantize(CENTS), Balance.from_signed(running),
    )
