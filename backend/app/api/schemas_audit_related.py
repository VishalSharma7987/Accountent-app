"""Request and response models for related-party flags (Phase 8, package D)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.services.audit_related import RelatedFlag


class RelatedFlagIn(BaseModel):
    ledger_id: uuid.UUID
    relationship: str
    note: str | None = None


class RelatedFlagUpdateIn(BaseModel):
    relationship: str | None = None
    active: bool | None = None
    note: str | None = None


class RelatedFlagOut(BaseModel):
    id: uuid.UUID
    ledger_id: uuid.UUID
    ledger_name: str
    relationship: str
    active: bool
    flagged_by: str
    flagged_at: datetime
    note: str | None


class IdOut(BaseModel):
    id: uuid.UUID


def flag_out(f: RelatedFlag) -> RelatedFlagOut:
    return RelatedFlagOut(id=f.id, ledger_id=f.ledger_id, ledger_name=f.ledger_name, relationship=f.relationship, active=f.active,
                          flagged_by=f.flagged_by, flagged_at=f.flagged_at, note=f.note)
