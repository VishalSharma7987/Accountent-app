"""Period-end adjustment helpers (Phase 6 package A, rules F-01 .. F-11). Pure Python: no DB, web or AI imports.

The accountant chooses the two ledgers of a simple adjustment (F-02); the engine checks they fit the type and builds the two-line
journal. Amounts that follow from a rule (provision for doubtful debts, interest on capital / drawings, partner's remuneration) are
COMPUTED here and a typed amount is rejected. Rounding: one `round_half_up` at the end of each computation. Signed balances follow
engine/reports.py (debit positive, credit negative).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.engine.final_types import (
    ZERO,
    AdjustmentInput,
    AdjustmentResult,
    AdjustmentType,
    EntityType,
    Finding,
    JournalLineDraft,
)
from app.engine.money import format_inr, round_half_up

T = AdjustmentType

# ---- which ledgers fit which side (group codes of the seeded groups) -------------------------------------------------------
LIABILITY_GROUPS = frozenset({"current_liabilities", "sundry_creditors", "duties_taxes"})   # outstanding / in advance
PROVISION_GROUPS = frozenset({"provisions"})
ASSET_GROUPS = frozenset({"current_assets", "loans_advances_asset", "deposits_asset"})       # prepaid / accrued income
PARTNER_GROUPS = frozenset({"capital_account", "reserves_surplus"})

# role -> groups a ledger of that role may sit in (F-02); default ledger name and group for `setup-ledgers`
ROLE_GROUPS: dict[str, frozenset[str]] = {
    "trading_account": frozenset({"reserves_surplus"}),
    "profit_and_loss": frozenset({"reserves_surplus"}),
    "surplus_in_pl": frozenset({"reserves_surplus"}),
    "stock_ledger": frozenset({"stock_in_hand"}),
    "depreciation_expense": frozenset({"indirect_expenses", "direct_expenses"}),
    "accumulated_depreciation": frozenset({"fixed_assets"}),
    "bad_debts": frozenset({"indirect_expenses", "direct_expenses"}),
    "doubtful_debts_expense": frozenset({"indirect_expenses", "direct_expenses"}),
    "provision_doubtful_debts": frozenset({"provisions", "current_liabilities"}),
    "interest_on_capital": frozenset({"indirect_expenses"}),
    "interest_on_drawings": frozenset({"indirect_incomes"}),
    "partner_remuneration": frozenset({"indirect_expenses"}),
}
ROLE_DEFAULTS: dict[str, tuple[str, str]] = {   # role -> (ledger name, group code)
    "trading_account": ("Trading Account", "reserves_surplus"),
    "profit_and_loss": ("Profit & Loss Account", "reserves_surplus"),
    "stock_ledger": ("Stock-in-hand", "stock_in_hand"),
    "depreciation_expense": ("Depreciation", "indirect_expenses"),
    "accumulated_depreciation": ("Accumulated Depreciation", "fixed_assets"),
    "bad_debts": ("Bad Debts", "indirect_expenses"),
    "doubtful_debts_expense": ("Provision for Doubtful Debts Expense", "indirect_expenses"),
    "provision_doubtful_debts": ("Provision for Doubtful Debts", "provisions"),
    "interest_on_capital": ("Interest on Capital", "indirect_expenses"),
    "interest_on_drawings": ("Interest on Drawings", "indirect_incomes"),
    "partner_remuneration": ("Partners Remuneration", "indirect_expenses"),
}
SETUP_ROLES_ALL = ("trading_account", "profit_and_loss", "depreciation_expense", "accumulated_depreciation", "bad_debts",
                   "doubtful_debts_expense", "provision_doubtful_debts", "stock_ledger")
SETUP_ROLES_PARTNERS = ("interest_on_capital", "interest_on_drawings", "partner_remuneration")

SIMPLE_TYPES = (T.OUTSTANDING_EXPENSE, T.PREPAID_EXPENSE, T.ACCRUED_INCOME, T.INCOME_IN_ADVANCE, T.PROVISION)
PARTNER_TYPES = (T.INTEREST_ON_CAPITAL, T.INTEREST_ON_DRAWINGS, T.PARTNER_REMUNERATION)
REVERSIBLE_TYPES = SIMPLE_TYPES   # F-04: only accruals / deferrals are reversed on the first day of the next year

_LABEL = {
    T.OUTSTANDING_EXPENSE: "Outstanding expense", T.PREPAID_EXPENSE: "Prepaid expense", T.ACCRUED_INCOME: "Accrued income",
    T.INCOME_IN_ADVANCE: "Income received in advance", T.PROVISION: "Provision", T.BAD_DEBT: "Bad debt written off",
    T.PROVISION_DOUBTFUL_DEBTS: "Provision for doubtful debts", T.INTEREST_ON_CAPITAL: "Interest on capital",
    T.INTEREST_ON_DRAWINGS: "Interest on drawings", T.PARTNER_REMUNERATION: "Partner's remuneration",
}


@dataclass(frozen=True)
class LedgerInfo:
    ledger_id: Any
    name: str
    group_code: str
    parent_group_code: str | None
    nature: str      # asset | liability | income | expense (from the group)


@dataclass(frozen=True)
class PartnerInfo:
    partner_id: Any
    name: str
    capital_ledger_id: Any
    profit_ledger_id: Any   # current ledger when the partner has one, else the capital ledger


@dataclass(frozen=True)
class PartnerTermsIn:
    interest_on_capital_rate: Decimal | None
    interest_on_drawings_rate: Decimal | None
    remuneration_annual: Decimal | None
    deed_reference: str | None


@dataclass(frozen=True)
class AdjustmentContext:
    """Facts the service loaded; the engine decides with them and invents nothing."""

    entity_type: EntityType
    fy_start: date
    fy_end: date
    ledgers: dict[Any, LedgerInfo]
    roles: dict[str, Any]                        # role -> ledger id
    closing_balances: dict[Any, Decimal] = field(default_factory=dict)   # signed, as on the adjustment date
    debtors_closing: Decimal | None = None       # sum of the debit balances of the Sundry Debtors ledgers, after bad debts
    partner: PartnerInfo | None = None
    terms: PartnerTermsIn | None = None
    capital_opening: Decimal = ZERO              # signed opening balance of the partner's capital ledger
    capital_movements: tuple[tuple[date, Decimal], ...] = ()   # (date, signed change) of its posted lines in the FY
    drawings: tuple[tuple[date, Decimal], ...] = ()            # (date, amount) debits of the drawings ledger in the FY


# ============================================================================================ small pure calculations


def _days(a: date, b: date) -> int:
    """Days from a to b with both days counted."""
    return (b - a).days + 1


def reversal_lines(lines: Sequence[JournalLineDraft]) -> tuple[JournalLineDraft, ...]:
    """F-04: the same lines with debit and credit exchanged."""
    return tuple(JournalLineDraft(x.ledger_id, x.credit, x.debit, x.narration) for x in lines)


def doubtful_provision(debtors_closing: Decimal, rate_percent: Decimal, existing_provision: Decimal) -> Decimal:
    """F-05: the CHANGE needed in the provision: round_half_up(debtors x rate / 100, 2) - existing credit balance. Positive = increase."""
    required = round_half_up(debtors_closing * rate_percent / Decimal(100), 2)
    return required - existing_provision


def interest_on_capital(opening_signed: Decimal, movements: Sequence[tuple[date, Decimal]], rate_percent: Decimal,
                        fy_start: date, fy_end: date) -> Decimal:
    """F-07: day-weighted interest on the credit balance of the capital ledger. Each balance segment runs from its date to the next
    change, both days counted; a debit balance segment earns nothing. Rounded half-up once."""
    changes: dict[date, Decimal] = {}
    for when, delta in movements:
        changes[when] = changes.get(when, ZERO) + delta
    balance, start, weighted = opening_signed, fy_start, ZERO
    for when in sorted(changes):
        if when > start:   # close the segment that ends the day before this change
            weighted += max(-balance, ZERO) * _days(start, when - timedelta(days=1))
            start = when
        balance += changes[when]
    weighted += max(-balance, ZERO) * _days(start, fy_end)
    return round_half_up(weighted * rate_percent / Decimal(100) / _days(fy_start, fy_end), 2)


def interest_on_drawings(drawings: Sequence[tuple[date, Decimal]], rate_percent: Decimal, fy_start: date, fy_end: date) -> Decimal:
    """F-07: each drawing from its date to the FY end (both days counted), rate per year over the days of the year, rounded once."""
    weighted = sum((amount * _days(max(when, fy_start), fy_end) for when, amount in drawings), ZERO)
    return round_half_up(weighted * rate_percent / Decimal(100) / _days(fy_start, fy_end), 2)


def remuneration(annual: Decimal, months: int) -> Decimal:
    """F-08: annual x months / 12, rounded half-up."""
    return round_half_up(annual * Decimal(months) / Decimal(12), 2)


# ============================================================================================ builder


def _fmt(on: date) -> str:
    return on.strftime("%d-%m-%Y")


def _err(rule: str, message: str, ledger_id: Any = None) -> Finding:
    return Finding(rule, message, "error", ledger_id=ledger_id)


def _amount_errors(amount: Decimal | None) -> list[Finding]:
    if amount is None:
        return [_err("F-01", "The amount is required.")]
    if amount <= 0:
        return [_err("F-01", f"The amount must be more than zero (got {amount}).")]
    if amount != round_half_up(amount, 2):
        return [_err("F-01", f"The amount {amount} has more than 2 decimal places; it is rejected, not rounded.")]
    return []


def _ledger(ctx: AdjustmentContext, ledger_id: Any, what: str, errors: list[Finding]) -> LedgerInfo | None:
    if ledger_id is None:
        errors.append(_err("F-02", f"Choose the {what} ledger."))
        return None
    info = ctx.ledgers.get(ledger_id)
    if info is None:
        errors.append(_err("F-02", f"The {what} ledger does not exist for this client.", ledger_id))
    return info


def _role(ctx: AdjustmentContext, role: str, errors: list[Finding]) -> LedgerInfo | None:
    ledger_id = ctx.roles.get(role)
    if ledger_id is None or ledger_id not in ctx.ledgers:
        errors.append(_err("F-02", f"The ledger role '{role}' is not set. Run 'Set up ledgers' (or set the role) before this adjustment."))
        return None
    return ctx.ledgers[ledger_id]


def _fit(info: LedgerInfo | None, what: str, ok: bool, expected: str, errors: list[Finding]) -> None:
    if info is not None and not ok:
        errors.append(_err("F-02", f"'{info.name}' is under {info.group_code.replace('_', ' ')}; the {what} must be {expected}.", info.ledger_id))


def _line(ledger_id: Any, amount: Decimal, side: str) -> JournalLineDraft:
    return JournalLineDraft(ledger_id, amount if side == "dr" else ZERO, amount if side == "cr" else ZERO)


def _simple(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding]) -> tuple[Decimal, tuple[JournalLineDraft, ...], dict] | None:
    errors += _amount_errors(inp.amount)
    dr = _ledger(ctx, inp.debit_ledger_id, "debit", errors)
    cr = _ledger(ctx, inp.credit_ledger_id, "credit", errors)
    if dr is not None and cr is not None and dr.ledger_id == cr.ledger_id:
        errors.append(_err("F-02", "The debit and credit ledgers must be different.", dr.ledger_id))
    t = inp.adj_type
    expense = lambda x: x.nature == "expense" 
    income = lambda x: x.nature == "income"   
    if t is T.OUTSTANDING_EXPENSE:
        _fit(dr, "expense", dr is not None and expense(dr), "an expense ledger", errors)
        _fit(cr, "outstanding-expenses ledger", cr is not None and cr.group_code in LIABILITY_GROUPS, "a Current Liabilities ledger", errors)
    elif t is T.PREPAID_EXPENSE:
        _fit(dr, "prepaid-expenses ledger", dr is not None and dr.group_code in ASSET_GROUPS, "a Current Assets ledger", errors)
        _fit(cr, "expense", cr is not None and expense(cr), "an expense ledger", errors)
    elif t is T.ACCRUED_INCOME:
        _fit(dr, "accrued-income ledger", dr is not None and dr.group_code in ASSET_GROUPS, "a Current Assets ledger", errors)
        _fit(cr, "income", cr is not None and income(cr), "an income ledger", errors)
    elif t is T.INCOME_IN_ADVANCE:
        _fit(dr, "income", dr is not None and income(dr), "an income ledger", errors)
        _fit(cr, "income-in-advance ledger", cr is not None and cr.group_code in LIABILITY_GROUPS, "a Current Liabilities ledger", errors)
    else:   # PROVISION
        _fit(dr, "expense", dr is not None and expense(dr), "an expense ledger", errors)
        _fit(cr, "provision ledger", cr is not None and cr.group_code in PROVISION_GROUPS, "a ledger of the Provisions group", errors)
    if errors or dr is None or cr is None or inp.amount is None:
        return None
    amount = round_half_up(inp.amount, 2)
    params = {"debit_ledger_id": dr.ledger_id, "credit_ledger_id": cr.ledger_id}
    return amount, (_line(dr.ledger_id, amount, "dr"), _line(cr.ledger_id, amount, "cr")), params


def _bad_debt(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding]):
    errors += _amount_errors(inp.amount)
    bad = _role(ctx, "bad_debts", errors)
    debtor = _ledger(ctx, inp.party_ledger_id, "debtor", errors)
    if debtor is not None and debtor.group_code != "sundry_debtors":
        errors.append(_err("F-06", f"'{debtor.name}' is not a Sundry Debtors ledger; only a debtor can be written off.", debtor.ledger_id))
        debtor = None
    if debtor is not None and inp.amount is not None and inp.amount > 0 and not errors:
        balance = ctx.closing_balances.get(debtor.ledger_id, ZERO)
        if balance < inp.amount:
            shown = f"debit balance of {format_inr(balance)}" if balance > 0 else "no debit balance"
            errors.append(_err("F-06", f"Bad debt {format_inr(inp.amount)} is more than the {shown} of '{debtor.name}' on {_fmt(inp.as_on_date)}.",
                               debtor.ledger_id))
    if errors or bad is None or debtor is None or inp.amount is None:
        return None
    amount = round_half_up(inp.amount, 2)
    return (amount, (_line(bad.ledger_id, amount, "dr"), _line(debtor.ledger_id, amount, "cr")),
            {"debit_ledger_id": bad.ledger_id, "credit_ledger_id": debtor.ledger_id, "debtor_balance": str(ctx.closing_balances.get(debtor.ledger_id, ZERO))})


def _doubtful(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding]):
    if inp.amount is not None:
        errors.append(_err("F-05", "The provision for doubtful debts is computed from the debtors and the rate; a typed amount is rejected."))
    rate = inp.rate_percent
    if rate is None or rate <= 0 or rate > 100 or rate != round_half_up(rate, 4):
        errors.append(_err("F-05", "Give the provision rate in percent: more than 0 and at most 100, up to 4 decimals."))
    exp = _role(ctx, "doubtful_debts_expense", errors)
    prov = _role(ctx, "provision_doubtful_debts", errors)
    if ctx.debtors_closing is None and not errors:
        errors.append(_err("F-05", "The closing debtors are not available."))
    if errors or exp is None or prov is None or rate is None or ctx.debtors_closing is None:
        return None
    existing = -ctx.closing_balances.get(prov.ledger_id, ZERO)   # credit balance of the provision ledger
    change = doubtful_provision(ctx.debtors_closing, rate, existing)
    if change == 0:
        errors.append(_err("F-05", f"No change: the provision of {format_inr(existing)} already equals {format_inr(rate_amount(ctx.debtors_closing, rate))} "
                                   f"({rate}% of {format_inr(ctx.debtors_closing)})."))
        return None
    amount = abs(change)
    if change > 0:
        lines = (_line(exp.ledger_id, amount, "dr"), _line(prov.ledger_id, amount, "cr"))
    else:
        lines = (_line(prov.ledger_id, amount, "dr"), _line(exp.ledger_id, amount, "cr"))
    params = {"debit_ledger_id": lines[0].ledger_id, "credit_ledger_id": lines[1].ledger_id, "debtors": str(ctx.debtors_closing),
              "rate_percent": str(rate), "required": str(rate_amount(ctx.debtors_closing, rate)), "existing": str(existing),
              "direction": "increase" if change > 0 else "decrease"}
    return amount, lines, params


def rate_amount(base: Decimal, rate: Decimal) -> Decimal:
    return round_half_up(base * rate / Decimal(100), 2)


def _partner_common(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding], rule: str):
    if ctx.entity_type not in (EntityType.PARTNERSHIP, EntityType.LLP):
        errors.append(_err("F-09", f"{_LABEL[inp.adj_type]} is only for a partnership or LLP; this client is a {ctx.entity_type.value}."))
        return None
    if inp.amount is not None:
        errors.append(_err(rule, f"{_LABEL[inp.adj_type]} is computed from the deed terms; a typed amount is rejected."))
    if inp.rate_percent is not None:
        errors.append(_err(rule, "The rate comes from the partner's deed terms for the year; a typed rate is rejected."))
    if ctx.partner is None:
        errors.append(_err(rule, "Choose the partner."))
        return None
    if ctx.terms is None:
        errors.append(_err(rule, f"No deed terms are entered for partner '{ctx.partner.name}' for this financial year."))
        return None
    return ctx.partner, ctx.terms


def _deed(terms: PartnerTermsIn) -> dict:
    return {"deed_reference": terms.deed_reference}


def _interest_capital(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding]):
    got = _partner_common(inp, ctx, errors, "F-07")
    role = _role(ctx, "interest_on_capital", errors) if got else None
    if got is None:
        return None
    partner, terms = got
    if terms.interest_on_capital_rate is None:
        errors.append(_err("F-07", f"No interest-on-capital rate is entered in the deed terms of '{partner.name}'."))
    if errors or role is None or terms.interest_on_capital_rate is None:
        return None
    amount = interest_on_capital(ctx.capital_opening, ctx.capital_movements, terms.interest_on_capital_rate, ctx.fy_start, ctx.fy_end)
    if amount <= 0:
        errors.append(_err("F-07", f"'{partner.name}' has no capital balance in this financial year, so no interest on capital arises."))
        return None
    params = {"debit_ledger_id": role.ledger_id, "credit_ledger_id": partner.profit_ledger_id, "partner_id": partner.partner_id,
              "rate_percent": str(terms.interest_on_capital_rate), "capital_opening": str(ctx.capital_opening),
              "movements": [[when.isoformat(), str(d)] for when, d in ctx.capital_movements], **_deed(terms)}
    return amount, (_line(role.ledger_id, amount, "dr"), _line(partner.profit_ledger_id, amount, "cr")), params


def _interest_drawings(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding]):
    got = _partner_common(inp, ctx, errors, "F-07")
    role = _role(ctx, "interest_on_drawings", errors) if got else None
    drawings_ledger = _ledger(ctx, inp.party_ledger_id, "drawings", errors) if got else None
    if drawings_ledger is not None and drawings_ledger.group_code not in PARTNER_GROUPS:
        errors.append(_err("F-02", f"'{drawings_ledger.name}' is not a Capital Account ledger; choose the partner's drawings ledger.",
                           drawings_ledger.ledger_id))
    if got is None:
        return None
    partner, terms = got
    if terms.interest_on_drawings_rate is None:
        errors.append(_err("F-07", f"No interest-on-drawings rate is entered in the deed terms of '{partner.name}'."))
    if errors or role is None or terms.interest_on_drawings_rate is None:
        return None
    amount = interest_on_drawings(ctx.drawings, terms.interest_on_drawings_rate, ctx.fy_start, ctx.fy_end)
    if amount <= 0:
        errors.append(_err("F-07", f"No drawings are recorded for '{partner.name}' in this financial year, so no interest on drawings arises."))
        return None
    params = {"debit_ledger_id": partner.profit_ledger_id, "credit_ledger_id": role.ledger_id, "partner_id": partner.partner_id,
              "drawings_ledger_id": drawings_ledger.ledger_id if drawings_ledger else None,
              "rate_percent": str(terms.interest_on_drawings_rate),
              "drawings": [[when.isoformat(), str(a)] for when, a in ctx.drawings], **_deed(terms)}
    return amount, (_line(partner.profit_ledger_id, amount, "dr"), _line(role.ledger_id, amount, "cr")), params


def _remuneration(inp: AdjustmentInput, ctx: AdjustmentContext, errors: list[Finding], months: int | None):
    got = _partner_common(inp, ctx, errors, "F-08")
    role = _role(ctx, "partner_remuneration", errors) if got else None
    m = 12 if months is None else months
    if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= 12:
        errors.append(_err("F-08", f"Months must be between 1 and 12 (got {months})."))
    if got is None:
        return None
    partner, terms = got
    if terms.remuneration_annual is None or terms.remuneration_annual <= 0:
        errors.append(_err("F-08", f"No annual remuneration is entered in the deed terms of '{partner.name}'."))
    if errors or role is None or terms.remuneration_annual is None:
        return None
    amount = remuneration(terms.remuneration_annual, m)
    params = {"debit_ledger_id": role.ledger_id, "credit_ledger_id": partner.profit_ledger_id, "partner_id": partner.partner_id,
              "remuneration_annual": str(terms.remuneration_annual), "months": m, **_deed(terms)}
    return amount, (_line(role.ledger_id, amount, "dr"), _line(partner.profit_ledger_id, amount, "cr")), params


def build_adjustment(inp: AdjustmentInput, ctx: AdjustmentContext, *, months: int | None = None) -> AdjustmentResult | list[Finding]:
    """The journal of one adjustment, or the list of errors (nothing is guessed, nothing is rounded silently)."""
    errors: list[Finding] = []
    if not (inp.basis_note or "").strip():
        errors.append(_err("F-01", "The basis note (why this adjustment is made) is required."))
    if not ctx.fy_start <= inp.as_on_date <= ctx.fy_end:
        errors.append(_err("F-01", f"The date {_fmt(inp.as_on_date)} is outside the financial year {_fmt(ctx.fy_start)} to {_fmt(ctx.fy_end)}."))
    if inp.auto_reverse_on is not None:
        if inp.adj_type not in REVERSIBLE_TYPES:
            errors.append(_err("F-04", f"{_LABEL[inp.adj_type]} is not reversed automatically; reverse the voucher instead."))
        elif inp.auto_reverse_on != ctx.fy_end + timedelta(days=1):
            errors.append(_err("F-04", f"The automatic reversal must be dated the first day of the next financial year, {_fmt(ctx.fy_end + timedelta(days=1))}."))

    t = inp.adj_type
    if t in SIMPLE_TYPES:
        built = _simple(inp, ctx, errors)
    elif t is T.BAD_DEBT:
        built = _bad_debt(inp, ctx, errors)
    elif t is T.PROVISION_DOUBTFUL_DEBTS:
        built = _doubtful(inp, ctx, errors)
    elif t is T.INTEREST_ON_CAPITAL:
        built = _interest_capital(inp, ctx, errors)
    elif t is T.INTEREST_ON_DRAWINGS:
        built = _interest_drawings(inp, ctx, errors)
    else:
        built = _remuneration(inp, ctx, errors, months)
    if errors or built is None:
        return errors
    amount, lines, params = built
    params = {**params, "as_on_date": inp.as_on_date.isoformat(), "basis_note": inp.basis_note.strip()}
    if inp.auto_reverse_on is not None:
        params["auto_reverse_on"] = inp.auto_reverse_on.isoformat()
    first = ctx.ledgers[lines[0].ledger_id].name
    narration = f"{_LABEL[t]} - {first} as on {_fmt(inp.as_on_date)}: {inp.basis_note.strip()}"
    return AdjustmentResult(t, amount, lines, narration, params)
