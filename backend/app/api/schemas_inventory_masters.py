"""Request and response models of the inventory masters (docs/PHASE5_API_CONTRACT.md, package A).
Amounts are 2-decimal strings, quantities 3-decimal strings, unit costs 4-decimal strings."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.api.schemas import money
from app.db import repositories_inventory_masters as inv
from app.engine.inventory_masters import unit_cost
from app.services.inventory_masters import OpeningView


def qty(value) -> str:
    return f"{value:.3f}"


class GodownIn(BaseModel):
    name: str


class GodownUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class GodownOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool


class GodownCreated(BaseModel):
    id: uuid.UUID


def godown_out(g: inv.GodownRow) -> GodownOut:
    return GodownOut(id=g.id, name=g.name, is_active=g.is_active)


class StockItemIn(BaseModel):
    sku: str
    default_godown_id: str
    is_active: bool = True


class StockItemOut(BaseModel):
    item_id: uuid.UUID
    sku: str
    name: str
    hsn_sac: str
    uqc: str | None
    default_godown_id: uuid.UUID
    default_godown_name: str
    is_active: bool
    has_entries: bool
    opening_qty: str | None = None
    opening_value: str | None = None


def stock_item_out(s: inv.StockItemRow) -> StockItemOut:
    return StockItemOut(
        item_id=s.item_id, sku=s.sku, name=s.name, hsn_sac=s.hsn_sac, uqc=s.uqc, default_godown_id=s.default_godown_id,
        default_godown_name=s.default_godown_name, is_active=s.is_active, has_entries=s.has_entries,
        opening_qty=None if s.opening_qty is None else qty(s.opening_qty),
        opening_value=None if s.opening_value is None else money(s.opening_value))


class PolicyIn(BaseModel):
    valuation_method: str
    negative_stock_mode: str


class PolicyCopyIn(BaseModel):
    from_financial_year_id: str
    to_financial_year_id: str


class PolicyOut(BaseModel):
    financial_year_id: uuid.UUID
    valuation_method: Literal["fifo", "wa_periodic", "wa_moving"]
    negative_stock_mode: Literal["block", "warn"]
    set_by: str
    set_at: datetime


def policy_out(p: inv.PolicyRow) -> PolicyOut:
    return PolicyOut(financial_year_id=p.financial_year_id, valuation_method=p.valuation_method,  # type: ignore[arg-type]
                     negative_stock_mode=p.negative_stock_mode, set_by=p.set_by, set_at=p.set_at)  # type: ignore[arg-type]


class OpeningRowIn(BaseModel):
    item_id: str
    godown_id: str
    quantity: str
    value: str


class OpeningIn(BaseModel):
    rows: list[OpeningRowIn]


class OpeningRowOut(BaseModel):
    item_id: uuid.UUID
    sku: str
    name: str
    godown_id: uuid.UUID
    godown_name: str
    quantity: str
    value: str
    unit_cost: str


class OpeningOut(BaseModel):
    rows: list[OpeningRowOut]
    total_value: str
    ledger_opening_value: str | None
    difference: str | None


class OpeningSaved(BaseModel):
    ok: bool = True
    total_value: str


def opening_out(v: OpeningView) -> OpeningOut:
    return OpeningOut(
        rows=[OpeningRowOut(item_id=r.item_id, sku=r.sku, name=r.name, godown_id=r.godown_id, godown_name=r.godown_name,
                            quantity=qty(r.quantity), value=money(r.value), unit_cost=f"{unit_cost(r.quantity, r.value):.4f}")
              for r in v.rows],
        total_value=money(v.total_value),
        ledger_opening_value=None if v.ledger_opening_value is None else money(v.ledger_opening_value),
        difference=None if v.difference is None else money(v.difference))
