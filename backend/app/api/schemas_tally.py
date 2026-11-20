"""Request bodies of the Tally endpoints (docs/PHASE7_API_CONTRACT.md, package B)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportIn(_Body):
    document_id: str


class MasterDecisionIn(_Body):
    decision: Literal["confirmed", "create", "skip"]
    target_group_id: str | None = None
    target_ledger_id: str | None = None
    target_item_id: str | None = None
    accept_nature_change: bool = False


class QueueVouchersIn(_Body):
    financial_year_id: str | None = None


class ExportIn(_Body):
    kind: Literal["masters", "vouchers", "both"]
    from_date: date | None = None
    to_date: date | None = None
    financial_year_id: str | None = None
    posted_only: bool = False
