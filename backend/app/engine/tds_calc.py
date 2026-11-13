"""TDS / TCS deduction engine (Phase 4, rules T-01 .. T-12, T-15 .. T-17, T-50). Pure Python: no database, web or AI.

The caller passes plain rule rows, masters and the position already in the books; the engine returns one result per
item with its whole working, or rule errors. Nothing here knows a rate: every rate, threshold and no-PAN rate comes from
the rule rows (law is data), chosen by the event date (the earlier of payment and credit date).

Conventions
- Amounts are Decimal with 2 places; rates are percentages (2 means 2%).
- Thresholds are "exceeds" thresholds: an amount equal to the threshold is not taxed.
- whole_amount mode: from the payment that crosses a threshold the base is the cumulative amount (catch-up of the earlier
  untaxed payments) and the tax already deducted on the year is set off. excess_only mode: only the part above the threshold.
- A lower / nil deduction certificate covers at most its remaining limit (payments); the rest is taxed at the normal rate.
  A certificate is applied only when the PAN is valid (T-08).
- Tax is rounded to the nearest rupee, halves up, in `round_tax` (the single shared helper, T-06).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine.models import ValidationError
from app.engine.money import TWO_PLACES, format_inr, round_half_up
from app.engine.tds_types import (
    Deductee,
    LowerDeductionCert,
    Nature,
    PanStatus,
    PriorPosition,
    RateReason,
    RateRule,
    SectionRef,
    TdsItemResult,
    TdsLineIn,
    VerificationStatus,
)

ZERO = Decimal("0.00")
HUNDRED = Decimal(100)
PURCHASE_OF_GOODS = "purchase_of_goods"  # the nature that depends on the buyer-turnover flag of the client (T-15)
_ORDER = {VerificationStatus.VERIFIED.value: 0, VerificationStatus.SECONDARY_VERIFIED.value: 1, VerificationStatus.PENDING.value: 2}
INDIVIDUAL_HUF = ("individual", "huf")


def round_tax(value: Decimal) -> Decimal:
    """T-06: tax to the nearest whole rupee, halves up (provision 288B, pending), as a 2-place Decimal. The one shared helper."""
    return round_half_up(value, 0).quantize(TWO_PLACES)


def worst_status(statuses: Iterable[str]) -> str:
    """The weakest verification status of the given ones (pending < secondary_verified < verified)."""
    found = [s for s in statuses]
    if not found:
        return VerificationStatus.VERIFIED.value
    return max(found, key=lambda s: _ORDER[s])


def event_date(credit_date: date | None, payment_date: date | None) -> date | None:
    """T-01: the earlier of the payment date and the credit date (the one that exists when only one is given)."""
    given = [d for d in (credit_date, payment_date) if d is not None]
    return min(given) if given else None


def deductee_group(deductee_type: str) -> str:
    """T-04: individual / HUF pay one rate, every other type the other."""
    return "individual_huf" if deductee_type in INDIVIDUAL_HUF else "others"


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _in_force(row, on: date) -> bool:
    return row.effective_from <= on and (row.effective_to is None or on <= row.effective_to)


def pick_rate_rule(rates: Sequence[RateRule], nature_key: str, group: str, on: date) -> RateRule | None:
    """The rate row in force on `on`: the one for the deductee's group, else the 'any' row. None when no row is in force (T-02)."""
    rows = [r for r in rates if r.nature_key == nature_key and _in_force(r, on)]
    for wanted in (group, "any"):
        hit = [r for r in rows if r.deductee_group == wanted]
        if hit:
            return max(hit, key=lambda r: r.effective_from)
    return None


def pick_section(section_refs: Sequence[SectionRef], nature_key: str, on: date, act: str | None = None) -> SectionRef | None:
    rows = [s for s in section_refs if s.nature_key == nature_key and _in_force(s, on) and (act is None or s.act == act)]
    return max(rows, key=lambda s: s.effective_from) if rows else None


