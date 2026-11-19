"""Fixed asset register and Companies Act book depreciation (Phase 6, package B; rules F-20 .. F-27). Pure Python: no DB, web or AI imports.

An asset is a list of events (opening / purchase / addition / disposal). Each cost event is its own TRANCHE (F-23): same life and method,
residual value in the same percentage of cost as the asset's first cost event. Depreciation of a financial year is computed from the put
to use date (or the FY start) to the FY end (or the disposal date), both days counted, and earlier years are replayed from the start
date so the opening accumulated depreciation of a year is always consistent with the same rule (the opening event carries the
accumulated depreciation brought forward at the first day of its financial year).

Rates and lives are never hardcoded: Schedule II rows arrive as `Sched2Rule`, picked by date with `pick_rule` (law is data).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from app.engine.final_types import (
    ZERO,
    AssetBookSetup,
    AssetEvent,
    BookDepreciationLine,
    EventKind,
    Finding,
    JournalLineDraft,
)
from app.engine.gst_masters import in_force
from app.engine.money import format_inr, round_half_up

_START_KINDS = (EventKind.OPENING, EventKind.PURCHASE)
_COST_KINDS = (EventKind.OPENING, EventKind.PURCHASE, EventKind.ADDITION)


class AmbiguousRule(ValueError):
    """Two rows of a rule table are in force for the same key and date: never guessed."""


@dataclass(frozen=True)
class Sched2Rule:
    """A Companies Act Schedule II class row (dep_sched2_classes)."""

    class_key: str
    description: str
    useful_life_years: Decimal
    max_residual_percent: Decimal
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_reference: str


def pick_rule(rows, on: date):
    """The one row of `rows` (already filtered to one key) in force on `on`; None when there is none; AmbiguousRule for two."""
    found = [r for r in rows if in_force(r.effective_from, r.effective_to, on)]
    if len(found) > 1:
        raise AmbiguousRule("more than one rule row is in force on the same date")
    return found[0] if found else None


# ================================================================================================== day counts and rates


def days_inclusive(a: date, b: date) -> int:
    """Number of days from a to b with both days counted (01-10-2026 to 31-03-2027 = 182)."""
    return (b - a).days + 1


def days_in_year(fy_start: date, fy_end: date) -> int:
    return days_inclusive(fy_start, fy_end)


def wdv_rate_percent(cost: Decimal, residual: Decimal, life: Decimal) -> Decimal:
    """F-23: rate % = round_half_up((1 - (residual / cost) ^ (1 / life)) x 100, 2). Needs 0 < residual < cost and life > 0."""
    if not (cost > 0 and 0 < residual < cost and life > 0):
        raise ValueError("a WDV rate needs a residual value above zero and below the cost, and a life above zero")
    with localcontext() as ctx:
        ctx.prec = 50
        root = (residual / cost) ** (Decimal(1) / life)
        return round_half_up((Decimal(1) - root) * 100, 2)


# ================================================================================================== setup and event rules


def _f(rule_id: str, message: str, severity: str = "error") -> Finding:
    return Finding(rule_id, message, severity)


def _d(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def validate_asset_setup(*, is_depreciable: bool, it_block_key: str | None, method: str | None, life: Decimal | None,
                         residual: Decimal, class_rule: Sched2Rule | None, override_reason: str | None) -> list[Finding]:
    """F-20 / F-23 / F-24 on the setup of an asset (no cost known yet; see residual_findings for the cost-dependent checks)."""
    out: list[Finding] = []
    if residual < 0:
        out.append(_f("F-20", "The residual value cannot be negative."))
    if not is_depreciable:
        return out
    reason = (override_reason or "").strip()
    if not (it_block_key or "").strip():
        out.append(_f("F-20", "A depreciable asset needs an income-tax block (for example furniture_fittings)."))
    if life is None or life <= 0:
        out.append(_f("F-20", "A depreciable asset needs a useful life in years above zero."))
    if method not in ("slm", "wdv"):
        out.append(_f("F-20", "A depreciable asset needs a book method: slm or wdv."))
    if class_rule is None and not reason:
        out.append(_f("F-20", "A depreciable asset needs a Schedule II class, or a reason for the life you typed."))
    if method == "wdv" and residual <= 0:
        out.append(_f("F-23", "Written down value depreciation needs a residual value above zero (with no residual the rate would be 100%)."))
    if class_rule is not None and life is not None and life > 0 and life != class_rule.useful_life_years:
        shown = f"{life.normalize():f}"
        if reason:
            out.append(_f("F-24", f"Useful life {shown} years differs from Schedule II class '{class_rule.class_key}' "
                                  f"({class_rule.useful_life_years.normalize():f} years). Reason on record: {reason}.", "warning"))
        else:
            out.append(_f("F-24", f"Useful life {shown} years differs from Schedule II class '{class_rule.class_key}' "
                                  f"({class_rule.useful_life_years.normalize():f} years): give the reason for the different life."))
    return out


def residual_findings(cost: Decimal, residual: Decimal, class_rule: Sched2Rule | None) -> list[Finding]:
    """F-24: residual value above the class ceiling is a warning; a residual that is not below the cost is an error (F-23)."""
    out: list[Finding] = []
    if residual >= cost:
        out.append(_f("F-23", f"The residual value {format_inr(residual)} must be less than the cost {format_inr(cost)}."))
    elif class_rule is not None:
        ceiling = round_half_up(cost * class_rule.max_residual_percent / 100, 2)
        if residual > ceiling:
            out.append(_f("F-24", f"The residual value {format_inr(residual)} is above {class_rule.max_residual_percent.normalize():f}% "
                                  f"of the cost ({format_inr(ceiling)}), the ceiling of Schedule II. Check the reason.", "warning"))
    return out


def validate_event(existing: list[AssetEvent], new: AssetEvent) -> list[Finding]:
    """F-21 / F-22: may `new` be added to an asset that already has the `existing` events?"""
    out: list[Finding] = []
    starts = [e for e in existing if e.kind in _START_KINDS]
    disposals = [e for e in existing if e.kind == EventKind.DISPOSAL]
    if new.kind == EventKind.DISPOSAL:
        if new.amount < 0:
            out.append(_f("F-22", "The sale proceeds cannot be negative."))
        if disposals:
            out.append(_f("F-21", "This asset has already been disposed of: only one disposal is allowed."))
        cost_events = [e for e in existing if e.kind in _COST_KINDS and e.put_to_use_date is not None]
        if not cost_events:
            out.append(_f("F-21", "An asset cannot be disposed of before it was acquired."))
        else:
            last_use = max(e.put_to_use_date for e in cost_events)
            if new.event_date < last_use:
                out.append(_f("F-21", f"The disposal date {_d(new.event_date)} is before the asset was put to use ({_d(last_use)})."))
        return out
    # cost events
    if new.amount <= 0:
        out.append(_f("F-21", "The cost must be above zero."))
    if new.put_to_use_date is None:
        out.append(_f("F-21", "The put-to-use date is required (it decides the half-rate rule and the part-year depreciation)."))
    elif new.kind != EventKind.OPENING and new.put_to_use_date < new.event_date:
        out.append(_f("F-21", f"The put-to-use date {_d(new.put_to_use_date)} cannot be before the purchase date {_d(new.event_date)}."))
    if new.kind == EventKind.OPENING and (new.event_date.month, new.event_date.day) != (4, 1):
        out.append(_f("F-21", f"An opening event must be dated the first day of a financial year (01-04-yyyy), not {_d(new.event_date)}: "
                              "the accumulated depreciation brought forward is taken as at that date."))
    if new.kind in _START_KINDS and starts:
        out.append(_f("F-21", "This asset already has an opening or purchase event: record later cost as an addition."))
    if new.kind == EventKind.ADDITION and not any(s.event_date <= new.event_date for s in starts):
        out.append(_f("F-21", "An addition needs an earlier opening or purchase event of the same asset."))
    if any(d.event_date < new.event_date for d in disposals):
        out.append(_f("F-21", f"No event can be dated after the asset was disposed of ({_d(disposals[0].event_date)})."))
    return out


# ================================================================================================== the replay


@dataclass(frozen=True)
class TrancheYear:
    index: int                       # position among the cost events (sorted by date)
    cost: Decimal
    residual: Decimal
    put_to_use_date: date
    days: int
    opening_accumulated: Decimal
    depreciation: Decimal
    closing_accumulated: Decimal
    capped: bool
    disposed_in_year: bool


def _prev_year(ws: date, we: date) -> tuple[date, date]:
    return ws.replace(year=ws.year - 1), ws - timedelta(days=1)


def _cost_events(setup: AssetBookSetup) -> list[AssetEvent]:
    return sorted((e for e in setup.events if e.kind in _COST_KINDS), key=lambda e: (e.event_date, e.kind != EventKind.OPENING))


def _disposal_date(setup: AssetBookSetup) -> date | None:
    d = [e.event_date for e in setup.events if e.kind == EventKind.DISPOSAL]
    return d[0] if d else None


def _tranche_residual(setup: AssetBookSetup, events: list[AssetEvent], i: int) -> Decimal:
    first = events[0].amount
    if i == 0:
        return setup.residual_value
    return round_half_up(events[i].amount * setup.residual_value / first, 2)


def _year_dep(method: str, cost: Decimal, residual: Decimal, life: Decimal, acc: Decimal, days: int, diy: int,
              rate: Decimal | None) -> tuple[Decimal, bool]:
    """(depreciation, capped) of one tranche for one financial year."""
    if method == "slm":
        raw = round_half_up((cost - residual) * days / (life * diy), 2)
    else:
        raw = round_half_up((cost - acc) * rate / 100 * days / diy, 2)
    room = max(cost - residual - acc, ZERO)
    return (room, True) if raw > room else (raw, False)


def _replay(setup: AssetBookSetup, i: int, events: list[AssetEvent], fy_start: date, fy_end: date) -> TrancheYear | None:
    """The tranche's year (None: not started yet, or gone because the asset was disposed of before the year)."""
    e = events[i]
    ptu = e.put_to_use_date
    disposal = _disposal_date(setup)
    life = setup.useful_life_years
    start = e.event_date if e.kind == EventKind.OPENING else ptu
    if start > fy_end:
        return None
    residual = _tranche_residual(setup, events, i)
    rate = wdv_rate_percent(events[0].amount, setup.residual_value, life) if setup.method == "wdv" else None
    # windows from the financial year containing `start` up to the target year
    windows = [(fy_start, fy_end)]
    while windows[0][0] > start:
        windows.insert(0, _prev_year(*windows[0]))
    acc = e.accumulated_dep_bf if e.kind == EventKind.OPENING else ZERO
    result: TrancheYear | None = None
    for ws, we in windows:
        if disposal is not None and disposal < ws:
            return None
        begin = max(ptu, ws)
        end = min(disposal, we) if disposal is not None else we
        days = days_inclusive(begin, end) if end >= begin else 0
        diy = days_in_year(ws, we)
        dep, capped = _year_dep(setup.method, e.amount, residual, life, acc, days, diy, rate)
        closing = acc + dep
        if (ws, we) == (fy_start, fy_end):
            result = TrancheYear(i, e.amount, residual, ptu, days, acc, dep, closing, capped,
                                 disposal is not None and ws <= disposal <= we)
        acc = closing
    return result


