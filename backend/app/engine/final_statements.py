"""Trading A/c, Profit and Loss, Appropriation and Balance Sheet of a non-company client (Phase 6 package C: F-40..F-43, F-44b, F-48).

Pure Python: no DB, web or AI imports. The statements are computed from `LedgerBalanceIn` rows (one per ledger: opening, the year's debit
and credit totals, closing, all excluding the year-end closing vouchers) and the approved closing stock. No ledger maths is repeated here:
`ledger_positions` takes the closing balance from `engine.reports.trial_balance`; everything else is sums of those balances.

Conventions
* `LedgerBalanceIn.parent_group_code` carries the PRIMARY (top) group of a ledger whose own group is a sub-group, else None.
* Signed balances: debit positive, credit negative. A statement line's amount is positive on its own side; where a ledger or group sits
  against its side the line moves to the other side (overdrawn bank on the liability side) - except Capital Account lines, which keep
  their side and may be negative (drawings, a debit current account), and drill-down amounts, which are signed relative to the line
  (a contra such as accumulated depreciation shows as a negative amount under the asset line).
* Line codes: `ledger:<id>` for a one-ledger line, the group code for a group line, fixed codes for the rest.
* Share of profit uses `round_half_up` (shared helper); the last partner takes the remainder so the shares add up exactly (F-62).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine import reports as ledger_reports
from app.engine.final_types import (
    ENGINE_VERSION,
    ClosingStockIn,
    Drill,
    EntityType,
    Finding,
    LedgerBalanceIn,
    PartnerShare,
    Statement,
    StatementFormat,
    StatementLine,
)
from app.engine.models import Group, Ledger, OpeningBalance, PostedLine
from app.engine.money import format_inr, round_half_up
from app.engine.validation import group_chain

ZERO = Decimal("0.00")
HUNDRED = Decimal(100)
TRADING_PRIMARIES = ("sales_accounts", "direct_incomes", "purchase_accounts", "direct_expenses")
PL_PRIMARIES = ("indirect_incomes", "indirect_expenses")
APPROPRIATION_ROLES = ("interest_on_capital", "interest_on_drawings", "partner_remuneration")
GROUP_LABELS = {"fixed_assets": "Fixed Assets", "investments": "Investments", "capital_account": "Capital"}
ORDER = {code: i for i, code in enumerate(ledger_reports.PRIMARY_ORDER)}


@dataclass(frozen=True)
class StatementContext:
    entity: EntityType
    from_date: date
    to_date: date
    stock: ClosingStockIn | None                     # None = not approved (F-41)
    partners: tuple[PartnerShare, ...] = ()
    group_names: Mapping[str, str] = field(default_factory=dict)   # group code -> name, for group lines


# ============================================================================================ ledger positions (loader support)


def ledger_positions(
    ledgers: Sequence[Ledger],
    groups: Mapping[str, Group],
    openings: Mapping[object, OpeningBalance],
    lines: Sequence[PostedLine],
    as_on: date,
    roles: Mapping[object, str] | None = None,
) -> list[LedgerBalanceIn]:
    """One row per ledger. `lines` must already exclude the closing vouchers of a closed year. The closing balance is the Trial Balance's."""
    tb = ledger_reports.trial_balance(ledgers, groups, openings, lines, as_on)
    closing = {row.ledger_id: row.debit - row.credit for section in tb.sections for row in section.rows}
    debit: dict[object, Decimal] = {}
    credit: dict[object, Decimal] = {}
    for x in lines:
        if x.status in ledger_reports.COUNTED_STATUSES and x.voucher_date <= as_on:
            debit[x.ledger_id] = debit.get(x.ledger_id, ZERO) + x.debit
            credit[x.ledger_id] = credit.get(x.ledger_id, ZERO) + x.credit
    out = []
    for ledger in ledgers:
        chain = group_chain(ledger.group_code, groups)
        group = groups.get(ledger.group_code)
        opening = openings.get(ledger.id)
        out.append(LedgerBalanceIn(
            ledger.id, ledger.name, ledger.group_code, chain[-1] if len(chain) > 1 else None,
            group.nature if group else "asset",
            (opening.debit - opening.credit) if opening else ZERO,
            debit.get(ledger.id, ZERO), credit.get(ledger.id, ZERO), closing[ledger.id],
            role=(roles or {}).get(ledger.id),
        ))
    return out


