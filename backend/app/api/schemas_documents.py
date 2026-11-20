"""Request / response shapes of the document endpoints (docs/PHASE7_API_CONTRACT.md, package A)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DocumentCreated(BaseModel):
    id: UUID
    sha256: str
    size_bytes: int
    content_type: str
    doc_type: str
    status: str
    page_count: int | None


class DocumentRow(BaseModel):
    id: UUID
    doc_type: str
    original_filename: str
    size_bytes: int
    status: str
    uploaded_by: str
    uploaded_at: datetime
    linked_voucher_ids: list[UUID]


class TextSummary(BaseModel):
    page_no: int
    method: str
    engine_version: str
    mean_confidence: str | None
    char_count: int


class ExtractionSummary(BaseModel):
    id: UUID
    version: int
    source: str
    status: str
    created_at: datetime
    superseded: bool


class DocumentOut(BaseModel):
    id: UUID
    doc_type: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    status: str
    status_note: str | None
    uploaded_by: str
    uploaded_at: datetime
    financial_year_id: UUID | None
    linked_voucher_ids: list[UUID]
    texts: list[TextSummary]
    extractions: list[ExtractionSummary]
    queue_item_id: UUID | None


class PageTextOut(BaseModel):
    page_no: int
    method: str
    text: str
    blocks: list[dict] | None


class ReadTextIn(BaseModel):
    method: Literal["auto", "pdf_text", "tesseract", "paddleocr"] = "auto"


class ReadPage(BaseModel):
    page_no: int
    method: str
    char_count: int
    mean_confidence: str | None


class ReadTextOut(BaseModel):
    pages: list[ReadPage]


class LinkIn(BaseModel):
    voucher_id: UUID
    link_kind: Literal["supporting"] = "supporting"


class LinkCreated(BaseModel):
    id: UUID


def confidence(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.4f}"
