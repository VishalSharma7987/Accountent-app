"""Request shapes of the approval queue and narration endpoints (docs/PHASE7_API_CONTRACT.md, package F). Responses are built by the
routers with amounts as 2-decimal strings."""

from typing import Any

from pydantic import BaseModel, Field


class EditIn(BaseModel):
    field_path: str
    value: Any = None


class EditFieldsIn(BaseModel):
    edits: list[EditIn] | None = None
    payload: dict | None = None


class AckIn(BaseModel):
    rule_id: str
    field_path: str | None = None


class AcceptIn(BaseModel):
    acknowledge: list[AckIn] = Field(default_factory=list)
    learn: bool = True


class RejectIn(BaseModel):
    reason: str


class AcceptCleanIn(BaseModel):
    ids: list[str]


class RuleActiveIn(BaseModel):
    is_active: bool
