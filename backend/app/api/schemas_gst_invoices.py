"""Request / response shapes of invoice-mode vouchers (Phase 3, package B). See docs/PHASE3_API_CONTRACT.md.

Amounts, quantities and rates travel as text (never floats). Tax amounts are NOT accepted (G-14): unknown keys on an
item are kept (extra="allow") only so the API can name them in a G-14 error instead of silently dropping them.
"""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class GstAllocationIn(BaseModel):
    kind: str
    amount: str | None = None
    bill_ref: str | None = None
    due_date: date | None = None


class StockIn(BaseModel):
    """Optional stock block of an item line (Phase 5): another godown than the item's default, and for a Credit / Debit Note the
    sale / purchase movement the goods came back from / went back to. Without it a Credit / Debit Note is value-only."""

    godown_id: uuid.UUID | None = None
    original_movement_id: uuid.UUID | None = None


class GstItemIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_id: uuid.UUID | None = None
    description: str
    hsn_sac: str
    uqc: str | None = None
    quantity: str
    unit_rate: str
    discount: str = "0.00"  # an amount, not a percentage
    ledger_id: uuid.UUID
    rcm_category_key: str | None = None
    itc_category_key: str | None = None
    itc_exception_claimed: bool = False
    itc_exception_note: str | None = None
    stock: StockIn | None = None


class GstIn(BaseModel):
    gst_registration_id: uuid.UUID
    document_kind: str
    supply_category: str
    place_of_supply: str
    invoice_date: date
    counterparty_gstin: str | None = None
    original_invoice_no: str | None = None
    original_invoice_date: date | None = None
    note_reason: str | None = None
    items: list[GstItemIn] = Field(default_factory=list)
    allocations: list[GstAllocationIn] = Field(default_factory=list)  # optional bill-wise allocation of the party line


class GstPreviewLine(BaseModel):
    ledger_id: str
    ledger_name: str
    debit: str
    credit: str
    gst_role: str
    item_line_no: int | None


class GstPreviewError(BaseModel):
    rule_id: str
    message: str
    line_no: int | None


class GstPreviewOut(BaseModel):
    lines: list[GstPreviewLine]
    gst: dict | None
    errors: list[GstPreviewError]
