"""Request and response models of the TDS masters (profile, deductees, certificates, ledger roles, rule tables).

Rates and rule numbers are strings with up to 4 decimals (never floats); INR amounts are 2-decimal strings.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.api.schemas import money
from app.api.schemas_gst_masters import rule_row
from app.engine.models import ValidationError
from app.services.tds_masters import CertView, DeducteeView

__all__ = ["rule_row"]


class TanIn(BaseModel):
    tan: str


class FyFlagIn(BaseModel):
    prev_year_turnover_over_threshold: bool
    note: str | None = None


class FyFlagOut(BaseModel):
    financial_year_id: uuid.UUID
    prev_year_turnover_over_threshold: bool
    note: str | None


class ProfileOut(BaseModel):
    tan: str | None
    fy_flags: list[FyFlagOut]


class CertIn(BaseModel):
    certificate_no: str
    nature_key: str | None = None
    rate: Decimal
    max_amount: Decimal
    valid_from: date
    valid_to: date
    note: str | None = None


class CertUpdate(BaseModel):
    is_active: bool = True
    note: str | None = None
    valid_to: date | None = None


class CertCreated(BaseModel):
    id: uuid.UUID


class CertOut(BaseModel):
    id: uuid.UUID
    certificate_no: str
    nature_key: str | None
    rate: str
    max_amount: str
    valid_from: date
    valid_to: date
    amount_used: str
    amount_left: str
    is_active: bool
    note: str | None


def cert_out(c: CertView) -> CertOut:
    return CertOut(id=c.id, certificate_no=c.certificate_no, nature_key=c.nature_key, rate=f"{c.rate:f}",
                   max_amount=money(c.max_amount), valid_from=c.valid_from, valid_to=c.valid_to,
                   amount_used=money(c.amount_used), amount_left=money(c.amount_left), is_active=c.is_active, note=c.note)


class DeducteeIn(BaseModel):
    pan: str | None = None
    pan_status: str
    deductee_type: str
    default_nature_key: str | None = None
    is_active: bool = True


class WarningOut(BaseModel):
    rule_id: str
    message: str


class DeducteeSaved(BaseModel):
    ok: bool = True
    warnings: list[WarningOut] = []


def saved(warnings: list[ValidationError]) -> DeducteeSaved:
    return DeducteeSaved(warnings=[WarningOut(rule_id=w.rule_id, message=w.message) for w in warnings])


class DeducteeOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str
    pan: str | None
    pan_status: str
    deductee_type: str
    default_nature_key: str | None
    is_active: bool
    lower_certs: list[CertOut]
    pan_warning: str | None


def deductee_out(d: DeducteeView) -> DeducteeOut:
    return DeducteeOut(ledger_id=d.ledger_id, ledger_name=d.ledger_name, pan=d.pan, pan_status=d.pan_status,
                       deductee_type=d.deductee_type, default_nature_key=d.default_nature_key, is_active=d.is_active,
                       lower_certs=[cert_out(c) for c in d.lower_certs], pan_warning=d.pan_warning)


class RoleIn(BaseModel):
    role: str
    nature_key: str | None = None
    ledger_id: str


class LedgerRolesIn(BaseModel):
    roles: list[RoleIn]


class RoleOut(BaseModel):
    role: str
    nature_key: str | None
    ledger_id: uuid.UUID
    ledger_name: str


class LedgerRolesOut(BaseModel):
    roles: list[RoleOut]


class RuleStatusOut(BaseModel):
    overall: str
    counts: dict[str, int]


class RuleSummaryOut(BaseModel):
    worst: str
    tables: dict[str, str]
    pending_sources: list[str]


class RuleTableOut(BaseModel):
    on: date
    status: RuleStatusOut
    rule_status: RuleSummaryOut
    rows: list[dict]
