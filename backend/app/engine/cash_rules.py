"""C-01: Cash-in-hand can never be negative on any date.

The balance is checked at the END of each day (a receipt and a payment of the same day net off). The check looks
at every date from the earliest date the new voucher touches onwards, so a backdated payment (or the reversal of a
receipt) that makes a LATER day negative is caught. Pure Decimal arithmetic, no database.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.models import OpeningBalance, ValidationError
from app.engine.money import format_inr


@dataclass(frozen=True)
class CashMovement:
    """One line on a cash ledger: its date and its debit / credit amounts."""

    on: date
    debit: Decimal
    credit: Decimal


def check_cash_never_negative(
    ledger_name: str,
    opening: OpeningBalance,
    posted: Sequence[CashMovement],
    new: Sequence[CashMovement],
) -> ValidationError | None:
    """The C-01 error for the first date whose end-of-day balance would be credit, or None.

    opening  the ledger's opening balance for the financial year
    posted   the ledger's lines of posted/reversed vouchers of the financial year (all dates)
    new      the lines of the voucher being approved/posted/reversed on this ledger
    """
    if not new:
        return None
    by_day: dict[date, Decimal] = {}
    for move in (*posted, *new):
        by_day[move.on] = by_day.get(move.on, Decimal("0.00")) + move.debit - move.credit
    first_new = min(m.on for m in new)
    running = opening.debit - opening.credit
    for on in sorted(by_day):
        running += by_day[on]
        if running < 0 and on >= first_new:
            return ValidationError(
                "C-01",
                f"Cash would be negative on {on.strftime('%d-%m-%Y')}: Cr {format_inr(-running)} in '{ledger_name}' "
                "after this voucher. Cash-in-hand cannot go below zero on any date. Record the cash receipt or "
                "opening cash first, or use a Bank ledger.",
            )
    return None
