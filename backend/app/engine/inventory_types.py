"""Plain data types of the inventory engine (Phase 5). Pure Python: no DB, web or AI imports.

Frozen dataclasses only. Packages A..E import these; nobody changes a signature without the main agent
(add optional fields at the end if a package really needs one). Quantities and money are Decimal, never float.
Quantity has at most 3 decimals (rule S-02), money 2 decimals (half-up through app.engine.money.round_half_up).
Ids are opaque values (uuid or str); the engine only compares them.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

ENGINE_VERSION = "inv-1"
QTY_PLACES = 3
ZERO = Decimal(0)


class ValuationMethod(str, Enum):
    FIFO = "fifo"
    WA_PERIODIC = "wa_periodic"  # weighted average over the report window (opening + inwards of the window)
    WA_MOVING = "wa_moving"      # average recomputed after every inward


class NegativeStockMode(str, Enum):
    BLOCK = "block"
    WARN = "warn"


class MovementKind(str, Enum):
    PURCHASE = "purchase"
    SALE = "sale"
    SALES_RETURN = "sales_return"        # Credit Note with goods back; ref = the sale movement
    PURCHASE_RETURN = "purchase_return"  # Debit Note with goods sent back; ref = the purchase movement
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    WRITE_OFF = "write_off"
    REVERSAL_IN = "reversal_in"          # mirror of an outward movement; ref = that movement
    REVERSAL_OUT = "reversal_out"        # mirror of an inward movement; ref = that movement


INWARD_KINDS = frozenset({MovementKind.PURCHASE, MovementKind.SALES_RETURN, MovementKind.TRANSFER_IN, MovementKind.REVERSAL_IN})
OUTWARD_KINDS = frozenset({MovementKind.SALE, MovementKind.PURCHASE_RETURN, MovementKind.TRANSFER_OUT, MovementKind.WRITE_OFF,
                           MovementKind.REVERSAL_OUT})
# transfers move goods between godowns only: they change godown quantities, never the item's cost layers or value
TRANSFER_KINDS = frozenset({MovementKind.TRANSFER_IN, MovementKind.TRANSFER_OUT})


@dataclass(frozen=True)
class InventoryPolicy:
    method: ValuationMethod
    negative_stock_mode: NegativeStockMode = NegativeStockMode.BLOCK


@dataclass(frozen=True)
class OpeningStock:
    """Opening of one item in one godown for a financial year (value = total cost, 2 decimals)."""

    item_id: Any
    godown_id: Any
    quantity: Decimal
    value: Decimal


@dataclass(frozen=True)
class Movement:
    """One posted stock movement, as read from stock_movements.

    `value` is set for a purchase only (its cost). Outward cost, and the cost of returns and reversals, is computed by the engine.
    Order of processing is (date, seq).
    """

    movement_id: Any
    seq: int
    date: date
    item_id: Any
    godown_id: Any
    kind: MovementKind
    quantity: Decimal
    value: Decimal | None = None
    ref_movement_id: Any = None


@dataclass(frozen=True)
class StockError:
    """A rule failure. Every error carries its rule_id; item_id / movement_id when it applies to one."""

    rule_id: str                    # 'S-01' ...
    message: str                    # plain language, Indian number format, dd-mm-yyyy dates
    severity: str = "error"         # 'error' blocks; 'warning' is shown (S-01 in 'warn' mode, missing NRV ...)
    item_id: Any = None
    godown_id: Any = None
    movement_id: Any = None
    on_date: date | None = None


@dataclass(frozen=True)
class CostedMovement:
    """A movement with the cost the engine gave it (outward cost, return cost); a purchase keeps its stored value."""

    movement_id: Any
    seq: int
    date: date
    item_id: Any
    godown_id: Any
    kind: MovementKind
    quantity: Decimal
    value: Decimal           # inward: cost added; outward: cost removed (always >= 0; the direction is in the kind)
    unit_cost: Decimal       # value / quantity, 4 decimals, for display only (never used to compute)


@dataclass(frozen=True)
class RegisterRow:
    """Stock register line of one item for a window [from_date, to_date]. Value columns are item-level (godowns carry quantities only)."""

    item_id: Any
    opening_qty: Decimal
    opening_value: Decimal
    inward_qty: Decimal
    inward_value: Decimal
    outward_qty: Decimal
    outward_value: Decimal
    closing_qty: Decimal
    closing_value: Decimal           # at cost under the policy, before the NRV test
    by_godown_qty: dict[Any, Decimal] = field(default_factory=dict)   # closing quantity per godown


@dataclass(frozen=True)
class NrvEntry:
    item_id: Any
    as_on_date: date
    nrv_per_unit: Decimal            # 2 decimals, >= 0
    basis_note: str


@dataclass(frozen=True)
class ClosingStockRow:
    """AS 2 line: closing stock at the lower of cost and net realisable value, item by item."""

    item_id: Any
    closing_qty: Decimal
    cost_value: Decimal
    nrv_per_unit: Decimal | None     # None = no NRV entered: no write-down is computed (S-15 warning), never guessed
    nrv_value: Decimal | None        # round_half_up(closing_qty x nrv_per_unit, 2)
    write_down: Decimal              # max(0, cost_value - nrv_value); 0 when nrv_value is None
    carrying_value: Decimal          # cost_value - write_down


@dataclass(frozen=True)
class ValuationResult:
    """Output of the valuation engine for one window: register rows, costed movements, AS 2 rows, every error and warning."""

    policy: InventoryPolicy
    from_date: date
    to_date: date
    register: list[RegisterRow] = field(default_factory=list)
    costed: list[CostedMovement] = field(default_factory=list)
    closing: list[ClosingStockRow] = field(default_factory=list)
    errors: list[StockError] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION
