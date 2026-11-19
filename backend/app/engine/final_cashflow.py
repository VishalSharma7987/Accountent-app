"""Cash Flow Statement, AS 3 indirect method (Phase 6 package E, rules F-49 and F-50). Pure Python: no DB, web or AI imports.

Input: the ledger positions of the year (opening and closing, as built for the other statements, closing vouchers excluded), the net profit
the Profit and Loss statement reports, and the approved closing stock. Nothing is estimated: every line is a movement of a ledger.

Identity used (debit positive): cash movement = profit - (closing stock - opening stock) - sum of the movements of all other
balance-sheet ledgers, where each movement is placed in exactly one section:
  * operating   : profit, plus P&L ledgers classed investing / financing taken out of profit, plus non-cash balance-sheet ledgers
                  (accumulated depreciation = the depreciation add-back), plus working-capital movements (stock, debtors, creditors,
                  provisions, duties, loans and advances, deposits, suspense);
  * investing   : fixed assets and investments, and P&L ledgers classed investing (interest and dividend received);
  * financing   : capital, reserves, loans, and P&L ledgers classed financing (interest paid).
The class of a ledger is its own `cf_class` (the Schedule III / client classification), else the default of its group below. Cash and bank
(class cash_equivalent) are the result, not a movement. F-50 compares the closing cash found this way with the cash and bank of the
balance sheet. Signed amounts: a positive line is cash received, a negative line is cash paid.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.engine import reports as ledger_reports
from app.engine.final_types import (
    ENGINE_VERSION,
    ClosingStockIn,
    Drill,
    EntityType,
    Finding,
    LedgerBalanceIn,
    Statement,
    StatementFormat,
    StatementLine,
)
from app.engine.money import format_inr

ZERO = Decimal("0.00")
STOCK_GROUP = "stock_in_hand"
APPROPRIATION_ROLES = ("interest_on_capital", "interest_on_drawings", "partner_remuneration")
TAX_LINE = "tax_expense"

# Default class of a balance-sheet group when the ledger has no class of its own (accounting practice, not law).
GROUP_CLASS = {
    "cash_in_hand": "cash_equivalent", "bank_accounts": "cash_equivalent",
    "fixed_assets": "investing", "investments": "investing",
    "capital_account": "financing", "reserves_surplus": "financing", "loans_liability": "financing",
}
ORDER = {code: i for i, code in enumerate(ledger_reports.PRIMARY_ORDER)}


@dataclass(frozen=True)
class CashFlowContext:
    entity: EntityType
    from_date: date
    to_date: date
    stock: ClosingStockIn | None                     # None = not approved
    labels: Mapping[str, str] = field(default_factory=dict)   # group code or Schedule III line code -> label
    required: bool = False                           # company, or the accountant asked: an F-50 difference is then an error


def _primary(x: LedgerBalanceIn) -> str:
    return x.parent_group_code or x.group_code


def _is_pl(x: LedgerBalanceIn) -> bool:
    return x.nature in ("income", "expense") and x.group_code != STOCK_GROUP


def _class(x: LedgerBalanceIn) -> str:
    """Cash-flow class of a balance-sheet ledger."""
    if x.role == "accumulated_depreciation":
        return "non_cash"
    if x.cf_class in ("operating", "investing", "financing", "cash_equivalent", "non_cash", "equity_profit"):
        return "financing" if x.cf_class == "equity_profit" else x.cf_class
    return GROUP_CLASS.get(x.group_code) or GROUP_CLASS.get(_primary(x)) or "operating"


def _key(x: LedgerBalanceIn) -> str:
    if x.role == "provision_doubtful_debts":
        return "sundry_debtors"
    return x.line_code or x.group_code


def _title(code: str) -> str:
    return code.replace("_", " ").strip().title()


def _label(code: str, ctx: CashFlowContext) -> str:
    return ctx.labels.get(code) or _title(code)


def _drills(items: Sequence[tuple[LedgerBalanceIn, Decimal]]) -> tuple[Drill, ...]:
    return tuple(Drill(x.ledger_id, x.name, amount) for x, amount in items if amount != 0)


def _sum(values) -> Decimal:
    return sum(values, ZERO)


def _sort(x: LedgerBalanceIn) -> tuple[int, str]:
    return (ORDER.get(_primary(x), len(ORDER)), x.name.lower())


def _heading(code: str, label: str) -> StatementLine:
    return StatementLine(f"heading:{code}", label, ZERO)


def _group_lines(prefix: str, items: Sequence[tuple[LedgerBalanceIn, Decimal]], ctx: CashFlowContext,
                 verb_asset: str, verb_liability: str) -> list[StatementLine]:
    """One line per group (or Schedule III line) with the ledger drill-down; groups whose movement is nil are left out."""
    groups: dict[str, list[tuple[LedgerBalanceIn, Decimal]]] = {}
    for x, effect in sorted(items, key=lambda t: _sort(t[0])):
        groups.setdefault(_key(x), []).append((x, effect))
    out = []
    for key, members in groups.items():
        total = _sum(e for _, e in members)
        if total == 0:
            continue
        lead = next((x for x, _ in members if x.role is None), members[0][0])
        verb = verb_asset if lead.nature == "asset" else verb_liability
        out.append(StatementLine(f"{prefix}:{key}", f"{verb} {_label(key, ctx)}".strip(), total, drill=_drills(members), level=1))
    return out


def build_cash_flow(ledgers: Sequence[LedgerBalanceIn], profit: Decimal, ctx: CashFlowContext,
                    upstream: Sequence[Finding] = ()) -> Statement:
    """F-49 / F-50. `profit` is the net profit before tax and extraordinary items that the P&L statement reports (before appropriation
    for a firm). `upstream` are the findings of that statement: its errors make this statement unreliable and are carried over."""
    findings: list[Finding] = [f for f in upstream if f.severity == "error"]

    stock_ledgers = [x for x in ledgers if x.group_code == STOCK_GROUP]
    opening_stock = _sum(x.opening for x in stock_ledgers)
    stock_missing = ctx.stock is None
    if stock_missing and opening_stock != 0:
        findings.append(Finding("F-41", "Closing stock is not approved for this financial year, so the stock movement of the cash flow "
                                        "cannot be found. Approve the closing stock first.", "error"))
    closing_stock = ZERO if ctx.stock is None else ctx.stock.carrying_value
    stock_effect = opening_stock - closing_stock                       # an increase in stock uses cash

    # ---- profit adjustments from P&L ledgers (taken out of profit and shown in their own section)
    pl_adjust: list[StatementLine] = []
    inv_pl: list[StatementLine] = []
    fin_pl: list[StatementLine] = []
    appropriation = ZERO
    appropriation_items: list[tuple[LedgerBalanceIn, Decimal]] = []
    tax = ZERO
    tax_items: list[tuple[LedgerBalanceIn, Decimal]] = []
    for x in sorted((y for y in ledgers if _is_pl(y)), key=lambda y: y.name.lower()):
        movement = x.closing - x.opening                               # debit positive
        if movement == 0:
            continue
        if x.role in APPROPRIATION_ROLES and ctx.entity != EntityType.COMPANY:
            appropriation += -movement
            appropriation_items.append((x, -movement))
        elif x.line_code == TAX_LINE:
            tax += -movement
            tax_items.append((x, -movement))
        elif x.cf_class in ("investing", "financing"):
            cash = -movement                                           # income received (+) / expense paid (-)
            pl_adjust.append(StatementLine(f"adj_pl:{x.name}", f"{'Less' if cash > 0 else 'Add'}: {x.name} (shown under "
                                           f"{x.cf_class} activities)", -cash, drill=(Drill(x.ledger_id, x.name, -cash),), level=1))
            target = inv_pl if x.cf_class == "investing" else fin_pl
            prefix = "inv_pl" if x.cf_class == "investing" else "fin_pl"
            target.append(StatementLine(f"{prefix}:{x.name}", x.name, cash, drill=(Drill(x.ledger_id, x.name, cash),), level=1))

    # ---- balance-sheet movements by class
    non_cash: list[tuple[LedgerBalanceIn, Decimal]] = []
    working: list[tuple[LedgerBalanceIn, Decimal]] = []
    investing: list[tuple[LedgerBalanceIn, Decimal]] = []
    financing: list[tuple[LedgerBalanceIn, Decimal]] = []
    cash_ledgers: list[LedgerBalanceIn] = []
    for x in sorted((y for y in ledgers if not _is_pl(y) and y.group_code != STOCK_GROUP), key=_sort):
        cls = _class(x)
        if cls == "cash_equivalent":
            cash_ledgers.append(x)
            continue
        effect = -(x.closing - x.opening)
        if effect == 0:
            continue
        {"non_cash": non_cash, "investing": investing, "financing": financing}.get(cls, working).append((x, effect))
        if x.group_code == "suspense":
            findings.append(Finding("F-49", f"Suspense account {x.name} moved by {format_inr(abs(effect))}: it is shown under working "
                                            "capital. Clear the suspense account before relying on the cash flow.", "warning",
                                    ledger_id=x.ledger_id))
        elif x.group_code == "reserves_surplus" or x.cf_class == "equity_profit":
            findings.append(Finding("F-49", f"Reserves ledger {x.name} moved by {format_inr(abs(effect))}: it is shown under financing. "
                                            "Check that it is not a transfer of profit.", "warning", ledger_id=x.ledger_id))

    # ---- A. operating
    lines: list[StatementLine] = [_heading("a", "A. Cash flow from operating activities")]
    lines.append(StatementLine("net_profit", "Net profit before tax and extraordinary items", profit,
                               drill=(Drill(None, "Profit and Loss statement", profit),)))
    lines += pl_adjust
    if appropriation != 0:
        lines.append(StatementLine("adj_appropriation", "Less: interest and remuneration credited to partners (appropriation, non-cash)",
                                   appropriation, drill=_drills(appropriation_items), level=1))
    nc_total = _sum(e for _, e in non_cash)
    if nc_total != 0:
        lines.append(StatementLine("non_cash", "Add: depreciation and other non-cash items", nc_total, drill=_drills(non_cash), level=1))
    before_wc = profit + _sum(x.amount for x in pl_adjust) + appropriation + nc_total
    lines.append(StatementLine("operating_before_wc", "Operating profit before working capital changes", before_wc, is_total=True))
    if stock_effect != 0:
        stock_drill = [Drill(x.ledger_id, x.name, x.opening) for x in stock_ledgers if x.opening != 0]
        if ctx.stock is not None and closing_stock != 0:
            stock_drill.append(Drill(None, f"Closing stock approved ({ctx.stock.source})", -closing_stock))
        lines.append(StatementLine(f"wc:{STOCK_GROUP}", f"(Increase) / decrease in {_label(STOCK_GROUP, ctx) if STOCK_GROUP in ctx.labels else 'Inventories'}",
                                   stock_effect, drill=tuple(stock_drill), level=1))
    lines += _group_lines("wc", working, ctx, "(Increase) / decrease in", "Increase / (decrease) in")
    wc_total = stock_effect + _sum(e for _, e in working)
    operating = before_wc + wc_total
    if tax != 0:
        lines.append(StatementLine("cash_generated", "Cash generated from operations", operating, is_total=True))
        lines.append(StatementLine("tax", "Less: income tax expense (provision movement is in working capital)", tax,
                                   drill=_drills(tax_items), level=1))
        operating += tax
    lines.append(StatementLine("cash_from_operations", "Net cash from operating activities (A)", operating, is_total=True))

    # ---- B. investing
    lines.append(_heading("b", "B. Cash flow from investing activities"))
    inv_lines = _group_lines("inv", investing, ctx, "(Purchase) / sale of", "(Purchase) / sale of")
    lines += inv_lines + inv_pl
    investing_total = _sum(x.amount for x in inv_lines + inv_pl)
    lines.append(StatementLine("cash_from_investing", "Net cash from investing activities (B)", investing_total, is_total=True))

    # ---- C. financing
    lines.append(_heading("c", "C. Cash flow from financing activities"))
    fin_lines = _group_lines("fin", financing, ctx, "Increase / (decrease) in", "Increase / (decrease) in")
    lines += fin_lines + fin_pl
    financing_total = _sum(x.amount for x in fin_lines + fin_pl)
    lines.append(StatementLine("cash_from_financing", "Net cash from financing activities (C)", financing_total, is_total=True))

    # ---- net movement, opening and closing cash, F-50
    net = operating + investing_total + financing_total
    opening_cash = _sum(x.opening for x in cash_ledgers)
    bs_cash = _sum(x.closing for x in cash_ledgers)
    closing_cash = opening_cash + net
    difference = closing_cash - bs_cash
    lines.append(StatementLine("net_increase", "Net increase / (decrease) in cash and cash equivalents (A + B + C)", net, is_total=True))
    lines.append(StatementLine("opening_cash", "Cash and cash equivalents at the beginning of the year", opening_cash,
                               drill=_drills([(x, x.opening) for x in cash_ledgers])))
    lines.append(StatementLine("closing_cash", "Cash and cash equivalents at the end of the year", closing_cash, is_total=True,
                               drill=_drills([(x, x.closing) for x in cash_ledgers])))
    if difference != 0:
        side = "more" if difference > 0 else "less"
        findings.append(Finding(
            "F-50", f"The closing cash of the cash flow ({format_inr(closing_cash)}) is {side} than the cash and bank of the balance "
                    f"sheet ({format_inr(bs_cash)}) by {format_inr(abs(difference))}. Check the Trial Balance, the opening balances "
                    "and the ledger classes before using this statement.", "error" if ctx.required else "warning"))

    totals = {"cash_from_operations": operating, "investing": investing_total, "financing": financing_total, "net_increase": net,
              "opening_cash": opening_cash, "closing_cash": closing_cash, "balance_sheet_cash": bs_cash, "difference": difference}
    return Statement("cash_flow", StatementFormat.VERTICAL, "Cash Flow Statement (AS 3, indirect method)", ctx.from_date, ctx.to_date,
                     tuple(lines), (), totals, (), tuple(findings), ENGINE_VERSION)
