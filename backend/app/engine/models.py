"""Plain data the accounting engine works on. No database, web or AI imports (CLAUDE.md section 2.6).

Ids are opaque (str, UUID, ...): the engine only compares them for equality.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# An amount "as entered": text from a cell, an int, a Decimal, or nothing (blank = zero).
# Floats are accepted here only so that validation can reject them (V-03).
RawAmount = str | int | Decimal | float | None


@dataclass(frozen=True)
class Group:
    code: str
    name: str
    nature: str  # asset | liability | income | expense
    report: str  # balance_sheet | trading | profit_loss
    parent_code: str | None = None


@dataclass(frozen=True)
class Ledger:
    id: object
    name: str
    group_code: str
    is_active: bool
    client_id: object


@dataclass(frozen=True)
class VoucherLine:
    ledger_id: object
    debit: RawAmount = None
    credit: RawAmount = None


@dataclass(frozen=True)
class VoucherDraft:
    client_id: object
    voucher_type: str
    voucher_date: date
    narration: str | None
    reference_no: str | None
    party_ledger_id: object | None
    lines: tuple[VoucherLine, ...]
    duplicate_override_reason: str | None = None  # the user's reason for saving a possible duplicate (V-10)


@dataclass(frozen=True)
class PeriodInfo:
    """The period a date falls into, as the caller found it."""

    start: date
    end: date
    status: str  # open | locked


@dataclass(frozen=True)
class ValidationError:
    rule_id: str  # V-01 .. V-14
    message: str  # plain accountant language
    line_no: int | None = None  # 1-based line of the voucher, None for voucher-level errors


@dataclass(frozen=True)
class OpeningBalance:
    """A ledger's opening balance for a financial year: at most one side is above zero."""

    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class Balance:
    """A balance as shown on a report: a positive amount and its side. A nil balance has side None."""

    amount: Decimal
    side: str | None  # "Dr" | "Cr" | None

    @staticmethod
    def from_signed(value: Decimal) -> "Balance":
        """Internal convention: debit positive, credit negative (CLAUDE.md section 5)."""
        cents = Decimal("0.01")
        if value > 0:
            return Balance(value.quantize(cents), "Dr")
        if value < 0:
            return Balance((-value).quantize(cents), "Cr")
        return Balance(Decimal("0.00"), None)

    @property
    def signed(self) -> Decimal:
        if self.side == "Dr":
            return self.amount
        if self.side == "Cr":
            return -self.amount
        return Decimal("0.00")


@dataclass(frozen=True)
class PostedLine:
    """One line of a voucher as stored. Reports count only status 'posted' and 'reversed'."""

    voucher_id: object
    voucher_number: str | None
    voucher_type: str
    voucher_date: date
    narration: str
    status: str  # draft | approved | posted | reversed
    line_no: int
    ledger_id: object
    ledger_name: str
    debit: Decimal
    credit: Decimal