@dataclass(frozen=True)
class TdsContext:
    kind: str  # 'tds' | 'tcs' (the block being computed)
    natures: Mapping[str, Nature]
    deductees: Mapping[object, Deductee]
    rates: Sequence[RateRule]
    section_refs: Sequence[SectionRef]
    certs: Mapping[object, LowerDeductionCert]
    priors: Mapping[tuple, PriorPosition]  # key (deductee_ledger_id, nature_key, fy_key); missing = nothing yet
    fy_of: Callable[[date], object | None]  # the financial year key of a date, None when the client has no year for it
    buyer_flags: Mapping[object, bool] = field(default_factory=dict)  # fy_key -> 194Q buyer condition entered by the accountant


@dataclass(frozen=True)
class TdsComputation:
    items: tuple[TdsItemResult, ...]
    errors: tuple[ValidationError, ...]
    rule_status: dict  # T-50: {"worst", "tables": {...}, "pending_sources": [...]}
    fy_keys: tuple = ()  # the financial year key of each item (same order as items)


@dataclass
class _Running:
    cumulative: Decimal = ZERO
    tax: Decimal = ZERO
    months: dict = field(default_factory=dict)


def _err(rule_id: str, n: int, message: str) -> ValidationError:
    return ValidationError(rule_id, f"Item {n}: {message}", n)


def _base_by_thresholds(rule: RateRule, amount: Decimal, cum_before: Decimal, month_before: Decimal, tax_prior: Decimal):
    """T-07: (taxable base, threshold crossed by this item, tax already deducted that is set off)."""
    single, monthly, annual = rule.single_payment_threshold, rule.monthly_threshold, rule.annual_threshold
    if single is None and monthly is None and annual is None:
        return amount, False, ZERO
    cum_after, month_after = cum_before + amount, month_before + amount
    if rule.threshold_mode == "excess_only":
        if annual is not None:
            return max(ZERO, cum_after - annual) - max(ZERO, cum_before - annual), cum_before <= annual < cum_after, ZERO
        if monthly is not None:
            return max(ZERO, month_after - monthly) - max(ZERO, month_before - monthly), month_before <= monthly < month_after, ZERO
        return max(ZERO, amount - single), False, ZERO
    candidates = []  # (base, crossed, tax set off)
    if annual is not None:
        if cum_before > annual:
            candidates.append((amount, False, ZERO))
        elif cum_after > annual:
            candidates.append((cum_after, True, tax_prior))
    if monthly is not None:
        if month_before > monthly:
            candidates.append((amount, False, ZERO))
        elif month_after > monthly:
            candidates.append((month_after, True, ZERO))
    if single is not None and amount > single:
        candidates.append((amount, False, ZERO))
    return max(candidates, key=lambda c: c[0]) if candidates else (ZERO, False, ZERO)


