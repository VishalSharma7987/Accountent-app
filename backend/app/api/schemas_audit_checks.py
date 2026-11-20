"""Request / response models of the audit runs API (Phase 8, package A). Amounts are strings with 2 decimals; dates ISO."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class CheckOut(BaseModel):
    check_id: str
    title: str
    description: str
    rule_text: str
    severity: str
    category: str
    evidence_query: str
    rule_key: str | None
    active: bool


class RuleOut(BaseModel):
    rule_key: str
    law: str
    section_ref: str
    amount: str
    breach_when: str
    disallow_percent: str | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str
    notes: str | None


class RunParamsIn(BaseModel):
    model_config = {"extra": "forbid"}
    duplicate_window_days: int | None = None
    doc_required_types: list[str] | None = None
    doc_min_amount: str | None = None
    round_unit: str | None = None
    round_min_amount: str | None = None
    late_posting_days: int | None = None
    variance_min_amount: str | None = None
    variance_band_percent: str | None = None


class RunCreate(BaseModel):
    financial_year_id: uuid.UUID
    from_date: date | None = None
    to_date: date | None = None
    check_ids: list[str] | None = None
    params: RunParamsIn | None = None


class RunCreated(BaseModel):
    id: uuid.UUID
    status: str
    finding_count: int
    summary: dict[str, Any]
    error: str | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    financial_year_id: uuid.UUID
    from_date: date
    to_date: date
    check_ids: list[str]
    finding_count: int
    status: str
    created_by: str
    created_at: datetime


class RunDetailOut(RunOut):
    params: dict[str, Any]
    rules_used: list[dict[str, Any]]
    engine_version: str
    summary: dict[str, Any]
    error_message: str | None = None


class FindingOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    check_id: str
    finding_key: str
    severity: str
    subject_kind: str
    subject_id: uuid.UUID | None
    subject_ref: str
    finding_date: date | None
    amount: str | None
    disallowance_amount: str | None
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    rule_status: str | None = None
