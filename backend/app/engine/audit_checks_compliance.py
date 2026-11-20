"""Compliance checks A-07..A-11, A-16, A-17 (Phase 8, package C). Thin adapters over the Phase 2 to 5 engines. Pure Python: no DB, web or AI imports.

The adapters do NOT repeat the earlier maths. They hand plain facts to the existing engines and turn the answers into findings with evidence:
  A-07  engine/msme.flag_msme_overdue            A-08  GST tie-out (engine/gst_tieout.build_tieout, run by services/gst_returns.tie_out)
  A-09 / A-10  engine/tds_calc.compute_items     A-11  engine/tds_challan.deposit_due_date + item_status
  A-16  engine/cash_rules.check_cash_never_negative (C-01)    A-17  engine/inventory_valuation.compute_valuation (S-01)
Law stays in the rule tables of those phases (rows carry their verification status; a pending row shows on the finding as `rule_status`).

Each entry of CHECKS maps a check id to a function (facts, params, rules) -> CheckResult. `facts` is a ComplianceFacts built by
services/audit_load_compliance.py; a part that was not loaded (None) gives an empty result with a note, never a guess. Evidence amounts are strings.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine import msme as msme_engine
from app.engine import tds_calc, tds_challan
from app.engine.audit_types import (
    ZERO,
    AuditParams,
    CheckResult,
    Finding,
    LimitRule,
    Severity,
    finding_key,
)
from app.engine.cash_rules import CashMovement, check_cash_never_negative
from app.engine.gst_tieout import Cause
from app.engine.inventory_types import InventoryPolicy, Movement, OpeningStock
from app.engine.inventory_valuation import compute_valuation
from app.engine.models import OpenBill, OpeningBalance
from app.engine.money import format_inr
from app.engine.tds_types import DueDateRule, TdsLineIn

# ---- facts ------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MsmeFacts:
    open_bills: tuple[OpenBill, ...]
    parties: dict[Any, msme_engine.PartyFacts]
    rules: tuple[msme_engine.MsmeRule, ...]
    as_on: date


@dataclass(frozen=True)
class GstPeriodFact:
    """The tie-out of one registration and one period, as returned by services/gst_returns.tie_out (rows, itc, causes, ties)."""

    registration_id: Any
    gstin: str
    period_start: date
    period_end: date
    rows: tuple[dict, ...]
    itc: dict
    causes: tuple[Cause, ...]
    ties: bool
    rule_status: str = "pending"


@dataclass(frozen=True)
class TdsCandidate:
    """One deduction to test: a voucher, a deductee and a nature, with the tax actually deducted on it (0 when no item was entered)."""

    voucher_id: Any
    voucher_ref: str               # voucher number, else the voucher id
    voucher_type: str
    voucher_date: date
    deductee_ledger_id: Any
    deductee_name: str
    nature_key: str
    base: Decimal                  # the amount the nature applies to: the typed item base, else the party line (gross, GST not removed)
    base_source: str               # 'item' | 'party_line'
    credit_date: date | None
    payment_date: date | None
    deducted: Decimal
    lower_cert_id: str | None = None


@dataclass(frozen=True)
class TdsFacts:
    candidates: tuple[TdsCandidate, ...]
    ctx: tds_calc.TdsContext      # rule rows, deductee masters and the client's year list; priors are empty (the whole year is re-worked in date order)


@dataclass(frozen=True)
class DepositItem:
    item_id: Any
    voucher_id: Any
    voucher_ref: str
    deductee_name: str
    section_ref: str
    kind: str                      # tds | tcs
    event_date: date
    tds_amount: Decimal
    deposits: tuple[tuple[date, Decimal], ...] = ()    # (challan deposit date, amount allocated to this item)


@dataclass(frozen=True)
class DepositFacts:
    items: tuple[DepositItem, ...]
    due_rules: tuple[DueDateRule, ...]
    as_on: date                    # undeposited tax is late only when its due date is before this (never later than today)


@dataclass(frozen=True)
class CashLedgerFact:
    ledger_id: Any
    name: str
    opening: OpeningBalance
    movements: tuple[CashMovement, ...]                 # all lines of the financial year (posted / reversed vouchers)
    voucher_ids_by_date: dict[date, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class StockFacts:
    policy: InventoryPolicy
    opening: tuple[OpeningStock, ...]
    movements: tuple[Movement, ...]
    voucher_numbers: dict[Any, str | None]              # movement id -> voucher / journal number
    item_names: dict[Any, str]
    godown_names: dict[Any, str]
    fy_start: date
    fy_end: date


@dataclass(frozen=True)
class ComplianceFacts:
    """Everything the seven checks read. A part left None was not loaded (the loader says why in `notes`)."""

    msme: MsmeFacts | None = None
    gst: tuple[GstPeriodFact, ...] | None = None
    tds: TdsFacts | None = None
    deposits: DepositFacts | None = None
    cash: tuple[CashLedgerFact, ...] | None = None
    stock: StockFacts | None = None
    notes: dict[str, tuple[str, ...]] = field(default_factory=dict)   # check id -> loader notes (e.g. "no inventory policy for the year")


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _s(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _rate(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _in_window(on: date, params: AuditParams) -> bool:
    return params.from_date <= on <= params.to_date


def _not_loaded(check_id: str, facts: ComplianceFacts, what: str) -> CheckResult:
    return CheckResult(check_id, notes=(*facts.notes.get(check_id, ()), f"{what} were not loaded: check not run"))


def _result(check_id: str, facts: ComplianceFacts, findings: list[Finding], population: list, amount: Decimal | None, notes: list[str]) -> CheckResult:
    return CheckResult(check_id, tuple(findings), tuple(population), amount, (*facts.notes.get(check_id, ()), *notes))


# ---- A-07 MSME dues -----------------------------------------------------------------------------------------------------------------------


def check_msme(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    m = facts.msme
    if m is None:
        return _not_loaded("A-07", facts, "Bills and MSME rules")
    flags = msme_engine.flag_msme_overdue(m.open_bills, m.parties, m.rules, m.as_on)
    examined = [b for b in m.open_bills if b.kind == "bill" and b.outstanding < 0 and b.party_ledger_id in m.parties
                and m.parties[b.party_ledger_id].msme_category in ("micro", "small")]
    population = [f"{b.party_ledger_id}:{b.bill_ref or b.bill_date}" for b in examined]
    pop_amount = sum((-b.outstanding for b in examined), ZERO)
    status, source = msme_engine.rules_status(m.rules, m.as_on)
    findings = []
    for f in flags:
        ref = f.bill_ref or _fmt(f.bill_date)
        findings.append(Finding(
            "A-07", finding_key("A-07", f.party_ledger_id, f.bill_ref or f.bill_date.isoformat()), Severity.ERROR, "bill",
            f"{f.party_name} bill {ref}",
            f"MSME dues: bill {ref} of {f.party_name} dated {_fmt(f.bill_date)}, outstanding {format_inr(f.outstanding)}, was due on "
            f"{_fmt(f.legal_due_date)} ({f.legal_days} days from {_fmt(f.acceptance_date)}, the {f.acceptance_basis}); it is "
            f"{f.days_overdue} days overdue" + (" (rule pending verification)" if f.rule_status == "pending" else ""),
            {"party_ledger_id": str(f.party_ledger_id), "party_name": f.party_name, "bill_ref": f.bill_ref, "bill_date": f.bill_date.isoformat(),
             "acceptance_date": f.acceptance_date.isoformat(), "acceptance_basis": f.acceptance_basis, "legal_days": str(f.legal_days),
             "legal_due_date": f.legal_due_date.isoformat(), "days_overdue": str(f.days_overdue), "outstanding": _s(f.outstanding),
             "as_on": m.as_on.isoformat(), "rule": {"status": f.rule_status, "source": f.rule_source}},
            subject_id=f.party_ledger_id, finding_date=f.legal_due_date, amount=f.outstanding, rule_status=f.rule_status))
    notes = [f"MSME rules in force on {_fmt(m.as_on)}: {status} ({source})"] if status != "verified" else []
    return _result("A-07", facts, findings, population, pop_amount, notes)


# ---- A-08 GST books versus returns ---------------------------------------------------------------------------------------------------


_ROW_PAIRS = (
    ("d_books_gstr1", "books", "books_output", "GSTR-1 working", "gstr1_working"),
    ("d_gstr1_gstr3b", "GSTR-1 working", "gstr1_working", "GSTR-3B working", "gstr3b_working"),
    ("d_books_filed", "books", "books_output", "filed GSTR-1", "filed_gstr1"),
    ("d_filed_gstr1_gstr3b", "filed GSTR-1", "filed_gstr1", "filed GSTR-3B", "filed_gstr3b"),
)
_LABEL = {"taxable_value": "taxable value", "igst": "IGST", "cgst": "CGST", "sgst": "SGST", "cess": "cess"}


def _gst_differences(p: GstPeriodFact) -> list[dict]:
    out = []
    for row in p.rows:
        for key, left, lkey, right, rkey in _ROW_PAIRS:
            if row.get(key):
                out.append({"head": _LABEL.get(row["head"], row["head"]), "left": left, "left_amount": _s(row[lkey]), "right": right,
                            "right_amount": _s(row[rkey]), "difference": _s(row[key])})
    for head, cells in p.itc.items():
        if cells.get("d_register_gstr3b"):
            out.append({"head": f"ITC {head.upper()}", "left": "ITC register (eligible)", "left_amount": _s(cells["itc_register_eligible"]),
                        "right": "GSTR-3B 4(A) net", "right_amount": _s(cells["gstr3b_4a"]), "difference": _s(cells["d_register_gstr3b"])})
        if cells.get("d_books_register_pending"):
            out.append({"head": f"ITC {head.upper()}", "left": "books input tax", "left_amount": _s(cells["books_input"]),
                        "right": "ITC register (eligible + pending)",
                        "right_amount": _s(cells["itc_register_eligible"] + cells["itc_register_pending"]),
                        "difference": _s(cells["d_books_register_pending"])})
    return out


def check_gst(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    if facts.gst is None:
        return _not_loaded("A-08", facts, "GST tie-out figures")
    findings, population = [], []
    for p in facts.gst:
        population.append(f"{p.registration_id}:{p.period_start.isoformat()}")
        if p.ties:
            continue
        diffs = _gst_differences(p)
        if not diffs:
            continue
        shown = "; ".join(
            f"{d['head']}: {d['left']} {format_inr(Decimal(d['left_amount']))} against {d['right']} {format_inr(Decimal(d['right_amount']))} "
            f"(difference {format_inr(Decimal(d['difference']))})" for d in diffs[:4]) + (f"; and {len(diffs) - 4} more" if len(diffs) > 4 else "")
        total = sum((abs(Decimal(d["difference"])) for d in diffs), ZERO)
        findings.append(Finding(
            "A-08", finding_key("A-08", p.registration_id, p.period_start.isoformat()), Severity.ERROR, "return",
            f"GSTIN {p.gstin} {_fmt(p.period_start)} to {_fmt(p.period_end)}",
            f"GST books and returns do not agree for GSTIN {p.gstin}, {_fmt(p.period_start)} to {_fmt(p.period_end)}: {shown}",
            {"registration_id": str(p.registration_id), "gstin": p.gstin, "period_start": p.period_start.isoformat(),
             "period_end": p.period_end.isoformat(), "differences": diffs,
             "causes": [{"kind": c.kind, "reference": c.reference, "amount": _s(c.amount), "head": c.head} for c in p.causes],
             "rule": {"status": p.rule_status}},
            subject_id=p.registration_id, finding_date=p.period_end, amount=total, rule_status=p.rule_status))
    return _result("A-08", facts, findings, population, None, [])


# ---- A-09 / A-10 TDS not deducted, short deducted ---------------------------------------------------------------------------------------


def _event(c: TdsCandidate) -> date:
    return tds_calc.event_date(c.credit_date, c.payment_date) or c.voucher_date


def review_tds(facts: TdsFacts) -> tuple[list[tuple[TdsCandidate, Any]], list[str]]:
    """Work every candidate through the Phase 4 engine in date order (the whole year, empty priors) -> [(candidate, TdsItemResult)], notes."""
    ordered = sorted(facts.candidates, key=lambda c: (_event(c), c.voucher_date, str(c.voucher_id), c.nature_key))
    items = [TdsLineIn(c.deductee_ledger_id, c.nature_key, c.base, c.credit_date, c.payment_date, c.lower_cert_id) for c in ordered]
    comp = tds_calc.compute_items(items, facts.ctx)
    by_no = {r.item_no: r for r in comp.items}
    notes = []
    for err in comp.errors:
        who = ordered[err.line_no - 1] if err.line_no else None
        if who is not None:
            notes.append(f"{who.voucher_ref} ({who.deductee_name}): not tested, {err.message}")
    reviewed = [(c, by_no[n]) for n, c in enumerate(ordered, start=1) if n in by_no]
    return reviewed, notes


def _tds_evidence(c: TdsCandidate, r: Any) -> dict:
    return {"voucher_id": str(c.voucher_id), "voucher_number": c.voucher_ref, "voucher_type": c.voucher_type, "voucher_date": c.voucher_date.isoformat(),
            "deductee_ledger_id": str(c.deductee_ledger_id), "deductee_name": c.deductee_name, "nature_key": c.nature_key,
            "section_ref": r.section_ref, "act": r.act, "base": _s(c.base), "base_source": c.base_source, "rate_applied": _rate(r.rate_applied),
            "rate_reason": r.rate_reason, "event_date": r.event_date.isoformat(), "computed_tax": _s(r.tds_amount), "deducted_tax": _s(c.deducted),
            "shortfall": _s(r.tds_amount - c.deducted), "rule": {"status": r.verification_status}}


def _tds_findings(facts: ComplianceFacts, params: AuditParams, check_id: str, short: bool) -> CheckResult:
    if facts.tds is None:
        return _not_loaded(check_id, facts, "TDS inputs")
    reviewed, notes = review_tds(facts.tds)
    population, findings, pop_amount = [], [], ZERO
    for c, r in reviewed:
        if not _in_window(r.event_date, params):
            continue
        population.append(f"{c.voucher_id}:{c.deductee_ledger_id}:{c.nature_key}")
        pop_amount += c.base
        computed = r.tds_amount
        if computed <= 0 or c.deducted >= computed or (c.deducted > 0) != short:
            continue
        gap = computed - c.deducted
        what = f"{c.voucher_type.replace('_', ' ').title()} {c.voucher_ref} dated {_fmt(c.voucher_date)} to {c.deductee_name}"
        basis = f"on {format_inr(c.base)} at {_rate(r.rate_applied)}% under {r.section_ref}"
        pend = " (rule pending verification)" if r.verification_status == "pending" else ""
        if short:
            msg = (f"TDS short deducted: {what}: tax {basis} is {format_inr(computed)}, deducted {format_inr(c.deducted)}, "
                   f"short by {format_inr(gap)}{pend}")
        else:
            msg = f"TDS not deducted: {what}: tax {basis} is {format_inr(computed)}, but none was deducted{pend}"
        findings.append(Finding(
            check_id, finding_key(check_id, c.voucher_id, c.deductee_ledger_id, c.nature_key), Severity.ERROR, "voucher",
            f"{c.voucher_ref} {c.deductee_name}", msg, _tds_evidence(c, r), subject_id=c.voucher_id, finding_date=c.voucher_date, amount=gap,
            rule_status=r.verification_status))
    return _result(check_id, facts, findings, population, pop_amount, notes)


def check_tds_not_deducted(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    return _tds_findings(facts, params, "A-09", short=False)


def check_tds_short_deducted(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    return _tds_findings(facts, params, "A-10", short=True)


# ---- A-11 TDS late deposited ---------------------------------------------------------------------------------------------------------------


def check_tds_late_deposit(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    d = facts.deposits
    if d is None:
        return _not_loaded("A-11", facts, "TDS deduction items and challans")
    findings, population, notes, pop_amount = [], [], [], ZERO
    for it in sorted(d.items, key=lambda x: (x.event_date, x.voucher_ref, str(x.item_id))):
        if not _in_window(it.event_date, params):
            continue
        try:
            due, rule = tds_challan.deposit_due_date(it.event_date, it.kind, list(d.due_rules))
        except tds_challan.ChallanRuleError as exc:
            notes.append(f"{it.voucher_ref} ({it.deductee_name}): due date not worked, {exc.errors[0].message}")
            continue
        population.append(str(it.item_id))
        pop_amount += it.tds_amount
        st = tds_challan.item_status(it.tds_amount, list(it.deposits), due, d.as_on)
        if not st.days_late:
            continue
        what = (f"{it.kind.upper()} of {format_inr(it.tds_amount)} on {it.deductee_name} ({it.section_ref}, voucher {it.voucher_ref}, "
                f"deducted {_fmt(it.event_date)})")
        pend = " (due-date rule pending verification)" if rule.verification_status == "pending" else ""
        if st.deposited_on is not None:
            msg = f"TDS late deposited: {what} was due on {_fmt(due)} and deposited on {_fmt(st.deposited_on)}, {st.days_late} days late{pend}"
        else:
            msg = (f"TDS not deposited in time: {what} was due on {_fmt(due)}; {format_inr(st.balance)} is still undeposited as on "
                   f"{_fmt(d.as_on)}, {st.days_late} days late{pend}")
        findings.append(Finding(
            "A-11", finding_key("A-11", it.item_id), Severity.ERROR, "voucher", f"{it.voucher_ref} {it.deductee_name}", msg,
            {"item_id": str(it.item_id), "voucher_id": str(it.voucher_id), "voucher_number": it.voucher_ref, "deductee_name": it.deductee_name,
             "section_ref": it.section_ref, "kind": it.kind, "event_date": it.event_date.isoformat(), "tds_amount": _s(it.tds_amount),
             "due_date": due.isoformat(), "deposited_on": None if st.deposited_on is None else st.deposited_on.isoformat(),
             "deposits": [{"date": x.isoformat(), "amount": _s(a)} for x, a in it.deposits], "undeposited": _s(st.balance),
             "days_late": str(st.days_late), "as_on": d.as_on.isoformat(), "rule": {"status": rule.verification_status, "due_key": rule.due_key}},
            subject_id=it.voucher_id, finding_date=due, amount=it.tds_amount, rule_status=rule.verification_status))
    return _result("A-11", facts, findings, population, pop_amount, notes)


# ---- A-16 negative cash history -------------------------------------------------------------------------------------------------------------


def _negative_days(opening: OpeningBalance, moves: Sequence[CashMovement]) -> list[tuple[date, Decimal]]:
    """Day-end balances below zero (debit positive), in date order: evidence only; the C-01 engine decides whether the ledger is flagged."""
    by_day: dict[date, Decimal] = {}
    for m in moves:
        by_day[m.on] = by_day.get(m.on, ZERO) + m.debit - m.credit
    running = opening.debit - opening.credit
    out = []
    for on in sorted(by_day):
        running += by_day[on]
        if running < 0:
            out.append((on, running))
    return out


def check_negative_cash(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    if facts.cash is None:
        return _not_loaded("A-16", facts, "Cash ledgers")
    findings, population = [], []
    for led in sorted(facts.cash, key=lambda x: (x.name, str(x.ledger_id))):
        population.append(str(led.ledger_id))
        if not led.movements:
            continue
        # C-01 looks at every day from the earliest date of `new` onwards: a zero movement on the first day makes it read the whole year
        rule_error = check_cash_never_negative(led.name, led.opening, led.movements, [CashMovement(min(m.on for m in led.movements), ZERO, ZERO)])
        if rule_error is None:
            continue
        days = [(on, bal) for on, bal in _negative_days(led.opening, led.movements) if _in_window(on, params)]
        if not days:
            continue
        first_on, first_bal = days[0]
        low_on, low_bal = min(days, key=lambda x: (x[1], x[0]))
        shown = [{"date": on.isoformat(), "balance": _s(bal), "voucher_ids": list(led.voucher_ids_by_date.get(on, ()))} for on, bal in days[:20]]
        findings.append(Finding(
            "A-16", finding_key("A-16", led.ledger_id, first_on.isoformat()), Severity.ERROR, "ledger", led.name,
            f"Negative cash: '{led.name}' is below zero at the end of {len(days)} day(s); first on {_fmt(first_on)} (Cr {format_inr(-first_bal)}), "
            f"lowest on {_fmt(low_on)} (Cr {format_inr(-low_bal)}). Cash-in-hand cannot be a credit balance.",
            {"ledger_id": str(led.ledger_id), "ledger_name": led.name, "opening": _s(led.opening.debit - led.opening.credit),
             "negative_day_count": str(len(days)), "first_negative_date": first_on.isoformat(), "first_balance": _s(first_bal),
             "lowest_date": low_on.isoformat(), "lowest_balance": _s(low_bal), "days": shown, "rule": "C-01 (cash never negative)",
             "engine_message": rule_error.message},
            subject_id=led.ledger_id, finding_date=first_on, amount=-low_bal))
    return _result("A-16", facts, findings, population, None, [])


# ---- A-17 negative stock history ------------------------------------------------------------------------------------------------------------


def check_negative_stock(facts: ComplianceFacts, params: AuditParams, rules: Sequence[LimitRule] = ()) -> CheckResult:
    s = facts.stock
    if s is None:
        return _not_loaded("A-17", facts, "Stock opening and movements")
    result = compute_valuation(s.policy, s.fy_start, s.fy_end, list(s.opening), list(s.movements))
    population = sorted({str(m.item_id) for m in s.movements} | {str(o.item_id) for o in s.opening})
    by_id = {m.movement_id: m for m in s.movements}
    findings = []
    for e in result.errors:
        if e.rule_id != "S-01" or e.on_date is None or e.movement_id is None or not _in_window(e.on_date, params):
            continue
        m = by_id.get(e.movement_id)
        item, godown = s.item_names.get(e.item_id, str(e.item_id)), s.godown_names.get(e.godown_id, str(e.godown_id))
        number = s.voucher_numbers.get(e.movement_id)
        message = e.message.replace(str(e.item_id), item).replace(str(e.godown_id), godown)
        findings.append(Finding(
            "A-17", finding_key("A-17", e.item_id, e.godown_id, e.on_date.isoformat()), Severity.ERROR, "stock_item", f"{item} / {godown}",
            f"Negative stock: {message}" + (f" (voucher {number})" if number else ""),
            {"item_id": str(e.item_id), "item_name": item, "godown_id": str(e.godown_id), "godown_name": godown, "date": e.on_date.isoformat(),
             "movement_id": str(e.movement_id), "voucher_number": number, "movement_kind": None if m is None else m.kind.value,
             "movement_quantity": None if m is None else f"{m.quantity:.3f}", "rule": "S-01 (stock cannot go below zero)",
             "negative_stock_mode": s.policy.negative_stock_mode.value, "engine_message": e.message},
            subject_id=e.item_id, finding_date=e.on_date))
    return _result("A-17", facts, findings, population, None, [])


def _for_registry(check):
    """The registry (package A) passes its `AuditFacts`; this package's loader puts a `ComplianceFacts` in `facts.extra["compliance"]`.
    A bare `ComplianceFacts` (the direct unit tests) is passed through unchanged."""

    def run(facts, params, rules):
        own = facts.extra["compliance"] if hasattr(facts, "extra") else facts
        return check(own, params, rules)

    run.__name__ = check.__name__
    run.__doc__ = check.__doc__
    return run


CHECKS: dict = {
    "A-07": _for_registry(check_msme),
    "A-08": _for_registry(check_gst),
    "A-09": _for_registry(check_tds_not_deducted),
    "A-10": _for_registry(check_tds_short_deducted),
    "A-11": _for_registry(check_tds_late_deposit),
    "A-16": _for_registry(check_negative_cash),
    "A-17": _for_registry(check_negative_stock),
}