def _item(n: int, it: TdsLineIn, ctx: TdsContext, state: dict[tuple, _Running], cert_used: dict, used: list):
    """One item -> (result | None, errors, fy_key)."""
    errors: list[ValidationError] = []
    ev = event_date(it.credit_date, it.payment_date)
    if ev is None:
        return None, [_err("T-01", n, "enter the payment date or the credit date (the earlier one decides the Act and the rate).")], None
    amount = it.amount
    if not isinstance(amount, Decimal) or amount <= 0 or amount != amount.quantize(TWO_PLACES):
        errors.append(_err("T-16", n, "the amount must be more than zero with at most 2 decimal places."))
    nature = ctx.natures.get(it.nature_key)
    if nature is None:
        errors.append(_err("T-03", n, f"the nature '{it.nature_key}' is not known."))
    elif nature.kind != ctx.kind:
        errors.append(_err("T-03" if ctx.kind == "tds" else "T-17", n,
                           f"'{nature.description}' is a {nature.kind.upper()} nature and cannot be used in a {ctx.kind.upper()} block."))
    deductee = ctx.deductees.get(it.deductee_ledger_id)
    if deductee is None:
        errors.append(_err("T-09", n, "the party ledger is not set up as a deductee (PAN and type are needed)."))
    fy_key = ctx.fy_of(ev)
    if fy_key is None:
        errors.append(_err("T-01", n, f"the date {_fmt(ev)} is not inside any financial year of this client."))
    if nature is not None and nature.rate_mode == "slab_manual":
        if it.manual_tax is None:
            errors.append(_err("T-03", n, f"'{nature.description}' needs the tax amount typed by the accountant (no payroll engine)."))
        elif it.manual_tax < 0 or it.manual_tax != it.manual_tax.quantize(TWO_PLACES):
            errors.append(_err("T-16", n, "the tax amount must not be negative and may have at most 2 decimal places."))
        elif isinstance(amount, Decimal) and it.manual_tax > amount:
            errors.append(_err("T-16", n, f"the tax {format_inr(it.manual_tax)} is more than the amount {format_inr(amount)}."))
    elif nature is not None and it.manual_tax is not None:
        errors.append(_err("T-03", n, f"'{nature.description}' is calculated by the engine; a typed tax amount is not accepted."))
    if errors:
        return None, errors, fy_key

    key = (it.deductee_ledger_id, it.nature_key, fy_key)
    prior = ctx.priors.get(key, PriorPosition())
    run = state.setdefault(key, _Running(prior.cumulative_amount, prior.tax_deducted, dict(prior.monthly_amounts)))
    month = ev.strftime("%Y-%m")
    cum_before, month_before = run.cumulative, run.months.get(month, ZERO)
    warnings: list[str] = []

    if nature.rate_mode == "slab_manual":
        sect = pick_section(ctx.section_refs, it.nature_key, ev)
        if sect is None:
            return None, [_err("T-02", n, f"no rule for {nature.description} on {_fmt(ev)}.")], fy_key
        status = worst_status([nature.verification_status, sect.verification_status])
        used.append(("section", sect.verification_status, sect.source_reference))
        tax = round_tax(it.manual_tax)
        result = TdsItemResult(
            n, it.deductee_ledger_id, it.nature_key, sect.act, sect.section_ref, sect.table_ref, None, ev, amount,
            cum_before, cum_before + amount, False, amount, Decimal(0), RateReason.MANUAL_SALARY.value, None, ZERO, tax, status,
            ("T-02: the section reference is pending verification.",) if sect.verification_status == "pending" else (),
        )
        _advance(run, month, amount, tax)
        return result, [], fy_key

    group = deductee_group(deductee.deductee_type)
    rule = pick_rate_rule(ctx.rates, it.nature_key, group, ev)
    if rule is None:
        near = sorted((s for s in ctx.section_refs if s.nature_key == it.nature_key), key=lambda s: abs((s.effective_from - ev).days))
        label = near[0].section_ref if near else nature.description
        return None, [_err("T-02", n, f"no rule for {label} on {_fmt(ev)} ({nature.description}); the rule table has no row in force for this date.")], fy_key
    sect = pick_section(ctx.section_refs, it.nature_key, ev, rule.act)
    if sect is None:
        return None, [_err("T-02", n, f"no section reference for {nature.description} under {rule.act} on {_fmt(ev)}.")], fy_key
    used.append(("rate", rule.verification_status, rule.source_reference))
    used.append(("section", sect.verification_status, sect.source_reference))
    status = worst_status([rule.verification_status, sect.verification_status, nature.verification_status])
    if rule.verification_status == "pending":
        warnings.append(f"T-02: the rate rule for {sect.section_ref} is pending verification; confirm it with the CA before relying on this figure.")

    def make(base, rate, reason, cert_id, already, tax, crossed):
        result = TdsItemResult(
            n, it.deductee_ledger_id, it.nature_key, rule.act, sect.section_ref, sect.table_ref, rule.id, ev, amount,
            cum_before, cum_before + amount, crossed, base, rate, reason, cert_id, already, tax, status, tuple(warnings),
        )
        _advance(run, month, amount, tax)
        return result, [], fy_key

    if it.nature_key == PURCHASE_OF_GOODS:  # T-15
        flag = ctx.buyer_flags.get(fy_key)
        if flag is None:
            return None, [_err("T-15", n, f"{sect.section_ref}: the buyer-turnover condition is not entered for this financial year; enter it first (no guess).")], fy_key
        if flag is False:
            warnings.append(f"T-15: {sect.section_ref} does not apply because the buyer-turnover condition is 'No' for this year; no tax deducted.")
            return make(ZERO, Decimal(0), RateReason.BELOW_THRESHOLD.value, None, ZERO, ZERO, False)

    base, crossed, already = _base_by_thresholds(rule, amount, cum_before, month_before, run.tax)
    if base <= 0:
        return make(ZERO, Decimal(0), RateReason.BELOW_THRESHOLD.value, None, ZERO, ZERO, False)

    pan_ok = deductee.pan_status == PanStatus.VALID.value
    normal = rule.rate if pan_ok else rule.no_pan_rate
    reason = RateReason.NORMAL.value if pan_ok else RateReason.NO_PAN.value
    if not pan_ok:
        warnings.append(f"T-08: PAN is {deductee.pan_status.replace('_', ' ')}; the higher rate {normal}% applies.")

    cert = None
    if it.lower_cert_id is not None:
        cert = ctx.certs.get(it.lower_cert_id)
        problem = _cert_problem(cert, it, deductee, ev, rule)
        if problem:
            return None, [_err("T-12", n, problem)], fy_key
        if not pan_ok:
            warnings.append(f"T-12: certificate {cert.certificate_no} is not applied because the PAN is not valid.")
            cert = None
    covered = ZERO
    if cert is not None:
        left = cert.max_amount - cert_used.setdefault(cert.id, cert.amount_used)
        covered = max(ZERO, min(base, amount, left))
        if covered <= 0:
            warnings.append(f"T-12: certificate {cert.certificate_no} limit of {format_inr(cert.max_amount)} is used up; the normal rate applies.")
            cert = None
        else:
            cert_used[cert.id] += covered
            if covered < min(base, amount):
                warnings.append(
                    f"T-12: certificate {cert.certificate_no} covers {format_inr(covered)} at {cert.rate}%; the rest is taxed at {normal}%."
                )
    if cert is not None:
        gross = covered * cert.rate / HUNDRED + (base - covered) * normal / HUNDRED
        reason, rate_applied, cert_id = (RateReason.NIL_CERTIFICATE.value if cert.rate == 0 else RateReason.LOWER_CERTIFICATE.value), cert.rate, cert.id
    else:
        gross, rate_applied, cert_id = base * normal / HUNDRED, normal, None
    tax = max(ZERO, round_tax(gross) - already)
    return make(base, rate_applied, reason, cert_id, already, tax, crossed)


