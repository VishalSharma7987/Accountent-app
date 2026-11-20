"""Request and response models of the AI switch and the model-call log (package C)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class AiSettingsIn(BaseModel):
    llm_enabled: bool
    data_class: Literal["synthetic", "anonymised", "real_acknowledged"]
    note: str | None = None


class AiSettingsOut(BaseModel):
    llm_enabled: bool
    data_class: str
    enabled_by: str | None
    enabled_at: datetime | None
    note: str | None
    model: str | None            # the model name is not a secret; the key is never returned
    model_configured: bool
    key_configured: bool


class LlmCallOut(BaseModel):
    id: uuid.UUID
    purpose: str
    provider: str
    model: str | None
    prompt_version: str
    status: str
    masking_applied: bool
    masking_report: dict[str, Any] | None   # {"data_class": ..., "counts": {kind: n}}: counts only, never values
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    document_id: uuid.UUID | None
    created_by: str
    created_at: datetime


class LlmCallDetailOut(LlmCallOut):
    prompt_masked: str | None     # what was sent: the masked prompt, never the original text
    response_raw: str | None
    error_message: str | None
