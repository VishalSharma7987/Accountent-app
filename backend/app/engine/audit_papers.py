"""Audit working-paper rules W-01 .. W-06 (docs/PHASE8_PLAN.md, package E). Pure Python: no database, web or model imports.

The engine only checks; it never decides an audit conclusion. A reviewer clears or confirms each exception (who, when, why) and writes the
conclusion; the database repeats these guards by trigger (migration 0019), the service turns a PaperError into a ServiceError.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.engine.audit_types import PAPER_TRANSITIONS, ItemStatus, PaperStatus, population_digest
from app.engine.money import TWO_PLACES


class PaperError(ValueError):
    """A refused working-paper action. `rule_id` is W-nn, `code` is the stable service error code."""

    def __init__(self, rule_id: str, code: str, message: str):
        super().__init__(message)
        self.rule_id = rule_id
        self.code = code
        self.message = message


def _status(value: object) -> PaperStatus:
    return PaperStatus(str(value))


def check_move(old: str, new: str) -> None:
    """W-04: open -> in_review -> signed_off; back from in_review to open; signed_off is terminal."""
    if _status(old) == PaperStatus.SIGNED_OFF:
        raise PaperError("W-05", "paper_signed_off", "This working paper is signed off and cannot be changed.")
    if _status(new) not in PAPER_TRANSITIONS[_status(old)]:
        raise PaperError("W-04", "paper_status_invalid", f"A working paper cannot move from {old} to {new}.")


def check_editable(status: str) -> None:
    """W-05 / W-06: after sign-off nothing on the paper, its items, its sample or its notes changes."""
    if _status(status) == PaperStatus.SIGNED_OFF:
        raise PaperError("W-05", "paper_signed_off", "This working paper is signed off: it, its exceptions and its notes cannot be changed.")


check_sample_allowed = check_editable


def check_decision(status: str, reviewer_note: str | None) -> None:
    """W-03: an exception is cleared or confirmed, with a reason; the decider and time are recorded by the service."""
    if status not in (ItemStatus.CLEARED.value, ItemStatus.CONFIRMED.value):
        raise PaperError("W-03", "invalid_decision", "An exception is decided as 'cleared' (not an issue) or 'confirmed' (a real exception).")
    if not (reviewer_note or "").strip():
        raise PaperError("W-03", "decision_reason_required",
                         "Write the reason for this decision (what you checked and why it is cleared or confirmed).")


def check_sign_off(status: str, item_statuses: Sequence[str], conclusion: str | None) -> None:
    """W-05: sign off only from in_review, with every exception decided and the reviewer's own conclusion."""
    check_move(status, PaperStatus.SIGNED_OFF.value)
    still_open = sum(1 for s in item_statuses if s == ItemStatus.OPEN.value)
    if still_open:
        noun = "exception is" if still_open == 1 else "exceptions are"
        raise PaperError("W-05", "open_exceptions",
                         f"{still_open} {noun} still open: clear or confirm each one, with a reason, before sign-off.")
    if not (conclusion or "").strip():
        raise PaperError("W-05", "invalid_conclusion", "Write your conclusion on this working paper before signing it off.")


@dataclass(frozen=True)
class Population:
    """What a sample is drawn from. `source` is 'run' (ids the run stored for the check) or 'findings' (the run stored only
    a count, so the exceptions themselves are the population)."""

    ids: tuple[str, ...]
    count: int
    digest: str | None
    amount: Decimal | None
    amounts: Mapping[str, Decimal]
    source: str


def _q(value: object) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES)   # values from the database carry 4 decimals; they are exact 2-decimal amounts


def resolve_population(summary_entry: Mapping[str, Any] | None, findings: Sequence[tuple[object, Decimal | None]]) -> Population:
    """W-01: the paper's population. Uses `population_ids` (and optional `population_amounts` / `population_amount`) from the run's
    per-check summary when the run stored them; otherwise the check's findings are the population, and the source says so."""
    entry = summary_entry or {}
    ids = entry.get("population_ids")
    if isinstance(ids, list) and ids:
        pop_ids = tuple(sorted(str(i) for i in ids))
        raw = entry.get("population_amounts")
        amounts = {str(k): _q(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        if entry.get("population_amount") is not None:
            total: Decimal | None = _q(entry["population_amount"])
        else:
            total = sum(amounts.values(), Decimal("0.00")) if amounts else None
        return Population(pop_ids, len(pop_ids), population_digest(pop_ids), total, amounts, "run")
    amounts = {str(i): _q(a) for i, a in findings if a is not None}
    pop_ids = tuple(sorted(str(i) for i, _ in findings))
    total = sum(amounts.values(), Decimal("0.00")) if amounts else None
    return Population(pop_ids, len(pop_ids), population_digest(pop_ids) if pop_ids else None, total, amounts, "findings")