# ============================================================================================ helpers


def _primary(x: LedgerBalanceIn) -> str:
    return x.parent_group_code or x.group_code


def _kind(x: LedgerBalanceIn) -> str:
    if x.group_code == "stock_in_hand":
        return "stock"
    primary = _primary(x)
    if primary in TRADING_PRIMARIES:
        return "trading"
    if primary in PL_PRIMARIES or x.nature in ("income", "expense"):
        return "pl"
    return "bs"


def _sort_key(x: LedgerBalanceIn) -> tuple[int, str]:
    return (ORDER.get(_primary(x), len(ORDER)), x.name.lower())


def _drill(x: LedgerBalanceIn, amount: Decimal) -> Drill:
    return Drill(x.ledger_id, x.name, amount)


def _ledger_line(x: LedgerBalanceIn, amount: Decimal) -> StatementLine:
    return StatementLine(f"ledger:{x.ledger_id}", x.name, amount, drill=(_drill(x, amount),))


def _split_sides(ledgers: Iterable[LedgerBalanceIn]) -> tuple[list[StatementLine], list[StatementLine]]:
    """Debit-balance ledgers to the debit side, credit-balance ledgers to the credit side (one line each, zero balances skipped)."""
    debit, credit = [], []
    for x in sorted(ledgers, key=_sort_key):
        if x.closing > 0:
            debit.append(_ledger_line(x, x.closing))
        elif x.closing < 0:
            credit.append(_ledger_line(x, -x.closing))
    return debit, credit


def _sum(lines: Iterable[StatementLine]) -> Decimal:
    return sum((x.amount for x in lines), ZERO)


def _total(amount: Decimal) -> StatementLine:
    return StatementLine("total", "Total", amount, is_total=True)


def _require_non_company(ctx: StatementContext) -> None:
    if ctx.entity == EntityType.COMPANY:
        raise ValueError("A company's statements follow Schedule III (F-47); use the Schedule III statements.")


def _firm(ctx: StatementContext) -> bool:
    return ctx.entity in (EntityType.PARTNERSHIP, EntityType.LLP)


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# ============================================================================================ findings (F-40, F-41)


