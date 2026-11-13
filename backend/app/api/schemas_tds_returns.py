"""Request bodies of the TDS return and certificate endpoints (Phase 4, package D). Responses are plain JSON (amounts as strings)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ReturnKind = Literal["salary", "non_salary_resident", "tcs"]
CertificateKind = Literal["non_salary", "salary", "tcs"]


class WorkingIn(BaseModel):
    financial_year_id: str
    quarter: int = Field(ge=1, le=4)
    return_kind: ReturnKind


class FiledReturnIn(BaseModel):
    financial_year_id: str
    quarter: int = Field(ge=1, le=4)
    return_kind: ReturnKind
    receipt_no: str | None = None
    filed_on: date | None = None
    data: dict = Field(default_factory=dict)


class CertificateIn(BaseModel):
    deductee_ledger_id: str
    financial_year_id: str
    quarter: int | None = Field(default=None, ge=1, le=4)
    certificate_kind: CertificateKind


class CertificateUpdateIn(BaseModel):
    certificate_no: str | None = None
    issued_on: date | None = None
