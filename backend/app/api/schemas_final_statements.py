"""Request bodies of the closing stock and statement endpoints (Phase 6 package C). Amounts are text (never floats); responses are JSON built by the services."""

from datetime import date

from pydantic import BaseModel


class ClosingStockIn(BaseModel):
    source: str                       # inventory_report | manual | none
    as_on_date: date
    cost_value: str | None = None
    write_down: str | None = None
    basis_note: str | None = None
