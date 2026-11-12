"""Request/response shapes of the bank statement endpoints (docs/PHASE2_API_CONTRACT.md, "Bank statements")."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class BankFormatIn(BaseModel):
    name: str
    mapping: dict


class BankFormatOut(BaseModel):
    id: UUID
    name: str
    mapping: dict


class FormatCreated(BaseModel):
    format_id: UUID


class PreviewRow(BaseModel):
    row: int
    txn_date: date
    description: str
    reference: str | None
    debit: str
    credit: str
    balance: str | None


class Problem(BaseModel):
    row: int
    message: str


class PreviewOut(BaseModel):
    rows: list[PreviewRow]
    count: int
    opening_balance: str | None
    closing_balance: str | None
    problems: list[Problem]


class StatementCreated(BaseModel):
    statement_id: UUID
    lines: int
    opening_balance: str
    closing_balance: str


class StatementOut(BaseModel):
    id: UUID
    bank_ledger_id: UUID
    file_name: str
    period_from: date
    period_to: date
    opening_balance: str
    closing_balance: str
    line_count: int
    matched_count: int


class StatementLineOut(BaseModel):
    id: UUID
    line_no: int
    txn_date: date
    description: str
    reference: str | None
    debit: str
    credit: str
    balance: str | None
    match_id: UUID | None
