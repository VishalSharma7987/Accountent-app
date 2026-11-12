"""Response models of the Cash/Bank Book and MSME reports (docs/PHASE2_API_CONTRACT.md). Amounts are strings."""

import uuid
from datetime import date

from pydantic import BaseModel

from app.api.schemas import BalanceOut


class CashBookEntryOut(BaseModel):
    voucher_id: uuid.UUID
    voucher_number: str | None
    voucher_type: str
    narration: str
    counter_ledgers: list[str]
    receipt: str
    payment: str


class CashBookDayOut(BaseModel):
    date: date
    receipts: str
    payments: str
    closing: BalanceOut
    entries: list[CashBookEntryOut]


class CashBookOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str
    from_date: date
    to_date: date
    opening: BalanceOut
    days: list[CashBookDayOut]
    total_receipts: str
    total_payments: str
    closing: BalanceOut


class MsmeItemOut(BaseModel):
    party_ledger_id: uuid.UUID
    party_name: str
    bill_ref: str | None
    bill_date: date
    acceptance_date: date
    acceptance_basis: str  # "goods received date" | "bill date"
    legal_days: int
    legal_due_date: date
    days_overdue: int
    outstanding: str
    rule_status: str  # "pending" | "secondary_verified" | "verified"
    rule_source: str


class MsmeDueOut(BaseModel):
    as_on: date
    rule_status: str  # "pending" | "secondary_verified" | "verified"
    rule_source: str
    items: list[MsmeItemOut]
    total_outstanding: str
