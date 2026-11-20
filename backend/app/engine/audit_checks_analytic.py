"""Analytical and related-party checks A-15, A-18. Pure functions over plain facts (engine/audit_types.py); no DB, web or AI imports.

Each entry of CHECKS maps a check id to a function (facts: AnalyticFacts, params: AuditParams, rules) -> CheckResult; package A aggregates
the three CHECKS dicts and builds `AnalyticFacts` with `services.audit_load_analytic.load_analytic_facts`. Neither check needs a legal limit
(`rules` is accepted for the common signature and not read). Thresholds (minimum change, variance band) come only from `AuditParams`.

A-15: per ledger, the net movement (debits minus credits, so a credit balance is negative) of the run period is compared with the same
period one year earlier. Flag when the absolute change is at or above `variance_min_amount` AND the change is more than
`variance_band_percent` of the previous year's absolute movement. When the previous year had no movement there is no ratio: the ledger is
flagged on the amount alone and the finding says so (never a made-up percentage).
A-18: per active flagged ledger, its live postings (reversed vouchers and their reversal vouchers are left out) in the period.
"""

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine.audit_types import CHECKS as CATALOGUE
from app.engine.audit_types import (
    ZERO,
    AuditParams,
    CheckResult,
    Finding,
    LimitRule,
    VoucherFact,
    finding_key,
)
from app.engine.money import format_inr, round_half_up

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class LedgerTotals:
    """Net movement (debit minus credit) of one ledger in this period and in the same period one year earlier."""

    ledger_id: Any
    name: str
    group_code: str
    this_year: Decimal
    previous_year: Decimal


@dataclass(frozen=True)
class RelatedLedger:
    ledger_id: Any
    name: str
    relationship: str
    active: bool


@dataclass(frozen=True)
class AnalyticFacts:
    ledger_totals: tuple[LedgerTotals, ...]
    related: tuple[RelatedLedger, ...]
    vouchers: tuple[VoucherFact, ...]   # non-draft vouchers touching the flagged ledgers (any dates; the check applies the period)
    previous_from: date
    previous_to: date