def _advance(run: _Running, month: str, amount: Decimal, tax: Decimal) -> None:
    run.cumulative += amount
    run.tax += tax
    run.months[month] = run.months.get(month, ZERO) + amount


def _cert_problem(cert, it: TdsLineIn, deductee: Deductee, ev: date, rule: RateRule) -> str | None:
    if cert is None:
        return "the lower / nil deduction certificate is not found or is switched off."
    if cert.deductee_ledger_id != it.deductee_ledger_id:
        return f"certificate {cert.certificate_no} was issued for another deductee."
    if cert.nature_key is not None and cert.nature_key != it.nature_key:
        return f"certificate {cert.certificate_no} does not cover this nature of payment."
    if not (cert.valid_from <= ev <= cert.valid_to):
        return (f"certificate {cert.certificate_no} is valid from {_fmt(cert.valid_from)} to {_fmt(cert.valid_to)}; "
                f"the payment / credit date {_fmt(ev)} is outside it.")
    if cert.rate >= rule.rate:
        return f"certificate {cert.certificate_no} rate {cert.rate}% is not lower than the normal rate {rule.rate}%."
    return None


def compute_items(items: Sequence[TdsLineIn], ctx: TdsContext) -> TdsComputation:
    """Run every item of a voucher in order (earlier items of the voucher count in the position of later ones)."""
    state: dict[tuple, _Running] = {}
    cert_used: dict = {}
    used: list[tuple[str, str, str]] = []
    results: list[TdsItemResult] = []
    fy_keys: list = []
    errors: list[ValidationError] = []
    for n, it in enumerate(items, start=1):
        result, errs, fy_key = _item(n, it, ctx, state, cert_used, used)
        errors += errs
        if result is not None:
            results.append(result)
            fy_keys.append(fy_key)
    return TdsComputation(tuple(results), tuple(errors), rule_status_of(used), tuple(fy_keys))