def _tranches(setup: AssetBookSetup, fy_start: date, fy_end: date) -> list[TrancheYear]:
    if setup.method not in ("slm", "wdv") or setup.useful_life_years is None or setup.useful_life_years <= 0:
        raise ValueError("the asset has no valid book method and life")
    events = _cost_events(setup)
    if not events:
        return []
    out = []
    for i in range(len(events)):
        t = _replay(setup, i, events, fy_start, fy_end)
        if t is not None:
            out.append(t)
    return out


# ================================================================================================== book depreciation of one asset


def book_depreciation(setup: AssetBookSetup, fy_start: date, fy_end: date) -> list[BookDepreciationLine]:
    """F-23 / F-25 / F-27: the asset's line for the year (a list of 0 or 1 lines; none for a non-depreciable asset, an asset not yet
    put to use, or an asset disposed of before the year)."""
    if not setup.is_depreciable:
        return []
    tranches = _tranches(setup, fy_start, fy_end)
    if not tranches:
        return []
    events = _cost_events(setup)
    rate = wdv_rate_percent(events[0].amount, setup.residual_value, setup.useful_life_years) if setup.method == "wdv" else None
    disposal = _disposal_date(setup)
    details: dict[str, Any] = {
        "life_years": f"{setup.useful_life_years.normalize():f}",
        "residual_value": f"{setup.residual_value:.2f}",
        "disposed_on": disposal.isoformat() if disposal else None,
        "capped": any(t.capped for t in tranches),
        "tranches": [{
            "cost": f"{t.cost:.2f}", "residual": f"{t.residual:.2f}", "put_to_use_date": t.put_to_use_date.isoformat(),
            "days": t.days, "opening_accumulated": f"{t.opening_accumulated:.2f}", "depreciation": f"{t.depreciation:.2f}",
        } for t in tranches],
    }
    return [BookDepreciationLine(
        asset_id=setup.asset_id, method=setup.method, cost=sum((t.cost for t in tranches), ZERO),
        opening_accumulated=sum((t.opening_accumulated for t in tranches), ZERO), wdv_rate_percent=rate,
        days_used=tranches[0].days, days_in_year=days_in_year(fy_start, fy_end),
        depreciation=sum((t.depreciation for t in tranches), ZERO), closing_accumulated=sum((t.closing_accumulated for t in tranches), ZERO),
        details=details)]


