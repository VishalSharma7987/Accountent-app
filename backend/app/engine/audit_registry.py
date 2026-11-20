"""Check registry of the audit assistant (Phase 8, package A). Pure Python: no DB, web or AI imports.

Aggregates the three CHECKS dicts of packages B (books), C (compliance) and D (analytical): each maps a check id (A-nn) to a function
`check(facts: AuditFacts, params: AuditParams, rules: Sequence[LimitRule]) -> CheckResult`. The registry runs the selected checks, keeps one
failing check from stopping the run, refuses findings without evidence, and builds the run summary. Nothing here reads or changes the books.

`AuditFacts` is what a loader hands to every check: the client's ledgers and ALL non-draft vouchers (posted / reversed) of the financial year
(checks apply `params.from_date` / `params.to_date` themselves; A-04 needs the whole year), plus `extra`: facts a package's own loader adds
(`services/audit_load_books|compliance|analytic.load_extra`, see docs/PHASE8_API_CONTRACT.md "Package interfaces").
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine import audit_checks_analytic, audit_checks_books, audit_checks_compliance
from app.engine.audit_types import CHECKS as CATALOGUE
from app.engine.audit_types import AuditParams, CheckResult, LedgerFact, LimitRule, VoucherFact
from app.engine.money import MoneyError, parse_amount

VOUCHER_TYPES = ("contra", "payment", "receipt", "sales", "purchase", "credit_note", "debit_note", "journal")


@dataclass(frozen=True)
class AuditFacts:
    ledgers: Mapping[Any, LedgerFact]
    vouchers: tuple[VoucherFact, ...]
    extra: Mapping[str, Any] = field(default_factory=dict)

    def vouchers_in_period(self, params: AuditParams) -> tuple[VoucherFact, ...]:
        return tuple(v for v in self.vouchers if params.from_date <= v.voucher_date <= params.to_date)


CheckFn = Callable[[AuditFacts, AuditParams, Sequence[LimitRule]], CheckResult]


@dataclass(frozen=True)
class CheckOutcome:
    check_id: str
    result: CheckResult | None
    error: str | None = None


def _modules() -> dict[str, dict]:
    return {"books": audit_checks_books.CHECKS, "compliance": audit_checks_compliance.CHECKS, "analytic": audit_checks_analytic.CHECKS}


def all_checks() -> dict[str, CheckFn]:
    """Every registered check function by id. An id outside the catalogue or registered twice is a programming error."""
    merged: dict[str, CheckFn] = {}
    for checks in _modules().values():
        for check_id, fn in checks.items():
            if check_id not in CATALOGUE:
                raise ValueError(f"{check_id} is not in the catalogue")
            if check_id in merged:
                raise ValueError(f"{check_id} is registered twice")
            merged[check_id] = fn
    return merged


def module_of(check_id: str) -> str | None:
    """'books' | 'compliance' | 'analytic': which package registered the check (its loader supplies the check's extra facts)."""
    for name, checks in _modules().items():
        if check_id in checks:
            return name
    return None


def _validated(check_id: str, result: CheckResult) -> str | None:
    """The reason a result is refused, or None. Evidence is mandatory (the database refuses a finding without it too)."""
    keys: set[str] = set()
    for f in result.findings:
        if f.check_id != check_id:
            return f"check {check_id} returned finding {f.finding_key} that belongs to check {f.check_id}"
        if not f.evidence:
            return f"check {check_id} returned finding {f.finding_key} without evidence"
        if f.finding_key in keys:
            return f"check {check_id} returned finding key {f.finding_key} twice"
        keys.add(f.finding_key)
    return None


def execute(check_ids: Sequence[str], facts: AuditFacts, params: AuditParams, rules: Sequence[LimitRule],
            checks: Mapping[str, CheckFn] | None = None) -> list[CheckOutcome]:
    """Run the selected checks in id order. A check that raises, is missing or returns a bad result gets an error text; the others still run."""
    available = all_checks() if checks is None else checks
    out: list[CheckOutcome] = []
    for check_id in sorted(set(check_ids)):
        fn = available.get(check_id)
        if fn is None:
            out.append(CheckOutcome(check_id, None, f"check {check_id} is not available in this build"))
            continue
        try:
            result = fn(facts, params, rules)
        except Exception as exc:  # noqa: BLE001 - a failing check must not stop the run; its error is shown in the summary and the report
            out.append(CheckOutcome(check_id, None, f"check {check_id} failed: {type(exc).__name__}: {exc}"))
            continue
        problem = _validated(check_id, result)
        out.append(CheckOutcome(check_id, None, problem) if problem else CheckOutcome(check_id, result))
    return out


def finding_total(outcomes: Sequence[CheckOutcome]) -> int:
    return sum(len(o.result.findings) for o in outcomes if o.result)


def build_summary(outcomes: Sequence[CheckOutcome]) -> dict:
    by_check: dict[str, dict] = {}
    severity: Counter[str] = Counter()
    for o in outcomes:
        if o.result is None:
            by_check[o.check_id] = {"findings": 0, "population": 0, "notes": [], "error": o.error}
            continue
        by_check[o.check_id] = {"findings": len(o.result.findings), "population": len(o.result.population), "notes": list(o.result.notes)}
        severity.update(f.severity.value for f in o.result.findings)
    return {"by_check": by_check, "by_severity": dict(severity)}


# ---- run parameters and rule rows as plain JSON --------------------------------------------------------------------------------------

_INT_PARAMS = ("duplicate_window_days", "late_posting_days")
_AMOUNT_PARAMS = ("doc_min_amount", "round_unit", "round_min_amount", "variance_min_amount")
_POSITIVE = ("duplicate_window_days", "late_posting_days", "round_unit", "round_min_amount")


def params_from_input(from_date: date, to_date: date, raw: Mapping[str, Any] | None) -> AuditParams:
    """AuditParams from the request's optional `params`; anything unknown or unclear is refused (ValueError), nothing is defaulted silently."""
    raw = dict(raw or {})
    values: dict[str, Any] = {}
    for key in _INT_PARAMS:
        if key in raw:
            v = raw.pop(key)
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(f"{key} must be a whole number of days")
            values[key] = v
    for key in (*_AMOUNT_PARAMS, "variance_band_percent"):
        if key in raw:
            try:
                values[key] = parse_amount(raw.pop(key))
            except MoneyError as exc:
                raise ValueError(f"{key}: {exc}") from None
    if "doc_required_types" in raw:
        types = raw.pop("doc_required_types")
        if not isinstance(types, (list, tuple)) or not all(isinstance(x, str) and x in VOUCHER_TYPES for x in types):
            raise ValueError("doc_required_types must be a list of voucher types")
        values["doc_required_types"] = tuple(types)
    if raw:
        raise ValueError("unknown parameter: " + ", ".join(sorted(raw)))
    for key in _POSITIVE:
        if key in values and values[key] <= 0:
            raise ValueError(f"{key} must be greater than zero")
    return AuditParams(from_date, to_date, **values)


def params_to_dict(p: AuditParams) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in vars(p).items():
        if isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = f"{v:.2f}"
        elif isinstance(v, tuple):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def rule_to_dict(r: LimitRule) -> dict[str, Any]:
    return {
        "rule_key": r.rule_key, "law": r.law, "section_ref": r.section_ref, "amount": f"{r.amount:.2f}", "breach_when": r.breach_when,
        "disallow_percent": None if r.disallow_percent is None else f"{r.disallow_percent:.2f}",
        "effective_from": r.effective_from.isoformat(), "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "verification_status": r.verification_status,
    }
