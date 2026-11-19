"""Year-end close of a financial year (Phase 6 package F: F-60..F-62, F-63, F-65, F-66). Pure Python: no DB, web or AI imports.

The engine takes the ledger positions the statements use (`LedgerBalanceIn`, which EXCLUDE the closing vouchers) and the approved closing
stock, and returns the three closing Journal drafts, the profit figures, the carry-forward and findings. It does no ledger maths of its
own beyond moving balances: the gross profit and the balance to share come from `engine/final_statements.py` and are cross-checked
(a difference is an internal-consistency error, never silently used). Amounts are Decimal; shares use the shared `round_half_up`.

Voucher shapes (docs/PHASE6_PLAN.md, worked example)
  trading        : every Sales / Purchase / Direct income / Direct expense ledger is closed; each Stock-in-hand ledger is credited with its
                   opening and the `stock_ledger` role ledger is debited with the approved closing stock; the balance goes to `trading_account`.
  profit_loss    : `trading_account` and every other Profit and Loss ledger (indirect items, and for firms interest / remuneration) are
                   closed to `profit_and_loss`.
  appropriation  : `profit_and_loss` to the owner. Proprietorship: drawings ledgers (a Capital Account ledger named Drawings) and the
                   profit go to the one capital ledger. Partnership / LLP: the balance is shared in the profit ratio (F-62). Company: to
                   `surplus_in_pl`.
A step with nothing to move is not created (V-01 needs two lines).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine import final_statements as fs
from app.engine.final_types import (
    CarryForward,
    ClosingEntryLine,
    ClosingStockIn,
    ClosingVoucherDraft,
    EntityType,
    Finding,
    LedgerBalanceIn,
    PartnerShare,
)
from app.engine.money import format_inr, round_half_up

ZERO = Decimal("0.00")
HUNDRED = Decimal("100.0000")
STEPS = ("trading", "profit_loss", "appropriation")
ON_ACCOUNT_REF = "On account"
FIRMS = (EntityType.PARTNERSHIP, EntityType.LLP)


@dataclass(frozen=True)
class CloseContext:
    entity: EntityType
    fy_start: date
    fy_end: date
    fy_label: str                                     # '2026-27'
    stock: ClosingStockIn | None
    partners: tuple[PartnerShare, ...] = ()
    group_names: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ClosePlan:
    vouchers: tuple[ClosingVoucherDraft, ...]
    gross_profit: Decimal                             # loss negative
    net_profit: Decimal                               # before appropriation for a firm; loss negative
    balance_to_transfer: Decimal                      # what the appropriation voucher moves (profit positive)
    appropriation: tuple[tuple[Any, str, Decimal], ...]   # (ledger_id, ledger name, credit amount; negative = debit)
    carry: CarryForward | None
    findings: tuple[Finding, ...]

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")


def _err(rule: str, message: str, ledger_id: Any = None) -> Finding:
    return Finding(rule, message, "error", ledger_id=ledger_id)


def _lines(net: Mapping[Any, Decimal]) -> tuple[ClosingEntryLine, ...]:
    """Signed amounts (debit positive) as voucher lines: debits first, then credits; zero amounts are dropped."""
    debit = [ClosingEntryLine(k, debit=v) for k, v in net.items() if v > 0]
    credit = [ClosingEntryLine(k, credit=-v) for k, v in net.items() if v < 0]
    return tuple(debit + credit)


def _draft(step: str, ctx: CloseContext, number: int, text: str, net: Mapping[Any, Decimal]) -> ClosingVoucherDraft | None:
    lines = _lines(net)
    if not lines:
        return None
    return ClosingVoucherDraft(step, ctx.fy_end, f"Year-end closing entry {number} of 3 ({ctx.fy_label}): {text}", f"YEC/{ctx.fy_label}/{step}", lines)


def _one(ledgers: Sequence[LedgerBalanceIn], role: str) -> LedgerBalanceIn | None:
    found = [x for x in ledgers if x.role == role]
    return found[0] if found else None


def share_profit(balance: Decimal, partners: Sequence[PartnerShare]) -> tuple[list[tuple[PartnerShare, Decimal]] | None, list[Finding]]:
    """F-61 / F-62: the shares must add up to exactly 100.0000; each partner but the last gets round_half_up(balance x share / 100, 2),
    the last takes the remainder (the split itself is `final_statements.split_profit`)."""
    if not partners:
        return None, [_err("F-61", "This is a partnership / LLP but no partner has a profit share for the year (F-61). "
                                   "Enter the partners and their profit shares.")]
    total = sum((p.share_percent for p in partners), Decimal(0))
    if total != HUNDRED:
        return None, [_err("F-62", f"The partners' profit shares add up to {total:.4f} per cent, not 100.0000 (F-62).")]
    return fs.split_profit(balance, partners), []


def _stock_net(ledgers: Sequence[LedgerBalanceIn], ctx: CloseContext, findings: list[Finding]) -> dict[Any, Decimal]:
    """Each stock ledger is credited with its opening; the stock_ledger role ledger is debited with the approved closing stock."""
    stock_ledgers = [x for x in ledgers if x.group_code == "stock_in_hand"]
    closing = ctx.stock.carrying_value if ctx.stock is not None else ZERO
    target = _one(ledgers, "stock_ledger")
    out: dict[Any, Decimal] = {}
    for x in stock_ledgers:
        if x.debit_total != 0 or x.credit_total != 0:
            findings.append(_err("F-60", f"The stock ledger {x.name} has entries in the year. Closing stock is carried only when the stock "
                                         "ledger holds just its opening balance; move the entries to purchases / sales first.", x.ledger_id))
    if target is None:
        if stock_ledgers or closing != 0:
            findings.append(_err("F-02", "The ledger role 'stock_ledger' is not set. Choose the Stock-in-hand ledger that carries the closing "
                                         "stock (Set up ledgers) before closing the year."))
        return out
    if target.group_code != "stock_in_hand":
        findings.append(_err("F-02", f"The stock ledger role is on {target.name}, which is not in the Stock-in-hand group.", target.ledger_id))
        return out
    for x in stock_ledgers:
        out[x.ledger_id] = -x.opening
    out[target.ledger_id] = out.get(target.ledger_id, ZERO) + closing
    return out


def _closing_candidates(ledgers: Sequence[LedgerBalanceIn]) -> tuple[list[LedgerBalanceIn], list[LedgerBalanceIn]]:
    capital = [x for x in ledgers if x.group_code == "capital_account" and not x.role]
    drawings = [x for x in capital if "drawing" in x.name.casefold()]
    return [x for x in capital if x not in drawings], drawings


def build_closing_plan(ledgers: Sequence[LedgerBalanceIn], ctx: CloseContext) -> ClosePlan:
    """The three closing vouchers, the figures behind them and the carry-forward. Any finding of severity error blocks the close."""
    findings: list[Finding] = []
    sctx = fs.StatementContext(ctx.entity, ctx.fy_start, ctx.fy_end, ctx.stock, ctx.partners, ctx.group_names)
    if ctx.stock is None:
        findings.append(_err("F-41", "Closing stock is not approved for this financial year (F-41)."))
    trading = _one(ledgers, "trading_account")
    pl = _one(ledgers, "profit_and_loss")
    for role, x in (("trading_account", trading), ("profit_and_loss", pl)):
        if x is None:
            findings.append(_err("F-02", f"The ledger role '{role}' is not set. Run 'Set up ledgers' for the year first."))
        elif x.closing != 0:
            findings.append(_err("F-60", f"The clearing ledger {x.name} must have a nil balance before the close (it has "
                                         f"{format_inr(abs(x.closing))} {'Dr' if x.closing > 0 else 'Cr'}).", x.ledger_id))
    if ctx.stock is None or trading is None or pl is None:
        return ClosePlan((), ZERO, ZERO, ZERO, (), None, tuple(findings))

    # ---- voucher 1: trading
    net1: dict[Any, Decimal] = {}
    for x in sorted((x for x in ledgers if fs._kind(x) == "trading"), key=fs._sort_key):
        if x.closing != 0:
            net1[x.ledger_id] = -x.closing
    net1.update(_stock_net(ledgers, ctx, findings))
    gross = fs._trading(ledgers, sctx).gross
    to_trading = -sum(net1.values(), ZERO)
    if to_trading != -gross and not any(f.severity == "error" for f in findings):
        findings.append(_err("F-63", "The trading closing entry does not agree with the Trading A/c (internal check failed)."))
    if to_trading != 0:
        net1[trading.ledger_id] = to_trading

    # ---- voucher 2: profit and loss
    net2: dict[Any, Decimal] = {}
    trading_after = trading.closing + net1.get(trading.ledger_id, ZERO)
    if trading_after != 0:
        net2[trading.ledger_id] = -trading_after
    for x in sorted((x for x in ledgers if fs._kind(x) == "pl"), key=fs._sort_key):
        if x.closing != 0:
            net2[x.ledger_id] = -x.closing
    to_pl = -sum(net2.values(), ZERO)
    profit = -to_pl                                    # signed credit-positive: profit to be transferred
    firm = ctx.entity in FIRMS
    net_before = fs._net_before_appropriation(ledgers, sctx)
    expected = fs._appropriation(ledgers, sctx).balance if firm else net_before
    if profit != expected and not any(f.severity == "error" for f in findings):
        findings.append(_err("F-63", "The profit and loss closing entry does not agree with the Profit and Loss A/c (internal check failed)."))
    if to_pl != 0:
        net2[pl.ledger_id] = to_pl

    # ---- voucher 3: appropriation
    net3: dict[Any, Decimal] = {}
    appropriation: list[tuple[Any, str, Decimal]] = []
    p = profit
    if ctx.entity == EntityType.PROPRIETORSHIP:
        capital, drawings = _closing_candidates(ledgers)
        owed = sum((x.closing for x in drawings), ZERO)
        if p != 0 or owed != 0:
            if len(capital) != 1:
                findings.append(_err("F-60", "The profit goes to the proprietor's capital ledger, but the Capital Account group does not have exactly one "
                                             f"such ledger ({len(capital)} found, drawings excluded). Keep one capital ledger and a ledger named "
                                             "Drawings."))
            else:
                if p != 0:
                    net3[pl.ledger_id] = p
                for x in drawings:
                    if x.closing != 0:
                        net3[x.ledger_id] = -x.closing
                        appropriation.append((x.ledger_id, x.name, x.closing))
                capital_net = -sum(net3.values(), ZERO)
                if capital_net != 0:
                    net3[capital[0].ledger_id] = capital_net
                appropriation.append((capital[0].ledger_id, capital[0].name, -capital_net))
    elif firm:
        shares, share_findings = share_profit(p, ctx.partners)
        findings += share_findings
        if shares is not None and p != 0:
            net3[pl.ledger_id] = p
            for partner, share in shares:
                net3[partner.profit_ledger_id] = net3.get(partner.profit_ledger_id, ZERO) - share
                appropriation.append((partner.profit_ledger_id, partner.name, share))
    else:   # company
        surplus = _one(ledgers, "surplus_in_pl")
        if p != 0:
            if surplus is None:
                findings.append(_err("F-02", "The ledger role 'surplus_in_pl' (Surplus in Profit and Loss, under Reserves & Surplus) is not set."))
            else:
                net3[pl.ledger_id] = p
                net3[surplus.ledger_id] = -p
                appropriation.append((surplus.ledger_id, surplus.name, p))
    net3 = {k: v for k, v in net3.items() if v != 0}
    if sum(net3.values(), ZERO) != 0:
        findings.append(_err("F-63", "The appropriation closing entry does not balance (internal check failed)."))

    drafts = [d for d in (
        _draft("trading", ctx, 1, "trading account balances and the stock adjustment transferred to the Trading A/c", net1),
        _draft("profit_loss", ctx, 2, "Trading A/c and profit and loss account balances transferred to the Profit and Loss A/c", net2),
        _draft("appropriation", ctx, 3, "Profit and Loss A/c balance transferred to the owner(s)", net3),
    ) if d is not None]
    carry = None
    if not any(f.severity == "error" for f in findings):    # a half-built close would only add noise
        carry, carry_findings = carry_forward(ledgers, drafts)
        findings += carry_findings
    return ClosePlan(tuple(drafts), gross, net_before, profit, tuple(appropriation), carry, tuple(findings))


# ============================================================================================ carry-forward (F-65)


def closing_after(ledgers: Sequence[LedgerBalanceIn], drafts: Sequence[ClosingVoucherDraft]) -> dict[Any, Decimal]:
    """Signed closing balance of every ledger once the closing vouchers are posted."""
    after = {x.ledger_id: x.closing for x in ledgers}
    for d in drafts:
        for line in d.lines:
            after[line.ledger_id] = after.get(line.ledger_id, ZERO) + line.debit - line.credit
    return after


def carry_forward(ledgers: Sequence[LedgerBalanceIn], drafts: Sequence[ClosingVoucherDraft]) -> tuple[CarryForward | None, list[Finding]]:
    """F-65: the opening of the next year = the closing balance (after the closing entries) of every Asset / Liability ledger that is not
    nil. Every Income / Expense ledger and both clearing ledgers must be nil. Total Dr must equal total Cr exactly, else nothing is carried."""
    after = closing_after(ledgers, drafts)
    findings: list[Finding] = []
    rows: list[tuple[Any, Decimal, Decimal]] = []
    for x in sorted(ledgers, key=fs._sort_key):
        balance = after[x.ledger_id]
        if balance != 0 and (x.nature in ("income", "expense") or x.role in ("trading_account", "profit_and_loss")):
            findings.append(_err("F-65", f"{x.name} still has a balance of {format_inr(abs(balance))} {'Dr' if balance > 0 else 'Cr'} after the "
                                         "closing entries, so the year cannot be closed.", x.ledger_id))
        elif balance != 0:
            rows.append((x.ledger_id, balance if balance > 0 else ZERO, -balance if balance < 0 else ZERO))
    debit = sum((r[1] for r in rows), ZERO)
    credit = sum((r[2] for r in rows), ZERO)
    if debit != credit:
        side = "debit" if debit > credit else "credit"
        findings.append(_err("F-65", f"The balances to carry forward do not balance: the {side} side is more by {format_inr(abs(debit - credit))} "
                                     f"(Debit {format_inr(debit)}, Credit {format_inr(credit)}). Nothing is carried."))
    if findings:
        return None, findings
    return CarryForward(tuple(rows), debit, credit), findings


# ============================================================================================ open bills (F-66)


@dataclass(frozen=True)
class OpenItem:
    party_ledger_id: Any
    party_name: str
    bill_ref: str | None             # None = the party's on-account item
    bill_date: date | None
    due_date: date | None
    outstanding: Decimal             # signed, debit positive


@dataclass(frozen=True)
class CarriedBill:
    party_ledger_id: Any
    bill_ref: str
    bill_date: date
    due_date: date
    amount: Decimal                  # signed


def carry_open_bills(items: Sequence[OpenItem], parties: Mapping[Any, str], carried_balance: Mapping[Any, Decimal]) -> tuple[list[CarriedBill], list[Finding]]:
    """F-66: the open bills carry with the same reference, dates and amount; the items of each bill-wise party must add up to that
    party ledger's carried opening balance (B-07), else the close is blocked and the difference shown. An on-account item carries as
    the reference 'On account'. Nothing is guessed: an item without a date, or two items with one reference, is an error."""
    out: list[CarriedBill] = []
    findings: list[Finding] = []
    seen: set[tuple[Any, str]] = set()
    totals: dict[Any, Decimal] = {}
    for it in items:
        ref = ON_ACCOUNT_REF if it.bill_ref is None else it.bill_ref.strip()
        if it.bill_date is None or it.due_date is None:
            findings.append(_err("F-66", f"The open item '{ref}' of {it.party_name} has no date, so it cannot be carried forward.", it.party_ledger_id))
            continue
        key = (it.party_ledger_id, ref.casefold())
        if key in seen:
            findings.append(_err("F-66", f"{it.party_name} has two open items with the reference '{ref}'; a reference can be carried once.", it.party_ledger_id))
            continue
        seen.add(key)
        totals[it.party_ledger_id] = totals.get(it.party_ledger_id, ZERO) + it.outstanding
        out.append(CarriedBill(it.party_ledger_id, ref, it.bill_date, it.due_date, it.outstanding))
    for party_id, name in parties.items():
        have, want = totals.get(party_id, ZERO), carried_balance.get(party_id, ZERO)
        if have != want:
            diff = have - want
            findings.append(_err("F-66", f"The open bills of {name} add up to {format_inr(abs(have))} {'Dr' if have >= 0 else 'Cr'} but its closing "
                                         f"balance is {format_inr(abs(want))} {'Dr' if want >= 0 else 'Cr'} (difference {format_inr(abs(diff))}). "
                                         "Fix the bills before closing.", party_id))
    return out, findings


# ============================================================================================ stock (F-66, Phase 5 S-08)


@dataclass(frozen=True)
class StockItemIn:
    item_id: Any
    name: str
    closing_qty: Decimal
    carrying_value: Decimal
    godown_qty: tuple[tuple[Any, Decimal], ...]     # closing quantity per godown


@dataclass(frozen=True)
class CarriedStock:
    item_id: Any
    godown_id: Any
    quantity: Decimal
    value: Decimal


def spread_over_godowns(value: Decimal, quantities: Sequence[Decimal]) -> list[Decimal]:
    """Value per godown in proportion to quantity: each but the last is round_half_up(value x qty / total, 2); the last takes the remainder."""
    total = sum(quantities, Decimal(0))
    out: list[Decimal] = []
    given = ZERO
    for q in quantities[:-1]:
        v = round_half_up(value * q / total, 2)
        out.append(v)
        given += v
    out.append(value - given)
    return out


def carry_stock(items: Sequence[StockItemIn], approved_carrying: Decimal) -> tuple[list[CarriedStock], list[Finding]]:
    """The closing stock carries per item and godown at carrying value (cost or NRV), godown values in proportion to quantity. The item
    values must add up to the approved closing stock."""
    findings: list[Finding] = []
    out: list[CarriedStock] = []
    total = sum((x.carrying_value for x in items), ZERO)
    if total != approved_carrying:
        findings.append(_err("F-66", f"The inventory report now values the closing stock at {format_inr(total)} but {format_inr(approved_carrying)} was "
                                     "approved. Approve the closing stock again."))
    for x in items:
        godowns = [(g, q) for g, q in x.godown_qty if q > 0]
        if x.closing_qty <= 0:
            if x.carrying_value != 0:
                findings.append(_err("F-66", f"{x.name} has no quantity but a value of {format_inr(x.carrying_value)}; it cannot be carried."))
            continue
        if sum((q for _, q in godowns), Decimal(0)) != x.closing_qty:
            findings.append(_err("F-66", f"The godown quantities of {x.name} do not add up to its closing quantity."))
            continue
        for (g, q), v in zip(godowns, spread_over_godowns(x.carrying_value, [q for _, q in godowns]), strict=True):
            out.append(CarriedStock(x.item_id, g, q, v))
    return out, findings
