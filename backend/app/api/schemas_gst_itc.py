"""Request bodies of the ITC endpoints (docs/PHASE3_API_CONTRACT.md, package C). Responses are plain JSON built by
`app/api/gst_itc.py` with every amount as a 2-decimal string."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_document_held: bool
    goods_services_received: bool
    received_date: date | None = None
    supplier_tax_paid: str | None = None  # only "manual_confirmed" (needs evidence_note); 2B results come from the 2B apply
    evidence_note: str | None = None


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class TagBlockedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_key: str
    note: str


class ReversalsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: uuid.UUID
    as_on: date
    itc_entry_ids: list[uuid.UUID] | None = None


class ReclaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_on: date


def jsonable(value: Any) -> Any:
    """Decimals become 2-decimal strings (never floats); the fraction of an unpaid share keeps its 4 decimals."""
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        return f"{value:.4f}" if exponent == -4 else f"{value:.2f}"
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