def rule_status_of(used: Iterable[tuple[str, str, str]]) -> dict:
    """T-50: {"worst", "tables": {table: weakest status}, "pending_sources": [...]} for the rule rows used."""
    rows = list(used)
    tables: dict[str, str] = {}
    for table in sorted({t for t, _, _ in rows}):
        tables[table] = worst_status(s for t, s, _ in rows if t == table)
    pending = sorted({src for _, s, src in rows if s == VerificationStatus.PENDING.value})
    return {"worst": worst_status(s for _, s, _ in rows), "tables": tables, "pending_sources": pending}


# ---- voucher lines: the generated tax line (T-14, T-16) ------------------------------------------------------------

TDS_VOUCHER_TYPES = ("payment", "purchase", "journal")
TCS_VOUCHER_TYPES = ("sales", "journal")


def expand_lines(
    voucher_type: str,
    kind: str,
    lines: Sequence[tuple[object, Decimal, Decimal]],
    results: Sequence[TdsItemResult],
    payable_of: Mapping[str, object],
    cash_bank_ids: frozenset | set = frozenset(),
) -> tuple[list[tuple[object, Decimal, Decimal]], dict[int, int], list[ValidationError]]:
    """Add the tax line of every item that has tax. `lines` = (ledger_id, debit, credit) as typed (gross amounts).

    TDS: Payment: the party's Debit line stays gross, the Cr Cash / Bank line is reduced by the tax and `Cr TDS payable` is added.
         Purchase / Journal: the party's Credit line is reduced by the tax and `Cr TDS payable` is added.
    TCS: Sales / Journal: the party's Debit line is increased by the tax (the buyer pays it) and `Cr TCS payable` is added.
    Returns (new lines, {item_no: line_no of the tax line}, errors). The tax never exceeds the party line (T-16)."""
    errors: list[ValidationError] = []
    allowed = TDS_VOUCHER_TYPES if kind == "tds" else TCS_VOUCHER_TYPES
    if voucher_type not in allowed:
        names = ", ".join(t.replace("_", " ").title() for t in allowed)
        return list(lines), {}, [ValidationError("T-16", f"{kind.upper()} can be entered on {names} vouchers only, not on a {voucher_type.replace('_', ' ').title()}.")]
    out = [list(x) for x in lines]
    tax_line_of: dict[int, int] = {}
    for r in results:
        if r.tds_amount <= 0:
            continue
        payable = payable_of.get(r.nature_key)
        if payable is None:
            errors.append(_err("T-14", r.item_no, f"no {kind.upper()} payable ledger is set up for '{r.nature_key}'; map the ledger first."))
            continue
        tax = r.tds_amount
        party = [x for x in out if x[0] == r.deductee_ledger_id]
        if kind == "tcs":
            hit = next((x for x in party if x[1] > 0), None)
            if hit is None:
                errors.append(_err("T-16", r.item_no, "the party ledger needs a Debit line in this voucher for the tax collected."))
                continue
            hit[1] += tax
        elif voucher_type == "payment":
            if not any(x[1] >= tax for x in party):
                errors.append(_err("T-16", r.item_no, f"the party ledger needs a Debit line of at least {format_inr(tax)} (the tax) in this Payment."))
                continue
            bank = next((x for x in out if x[0] in cash_bank_ids and x[2] >= tax), None)
            if bank is None:
                errors.append(_err("T-16", r.item_no, f"no Cash / Bank Credit line of at least {format_inr(tax)} to take the tax from."))
                continue
            bank[2] -= tax
        else:
            hit = next((x for x in party if x[2] >= tax), None)
            if hit is None:
                errors.append(_err("T-16", r.item_no, f"the party ledger needs a Credit line of at least {format_inr(tax)} (the tax) in this voucher."))
                continue
            hit[2] -= tax
        out.append([payable, ZERO, tax])
        tax_line_of[r.item_no] = len(out)
    return [tuple(x) for x in out], tax_line_of, errors
