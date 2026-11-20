"""Books checks A-01..A-06, A-12, A-13, A-14 (Phase 8, package B). Pure functions over plain facts (engine/audit_types.py + BooksFacts below);
no DB, web or AI imports. The audit only reads: a check never changes a voucher.

CHECKS maps a check id to `fn(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule]) -> CheckResult`. Package A's registry calls
them with the facts built by `services/audit_load_books.load_books_facts`.

Conventions (docs/decisions_parts/B8.md): a "live" voucher is posted and is not a reversal voucher (a reversed original and its reversal cancel
each other and are ignored by A-01, A-02, A-03, A-05, A-06, A-12). A-13 and A-14 look at every posted or reversed voucher. All checks except
A-04 examine vouchers dated inside [params.from_date, params.to_date]; A-04 always looks at the whole financial year (a gap is a gap
whatever period is being audited).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.engine.audit_types import (
    CHECKS as CATALOGUE,
)
from app.engine.audit_types import (
    ZERO,
    AuditParams,
    CheckResult,
    Finding,
    LimitRule,
    VoucherFact,
    breaches,
    finding_key,
    is_sunday,
    pick_limit,
)
from app.engine.duplicates import TYPE_LABELS
from app.engine.money import format_inr, round_half_up

IST = timezone(timedelta(hours=5, minutes=30))
CASH_GROUP = "cash_in_hand"
CASH_BANK_GROUPS = ("cash_in_hand", "bank_accounts")
LISTED_DATES = 10


@dataclass(frozen=True)
class PeriodFact:
    id: Any
    start: date
    end: date


@dataclass(frozen=True)
class LockEvent:
    """One `lock` / `unlock` row of audit_log for a period (entity `period`)."""

    log_id: Any
    period_id: Any
    action: str          # lock | unlock
    at: datetime
    actor: str
    reason: str | None = None


@dataclass(frozen=True)
class BooksFacts:
    vouchers: tuple[VoucherFact, ...]                      # every non-draft voucher of the financial year, with lines
    ledgers: tuple = ()                                    # LedgerFact
    document_voucher_ids: frozenset = frozenset()          # vouchers that have a document_vouchers link (A-03)
    number_counters: Mapping[str, int] = field(default_factory=dict)   # voucher_type -> voucher_number_sequences.last_number (A-04)
    holidays: Mapping[date, str] = field(default_factory=dict)         # audit_holidays: date -> name (A-13)
    periods: tuple[PeriodFact, ...] = ()
    lock_events: tuple[LockEvent, ...] = ()


# ---- small helpers ----------------------------------------------------------------------------------------------------------------------


def _d(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _s(amount: Decimal) -> str:
    return format(amount, "f")


def _label(voucher_type: str) -> str:
    return TYPE_LABELS.get(voucher_type, voucher_type)


def _ref(v: VoucherFact) -> str:
    return v.voucher_number or str(v.id)


def _is_live(v: VoucherFact) -> bool:
    return v.status == "posted" and v.reverses_voucher_id is None


def _in_period(v: VoucherFact, p: AuditParams) -> bool:
    return p.from_date <= v.voucher_date <= p.to_date


def _sorted(vs: Sequence[VoucherFact]) -> list[VoucherFact]:
    return sorted(vs, key=lambda v: (v.voucher_date, str(v.id)))


def _ist_date(moment: datetime) -> date:
    return moment.astimezone(IST).date() if moment.tzinfo else moment.date()


def normalise_reference(reference_no: str | None) -> str:
    """Bill number compared ignoring case, spaces and punctuation: 'INV-17' and 'inv 17 ' are the same bill."""
    return "".join(ch for ch in (reference_no or "").casefold() if ch.isalnum())


def _names(facts: BooksFacts) -> dict[Any, str]:
    return {ln.id: ln.name for ln in facts.ledgers}


def _group_of(facts: BooksFacts) -> dict[Any, str]:
    return {ln.id: ln.group_code for ln in facts.ledgers}


def _voucher_finding(check_id: str, v: VoucherFact, message: str, evidence: dict[str, Any]) -> Finding:
    return Finding(
        check_id, finding_key(check_id, v.id), CATALOGUE[check_id].severity, "voucher", _ref(v), message, evidence,
        subject_id=v.id, finding_date=v.voucher_date, amount=v.total,
    )


# ---- A-01 duplicate bills ---------------------------------------------------------------------------------------------------------------


def check_a01(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    names = _names(facts)
    pool = [v for v in facts.vouchers if _is_live(v) and v.voucher_type == "purchase" and _in_period(v, params)
            and v.party_ledger_id is not None and normalise_reference(v.reference_no)]
    groups: dict[tuple, list[VoucherFact]] = defaultdict(list)
    for v in pool:
        groups[(v.party_ledger_id, normalise_reference(v.reference_no))].append(v)
    findings = []
    for (party, norm), vs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        if len(vs) < 2:
            continue
        vs = _sorted(vs)
        party_name = names.get(party, str(party))
        listed = ", ".join(f"{_ref(v)} ({_d(v.voucher_date)}, {format_inr(v.total)})" for v in vs)
        findings.append(Finding(
            "A-01", finding_key("A-01", party, norm), CATALOGUE["A-01"].severity, "voucher", _ref(vs[0]),
            f"Bill no {vs[0].reference_no.strip()} of {party_name} appears on {len(vs)} vouchers: {listed}",
            {"voucher_ids": [str(v.id) for v in vs], "party_ledger_id": str(party), "reference": norm,
             "amounts": [_s(v.total) for v in vs], "dates": [v.voucher_date.isoformat() for v in vs]},
            subject_id=vs[0].id, finding_date=vs[0].voucher_date, amount=vs[0].total))
    return CheckResult("A-01", tuple(findings), tuple(v.id for v in _sorted(pool)), sum((v.total for v in pool), ZERO))


# ---- A-02 duplicate payments ------------------------------------------------------------------------------------------------------------


def check_a02(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    names = _names(facts)
    live = [v for v in facts.vouchers if _is_live(v) and v.voucher_type == "payment" and _in_period(v, params)]
    pool = [v for v in live if v.party_ledger_id is not None]
    notes = []
    if len(pool) != len(live):
        notes.append(f"{len(live) - len(pool)} payment voucher(s) have no party ledger and could not be compared")
    groups: dict[tuple, list[VoucherFact]] = defaultdict(list)
    for v in pool:
        groups[(v.party_ledger_id, v.total)].append(v)
    window = timedelta(days=params.duplicate_window_days)
    findings = []
    for (party, total), vs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        clusters: list[list[VoucherFact]] = []
        for v in _sorted(vs):
            if clusters and v.voucher_date - clusters[-1][-1].voucher_date <= window:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            first = cluster[0]
            listed = ", ".join(f"{_ref(v)} ({_d(v.voucher_date)})" for v in cluster)
            findings.append(Finding(
                "A-02", finding_key("A-02", party, _s(total), first.voucher_date.isoformat()), CATALOGUE["A-02"].severity, "voucher",
                _ref(first),
                f"{len(cluster)} payments of {format_inr(total)} to {names.get(party, str(party))} within "
                f"{params.duplicate_window_days} days: {listed}",
                {"voucher_ids": [str(v.id) for v in cluster], "party_ledger_id": str(party), "amount": _s(total),
                 "dates": [v.voucher_date.isoformat() for v in cluster], "window_days": str(params.duplicate_window_days)},
                subject_id=first.id, finding_date=first.voucher_date, amount=total))
    return CheckResult("A-02", tuple(findings), tuple(v.id for v in _sorted(pool)), sum((v.total for v in pool), ZERO), tuple(notes))


# ---- A-03 missing supporting document ---------------------------------------------------------------------------------------------------


def check_a03(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    pool = _sorted([v for v in facts.vouchers if _is_live(v) and v.voucher_type in params.doc_required_types
                    and _in_period(v, params) and v.total >= params.doc_min_amount])
    findings = [
        _voucher_finding("A-03", v, f"{_label(v.voucher_type)} {_ref(v)} dated {_d(v.voucher_date)} for {format_inr(v.total)} has no "
                         f"supporting document linked",
                         {"voucher_ids": [str(v.id)], "voucher_type": v.voucher_type, "amount": _s(v.total), "date": v.voucher_date.isoformat()})
        for v in pool if v.id not in facts.document_voucher_ids]
    return CheckResult("A-03", tuple(findings), tuple(v.id for v in pool), sum((v.total for v in pool), ZERO))


# ---- A-04 voucher number gaps -----------------------------------------------------------------------------------------------------------


def _split_number(number: str | None) -> tuple[str, int, int] | None:
    """('PUR/2026-27', 4, 4) from 'PUR/2026-27/0004' (prefix, number, width); None when it does not end in digits after a slash."""
    if not number or "/" not in number:
        return None
    prefix, _, tail = number.rpartition("/")
    return (prefix, int(tail), len(tail)) if tail.isdigit() else None


def check_a04(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    numbered: dict[str, list[VoucherFact]] = defaultdict(list)
    for v in facts.vouchers:
        if v.status in ("posted", "reversed") and v.voucher_number:
            numbered[v.voucher_type].append(v)
    findings, notes = [], []
    for vtype in sorted(set(numbered) | set(facts.number_counters)):
        parsed: dict[int, tuple[str, int, int]] = {}
        for v in numbered.get(vtype, []):
            p = _split_number(v.voucher_number)
            if p is None:
                notes.append(f"voucher number {v.voucher_number} could not be read as prefix/number")
            else:
                parsed[p[1]] = p
        highest = max(parsed) if parsed else 0
        label = _label(vtype)
        counter = facts.number_counters.get(vtype)
        missing = [n for n in range(1, highest + 1) if n not in parsed]
        if missing:
            prefix, _, width = next(iter(parsed.values()))
            shown = [f"{prefix}/{n:0{width}d}" for n in missing]
            findings.append(Finding(
                "A-04", finding_key("A-04", vtype, "gap"), CATALOGUE["A-04"].severity, "period", f"{label} numbers",
                f"{label} voucher numbers are not continuous: number {', '.join(shown)} missing (posted numbers run up to {highest})",
                {"voucher_type": vtype, "missing_numbers": shown, "highest_posted": str(highest),
                 "counter": "" if counter is None else str(counter), "posted_count": str(len(parsed))}))
        if counter is not None and counter != highest:
            findings.append(Finding(
                "A-04", finding_key("A-04", vtype, "counter"), CATALOGUE["A-04"].severity, "period", f"{label} numbers",
                f"{label} number counter shows {counter} but the highest posted number is {highest}",
                {"voucher_type": vtype, "counter": str(counter), "highest_posted": str(highest), "posted_count": str(len(parsed))}))
    population = tuple(v.id for t in sorted(numbered) for v in sorted(numbered[t], key=lambda x: str(x.voucher_number)))
    return CheckResult("A-04", tuple(findings), population, None, tuple(notes))


# ---- A-05 / A-06 cash limits ------------------------------------------------------------------------------------------------------------


def _cash_by_person(facts: BooksFacts, params: AuditParams, vtype: str, cash_side: str, other_side: str):
    """({(person, day): [(voucher, cash amount)]}, population [(voucher, cash)]) for live vouchers of `vtype` with cash on `cash_side`.

    The person is the voucher's party ledger, else the single ledger on the other side that is not cash / bank; if neither identifies one
    person the voucher stands alone (keyed by the voucher) so it is still tested, never dropped."""
    group = _group_of(facts)
    out: dict[tuple, list[tuple[VoucherFact, Decimal]]] = defaultdict(list)
    population = []
    for v in _sorted([x for x in facts.vouchers if _is_live(x) and x.voucher_type == vtype and _in_period(x, params)]):
        cash = sum((getattr(ln, cash_side) for ln in v.lines if group.get(ln.ledger_id) == CASH_GROUP), ZERO)
        if cash <= ZERO:
            continue
        population.append((v, cash))
        person = v.party_ledger_id
        if person is None:
            others = {ln.ledger_id for ln in v.lines if getattr(ln, other_side) > ZERO and group.get(ln.ledger_id) not in CASH_BANK_GROUPS}
            person = next(iter(others)) if len(others) == 1 else ("voucher", v.id)
        out[(person, v.voucher_date)].append((v, cash))
    return out, population


def _cash_limit_check(check_id: str, facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule], vtype: str, cash_side: str,
                      other_side: str, rule_key: str, what: str, prep: str) -> CheckResult:
    groups, population = _cash_by_person(facts, params, vtype, cash_side, other_side)
    names = _names(facts)
    transporter = {ln.id for ln in facts.ledgers if ln.is_transporter}
    findings, skipped = [], set()
    for (person, day), items in sorted(groups.items(), key=lambda kv: (kv[0][1], str(kv[0][0]))):
        key = f"{rule_key}_transport" if (check_id == "A-05" and person in transporter) else rule_key
        rule = pick_limit(rules, key, day)
        if rule is None:
            skipped.add(day)
            continue
        total = sum((amt for _, amt in items), ZERO)
        if not breaches(rule, total):
            continue
        standalone = isinstance(person, tuple)
        who = "an unidentified party" if standalone else names.get(person, str(person))
        pending = " (limit pending verification)" if rule.verification_status == "pending" else ""
        wording = "above" if rule.breach_when == "above" else "at or above"
        disallowance, tail = None, ""
        if check_id == "A-05" and rule.disallow_percent is not None:
            disallowance = round_half_up(total * rule.disallow_percent / Decimal(100))
            tail = f"; expenditure of {format_inr(disallowance)} may be disallowed"
        message = (f"Cash {what} {prep} {who} on {_d(day)} total {format_inr(total)}, {wording} the daily limit of "
                   f"{format_inr(rule.amount)}{pending}{tail}")
        vs = [v for v, _ in items]
        evidence = {
            "voucher_ids": [str(v.id) for v in vs], "party_ledger_id": None if standalone else str(person), "party": who,
            "date": day.isoformat(), "day_total": _s(total), "limit": _s(rule.amount), "breach_when": rule.breach_when,
            "cash_amounts": [_s(a) for _, a in items],
            "rule": {"rule_key": rule.rule_key, "law": rule.law, "section_ref": rule.section_ref, "status": rule.verification_status,
                     "effective_from": rule.effective_from.isoformat()},
        }
        part = ("v" + str(person[1])) if standalone else person
        findings.append(Finding(
            check_id, finding_key(check_id, part, day.isoformat()), CATALOGUE[check_id].severity, "voucher" if standalone else "party",
            _ref(vs[0]) if standalone else who, message, evidence,
            subject_id=vs[0].id if standalone else person, finding_date=day, amount=total, disallowance_amount=disallowance,
            rule_status=rule.verification_status))
    notes = []
    if skipped:
        days = sorted(skipped)
        shown = ", ".join(_d(x) for x in days[:LISTED_DATES]) + (f" and {len(days) - LISTED_DATES} more" if len(days) > LISTED_DATES else "")
        notes.append(f"limit not available for {len(days)} date(s) ({rule_key}): {shown}; check skipped for them")
    return CheckResult(check_id, tuple(findings), tuple(v.id for v, _ in population), sum((a for _, a in population), ZERO), tuple(notes))


def check_a05(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule]) -> CheckResult:
    return _cash_limit_check("A-05", facts, params, rules, "payment", "credit", "debit", "cash_payment_daily_limit", "payments", "to")


def check_a06(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule]) -> CheckResult:
    return _cash_limit_check("A-06", facts, params, rules, "receipt", "debit", "credit", "cash_receipt_limit", "receipts", "from")


# ---- A-12 round amounts -----------------------------------------------------------------------------------------------------------------


def check_a12(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    pool = _sorted([v for v in facts.vouchers if _is_live(v) and _in_period(v, params)])
    if params.round_unit <= ZERO:
        return CheckResult("A-12", (), tuple(v.id for v in pool), None, ("round unit is not positive: check skipped",))
    findings = [
        _voucher_finding("A-12", v, f"{_label(v.voucher_type)} {_ref(v)} dated {_d(v.voucher_date)} is a round amount of {format_inr(v.total)} "
                         f"(multiple of {format_inr(params.round_unit)})",
                         {"voucher_ids": [str(v.id)], "total": _s(v.total), "round_unit": _s(params.round_unit),
                          "minimum": _s(params.round_min_amount), "date": v.voucher_date.isoformat()})
        for v in pool if v.total >= params.round_min_amount and v.total > ZERO and v.total % params.round_unit == ZERO]
    return CheckResult("A-12", tuple(findings), tuple(v.id for v in pool), sum((v.total for v in pool), ZERO))


# ---- A-13 Sundays and holidays ----------------------------------------------------------------------------------------------------------


def check_a13(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    pool = _sorted([v for v in facts.vouchers if v.status in ("posted", "reversed") and _in_period(v, params)])
    findings = []
    for v in pool:
        holiday = facts.holidays.get(v.voucher_date)
        sunday = is_sunday(v.voucher_date)
        if not holiday and not sunday:
            continue
        reason = "Sunday and holiday" if (sunday and holiday) else ("Sunday" if sunday else "Holiday")
        evidence = {"voucher_ids": [str(v.id)], "date": v.voucher_date.isoformat(), "total": _s(v.total), "reason": reason}
        what = " and ".join((["a Sunday"] if sunday else []) + ([f"a holiday ({holiday})"] if holiday else []))
        if holiday:
            evidence["holiday_name"] = holiday
        findings.append(_voucher_finding("A-13", v, f"{_label(v.voucher_type)} {_ref(v)} is dated {_d(v.voucher_date)}, {what}", evidence))
    return CheckResult("A-13", tuple(findings), tuple(v.id for v in pool), sum((v.total for v in pool), ZERO))


# ---- A-14 entries after the period was locked -------------------------------------------------------------------------------------------


def check_a14(facts: BooksFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    pool = _sorted([v for v in facts.vouchers if v.status in ("posted", "reversed") and v.posted_at is not None and _in_period(v, params)])
    events = sorted(facts.lock_events, key=lambda e: e.at)
    findings, unplaced = [], 0
    for v in pool:
        period = next((p for p in facts.periods if p.start <= v.voucher_date <= p.end), None)
        if period is None:
            unplaced += 1
            continue
        posted_on = _ist_date(v.posted_at)
        reasons = []
        evidence: dict[str, Any] = {
            "voucher_ids": [str(v.id)], "voucher_date": v.voucher_date.isoformat(), "posted_at": v.posted_at.isoformat(),
            "period_start": period.start.isoformat(), "period_end": period.end.isoformat()}
        lock = next((e for e in events if e.period_id == period.id and e.action == "lock" and e.at < v.posted_at), None)
        if lock is not None:
            unlock = next((e for e in events if e.period_id == period.id and e.action == "unlock" and e.at >= lock.at), None)
            evidence.update({"lock_audit_log_id": str(lock.log_id), "locked_at": lock.at.isoformat(), "locked_by": lock.actor})
            text = f"posted on {_d(posted_on)} after the period {_d(period.start)} to {_d(period.end)} was locked on {_d(_ist_date(lock.at))}"
            if unlock is not None:
                evidence.update({"unlock_audit_log_id": str(unlock.log_id), "unlocked_at": unlock.at.isoformat(),
                                 "unlocked_by": unlock.actor, "unlock_reason": unlock.reason or ""})
                text += f" (unlocked on {_d(_ist_date(unlock.at))}: {unlock.reason or 'no reason recorded'})"
            reasons.append(text)
        late_days = (posted_on - period.end).days
        if late_days > params.late_posting_days:
            evidence.update({"days_after_period_end": str(late_days), "late_posting_days": str(params.late_posting_days)})
            reasons.append(f"posted {late_days} days after the period ended on {_d(period.end)} (allowed {params.late_posting_days} days)")
        if reasons:
            findings.append(_voucher_finding(
                "A-14", v, f"{_label(v.voucher_type)} {_ref(v)} dated {_d(v.voucher_date)} was " + "; ".join(reasons), evidence))
    notes = [f"{unplaced} voucher(s) fall in no period: lock and lateness not tested for them"] if unplaced else []
    return CheckResult("A-14", tuple(findings), tuple(v.id for v in pool), sum((v.total for v in pool), ZERO), tuple(notes))


def _for_registry(check):
    """The registry passes its `AuditFacts` (ledgers, vouchers, extra); the books loader's extras are in `facts.extra["books"]`.
    A bare `BooksFacts` (the direct unit tests) is passed through unchanged."""

    def run(facts, params, rules):
        if isinstance(facts, BooksFacts):
            return check(facts, params, rules)
        own = BooksFacts(vouchers=tuple(facts.vouchers), ledgers=tuple(facts.ledgers.values()), **facts.extra.get("books", {}))
        return check(own, params, rules)

    run.__name__ = check.__name__
    run.__doc__ = check.__doc__
    return run


CHECKS: dict = {k: _for_registry(fn) for k, fn in {
    "A-01": check_a01, "A-02": check_a02, "A-03": check_a03, "A-04": check_a04, "A-05": check_a05, "A-06": check_a06,
    "A-12": check_a12, "A-13": check_a13, "A-14": check_a14,
}.items()}
