"""AS 2: closing stock at the lower of cost and net realisable value, item by item (rule S-15). Pure Python."""

from datetime import date
from decimal import Decimal

from app.engine.inventory_types import ClosingStockRow, NrvEntry, RegisterRow, StockError
from app.engine.money import round_half_up

ZERO = Decimal("0.00")


def closing_stock_rows(
    register: list[RegisterRow], nrv_entries: list[NrvEntry], as_on: date
) -> tuple[list[ClosingStockRow], list[StockError]]:
    """One ClosingStockRow per register row.

    Only the NRV entered for exactly `as_on` is used (an older figure would be a guess). An item with stock and no
    usable NRV gets a warning (S-15) and no write-down; an NRV that is negative or has more than 2 decimals is an
    error (S-15) and is not used. Items are never netted against each other.
    """
    by_item = {e.item_id: e for e in nrv_entries if e.as_on_date == as_on}
    rows: list[ClosingStockRow] = []
    errors: list[StockError] = []
    for r in register:
        entry = by_item.get(r.item_id)
        usable = None
        if entry is None:
            if r.closing_qty > 0:
                errors.append(StockError(
                    "S-15", f"No net realisable value entered for item {r.item_id} as on {as_on:%d-%m-%Y}; "
                    "stock is shown at cost with no write-down", "warning", item_id=r.item_id, on_date=as_on))
        elif entry.nrv_per_unit < 0 or entry.nrv_per_unit != entry.nrv_per_unit.quantize(Decimal("0.01")):
            errors.append(StockError(
                "S-15", f"Net realisable value {entry.nrv_per_unit} of item {r.item_id} must be 0 or more with at most 2 decimal "
                "places; it was not used", "error", item_id=r.item_id, on_date=as_on))
        else:
            usable = entry.nrv_per_unit
        if usable is None:
            rows.append(ClosingStockRow(r.item_id, r.closing_qty, r.closing_value, None, None, ZERO, r.closing_value))
            continue
        nrv_value = round_half_up(r.closing_qty * usable, 2)
        write_down = max(ZERO, r.closing_value - nrv_value)
        rows.append(ClosingStockRow(r.item_id, r.closing_qty, r.closing_value, usable, nrv_value, write_down,
                                    r.closing_value - write_down))
    return rows, errors

