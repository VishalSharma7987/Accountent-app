"""Request and response models. Amounts are STRINGS with 2 decimals everywhere (never JSON numbers)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.schemas_gst_invoices import GstIn
from app.engine.models import Balance

CENTS = Decimal("0.01")
VoucherType = Literal["contra", "payment", "receipt", "sales", "purchase", "credit_note", "debit_note", "journal"]
VoucherStatus = Literal["draft", "approved", "posted", "reversed"]


def money(value: Decimal) -> str:
    return f"{value.quantize(CENTS):.2f}"


class BalanceOut(BaseModel):
    amount: str
    side: str | None  # "Dr" | "Cr" | None (nil)


def balance_out(balance: Balance) -> BalanceOut:
    return BalanceOut(amount=money(balance.amount), side=balance.side)


class OkOut(BaseModel):
    ok: bool = True


# ------------------------------------------------------------------------------------------------ clients


class ClientCreate(BaseModel):
    name: str
    entity_type: str
    business_type: str
    gst_type: str
    fy_start: date
    legal_name: str | None = None
    pan: str | None = None
    state_code: str | None = None
    books_begin_date: date | None = None
    proprietor_name: str | None = None
    partners: list[str] | None = None


class ClientCreated(BaseModel):
    client_id: uuid.UUID
    financial_year_id: uuid.UUID
    ledger_ids: dict[str, uuid.UUID]


class ClientOut(BaseModel):
    id: uuid.UUID
    name: str
    legal_name: str | None
    entity_type: str
    business_type: str
    gst_type: str
    is_active: bool


class FinancialYearOut(BaseModel):
    id: uuid.UUID
    start_date: date
    end_date: date


class ClientDetail(ClientOut):
    pan: str | None
    state_code: str | None
    books_begin_date: date | None
    financial_years: list[FinancialYearOut]


# ------------------------------------------------------------------------------------- groups and ledgers


class GroupNode(BaseModel):
    code: str
    name: str
    nature: str
    report: str
    is_system: bool
    children: list["GroupNode"] = Field(default_factory=list)


class LedgerCreate(BaseModel):
    name: str
    group_code: str


class LedgerCreated(BaseModel):
    ledger_id: uuid.UUID


class LedgerOut(BaseModel):
    id: uuid.UUID
    name: str
    group_code: str
    group_name: str
    group_path: list[str]
    is_active: bool
    balance: BalanceOut


class OpeningIn(BaseModel):
    debit: str | None = None
    credit: str | None = None


class OpeningRowOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str
    debit: str
    credit: str


class OpeningBalancesOut(BaseModel):
    rows: list[OpeningRowOut]
    total_debit: str
    total_credit: str
    difference: BalanceOut
    is_balanced: bool


# ---------------------------------------------------------------------------------------------- vouchers


class AllocationIn(BaseModel):
    """Bill-wise allocation of a party line (Phase 2). kind: new_ref | against_ref | advance | on_account."""

    kind: str
    amount: str | None = None
    bill_ref: str | None = None
    due_date: date | None = None


class AllocationOut(BaseModel):
    kind: str
    amount: str
    bill_ref: str | None
    due_date: date | None  # resolved: bill date + credit days when not given (new_ref only)


class VoucherLineIn(BaseModel):
    ledger_id: uuid.UUID
    debit: str | None = None
    credit: str | None = None
    allocations: list[AllocationIn] = Field(default_factory=list)


class VoucherIn(BaseModel):
    voucher_type: VoucherType
    voucher_date: date
    narration: str | None = None
    reference_no: str | None = None
    party_ledger_id: uuid.UUID | None = None
    duplicate_override_reason: str | None = None
    goods_received_date: date | None = None  # Purchase only (V-15)
    lines: list[VoucherLineIn] = Field(default_factory=list)  # empty in invoice mode (Phase 3: `gst` builds them)
    gst: GstIn | None = None


class VoucherLineOut(BaseModel):
    line_no: int
    ledger_id: uuid.UUID
    ledger_name: str
    debit: str
    credit: str
    allocations: list[AllocationOut] = Field(default_factory=list)
    gst_role: str | None = None  # Phase 3 invoice mode: party | taxable | tax_cgst | ... | round_off
    item_line_no: int | None = None


class VoucherOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    financial_year_id: uuid.UUID
    voucher_type: str
    voucher_number: str | None
    voucher_date: date
    narration: str
    reference_no: str | None
    party_ledger_id: uuid.UUID | None
    status: str
    reverses_voucher_id: uuid.UUID | None
    reversed_by_voucher_id: uuid.UUID | None
    duplicate_override_reason: str | None
    created_by: str
    approved_by: str | None
    posted_by: str | None
    goods_received_date: date | None = None
    lines: list[VoucherLineOut]
    gst: dict | None = None  # Phase 3: header, items and engine figures when the voucher is in invoice mode


class VoucherCreated(BaseModel):
    voucher_id: uuid.UUID


class VoucherSummary(BaseModel):
    id: uuid.UUID
    voucher_number: str | None
    voucher_type: str
    voucher_date: date
    narration: str
    reference_no: str | None
    status: str
    total: str  # total debit


class VoucherList(BaseModel):
    items: list[VoucherSummary]
    total_count: int


class PostedOut(BaseModel):
    voucher_number: str


class ReverseIn(BaseModel):
    reversal_date: date
    reason: str


class ReversedOut(BaseModel):
    reversal_voucher_id: uuid.UUID


# ------------------------------------------------------------------------------------ periods and reports


class PeriodOut(BaseModel):
    id: uuid.UUID
    financial_year_id: uuid.UUID
    start: date
    end: date
    status: str
    locked_at: datetime | None
    locked_by: str | None


class UnlockIn(BaseModel):
    reason: str


class StatementRowOut(BaseModel):
    kind: str
    date: date
    voucher_number: str | None
    voucher_type: str | None
    narration: str | None
    particulars: str
    debit: str
    credit: str
    balance: BalanceOut


class StatementOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str
    from_date: date
    to_date: date
    opening: BalanceOut
    closing: BalanceOut
    total_debit: str
    total_credit: str
    rows: list[StatementRowOut]


class TrialBalanceRowOut(BaseModel):
    group_path: list[str]
    ledger_id: uuid.UUID
    ledger_name: str
    debit: str
    credit: str


class TrialBalanceSectionOut(BaseModel):
    group_code: str
    group_name: str
    debit: str
    credit: str
    rows: list[TrialBalanceRowOut]


class TrialBalanceOut(BaseModel):
    as_on: date
    sections: list[TrialBalanceSectionOut]
    total_debit: str
    total_credit: str
    difference: BalanceOut
    is_balanced: bool


class AuditOut(BaseModel):
    id: int
    actor: str
    action: str
    entity: str
    entity_id: uuid.UUID
    old_data: dict[str, Any] | None
    new_data: dict[str, Any] | None
    created_at: datetime