# ================================================================================================== disposal working (F-22)


@dataclass(frozen=True)
class DisposalWorking:
    proceeds: Decimal
    book_value: Decimal
    profit_or_loss: Decimal      # proceeds - book value; a loss is negative


def disposal_working(cost: Decimal, accumulated: Decimal, proceeds: Decimal) -> DisposalWorking:
    """F-22: profit / loss on sale = proceeds - (cost - accumulated book depreciation to the disposal date). A working only."""
    book_value = round_half_up(cost - accumulated, 2)
    return DisposalWorking(round_half_up(proceeds, 2), book_value, round_half_up(proceeds - book_value, 2))


# ================================================================================================== register row


@dataclass(frozen=True)
class RegisterRow:
    opening_cost: Decimal
    additions: Decimal
    disposals_cost: Decimal
    closing_cost: Decimal
    opening_accumulated: Decimal
    depreciation: Decimal
    disposal_accumulated: Decimal
    closing_accumulated: Decimal
    net_block: Decimal
    put_to_use_dates: tuple[date, ...] = field(default_factory=tuple)


def register_row(setup: AssetBookSetup, fy_start: date, fy_end: date) -> RegisterRow | None:
    """The book view of one asset for the year (None when the asset was not in the books during the year)."""
    events = _cost_events(setup)
    disposal = _disposal_date(setup)
    if not events or events[0].event_date > fy_end or (disposal is not None and disposal < fy_start):
        return None
    by_index = {t.index: t for t in _tranches(setup, fy_start, fy_end)} if setup.is_depreciable else {}
    opening_cost = additions = ZERO
    opening_acc = dep = ZERO
    for i, e in enumerate(events):
        if e.event_date > fy_end:
            continue
        if e.event_date < fy_start or (e.kind == EventKind.OPENING and e.event_date == fy_start):
            opening_cost += e.amount
        else:
            additions += e.amount
        t = by_index.get(i)
        if t is not None:
            opening_acc += t.opening_accumulated
            dep += t.depreciation
        elif e.kind == EventKind.OPENING:
            opening_acc += e.accumulated_dep_bf          # a non-depreciable asset keeps what was brought forward
    in_books = opening_cost + additions
    disposed = disposal is not None and fy_start <= disposal <= fy_end
    disposals_cost = in_books if disposed else ZERO
    gross_acc = opening_acc + dep
    disposal_acc = gross_acc if disposed else ZERO
    closing_cost = in_books - disposals_cost
    closing_acc = gross_acc - disposal_acc
    return RegisterRow(opening_cost, additions, disposals_cost, closing_cost, opening_acc, dep, disposal_acc, closing_acc,
                       closing_cost - closing_acc, tuple(e.put_to_use_date for e in events if e.put_to_use_date))


# ================================================================================================== the journal (F-26)


def depreciation_journal_lines(lines: list[BookDepreciationLine], expense_ledger_id: Any,
                               credit_ledger_by_asset: dict[Any, Any]) -> list[JournalLineDraft]:
    """F-26: one Dr line to the depreciation expense ledger for the total, one Cr line per accumulated-depreciation ledger (summed over
    the assets that use it; the asset ledger itself when the asset has no accumulated ledger). Zero lines are left out."""
    credits: dict[Any, Decimal] = {}
    for line in lines:
        if line.depreciation > 0:
            ledger = credit_ledger_by_asset[line.asset_id]
            credits[ledger] = credits.get(ledger, ZERO) + line.depreciation
    total = sum(credits.values(), ZERO)
    if total <= 0:
        return []
    return [JournalLineDraft(expense_ledger_id, debit=total)] + [JournalLineDraft(ledger, credit=amount) for ledger, amount in credits.items()]
