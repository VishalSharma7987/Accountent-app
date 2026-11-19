"""Request bodies of the Schedule III endpoints (docs/PHASE6_API_CONTRACT.md, package D)."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CfClass = Literal["operating", "investing", "financing", "cash_equivalent", "non_cash", "equity_profit"]


class ClassificationRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ledger_id: uuid.UUID
    line_code: str | None = Field(default=None, max_length=80)
    cf_class: CfClass | None = None
    note: str | None = Field(default=None, max_length=500)


class ClassificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[ClassificationRowIn] = Field(min_length=1, max_length=2000)
