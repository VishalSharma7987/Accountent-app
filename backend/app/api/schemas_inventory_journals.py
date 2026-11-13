"""Request and response models of the stock journals (docs/PHASE5_API_CONTRACT.md, package D). Quantities are 3-decimal strings."""

import uuid
from datetime import date

from pydantic import BaseModel

from app.services.inventory_journals import JournalView


class JournalLineIn(BaseModel):
    item_id: str
    from_godown_id: str
    to_godown_id: str | None = None
    quantity: str


class JournalIn(BaseModel):
    journal_type: str
    journal_date: date
    narration: str
    reason_code: str | None = None
    reason_note: str | None = None
    lines: list[JournalLineIn]


class ReverseIn(BaseModel):
    reason: str
    reversal_date: date | None = None  # default: the journal's own date


class JournalLineOut(BaseModel):
    line_no: int
    item_id: uuid.UUID
    item_name: str
    from_godown_id: uuid.UUID
    to_godown_id: uuid.UUID | None
    quantity: str


class WarningOut(BaseModel):
    rule_id: str
    message: str
    item_id: uuid.UUID | None = None
    severity: str = "warning"


class JournalOut(BaseModel):
    id: uuid.UUID
    journal_type: str
    journal_number: str | None
    journal_date: date
    narration: str
    reason_code: str | None
    reason_note: str | None
    status: str
    financial_year_id: uuid.UUID
    lines: list[JournalLineOut]
    created_by: str
    approved_by: str | None
    posted_by: str | None
    reversed_by: str | None
    reverse_reason: str | None
    warnings: list[WarningOut] = []


def journal_out(v: JournalView) -> JournalOut:
    r = v.row
    return JournalOut(
        id=r.id, journal_type=r.journal_type, journal_number=r.journal_number, journal_date=r.journal_date, narration=r.narration,
        reason_code=r.reason_code, reason_note=r.reason_note, status=r.status, financial_year_id=r.financial_year_id,
        lines=[JournalLineOut(line_no=x.line_no, item_id=x.item_id, item_name=x.item_name, from_godown_id=x.from_godown_id,
                              to_godown_id=x.to_godown_id, quantity=f"{x.quantity:.3f}") for x in v.lines],
        created_by=r.created_by, approved_by=r.approved_by, posted_by=r.posted_by, reversed_by=r.reversed_by,
        reverse_reason=r.reverse_reason,
        warnings=[WarningOut(rule_id=w.rule_id, message=w.message, item_id=w.item_id, severity=w.severity) for w in v.warnings])
