"""Stock journal rules (Phase 5, package D): S-10 (transfer / write-off document), S-11 (lifecycle), and the movement
plans they produce (S-17 mirrors). Pure Python: no DB, web or AI imports.

A transfer moves quantity between godowns (transfer_out + transfer_in per line) and never changes value; a write-off takes
goods out of one godown (write_off) and needs a reason. The cost of a write-off is computed by the valuation engine (S-13).
Errors are ValidationError (rule_id, message, line_no); line_no is the 1-based journal line.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.inventory_masters import validate_quantity
from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    MovementKind,
    OpeningStock,
    StockError,
)
from app.engine.inventory_valuation import compute_valuation
from app.engine.models import ValidationError

JOURNAL_TYPES = ("transfer", "write_off")
REASON_CODES = ("damage", "expiry", "theft", "loss", "sample", "other")
TYPE_CODE = "SJ"


def _fmt_date(value: date) -> str:
    return f"{value:%d-%m-%Y}"


@dataclass(frozen=True)
class JournalLineInput:
    """One journal line as entered; quantity is text or Decimal."""

    item_id: object
    from_godown_id: object
    to_godown_id: object
    quantity: object


@dataclass(frozen=True)
class JournalInput:
    journal_type: str
    journal_date: date
    narration: str
    reason_code: str | None
    reason_note: str | None
    lines: list[JournalLineInput]


@dataclass(frozen=True)
class JournalLine:
    """A checked line (quantity is a Decimal with 3 places)."""

    line_no: int
    item_id: object
    from_godown_id: object
    to_godown_id: object
    quantity: Decimal


@dataclass(frozen=True)
class JournalFacts:
    """What the rules need to know about the client: item id -> is_active (only stock items are present), godown id ->
    is_active, the financial years (start, end) and the periods (start, end, status)."""

    items: dict
    godowns: dict
    fy_ranges: list[tuple[date, date]]
    periods: list[tuple[date, date, str]] = field(default_factory=list)


def check_date(on: date, fy_ranges: list[tuple[date, date]], periods: list[tuple[date, date, str]], what: str) -> list[ValidationError]:
    """V-06 (inside a financial year) and V-07 (the period exists and is open); S-10 / S-20 use these ids for dates."""
    if not any(start <= on <= end for start, end in fy_ranges):
        return [ValidationError("V-06", f"{what} date {_fmt_date(on)} is not inside any financial year of this client.")]
    period = next(((s, e, st) for s, e, st in periods if s <= on <= e), None)
    if period is None:
        return [ValidationError("V-07", f"No period is defined for {_fmt_date(on)}; create the period before entering this journal.")]
    if period[2] == "locked":
        return [ValidationError("V-07", f"The period {_fmt_date(period[0])} to {_fmt_date(period[1])} is locked.")]
    return []


def validate_journal(journal: JournalInput, facts: JournalFacts) -> tuple[list[ValidationError], list[JournalLine]]:
    """S-10 (type, lines, godowns, reason), S-02, S-03, S-07, V-09, V-06, V-07. Returns (errors, checked lines); the
    lines are empty when there is any error."""
    errors: list[ValidationError] = []
    jtype = journal.journal_type
    if jtype not in JOURNAL_TYPES:
        errors.append(ValidationError("S-10", "The journal type must be transfer or write_off."))
    if not (journal.narration or "").strip():
        errors.append(ValidationError("V-09", "Narration is required."))
    errors.extend(check_date(journal.journal_date, facts.fy_ranges, facts.periods, "Journal"))
    if not journal.lines:
        errors.append(ValidationError("S-10", "A stock journal needs at least one line."))
    if jtype == "write_off":
        if journal.reason_code not in REASON_CODES:
            errors.append(ValidationError("S-10", "A write-off needs a reason: damage, expiry, theft, loss, sample or other."))
        if not (journal.reason_note or "").strip():
            errors.append(ValidationError("S-10", "A write-off needs a reason note explaining what happened."))
    elif jtype == "transfer" and (journal.reason_code or (journal.reason_note or "").strip()):
        errors.append(ValidationError("S-10", "A transfer carries no write-off reason."))
    lines: list[JournalLine] = []
    for number, line in enumerate(journal.lines, start=1):
        qty, qty_errors = validate_quantity(line.quantity, allow_zero=False, line_no=number)
        errors.extend(qty_errors)
        if facts.items.get(line.item_id) is not True:
            errors.append(ValidationError("S-03", f"Line {number}: the item is not an active stock item of this client.", number))
        if facts.godowns.get(line.from_godown_id) is not True:
            errors.append(ValidationError("S-07", f"Line {number}: the {'from-' if jtype == 'transfer' else ''}godown "
                                          "does not exist for this client or is inactive.", number))
        if jtype == "transfer":
            if line.to_godown_id is None:
                errors.append(ValidationError("S-10", f"Line {number}: a transfer needs a destination godown.", number))
            elif facts.godowns.get(line.to_godown_id) is not True:
                errors.append(ValidationError("S-07", f"Line {number}: the destination godown does not exist for this client "
                                              "or is inactive.", number))
            elif line.to_godown_id == line.from_godown_id:
                errors.append(ValidationError("S-10", f"Line {number}: the source and destination godown must be different.", number))
        elif jtype == "write_off" and line.to_godown_id is not None:
            errors.append(ValidationError("S-10", f"Line {number}: a write-off has no destination godown.", number))
        if qty is not None:
            lines.append(JournalLine(number, line.item_id, line.from_godown_id, line.to_godown_id, qty))
    return (errors, []) if errors else (errors, lines)


_STATE_MESSAGES = {
    ("update", "approved"): "An approved stock journal cannot be edited; it must go back to draft first.",
    ("update", "posted"): "A posted stock journal cannot be edited; reverse it instead.",
    ("update", "reversed"): "A reversed stock journal cannot be edited.",
    ("delete", "approved"): "An approved stock journal cannot be deleted.",
    ("delete", "posted"): "A posted stock journal cannot be deleted; reverse it instead.",
    ("delete", "reversed"): "A reversed stock journal cannot be deleted.",
}


def check_transition(status: str, action: str) -> str | None:
    """S-11 lifecycle Draft -> Approved -> Posted -> Reversed. Returns the plain-language refusal, or None when allowed."""
    if action in ("update", "delete"):
        return None if status == "draft" else _STATE_MESSAGES[(action, status)]
    if action == "approve":
        return None if status == "draft" else f"Only a draft stock journal can be approved (this one is {status})."
    if action == "post":
        return None if status == "approved" else f"Only an approved stock journal can be posted (this one is {status})."
    if action == "reverse":
        if status == "posted":
            return None
        if status == "reversed":
            return "This stock journal has already been reversed."
        return f"Only a posted stock journal can be reversed (this one is {status})."
    raise ValueError(f"unknown action {action!r}")


def validate_reversal(
    reason: str | None, reversal_date: date, *, journal_fy: tuple[date, date], fy_ranges: list[tuple[date, date]],
    periods: list[tuple[date, date, str]],
) -> list[ValidationError]:
    """S-11: a reason is required; the reversal date must be in the journal's own financial year (S-20) and an open period (V-07)."""
    errors: list[ValidationError] = []
    if not (reason or "").strip():
        errors.append(ValidationError("S-11", "A reason for the reversal is required."))
    date_errors = check_date(reversal_date, fy_ranges, [], "Reversal")[:1] if not any(s <= reversal_date <= e for s, e in fy_ranges) else []
    if date_errors:
        return errors + date_errors
    if not (journal_fy[0] <= reversal_date <= journal_fy[1]):
        errors.append(ValidationError("S-20", f"The reversal date {_fmt_date(reversal_date)} must be inside the financial year "
                                      f"of the journal ({_fmt_date(journal_fy[0])} to {_fmt_date(journal_fy[1])})."))
        return errors
    errors.extend(check_date(reversal_date, fy_ranges, periods, "Reversal"))
    return errors


