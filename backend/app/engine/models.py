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
