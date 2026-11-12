"""Request and response models of the reconciliation endpoints (docs/PHASE2_API_CONTRACT.md). Amounts are strings."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.api.schemas import BalanceOut, balance_out, money
from app.engine.brs import BrsItem, BrsResult
from app.engine.reconcile import DEPOSIT, BankLine, BookItem, Suggestion


class AutoMatchIn(BaseModel):
    as_on: date
    date_window_days: int | None = Field(default=None, ge=0, le=60)


class AutoMatchOut(BaseModel):
    matched_groups: int
    matched_bank_lines: int
    matched_book_items: int
    suggestions_left: int


class MatchIn(BaseModel):
    bank_line_ids: list[uuid.UUID] = []
    voucher_line_ids: list[uuid.UUID] = []
    opening_item_ids: list[uuid.UUID] = []
    note: str | None = None


class MatchCreated(BaseModel):
    match_id: uuid.UUID


class BankLineOut(BaseModel):
    line_id: uuid.UUID
    txn_date: date
    description: str
    reference: str | None
    debit: str  # money out (the bank's wording)
    credit: str  # money in


class BookItemOut(BaseModel):
    voucher_line_id: uuid.UUID | None
    opening_item_id: uuid.UUID | None
    date: date
    voucher_number: str | None
    narration: str
    reference_no: str | None
    debit: str  # Dr to the bank ledger = deposit
    credit: str  # Cr = payment


class SuggestionOut(BaseModel):
    bank_line_ids: list[uuid.UUID]
    book_item_ids: list[uuid.UUID]
    reason: str


class UnmatchedOut(BaseModel):
    bank: list[BankLineOut]
    book: list[BookItemOut]
    suggestions: list[SuggestionOut]


class MatchOut(BaseModel):
    match_id: uuid.UUID
    method: str
    note: str | None
    created_by: str
    created_at: datetime
    bank_items: list[BankLineOut]
    book_items: list[BookItemOut]
    total_bank: str  # net money in: deposits - payments (signed)
    total_book: str  # net money in: Dr - Cr (signed); equals total_bank


class MatchesOut(BaseModel):
    matches: list[MatchOut]


ZERO = "0.00"


def bank_out(x: BankLine) -> BankLineOut:
    deposit = x.direction == DEPOSIT
    return BankLineOut(line_id=x.id, txn_date=x.date, description=x.description, reference=x.reference,
                       debit=ZERO if deposit else money(x.amount), credit=money(x.amount) if deposit else ZERO)


def book_out(x: BookItem) -> BookItemOut:
    deposit = x.direction == DEPOSIT
    voucher = x.kind == "voucher_line"
    return BookItemOut(
        voucher_line_id=x.id if voucher else None, opening_item_id=None if voucher else x.id, date=x.date,
        voucher_number=x.voucher_number, narration=x.narration, reference_no=x.reference_no,
        debit=money(x.amount) if deposit else ZERO, credit=ZERO if deposit else money(x.amount),
    )


def suggestion_out(x: Suggestion) -> SuggestionOut:
    return SuggestionOut(bank_line_ids=list(x.bank_line_ids), book_item_ids=list(x.book_item_ids), reason=x.reason)


class BrsItemOut(BaseModel):
    date: date
    reference: str | None
    description: str
    amount: str


class BrsOut(BaseModel):
    as_on: date
    balance_per_books: BalanceOut
    issued_not_presented: list[BrsItemOut]
    deposited_not_cleared: list[BrsItemOut]
    bank_only_credits: list[BrsItemOut]
    bank_only_debits: list[BrsItemOut]
    computed_bank_balance: BalanceOut
    balance_per_bank: BalanceOut
    difference: BalanceOut
    ties: bool


def _item(x: BrsItem) -> BrsItemOut:
    return BrsItemOut(date=x.date, reference=x.reference, description=x.description, amount=money(x.amount))


def brs_out(r: BrsResult) -> BrsOut:
    from app.engine.models import Balance

    return BrsOut(
        as_on=r.as_on, balance_per_books=balance_out(Balance.from_signed(r.balance_per_books)),
        issued_not_presented=[_item(x) for x in r.issued_not_presented],
        deposited_not_cleared=[_item(x) for x in r.deposited_not_cleared],
        bank_only_credits=[_item(x) for x in r.bank_only_credits],
        bank_only_debits=[_item(x) for x in r.bank_only_debits],
        computed_bank_balance=balance_out(Balance.from_signed(r.computed_bank_balance)),
        balance_per_bank=balance_out(Balance.from_signed(r.balance_per_bank)),
        difference=balance_out(Balance.from_signed(r.difference)), ties=r.ties,
    )


class OpeningItemIn(BaseModel):
    kind: str
    reference: str | None = None
    item_date: date
    amount: str


class OpeningItemOut(OpeningItemIn):
    id: uuid.UUID | None = None


class OpeningItemsIn(BaseModel):
    items: list[OpeningItemIn]


class OpeningItemsOut(BaseModel):
    items: list[OpeningItemOut]


class DraftItemIn(BaseModel):
    bank_line_id: uuid.UUID
    counter_ledger_id: uuid.UUID


class DraftsIn(BaseModel):
    items: list[DraftItemIn]


class DraftCreated(BaseModel):
    bank_line_id: uuid.UUID
    voucher_id: uuid.UUID


class DraftsOut(BaseModel):
    created: list[DraftCreated]


class BankOnlySuggestionOut(BaseModel):
    bank_line_id: uuid.UUID
    txn_date: date
    description: str
    amount: str
    direction: str  # deposit | payment
    counter_ledger_id: uuid.UUID | None
    counter_ledger_name: str | None
    reason: str


def match_out(g) -> MatchOut:
    return MatchOut(
        match_id=g.match_id, method=g.method, note=g.note, created_by=g.created_by, created_at=g.created_at,
        bank_items=[bank_out(x) for x in g.bank_items], book_items=[book_out(x) for x in g.book_items],
        total_bank=money(g.total_bank), total_book=money(g.total_book),
    )
