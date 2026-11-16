"""Which invoice item lines move stock, and the save-time stock rules (Phase 5, package C). Pure Python: no DB, web or AI imports.

Rules here: S-02 (quantity above zero, at most 3 decimals), S-03 (active goods item with a stock_items row), S-06 (unit and HSN equal
the item's), S-07 (godown exists, is active; override else default), S-12 (a Credit / Debit Note moves stock only with the original
sale / purchase movement; quantity within what is left to return), S-14 (purchase cost, through engine/inventory_costing).
S-01 (no negative stock) needs the whole chronology and lives in services/inventory_movements.py with the valuation engine.
Ids are compared as strings by the caller; nothing is guessed: a line that cannot be decided is an error.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.engine.inventory_costing import purchase_cost
from app.engine.inventory_types import QTY_PLACES, MovementKind
from app.engine.models import ValidationError

NOTE_KIND = {"credit_note": MovementKind.SALES_RETURN, "debit_note": MovementKind.PURCHASE_RETURN}
KIND_OF = {"sales": MovementKind.SALE, "purchase": MovementKind.PURCHASE, **NOTE_KIND}
ORIGINAL_KIND = {"credit_note": MovementKind.SALE, "debit_note": MovementKind.PURCHASE}
QTY_UNIT = Decimal(1).scaleb(-QTY_PLACES)


@dataclass(frozen=True)
class StockLineIn:
    """The optional `stock` block of an invoice item line: godown override, original movement of a Credit / Debit Note."""

    item_line_no: int
    godown_id: str | None = None
    original_movement_id: str | None = None


@dataclass(frozen=True)
class ItemFacts:
    """A stock item as the database knows it (only items that HAVE a stock_items row are given to the engine)."""

    name: str
    stock_active: bool
    item_active: bool
    uqc: str | None
    hsn_sac: str
    default_godown_id: str


@dataclass(frozen=True)
class LineFacts:
    """An invoice item line with the figures of the GST engine."""

    item_line_no: int
    item_id: str | None
    quantity: Decimal
    uqc: str | None
    hsn_sac: str
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    tax_in_cost: bool


@dataclass(frozen=True)
class OriginalFacts:
    """A sale / purchase movement named by a return; `returned` = quantity of its non-reversed returns so far."""

    movement_id: str
    item_id: str
    kind: MovementKind
    quantity: Decimal
    godown_id: str
    reversed: bool
    returned: Decimal


@dataclass(frozen=True)
class PlannedMovement:
    item_line_no: int
    item_id: str
    godown_id: str
    kind: MovementKind
    quantity: Decimal
    value: Decimal | None = None             # purchase only (S-14)
    original_movement_id: str | None = None  # returns only


@dataclass
class StockPlan:
    errors: list[ValidationError] = field(default_factory=list)
    movements: list[PlannedMovement] = field(default_factory=list)


def _q(value: Decimal) -> str:
    return f"{value:.3f}"


def plan_stock(
    voucher_type: str,
    lines: list[LineFacts],
    stock_lines: dict[int, StockLineIn],
    items: dict[str, ItemFacts],
    godowns: dict[str, bool],
    originals: dict[str, OriginalFacts],
) -> StockPlan:
    """The movements an invoice would make and the rule errors of its stock lines.

    `items` holds only items with a stock_items row; `godowns` maps godown id -> is_active for the client's godowns;
    `originals` the movements named by returns. A Credit / Debit Note line moves stock only when it has a stock block."""
    plan = StockPlan()
    kind = KIND_OF.get(voucher_type)
    if kind is None:
        return plan
    is_note = voucher_type in NOTE_KIND
    left: dict[str, Decimal] = {}  # balance of each original still returnable, across the lines of this note
    for ln in lines:
        n = ln.item_line_no
        block = stock_lines.get(n)
        item = items.get(ln.item_id) if ln.item_id is not None else None
        if item is None:
            if block is not None:
                plan.errors.append(ValidationError(
                    "S-03", f"Item {n}: a stock block is given but this line is not an item with stock tracking.", n))
            continue
        if is_note and block is None:
            continue  # value-only note: no stock effect
        label = f"Item {n} ({item.name})"
        before = len(plan.errors)
        if not item.stock_active or not item.item_active:
            plan.errors.append(ValidationError("S-03", f"{label}: the item is not active, so it cannot move stock.", n))
        if ln.quantity <= 0 or ln.quantity != ln.quantity.quantize(QTY_UNIT):
            plan.errors.append(ValidationError(
                "S-02", f"{label}: quantity {ln.quantity.normalize():f} must be above zero with at most {QTY_PLACES} decimal places.", n))
        if (ln.uqc or "") != (item.uqc or ""):
            plan.errors.append(ValidationError(
                "S-06", f"{label}: the line unit '{ln.uqc or ''}' is not the item's unit '{item.uqc or ''}'.", n))
        if ln.hsn_sac != item.hsn_sac:
            plan.errors.append(ValidationError(
                "S-06", f"{label}: the line HSN {ln.hsn_sac} is not the item's HSN {item.hsn_sac}.", n))
        original_id = block.original_movement_id if block else None
        original = None
        if is_note:
            original = _original(plan, label, n, voucher_type, ln, original_id, originals, left)
        godown_id = block.godown_id if block and block.godown_id else (original.godown_id if original else item.default_godown_id)
        if godowns.get(godown_id) is not True:
            plan.errors.append(ValidationError("S-07", f"{label}: the godown does not exist or is not active.", n))
        if len(plan.errors) > before:
            continue
        value = None
        if kind == MovementKind.PURCHASE:
            value = purchase_cost(ln.taxable_value, ln.cgst, ln.sgst, ln.igst, ln.cess, ln.tax_in_cost)
        plan.movements.append(PlannedMovement(n, ln.item_id, godown_id, kind, ln.quantity, value, original_id))
    return plan


def _original(plan, label, n, voucher_type, ln, original_id, originals, left) -> OriginalFacts | None:
    what = "sale" if voucher_type == "credit_note" else "purchase"
    if not original_id:
        plan.errors.append(ValidationError(
            "S-12", f"{label}: goods are returned, so the original {what} movement is required (or leave out the stock block "
                    "for a value-only note).", n))
        return None
    original = originals.get(original_id)
    if original is None or original.item_id != ln.item_id or original.kind != ORIGINAL_KIND[voucher_type]:
        plan.errors.append(ValidationError("S-12", f"{label}: the original movement is not a {what} of this item.", n))
        return None
    if original.reversed:
        plan.errors.append(ValidationError("S-12", f"{label}: the original {what} has been reversed.", n))
        return None
    balance = left.setdefault(original_id, original.quantity - original.returned)
    if ln.quantity > balance:
        plan.errors.append(ValidationError(
            "S-12", f"{label}: {_q(ln.quantity)} cannot be returned; only {_q(max(balance, Decimal(0)))} of the original "
                    f"{_q(original.quantity)} is left to return ({_q(original.returned)} already returned).", n))
        return None
    left[original_id] = balance - ln.quantity
    return original
