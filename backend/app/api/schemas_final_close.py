"""Request bodies of the year-end close endpoints (Phase 6 package F)."""

from pydantic import BaseModel


class CloseIn(BaseModel):
    financial_year_id: str
    create_next_year: bool = False
    confirm_no_depreciation: bool = False        # added to the contract: the explicit "no depreciation" confirmation of F-60
    acknowledged_flags: list[str] = []           # added: income-tax blocks whose flags the CA acknowledges (F-33)


class ReopenIn(BaseModel):
    reason: str
