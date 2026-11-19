"""Request bodies of the fixed asset / depreciation endpoints (docs/PHASE6_API_CONTRACT.md, package B).
Amounts are text ("1000.00"), never numbers; the service validates them (at most 2 decimals, rejected not rounded)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_no: str
    name: str
    asset_ledger_id: uuid.UUID
    accumulated_dep_ledger_id: uuid.UUID | None = None
    is_depreciable: bool = True
    it_block_key: str | None = None
    sched2_class_key: str | None = None
    useful_life_years: str | None = None
    life_override_reason: str | None = None
    residual_value: str | None = None
    book_method: str | None = None


class AssetUpdate(AssetIn):
    is_active: bool | None = None


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    event_date: date
    put_to_use_date: date | None = None
    amount: str | None = None
    accumulated_dep_bf: str | None = None
    voucher_id: uuid.UUID | None = None
    note: str | None = None


class FyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    financial_year_id: uuid.UUID


class ItOpeningRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_key: str
    opening_wdv: str


class ItOpeningsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ItOpeningRow]


class ItFinalizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    financial_year_id: uuid.UUID
    acknowledged_flags: list[str] | None = None


def jsonable(value: Any) -> Any:
    """Decimals become 2-decimal strings (never floats); ids and dates become text. Rates are formatted by the service."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
