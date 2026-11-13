"""Inventory masters rules (Phase 5, package A): S-02 quantity, S-03 stock item, S-04 policy values, S-07 godown,
S-08 opening stock. Pure Python: no DB, web or AI imports. Errors are ValidationError (rule_id, message, line_no);
line_no is the 1-based row of an opening list."""

from dataclasses import dataclass
from decimal import Decimal

from app.engine.inventory_types import QTY_PLACES, NegativeStockMode, OpeningStock, ValuationMethod
from app.engine.models import ValidationError
from app.engine.money import MoneyError, format_inr, parse_amount, round_half_up

QTY_STEP = Decimal(1).scaleb(-QTY_PLACES)
MAX_QTY = Decimal("99999999999999.999")


@dataclass(frozen=True)
class ItemFacts:
    kind: str       # goods | service
    is_active: bool


@dataclass(frozen=True)
class OpeningInput:
    """One opening row as entered (quantity and value are text or Decimal)."""

    item_id: object
    godown_id: object
    quantity: object
    value: object


def validate_quantity(
    value: object, *, allow_zero: bool = True, line_no: int | None = None,
) -> tuple[Decimal | None, list[ValidationError]]:
    """S-02: a quantity with at most 3 decimals (rejected, never rounded); never negative; zero only when allowed."""

    def bad(why: str) -> tuple[None, list[ValidationError]]:
        return None, [ValidationError("S-02", f"Quantity {value!r} is not accepted: {why}.", line_no)]

    if value is None or isinstance(value, (bool, float)):
        return bad("it must be a number given as text")
    try:
        number = Decimal(str(value).strip())
    except ArithmeticError:
        return bad("it is not a valid number")
    if not number.is_finite() or "e" in str(value).lower():
        return bad("it is not a valid number")
    if number < 0:
        return bad("it cannot be negative")
    if number != number.quantize(QTY_STEP):
        return bad(f"it has more than {QTY_PLACES} decimal places")
    if number > MAX_QTY:
        return bad("it is too large")
    if number == 0 and not allow_zero:
        return bad("it must be more than zero")
    return number.quantize(QTY_STEP), []


def validate_stock_item(
    sku: str | None, item_kind: str | None, item_active: bool, godown_active: bool | None,
) -> list[ValidationError]:
    """S-03 (SKU given; an active goods item) and S-07 (default godown exists and is active; None = not found)."""
    errors: list[ValidationError] = []
    if not (sku or "").strip():
        errors.append(ValidationError("S-03", "The SKU (stock code) is required."))
    if item_kind != "goods":
        errors.append(ValidationError("S-03", "Only a goods item can be a stock item; services and expenses do not hold stock."))
    elif not item_active:
        errors.append(ValidationError("S-03", "The item is inactive; switch it on before making it a stock item."))
    if godown_active is None:
        errors.append(ValidationError("S-07", "The default godown was not found for this client."))
    elif not godown_active:
        errors.append(ValidationError("S-07", "The default godown is inactive."))
    return errors


def validate_policy(method: str | None, negative_stock_mode: str | None) -> list[ValidationError]:
    """S-04: the valuation method and the negative-stock mode must each be one of the allowed values (never defaulted)."""
    errors: list[ValidationError] = []
    if method not in {m.value for m in ValuationMethod}:
        errors.append(ValidationError("S-04", "Choose the valuation method: fifo, wa_periodic or wa_moving."))
    if negative_stock_mode not in {m.value for m in NegativeStockMode}:
        errors.append(ValidationError("S-04", "Choose what happens on negative stock: block or warn."))
    return errors


def validate_opening(
    rows: list[OpeningInput], items: dict[object, ItemFacts], godowns: dict[object, bool],
) -> tuple[list[OpeningStock], list[ValidationError]]:
    """S-02, S-03, S-07, S-08 over a whole opening list; returns the clean rows (empty when there is any error)."""
    clean: list[OpeningStock] = []
    errors: list[ValidationError] = []
    seen: set[tuple[object, object]] = set()
    for line_no, row in enumerate(rows, start=1):
        row_errors: list[ValidationError] = []
        item = items.get(row.item_id)
        if item is None or item.kind != "goods" or not item.is_active:
            row_errors.append(ValidationError("S-03", "The item is not an active goods stock item of this client.", line_no))
        active = godowns.get(row.godown_id)
        if active is None:
            row_errors.append(ValidationError("S-07", "The godown was not found for this client.", line_no))
        elif not active:
            row_errors.append(ValidationError("S-07", "The godown is inactive.", line_no))
        qty, qty_errors = validate_quantity(row.quantity, line_no=line_no)
        row_errors += qty_errors
        value: Decimal | None = None
        try:
            value = parse_amount(row.value)
        except MoneyError as exc:
            row_errors.append(ValidationError("S-08", f"Opening value is not accepted: {exc}.", line_no))
        if (row.item_id, row.godown_id) in seen:
            row_errors.append(ValidationError(
                "S-08", "This item and godown already appear in the opening list; one row only.", line_no))
        seen.add((row.item_id, row.godown_id))
        if qty is not None and value is not None and qty == 0 and value > 0:
            row_errors.append(ValidationError(
                "S-08", f"Opening value {format_inr(value)} needs a quantity above zero.", line_no))
        errors += row_errors
        if not row_errors and qty is not None and value is not None:
            clean.append(OpeningStock(row.item_id, row.godown_id, qty, value))
    return ([] if errors else clean), errors


def opening_difference(total_value: Decimal, ledger_value: Decimal | None) -> Decimal | None:
    """S-08: opening stock total less the Stock-in-hand ledger's opening balance (Dr positive); None when there is no ledger.
    Information only: it never blocks."""
    if ledger_value is None:
        return None
    return round_half_up(total_value - ledger_value, 2)


def unit_cost(quantity: Decimal, value: Decimal) -> Decimal:
    """value / quantity to 4 decimals, for display only; 0 when there is no quantity."""
    if quantity == 0:
        return Decimal("0.0000")
    return round_half_up(value / quantity, 4)
