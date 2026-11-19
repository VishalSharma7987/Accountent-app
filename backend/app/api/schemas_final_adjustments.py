"""Request and response models of the Phase 6 package A API (docs/PHASE6_API_CONTRACT.md). Amounts are 2-decimal strings, rates 4-decimal strings."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.api.schemas import money
from app.services.final_adjustments import AdjustmentRequest

FOUR = Decimal("0.0001")


def pct(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value).quantize(FOUR):.4f}"


def amt(value: Decimal | None) -> str | None:
    return None if value is None else money(Decimal(value))


class RoleRow(BaseModel):
    role: str
    ledger_id: uuid.UUID
    ledger_name: str


class SetupRoleRow(RoleRow):
    created: bool


class SetupIn(BaseModel):
    financial_year_id: uuid.UUID


class SetupOut(BaseModel):
    roles: list[SetupRoleRow]


class RoleIn(BaseModel):
    ledger_id: uuid.UUID


class PartnerOut(BaseModel):
    id: uuid.UUID
    name: str
    capital_ledger_id: uuid.UUID
    current_ledger_id: uuid.UUID | None
    is_active: bool


class PartnerIn(BaseModel):
    name: str
    capital_ledger_id: uuid.UUID
    current_ledger_id: uuid.UUID | None = None


class PartnerUpdate(BaseModel):
    name: str | None = None
    capital_ledger_id: uuid.UUID | None = None
    current_ledger_id: uuid.UUID | None = None
    is_active: bool | None = None


class PartnerCreated(BaseModel):
    id: uuid.UUID


class TermsRowIn(BaseModel):
    partner_id: uuid.UUID
    profit_share_percent: Decimal
    interest_on_capital_rate: Decimal | None = None
    interest_on_drawings_rate: Decimal | None = None
    remuneration_annual: Decimal | None = None
    deed_reference: str | None = None


class TermsIn(BaseModel):
    rows: list[TermsRowIn]


class TermsRowOut(BaseModel):
    partner_id: uuid.UUID
    name: str
    profit_share_percent: str
    interest_on_capital_rate: str | None
    interest_on_drawings_rate: str | None
    remuneration_annual: str | None
    deed_reference: str | None


class TermsOut(BaseModel):
    rows: list[TermsRowOut]
    share_total: str
    share_ok: bool


def terms_out(data: dict) -> TermsOut:
    return TermsOut(
        rows=[TermsRowOut(partner_id=r["partner_id"], name=r["name"], profit_share_percent=pct(r["profit_share_percent"]),
                          interest_on_capital_rate=pct(r["interest_on_capital_rate"]), interest_on_drawings_rate=pct(r["interest_on_drawings_rate"]),
                          remuneration_annual=amt(r["remuneration_annual"]), deed_reference=r["deed_reference"]) for r in data["rows"]],
        share_total=pct(data["share_total"]), share_ok=data["share_ok"])


class AdjustmentIn(BaseModel):
    adj_type: str
    as_on_date: date
    basis_note: str
    amount: Decimal | None = None
    debit_ledger_id: uuid.UUID | None = None
    credit_ledger_id: uuid.UUID | None = None
    party_ledger_id: uuid.UUID | None = None
    rate_percent: Decimal | None = None
    partner_id: uuid.UUID | None = None
    months: int | None = None
    auto_reverse_on: date | None = None
    duplicate_reason: str | None = None

    def to_request(self) -> AdjustmentRequest:
        return AdjustmentRequest(**self.model_dump())


class LineOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str
    debit: str
    credit: str


def lines_out(lines: list[dict]) -> list[LineOut]:
    return [LineOut(ledger_id=x["ledger_id"], ledger_name=x["ledger_name"], debit=money(x["debit"]), credit=money(x["credit"])) for x in lines]


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str


class PreviewOut(BaseModel):
    amount: str
    lines: list[LineOut]
    narration: str
    params: dict
    findings: list[FindingOut]


class AdjustmentCreated(BaseModel):
    adjustment_id: uuid.UUID
    voucher_id: uuid.UUID
    auto_reverse_voucher_id: uuid.UUID | None
    amount: str
    lines: list[LineOut]


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    adj_type: str
    as_on_date: date
    amount: str
    basis_note: str
    params: dict
    voucher_id: uuid.UUID
    voucher_status: str
    voucher_number: str | None
    auto_reverse_voucher_id: uuid.UUID | None
