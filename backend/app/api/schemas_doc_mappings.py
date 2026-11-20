"""Request / response shapes of the mapping and draft endpoints (Phase 7 package E)."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartyMappingIn(_Strict):
    match_kind: Literal["gstin", "name"]
    match_key: str
    party_ledger_id: uuid.UUID
    replace: bool = False


class LineMappingIn(_Strict):
    match_kind: Literal["hsn_sac", "description"]
    match_key: str
    party_ledger_id: uuid.UUID | None = None
    ledger_id: uuid.UUID
    item_id: uuid.UUID | None = None
    replace: bool = False


class PartyMappingOut(BaseModel):
    id: uuid.UUID
    match_kind: str
    match_key: str
    party_ledger_id: uuid.UUID
    party_ledger_name: str
    use_count: int


class LineMappingOut(BaseModel):
    id: uuid.UUID
    match_kind: str
    match_key: str
    party_ledger_id: uuid.UUID | None
    party_ledger_name: str | None
    ledger_id: uuid.UUID
    ledger_name: str
    item_id: uuid.UUID | None
    item_name: str | None
    use_count: int


class IdOut(BaseModel):
    id: uuid.UUID


class BuildDraftIn(_Strict):
    extraction_id: uuid.UUID | None = None


class BuildDraftOut(BaseModel):
    queue_item_id: uuid.UUID
    status: str
    findings: list[dict]
    draft_voucher_id: uuid.UUID | None
