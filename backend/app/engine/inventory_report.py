"""Report assembly of the inventory package (Phase 5, package E): stock register (item level and by godown), item ledger,
NRV entry check (S-15). Pure Python: no DB, web or AI imports. All values come from the valuation engine; nothing is
computed here except sums and running balances of figures the engine already gave."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine.inventory_types import (
    INWARD_KINDS,
    ZERO,
    Movement,
    MovementKind,
    OpeningStock,
    ValuationResult,
)
from app.engine.models import ValidationError

MONEY0 = Decimal("0.00")


@dataclass(frozen=True)
class ItemMeta:
    sku: str
    name: str
    uqc: str


@dataclass(frozen=True)
class RegisterLine:
    """One register line. Value fields are None in the by-godown view (valuation is per item, never per godown)."""

    item_id: Any
    sku: str
    name: str
    uqc: str
    opening_qty: Decimal
    opening_value: Decimal | None
    inward_qty: Decimal
    inward_value: Decimal | None
    outward_qty: Decimal
    outward_value: Decimal | None
    closing_qty: Decimal
    closing_value: Decimal | None
    by_godown: dict[Any, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerLine:
    date: date
    seq: int
    kind: MovementKind
    doc_number: str | None
    godown_id: Any
    in_qty: Decimal
    in_value: Decimal
    out_qty: Decimal
    out_value: Decimal
    balance_qty: Decimal
    balance_value: Decimal
    movement_id: Any = None


def _meta(meta: dict, item_id: Any) -> ItemMeta:
    return meta.get(item_id) or ItemMeta("", str(item_id), "")


def _godown_lines(meta, opening, movements, from_date, to_date, godown_id, valued_items) -> list[RegisterLine]:
    lines = []
    for item_id in sorted(valued_items, key=str):
        open_q = sum((o.quantity for o in opening if o.item_id == item_id and o.godown_id == godown_id), ZERO)
        inward = outward = ZERO
        for m in movements:
            if m.item_id != item_id or m.godown_id != godown_id or m.date > to_date:
                continue
            signed = m.quantity if m.kind in INWARD_KINDS else -m.quantity
            if m.date < from_date:
                open_q += signed
            elif signed > 0:
                inward += m.quantity
            else:
                outward += m.quantity
        close_q = open_q + inward - outward
        if open_q == 0 and inward == 0 and outward == 0 and close_q == 0:
            continue
        info = _meta(meta, item_id)
        lines.append(RegisterLine(item_id, info.sku, info.name, info.uqc, open_q, None, inward, None, outward, None, close_q, None,
                                  {godown_id: close_q}))
    return lines


def register_lines(result: ValuationResult, meta: dict, opening: list[OpeningStock], movements: list[Movement],
                   from_date: date, to_date: date, godown_id: Any = None) -> list[RegisterLine]:
    """Register lines for the window. Items the engine could not value (errors) are not listed; the errors say why.
    With `godown_id` the quantities are that godown's and all value fields are None."""
    if godown_id is not None:
        return _godown_lines(meta, opening, movements, from_date, to_date, godown_id, [r.item_id for r in result.register])
    lines = []
    for r in result.register:
        info = _meta(meta, r.item_id)
        lines.append(RegisterLine(r.item_id, info.sku, info.name, info.uqc, r.opening_qty, r.opening_value, r.inward_qty,
                                  r.inward_value, r.outward_qty, r.outward_value, r.closing_qty, r.closing_value,
                                  dict(r.by_godown_qty)))
    return lines


def register_totals(lines: list[RegisterLine]) -> dict[str, Decimal]:
    def total(attr: str) -> Decimal:
        return sum((getattr(x, attr) or MONEY0 for x in lines), MONEY0)

    return {"opening_value": total("opening_value"), "inward_value": total("inward_value"),
            "outward_value": total("outward_value"), "closing_value": total("closing_value")}


def item_ledger(result: ValuationResult, item_id: Any, doc_numbers: dict) -> list[LedgerLine]:
    """The movements of one item in the window with the engine's cost and a running balance that starts at the window's
    opening. Transfers change no value. (Under weighted average periodic the per-movement costs are each rounded, so the
    last balance can differ from the register closing by a few paise.)"""
    row = next((r for r in result.register if r.item_id == item_id), None)
    if row is None:
        return []
    qty, value = row.opening_qty, row.opening_value
    lines = []
    for c in result.costed:
        if c.item_id != item_id:
            continue
        inward = c.kind in INWARD_KINDS
        if inward:
            qty, value = qty + c.quantity, value + c.value
        else:
            qty, value = qty - c.quantity, value - c.value
        lines.append(LedgerLine(
            c.date, c.seq, c.kind, doc_numbers.get(c.movement_id), c.godown_id,
            c.quantity if inward else ZERO, c.value if inward else MONEY0,
            ZERO if inward else c.quantity, MONEY0 if inward else c.value, qty, value, c.movement_id))
    return lines


def validate_nrv_row(item_id: Any, nrv_per_unit: Decimal, basis_note: str) -> list[ValidationError]:
    """S-15: NRV per unit is 0 or more with at most 2 decimal places (rejected, not rounded); the basis is required."""
    errors = []
    if nrv_per_unit < 0 or nrv_per_unit != nrv_per_unit.quantize(Decimal("0.01")):
        errors.append(ValidationError(
            "S-15", f"Net realisable value {nrv_per_unit} must be 0 or more with at most 2 decimal places"))
    if not (basis_note or "").strip():
        errors.append(ValidationError("S-15", "The basis of the net realisable value (quote, price list, sale after year end) is required"))
    return errors
