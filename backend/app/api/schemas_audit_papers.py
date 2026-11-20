"""Request and response models of audit working papers and sampling (Phase 8, package E). Amounts are 2-decimal STRINGS."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.api.schemas import money


def amount_out(value: Any) -> str | None:
    return None if value is None else money(value)


class PaperIn(BaseModel):
    run_id: uuid.UUID
    check_id: str


class PaperCreatedOut(BaseModel):
    id: uuid.UUID
    status: str
    population_count: int
    population_digest: str | None
    items: int


class SampleOut(BaseModel):
    method: str
    seed: int | None
    params: dict[str, Any]
    ids: list[str]


class PaperBaseOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    check_id: str
    status: str
    population_count: int
    population_digest: str | None
    population_amount: str | None
    sample_method: str
    created_by: str
    created_at: datetime
    signed_off_by: str | None
    signed_off_at: datetime | None


class PaperListOut(PaperBaseOut):
    item_count: int
    open_count: int


class FindingBriefOut(BaseModel):
    id: uuid.UUID
    finding_key: str
    severity: str
    subject_kind: str
    subject_ref: str
    finding_date: date | None
    amount: str | None
    disallowance_amount: str | None
    message: str
    evidence: dict[str, Any]


class PaperItemOut(BaseModel):
    id: uuid.UUID
    finding: FindingBriefOut
    status: str
    reviewer_note: str | None
    decided_by: str | None
    decided_at: datetime | None


class PaperNoteOut(BaseModel):
    id: uuid.UUID
    note: str
    created_by: str
    created_at: datetime


class PaperDetailOut(PaperBaseOut):
    financial_year_id: uuid.UUID
    sample: SampleOut
    conclusion: str | None
    items: list[PaperItemOut]
    notes: list[PaperNoteOut]


class DecisionIn(BaseModel):
    status: Literal["cleared", "confirmed"]
    reviewer_note: str | None = None


class NoteIn(BaseModel):
    note: str | None = None


class SignOffIn(BaseModel):
    conclusion: str | None = None


class SignOffOut(BaseModel):
    ok: bool = True
    signed_off_at: datetime


class SampleIn(BaseModel):
    method: Literal["random", "systematic", "value"]
    seed: int | None = None
    size: int | None = None
    threshold: str | None = None      # value method: amount as text
    rest_size: int | None = None      # value method: extra items drawn from below the threshold
    start: int | None = None          # systematic: fixed start index (tests only)


class SampleStoredOut(SampleOut):
    population_count: int
    population_digest: str | None


class PreviewIn(SampleIn):
    ids: list[str]
    amounts: dict[str, str] | None = None   # value method: amount per id (text)


class PreviewOut(BaseModel):
    ids: list[str]
