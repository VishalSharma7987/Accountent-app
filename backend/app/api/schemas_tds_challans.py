"""Request bodies of the challan endpoints (docs/PHASE4_API_CONTRACT.md, package C). Amounts are text ("1000.00"), never numbers."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class AllocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: uuid.UUID
    amount: str


class ChallanFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    financial_year_id: uuid.UUID
    quarter: int
    bsr_code: str
    deposit_date: date
    challan_serial_no: str
    tax_amount: str
    interest_amount: str | None = None
    fee_amount: str | None = None
    other_amount: str | None = None
    payment_voucher_id: uuid.UUID | None = None
    note: str | None = None


class ChallanIn(ChallanFields):
    kind: str
    allocations: list[AllocationIn] | None = None


class AllocationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allocations: list[AllocationIn]


class AutoMatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    financial_year_id: uuid.UUID
    quarter: int | None = None
    kind: str | None = None


def jsonable(value: Any) -> Any:
    """Decimals become 2-decimal strings (never floats); ids and dates become text."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
