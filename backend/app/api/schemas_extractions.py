"""Request / response shapes of the extraction endpoints (docs/PHASE7_API_CONTRACT.md "Extraction")."""

from typing import Any, Literal

from pydantic import BaseModel

from app.engine.doc_types import DocFinding


class ExtractIn(BaseModel):
    mode: Literal["llm", "manual"]
    payload: dict | None = None


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    field_path: str | None = None
    printed: str | None = None
    computed: str | None = None


def finding_out(f: DocFinding) -> dict:
    return f.as_dict()


class ExtractOut(BaseModel):
    status: Literal["ok", "blocked", "invalid", "error"]
    extraction_id: str | None
    llm_call_id: str | None
    findings: list[FindingOut]
    message: str


class ExtractionVersionOut(BaseModel):
    id: str
    version: int
    source: str
    status: str
    created_at: str
    superseded: bool


class ExtractionOut(BaseModel):
    id: str
    document_id: str
    version: int
    source: str
    status: str
    schema_version: str
    payload: dict[str, Any]
    invalid_reason: str | None
    llm_call_id: str | None
    superseded: bool


class CheckOut(BaseModel):
    findings: list[FindingOut]
    recomputed: dict[str, Any]
    direction: str | None
    place_of_supply: str | None
