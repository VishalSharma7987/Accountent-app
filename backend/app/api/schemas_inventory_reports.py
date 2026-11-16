"""Request bodies of the inventory report endpoints (Phase 5, package E). Responses are plain JSON built by the services."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class NrvRowIn(BaseModel):
    item_id: str
    nrv_per_unit: Decimal | None = None   # null deletes the entry
    basis_note: str = ""


class NrvIn(BaseModel):
    as_on_date: date
    rows: list[NrvRowIn]