def _shift_year(d: date, years: int) -> date:
    day = min(d.day, calendar.monthrange(d.year + years, d.month)[1])
    return date(d.year + years, d.month, day)


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same dates one year earlier (29 February becomes 28 February). For a full financial year this is the previous one."""
    return _shift_year(from_date, -1), _shift_year(to_date, -1)


def _s(value: Decimal) -> str:
    return str(round_half_up(value, 2))


def _dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _drcr(value: Decimal) -> str:
    return f"{format_inr(abs(value))} {'Dr' if value >= 0 else 'Cr'}"


def check_unusual_movement(facts: AnalyticFacts, params: AuditParams, rules: Sequence[LimitRule]) -> CheckResult:
    if params.variance_min_amount < 0 or params.variance_band_percent < 0:
        raise ValueError("The minimum change and the variance band must not be negative.")
    info = CATALOGUE["A-15"]
    findings: list[Finding] = []
    population: list[Any] = []
    pop_amount = ZERO
    for lt in facts.ledger_totals:
        if lt.this_year == 0 and lt.previous_year == 0:
            continue
        population.append(lt.ledger_id)
        pop_amount += abs(lt.this_year)
        change = lt.this_year - lt.previous_year
        if abs(change) < params.variance_min_amount:
            continue
        prev_abs = abs(lt.previous_year)
        percent: Decimal | None = None
        if prev_abs == 0:
            reason = "there was no movement in the previous year, so no percentage can be worked out"
        else:
            exact = abs(change) * HUNDRED / prev_abs   # compared unrounded; only the shown figure is rounded
            if exact <= params.variance_band_percent:
                continue
            percent = round_half_up(exact, 2)
            reason = f"{percent}% against the previous year, more than the {_s(params.variance_band_percent)}% band"
        word = "rose" if abs(lt.this_year) > prev_abs else "fell"
        message = (f"Movement in {lt.name} {word} from {_drcr(lt.previous_year)} in the previous year to {_drcr(lt.this_year)} this year "
                   f"(change {format_inr(abs(change))}); {reason}. Minimum change for this check is {format_inr(params.variance_min_amount)}.")
        findings.append(Finding(
            check_id="A-15", finding_key=finding_key("A-15", lt.ledger_id), severity=info.severity, subject_kind="ledger",
            subject_ref=lt.name, message=message, subject_id=lt.ledger_id, finding_date=params.to_date, amount=abs(change),
            evidence={
                "ledger_id": str(lt.ledger_id), "ledger": lt.name, "group": lt.group_code,
                "this_year": _s(lt.this_year), "previous_year": _s(lt.previous_year), "change": _s(change),
                "change_percent": None if percent is None else str(percent),
                "min_change": _s(params.variance_min_amount), "band_percent": _s(params.variance_band_percent),
                "from": params.from_date.isoformat(), "to": params.to_date.isoformat(),
                "previous_from": facts.previous_from.isoformat(), "previous_to": facts.previous_to.isoformat(),
            }))
    return CheckResult("A-15", tuple(findings), tuple(population), pop_amount)


def check_related_party(facts: AnalyticFacts, params: AuditParams, rules: Sequence[LimitRule]) -> CheckResult:
    info = CATALOGUE["A-18"]
    live = [v for v in facts.vouchers
            if v.status == "posted" and v.reverses_voucher_id is None and params.from_date <= v.voucher_date <= params.to_date]
    findings: list[Finding] = []
    notes: list[str] = []
    population: list[Any] = []
    pop_amount = ZERO
    for rel in facts.related:
        if not rel.active:
            continue
        mine = sorted((v for v in live if any(ln.ledger_id == rel.ledger_id for ln in v.lines)), key=lambda v: (v.voucher_date, str(v.id)))
        if not mine:
            notes.append(f"{rel.name} is flagged as a related party but has no postings between {_dmy(params.from_date)} and {_dmy(params.to_date)}.")
            continue
        dr = sum((ln.debit for v in mine for ln in v.lines if ln.ledger_id == rel.ledger_id), ZERO)
        cr = sum((ln.credit for v in mine for ln in v.lines if ln.ledger_id == rel.ledger_id), ZERO)
        ids = [str(v.id) for v in mine]
        population.extend(v.id for v in mine)
        pop_amount += dr + cr
        message = (f"Related party {rel.name} ({rel.relationship}): {len(mine)} voucher(s) between {_dmy(params.from_date)} and "
                   f"{_dmy(params.to_date)}, debits {format_inr(dr)} and credits {format_inr(cr)}.")
        findings.append(Finding(
            check_id="A-18", finding_key=finding_key("A-18", rel.ledger_id), severity=info.severity, subject_kind="ledger",
            subject_ref=rel.name, message=message, subject_id=rel.ledger_id, finding_date=params.to_date, amount=dr + cr,
            evidence={
                "ledger_id": str(rel.ledger_id), "ledger": rel.name, "relationship": rel.relationship, "voucher_ids": ids,
                "voucher_count": len(mine), "total_debit": _s(dr), "total_credit": _s(cr),
                "vouchers": [{"id": str(v.id), "type": v.voucher_type, "number": v.voucher_number, "date": v.voucher_date.isoformat()} for v in mine],
                "from": params.from_date.isoformat(), "to": params.to_date.isoformat(),
            }))
    return CheckResult("A-18", tuple(findings), tuple(population), pop_amount, tuple(notes))


def _for_registry(check):
    """The registry (package A) passes its `AuditFacts`; this package's loader puts its own facts in `facts.extra["analytic"]`.
    A bare `AnalyticFacts` (the direct unit tests) is passed through unchanged."""

    def run(facts, params, rules):
        own = facts.extra["analytic"] if hasattr(facts, "extra") else facts
        return check(own, params, rules)

    run.__name__ = check.__name__
    run.__doc__ = check.__doc__
    return run


CHECKS: dict = {"A-15": _for_registry(check_unusual_movement), "A-18": _for_registry(check_related_party)}
