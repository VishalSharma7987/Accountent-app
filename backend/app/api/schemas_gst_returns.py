"""Request bodies of the GST return endpoints (Phase 3, package E). Responses are the workings as plain JSON (strings for amounts)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

PeriodKind = Literal["month", "quarter"]


class WorkingIn(BaseModel):
    registration_id: str
    return_type: Literal["gstr1", "gstr3b", "cmp08"]
    period_start: date
    period_kind: PeriodKind = "month"


class FiledReturnIn(BaseModel):
    registration_id: str
    return_type: Literal["gstr1", "gstr3b", "cmp08", "gstr4"]
    period_start: date
    arn: str | None = None
    filed_on: date | None = None
    data: dict = Field(default_factory=dict)