@dataclass(frozen=True)
class PlannedMovement:
    """A movement a posted journal appends (cost is never stored: the valuation engine computes it)."""

    line_no: int
    kind: MovementKind
    item_id: object
    godown_id: object
    quantity: Decimal


def planned_movements(journal_type: str, lines: list[JournalLine]) -> list[PlannedMovement]:
    """Transfer: transfer_out (from) then transfer_in (to) per line. Write-off: one write_off (from) per line."""
    plan: list[PlannedMovement] = []
    for line in lines:
        if journal_type == "transfer":
            plan.append(PlannedMovement(line.line_no, MovementKind.TRANSFER_OUT, line.item_id, line.from_godown_id, line.quantity))
            plan.append(PlannedMovement(line.line_no, MovementKind.TRANSFER_IN, line.item_id, line.to_godown_id, line.quantity))
        else:
            plan.append(PlannedMovement(line.line_no, MovementKind.WRITE_OFF, line.item_id, line.from_godown_id, line.quantity))
    return plan


@dataclass(frozen=True)
class MirrorMovement:
    """S-17: the mirror of one movement: same item, godown and quantity, opposite direction, ref = the movement it reverses."""

    kind: MovementKind
    item_id: object
    godown_id: object
    quantity: Decimal
    ref_movement_id: object


def mirror_movements(originals: list[Movement]) -> list[MirrorMovement]:
    """An outward movement is mirrored by reversal_in, an inward one by reversal_out."""
    outward = {MovementKind.TRANSFER_OUT, MovementKind.WRITE_OFF}
    inward = {MovementKind.TRANSFER_IN}
    mirrors: list[MirrorMovement] = []
    for m in originals:
        if m.kind in outward:
            kind = MovementKind.REVERSAL_IN
        elif m.kind in inward:
            kind = MovementKind.REVERSAL_OUT
        else:
            raise ValueError(f"a {m.kind.value} movement does not come from a stock journal")
        mirrors.append(MirrorMovement(kind, m.item_id, m.godown_id, m.quantity, m.movement_id))
    return mirrors


def new_movement(on: date, seq: int, kind: MovementKind, item_id: object, godown_id: object, quantity: Decimal,
                 ref_movement_id: object = None) -> Movement:
    """A not-yet-stored movement (fresh id, the given seq) for the S-01 chain check."""
    return Movement(uuid.uuid4(), seq, on, item_id, godown_id, kind, quantity, None, ref_movement_id)


def check_stock_chain(
    policy: InventoryPolicy, fy_start: date, fy_end: date, opening: list[OpeningStock], existing: list[Movement],
    new: list[Movement], item_ids: set, names: dict | None = None,
) -> list[StockError]:
    """S-01 over the whole chronology of the year with the new movements added; only findings about `item_ids` (the
    items of this journal) are returned, so another item's old problem never blocks this journal. Severity follows the
    policy (block -> error, warn -> warning)."""
    result = compute_valuation(policy, fy_start, fy_end, opening, existing + new)
    out: list[StockError] = []
    for e in result.errors:
        if e.item_id not in item_ids:
            continue
        if e.rule_id == "S-01" and e.godown_id is None:
            continue  # the item-level "left out of valuation" note in warn mode; the godown finding carries the date
        message = e.message
        for key, name in (names or {}).items():
            message = message.replace(str(key), str(name))
        out.append(StockError(e.rule_id, message, e.severity, e.item_id, e.godown_id, e.movement_id, e.on_date))
    return out