def _books_findings(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> list[Finding]:
    out: list[Finding] = []
    tb = sum((x.closing for x in ledgers), ZERO)
    if tb != 0:
        side = "debit" if tb > 0 else "credit"
        out.append(Finding("F-40", f"The Trial Balance does not balance: the {side} side is more by {format_inr(abs(tb))}. "
                                   "Correct the books before relying on the statements.", "error"))
    opening = sum((x.opening for x in ledgers), ZERO)
    if opening != 0:
        side = "debit" if opening > 0 else "credit"
        out.append(Finding("F-40", f"The opening balances of the year do not balance: the {side} side is more by "
                                   f"{format_inr(abs(opening))} (total Debit must equal total Credit).", "error"))
    for x in ledgers:
        if x.group_code == "stock_in_hand" and (x.debit_total != 0 or x.credit_total != 0):
            out.append(Finding("F-40", f"The stock ledger {x.name} has entries in the year. Stock is valued only by the approved closing "
                                       "stock; the entries are not part of the statements.", "warning", ledger_id=x.ledger_id))
        if _kind(x) == "pl" and _primary(x) not in PL_PRIMARIES and x.closing != 0:
            out.append(Finding("F-40", f"The ledger {x.name} is in a group outside the standard Profit and Loss groups; it is shown with "
                                       "the indirect items.", "warning", ledger_id=x.ledger_id))
    stock = ctx.stock
    if stock is None:
        out.append(Finding("F-41", "Closing stock is not approved for this financial year (F-41). Approve the closing stock "
                                   "(from the inventory report, typed, or 'none' for a service business) before using the statements.", "error"))
    elif stock.as_on_date != ctx.to_date:
        out.append(Finding("F-41", f"Closing stock was approved as on {_fmt(stock.as_on_date)}, but this statement is as on "
                                   f"{_fmt(ctx.to_date)}. Approve the closing stock for that date.", "error"))
    return out


# ============================================================================================ core numbers


@dataclass
class _Trading:
    left: list[StatementLine]
    right: list[StatementLine]
    gross: Decimal          # profit positive, loss negative
    opening_stock: Decimal
    closing_stock: Decimal


def _stock_values(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> tuple[Decimal, Decimal, tuple[Drill, ...]]:
    stock_ledgers = [x for x in ledgers if x.group_code == "stock_in_hand"]
    opening = sum((x.opening for x in stock_ledgers), ZERO)
    drill = tuple(_drill(x, x.opening) for x in stock_ledgers if x.opening != 0)
    closing = ctx.stock.carrying_value if ctx.stock is not None else ZERO
    return opening, closing, drill


def _trading(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> _Trading:
    opening, closing, opening_drill = _stock_values(ledgers, ctx)
    debit, credit = _split_sides(x for x in ledgers if _kind(x) == "trading")
    left = [StatementLine("opening_stock", "Opening stock", opening, drill=opening_drill), *debit]
    stock_drill = () if ctx.stock is None else (Drill(None, "Closing stock approved (" + ctx.stock.source + ")", closing),)
    right = [*credit, StatementLine("closing_stock", "Closing stock", closing, drill=stock_drill)]
    return _Trading(left, right, _sum(right) - _sum(left), opening, closing)


def _is_appropriation(x: LedgerBalanceIn, ctx: StatementContext) -> bool:
    return _firm(ctx) and x.role in APPROPRIATION_ROLES


def _pl_items(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> tuple[list[StatementLine], list[StatementLine]]:
    return _split_sides(x for x in ledgers if _kind(x) == "pl" and not _is_appropriation(x, ctx))


def _net_before_appropriation(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> Decimal:
    debit, credit = _pl_items(ledgers, ctx)
    return _trading(ledgers, ctx).gross + _sum(credit) - _sum(debit)


@dataclass
class _Appropriation:
    interest_capital: list[StatementLine]
    remuneration: list[StatementLine]
    interest_drawings: list[StatementLine]
    before: Decimal
    balance: Decimal
    shares: list[tuple[PartnerShare, Decimal]] | None     # None = cannot be shared (F-61 / F-62)
    findings: list[Finding]


def split_profit(balance: Decimal, partners: Sequence[PartnerShare]) -> list[tuple[PartnerShare, Decimal]]:
    """Each partner but the last gets round_half_up(balance x share / 100, 2); the last takes the remainder (F-62)."""
    out: list[tuple[PartnerShare, Decimal]] = []
    given = ZERO
    for partner in partners[:-1]:
        share = round_half_up(balance * partner.share_percent / HUNDRED, 2)
        out.append((partner, share))
        given += share
    out.append((partners[-1], balance - given))
    return out


def _appropriation(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> _Appropriation:
    by_role = {r: [x for x in ledgers if x.role == r] for r in APPROPRIATION_ROLES}
    ioc, ioc_cr = _split_sides(by_role["interest_on_capital"])
    rem, rem_cr = _split_sides(by_role["partner_remuneration"])
    iod_dr, iod = _split_sides(by_role["interest_on_drawings"])
    before = _net_before_appropriation(ledgers, ctx)
    # an unusual side (e.g. a credit balance on the interest on capital ledger) is an income of the account, never dropped
    balance = before + _sum(iod) + _sum(ioc_cr) + _sum(rem_cr) - _sum(ioc) - _sum(rem) - _sum(iod_dr)
    findings: list[Finding] = []
    shares = None
    if not ctx.partners:
        findings.append(Finding("F-61", "This is a partnership / LLP but no partner has a profit share for the year (F-61). "
                                        "Enter the partners and their profit shares.", "error"))
    else:
        total = sum((p.share_percent for p in ctx.partners), Decimal(0))
        if total != HUNDRED:
            findings.append(Finding("F-62", f"The partners' profit shares add up to {total:.4f} per cent, not 100.0000 (F-62). "
                                            "The profit is shown unallocated until the shares are corrected.", "error"))
        else:
            shares = split_profit(balance, ctx.partners)
    return _Appropriation(ioc + ioc_cr, rem + rem_cr, iod + iod_dr, before, balance, shares, findings)


# ============================================================================================ builders


def _statement(key: str, fmt: StatementFormat, title: str, ctx: StatementContext, left, right, totals, findings) -> Statement:
    return Statement(key, fmt, title, ctx.from_date, ctx.to_date, tuple(left), tuple(right), totals, (), tuple(findings), ENGINE_VERSION)


def build_trading(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> Statement:
    """F-42: Dr opening stock + purchases + direct expenses (+ gross profit); Cr sales + direct incomes + closing stock (+ gross loss)."""
    _require_non_company(ctx)
    t = _trading(ledgers, ctx)
    left, right = list(t.left), list(t.right)
    if t.gross > 0:
        left.append(StatementLine("gross_profit", "Gross profit c/d", t.gross))
    elif t.gross < 0:
        right.append(StatementLine("gross_loss", "Gross loss c/d", -t.gross))
    total = max(_sum(left), _sum(right))
    left.append(_total(total))
    right.append(_total(total))
    totals = {"gross_profit": t.gross, "opening_stock": t.opening_stock, "closing_stock": t.closing_stock}
    return _statement("trading", StatementFormat.HORIZONTAL, "Trading Account", ctx, left, right, totals, _books_findings(ledgers, ctx))


def build_profit_loss(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext, fmt: StatementFormat) -> Statement:
    """F-43: gross profit / loss + indirect incomes - indirect expenses (partnership / LLP: net profit BEFORE appropriation)."""
    _require_non_company(ctx)
    gross = _trading(ledgers, ctx).gross
    debit, credit = _pl_items(ledgers, ctx)
    net = gross + _sum(credit) - _sum(debit)
    name = "Net profit before appropriation" if _firm(ctx) else "Net profit"
    loss_name = "Net loss before appropriation" if _firm(ctx) else "Net loss"
    totals = {"gross_profit": gross, "net_profit": net}
    findings = _books_findings(ledgers, ctx)
    title = "Profit and Loss Account"
    if fmt == StatementFormat.VERTICAL:
        lines = [StatementLine("gross_profit", "Gross profit b/d" if gross >= 0 else "Gross loss b/d", abs(gross))]
        lines += [StatementLine(x.code, "Add: " + x.label, x.amount, drill=x.drill) for x in credit]
        lines += [StatementLine(x.code, "Less: " + x.label, x.amount, drill=x.drill) for x in debit]
        lines.append(StatementLine("net_profit", name if net >= 0 else loss_name, abs(net), is_total=True))
        return _statement("profit_loss", fmt, title, ctx, lines, (), totals, findings)
    left, right = list(debit), list(credit)
    if gross > 0:
        right.insert(0, StatementLine("gross_profit", "Gross profit b/d", gross))
    elif gross < 0:
        left.insert(0, StatementLine("gross_loss", "Gross loss b/d", -gross))
    if net > 0:
        left.append(StatementLine("net_profit", name + " c/d", net))
    elif net < 0:
        right.append(StatementLine("net_loss", loss_name + " c/d", -net))
    total = max(_sum(left), _sum(right))
    left.append(_total(total))
    right.append(_total(total))
    return _statement("profit_loss", StatementFormat.HORIZONTAL, title, ctx, left, right, totals, findings)


def build_appropriation(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> Statement:
    """F-43 / F-62 (partnership and LLP): interest and remuneration, then the balance shared in the profit ratio."""
    if not _firm(ctx):
        raise ValueError("The appropriation account exists only for a partnership or an LLP.")
    a = _appropriation(ledgers, ctx)
    left = [*a.interest_capital, *a.remuneration]
    right: list[StatementLine] = []
    if a.before >= 0:
        right.append(StatementLine("net_profit_before_appropriation", "Net profit before appropriation", a.before))
    else:
        left.append(StatementLine("net_loss_before_appropriation", "Net loss before appropriation", -a.before))
    right += a.interest_drawings
    if a.shares is not None:
        for partner, share in a.shares:
            left.append(StatementLine(f"share:{partner.partner_id}", f"Share of profit: {partner.name}", share,
                                      drill=(Drill(partner.profit_ledger_id, partner.name, share),)))
    elif a.balance != 0:
        left.append(StatementLine("profit_unallocated", "Profit to be shared (not allocated)", a.balance))
    total = max(_sum(left), _sum(right))
    left.append(_total(total))
    right.append(_total(total))
    totals = {"net_profit_before_appropriation": a.before, "balance_to_share": a.balance}
    findings = a.findings + _books_findings(ledgers, ctx)
    return _statement("appropriation", StatementFormat.HORIZONTAL, "Profit and Loss Appropriation Account", ctx, left, right, totals, findings)


# ---------------------------------------------------------------------------------------------- balance sheet


@dataclass
class _Item:
    code: str
    label: str
    bucket: str                     # capital | loans | cur_liab | fixed | invest | cur_assets
    signed: Decimal = ZERO          # debit positive
    drill: list[tuple[Any, str, Decimal]] = field(default_factory=list)   # (ledger id, name, signed)


def _bucket(x: LedgerBalanceIn) -> str:
    primary = _primary(x)
    if x.role == "accumulated_depreciation":
        return "fixed"
    if x.role == "provision_doubtful_debts":
        return "cur_assets"
    if primary == "capital_account":
        return "capital"
    if primary == "loans_liability":
        return "loans"
    if primary == "fixed_assets":
        return "fixed"
    if primary == "investments":
        return "invest"
    if primary in ("current_liabilities", "suspense") or x.nature == "liability":
        return "cur_liab"
    return "cur_assets"


def _bs_sort_key(x: LedgerBalanceIn) -> tuple[int, bool, str]:
    """Contra ledgers (accumulated depreciation, provision for doubtful debts) sort with the assets they reduce, after them."""
    primary = {"accumulated_depreciation": "fixed_assets", "provision_doubtful_debts": "current_assets"}.get(x.role or "", _primary(x))
    return (ORDER.get(primary, len(ORDER)), x.role is not None, x.name.lower())


def _bs_items(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext) -> list[_Item]:
    items: dict[str, _Item] = {}

    def add(code: str, label: str, bucket: str, x: LedgerBalanceIn) -> None:
        item = items.setdefault(code, _Item(code, label, bucket))
        item.signed += x.closing
        item.drill.append((x.ledger_id, x.name, x.closing))

    for x in sorted(ledgers, key=_bs_sort_key):
        if _kind(x) != "bs" or x.closing == 0:
            continue
        bucket = _bucket(x)
        if x.role == "accumulated_depreciation":
            add("fixed_assets", GROUP_LABELS["fixed_assets"], "fixed", x)
        elif x.role == "provision_doubtful_debts":
            add("sundry_debtors", ctx.group_names.get("sundry_debtors", "Sundry Debtors"), "cur_assets", x)
        elif bucket in ("fixed", "invest"):
            add(_primary(x), GROUP_LABELS[_primary(x)] if _primary(x) in GROUP_LABELS else ctx.group_names.get(_primary(x), _primary(x)), bucket, x)
        elif bucket == "capital" and ctx.entity == EntityType.PROPRIETORSHIP:
            add("capital", "Capital", "capital", x)
        elif x.parent_group_code is not None:
            add(x.group_code, ctx.group_names.get(x.group_code, x.group_code), bucket, x)
        else:
            add(f"ledger:{x.ledger_id}", x.name, bucket, x)
    return list(items.values())


def _lines_from_items(items: Iterable[_Item], liability_side: bool) -> list[StatementLine]:
    out = []
    for item in items:
        amount = -item.signed if liability_side else item.signed
        sign = Decimal(-1) if liability_side else Decimal(1)
        out.append(StatementLine(item.code, item.label, amount, drill=tuple(Drill(i, n, sign * a) for i, n, a in item.drill)))
    return out


def build_balance_sheet(ledgers: Sequence[LedgerBalanceIn], ctx: StatementContext, fmt: StatementFormat) -> Statement:
    """F-44b: total assets = total capital and liabilities including the current year's profit, else the difference is an error."""
    _require_non_company(ctx)
    t = _trading(ledgers, ctx)
    net = _net_before_appropriation(ledgers, ctx)
    findings = _books_findings(ledgers, ctx)
    items = _bs_items(ledgers, ctx)
    stock_item = _Item("closing_stock", "Closing stock", "cur_assets", t.closing_stock,
                       [] if ctx.stock is None else [(None, "Closing stock approved (" + ctx.stock.source + ")", t.closing_stock)])
    items.append(stock_item)

    profit_lines: list[StatementLine] = []     # partnership: each partner's share of the year's profit, on the liability side
    if ctx.entity == EntityType.PROPRIETORSHIP:
        capital = next((i for i in items if i.code == "capital"), None)
        if capital is None:
            capital = _Item("capital", "Capital", "capital")
            items.append(capital)
        capital.signed -= net
        capital.drill.append((None, "Net profit for the year" if net >= 0 else "Net loss for the year", -net))
    elif _firm(ctx):
        a = _appropriation(ledgers, ctx)
        findings += a.findings
        if a.shares is not None:
            profit_lines = [StatementLine(f"share:{p.partner_id}", f"{p.name} - share of profit for the year", s,
                                          drill=(Drill(p.profit_ledger_id, p.name, s),)) for p, s in a.shares]
        elif a.balance != 0:
            profit_lines = [StatementLine("profit_unallocated", "Profit for the year (not yet shared)", a.balance,
                                          drill=(Drill(None, "Profit after appropriation", a.balance),))]
        # interest / remuneration ledgers are real ledgers (already credited to the partners); the balance sheet needs only the shares

    totals: dict[str, Decimal] = {"net_profit": _net_before_appropriation(ledgers, ctx), "closing_stock": t.closing_stock}
    if fmt == StatementFormat.VERTICAL:
        return _vertical_bs(items, profit_lines, ctx, totals, findings)
    return _horizontal_bs(items, profit_lines, ctx, totals, findings)


LIABILITY_BUCKETS = ("capital", "loans", "cur_liab")
LEFT_RANK = {"capital": 0, "loans": 1, "cur_liab": 2}
RIGHT_RANK = {"fixed": 0, "invest": 1, "cur_assets": 2}


def _horizontal_bs(items, profit_lines, ctx, totals, findings) -> Statement:
    left: list[tuple[int, int, str, StatementLine]] = []
    right: list[tuple[int, int, str, StatementLine]] = []
    for item in items:
        if item.signed == 0:
            continue
        liability = item.bucket in LIABILITY_BUCKETS
        natural = item.signed <= 0 if liability else item.signed >= 0
        stock_first = 0 if item.code == "closing_stock" else 1
        if liability and (natural or item.bucket == "capital"):          # capital keeps its side even when negative
            left.append((LEFT_RANK[item.bucket], stock_first, item.label.lower(), _lines_from_items([item], True)[0]))
        elif liability:                                                  # debit balance of a liability: shown as an asset
            right.append((3, stock_first, item.label.lower(), _lines_from_items([item], False)[0]))
        elif natural:
            right.append((RIGHT_RANK[item.bucket], stock_first, item.label.lower(), _lines_from_items([item], False)[0]))
        else:                                                            # credit balance of an asset (bank overdraft): a liability
            left.append((3, stock_first, item.label.lower(), _lines_from_items([item], True)[0]))
    left_lines = [x[3] for x in sorted(left, key=lambda r: r[:3])]
    capital_end = sum(1 for x in left if x[0] == 0)
    left_lines[capital_end:capital_end] = profit_lines
    right_lines = [x[3] for x in sorted(right, key=lambda r: r[:3])]
    total_liabilities, total_assets = _sum(left_lines), _sum(right_lines)
    findings = list(findings)
    if total_liabilities != total_assets:
        findings.append(_unbalanced(total_assets, total_liabilities))
    left_lines.append(_total(total_liabilities))
    right_lines.append(_total(total_assets))
    totals.update({"total_liabilities": total_liabilities, "total_assets": total_assets, "difference": total_assets - total_liabilities})
    return _statement("balance_sheet", StatementFormat.HORIZONTAL, "Balance Sheet", ctx, left_lines, right_lines, totals, findings)


def _unbalanced(assets: Decimal, liabilities: Decimal) -> Finding:
    side = "assets" if assets > liabilities else "capital and liabilities"
    return Finding("F-44b", f"The Balance Sheet does not balance: assets {format_inr(assets)}, capital and liabilities {format_inr(liabilities)}; "
                            f"the {side} side is more by {format_inr(abs(assets - liabilities))}.", "error")


def _vertical_bs(items, profit_lines, ctx, totals, findings) -> Statement:
    def pick(*buckets):
        return [i for i in items if i.bucket in buckets and i.signed != 0]

    sources = _lines_from_items(sorted(pick("capital", "loans"), key=lambda i: (i.bucket != "capital", i.label.lower())), True)
    capital_count = sum(1 for i in items if i.bucket == "capital" and i.signed != 0)
    sources[capital_count:capital_count] = profit_lines
    sources_total = _sum(sources)
    fixed = [StatementLine(i.code, i.label, i.signed, drill=_lines_from_items([i], False)[0].drill) for i in pick("fixed", "invest")]
    current_assets = _lines_from_items(sorted(pick("cur_assets"), key=lambda i: (i.code != "closing_stock", i.label.lower())), False)
    current_liabilities = _lines_from_items(sorted(pick("cur_liab"), key=lambda i: i.label.lower()), True)
    nca = _sum(current_assets) - _sum(current_liabilities)
    application_total = _sum(fixed) + nca
    findings = list(findings)
    if sources_total != application_total:
        findings.append(_unbalanced(application_total, sources_total))
    lines = [StatementLine("hdr_sources", "Sources of funds", ZERO), *sources, StatementLine("sources_total", "Total sources of funds", sources_total, is_total=True),
             StatementLine("hdr_application", "Application of funds", ZERO), *fixed,
             StatementLine("net_current_assets", "Net current assets", nca)]
    lines += [StatementLine(x.code, x.label, x.amount, drill=x.drill, level=1) for x in current_assets]
    lines += [StatementLine(x.code, "Less: " + x.label, x.amount, drill=x.drill, level=1) for x in current_liabilities]
    lines.append(StatementLine("application_total", "Total application of funds", application_total, is_total=True))
    totals.update({"sources_total": sources_total, "application_total": application_total, "net_current_assets": nca,
                   "difference": application_total - sources_total})
    return _statement("balance_sheet", StatementFormat.VERTICAL, "Balance Sheet", ctx, lines, (), totals, findings)
