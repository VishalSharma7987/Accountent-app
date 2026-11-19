"""Schedule III (Companies Act 2013, Division I) Balance Sheet and Statement of Profit and Loss for a company (rules F-44..F-46, F-48).

Pure Python: no DB, web or AI imports. Decimal only. Input = classified ledger positions (`LedgerBalanceIn`, debit positive),
the approved closing stock and the Schedule III line rows (rule data: every row is 'pending' until verified; the service prints
the status). Nothing is guessed: an unclassified ledger is an error finding (F-44), a ledger on a non-firm group default is a
warning (F-44w), a Balance Sheet that does not balance is an error (F-44b), a missing previous year is shown as "-" with a warning (F-45).

Sign conventions: ledger balances are debit positive / credit negative (engine/reports.py). Every statement line amount is the
value on the line's own side (asset lines debit positive, liability / equity / income lines credit positive, expense lines debit
positive). A contra ledger (accumulated depreciation, provision for doubtful debts) nets against its line, so its drill-down
amount is negative.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine.final_types import (
    ENGINE_VERSION,
    ZERO,
    ClosingStockIn,
    Drill,
    Finding,
    LedgerBalanceIn,
    Statement,
    StatementFormat,
    StatementLine,
)
from app.engine.money import format_inr

BS = "sch3_bs"
PL = "sch3_pl"
STOCK_GROUP = "stock_in_hand"
ASSET_SECTIONS = ("non_current_assets", "current_assets")
EQUITY_LIABILITY_SECTIONS = ("equity", "non_current_liabilities", "current_liabilities")
SECTION_LABELS = {
    "equity": "Shareholders' funds",
    "non_current_liabilities": "Non-current liabilities",
    "current_liabilities": "Current liabilities",
    "non_current_assets": "Non-current assets",
    "current_assets": "Current assets",
    "income": "Revenue",
    "expenses": "Expenses",
}
LINE_RESERVES = "reserves_surplus"
LINE_INVENTORIES = "inventories"
LINE_CHANGES = "changes_in_inventories"
LINE_TAX = "tax_expense"
LINE_PPE = "ppe"


@dataclass(frozen=True)
class FsLineRule:
    """One Schedule III line item (row of fs_lines in force on the statement date)."""

    format_key: str            # sch3_bs | sch3_pl
    line_code: str
    label: str
    section: str
    sort_order: int
    note_title: str | None
    cf_class: str
    verification_status: str = "pending"
    source_reference: str = ""


@dataclass(frozen=True)
class GroupDefault:
    group_code: str
    format_key: str
    line_code: str
    is_firm: bool


@dataclass(frozen=True)
class LedgerOverride:
    line_code: str | None
    cf_class: str | None


@dataclass(frozen=True)
class ClassifiedLedger:
    ledger: LedgerBalanceIn
    source: str                # ledger | group_firm | group_default | none


@dataclass(frozen=True)
class PpeRow:
    """Fixed-asset register row of the year (book view) for the Property, plant and equipment note (F-46)."""

    name: str
    opening_cost: Decimal
    additions: Decimal
    disposals: Decimal
    opening_accumulated: Decimal
    depreciation_for_year: Decimal
    disposal_accumulated: Decimal


@dataclass(frozen=True)
class Sch3Input:
    from_date: date
    to_date: date
    ledgers: tuple[LedgerBalanceIn, ...]            # already classified (line_code set or None)
    closing_stock: ClosingStockIn | None
    stock_required: bool
    lines: tuple[FsLineRule, ...]
    previous_bs: dict[str, Decimal] | None = None   # previous-year amounts by line code (snapshot or recomputation); None = not available
    previous_pl: dict[str, Decimal] | None = None
    ppe_register: tuple[PpeRow, ...] | None = None


@dataclass(frozen=True)
class Sch3Result:
    balance_sheet: Statement
    profit_loss: Statement
    unclassified: tuple[Any, ...]
    defaults: tuple[Any, ...]


# ======================================================================================================== classification (F-44)


def format_for_nature(nature: str) -> str:
    return PL if nature in ("income", "expense") else BS


def has_activity(ledger: LedgerBalanceIn) -> bool:
    """A ledger that never moved and has no balance needs no classification."""
    return any(v != ZERO for v in (ledger.opening, ledger.debit_total, ledger.credit_total, ledger.closing))


def classify(
    ledgers: tuple[LedgerBalanceIn, ...],
    overrides: dict[Any, LedgerOverride],
    defaults: tuple[GroupDefault, ...],
    lines: tuple[FsLineRule, ...],
) -> tuple[ClassifiedLedger, ...]:
    """Line of each ledger: the ledger's own override, else the group default (the ledger's group, then its parent group)."""
    default_map = {(d.group_code, d.format_key): d for d in defaults}
    cf_default = {r.line_code: r.cf_class for r in lines}
    out = []
    for ledger in ledgers:
        fmt = format_for_nature(ledger.nature)
        override = overrides.get(ledger.ledger_id)
        line_code: str | None = None
        source = "none"
        is_default = False
        if override is not None and override.line_code is not None:
            line_code, source = override.line_code, "ledger"
        else:
            group = default_map.get((ledger.group_code, fmt)) or (
                default_map.get((ledger.parent_group_code, fmt)) if ledger.parent_group_code else None
            )
            if group is not None:
                line_code = group.line_code
                is_default = not group.is_firm
                source = "group_default" if is_default else "group_firm"
        cf = override.cf_class if override is not None and override.cf_class is not None else cf_default.get(line_code or "")
        out.append(ClassifiedLedger(replace(ledger, line_code=line_code, line_is_default=is_default, cf_class=cf), source))
    return tuple(out)


# ======================================================================================================== statements


def _inr(value: Decimal) -> str:
    return format_inr(value)


def _side_amount(ledger: LedgerBalanceIn, rule: FsLineRule) -> Decimal:
    if rule.format_key == BS:
        return ledger.closing if rule.section in ASSET_SECTIONS else -ledger.closing
    return -ledger.closing if rule.section == "income" else ledger.closing


class _Acc:
    """Amount and drill-down of one statement line while it is being built."""

    def __init__(self) -> None:
        self.amount = ZERO
        self.drill: list[Drill] = []

    def add(self, ledger_id: Any, name: str, amount: Decimal) -> None:
        if amount == ZERO:
            return
        self.amount += amount
        self.drill.append(Drill(ledger_id, name, amount))


def _prev(previous: dict[str, Decimal] | None, code: str) -> Decimal | None:
    return None if previous is None else previous.get(code, ZERO)


def _line(code: str, label: str, amount: Decimal, previous: dict[str, Decimal] | None, *, note_no: int | None = None,
          drill: tuple[Drill, ...] = (), level: int = 1, is_total: bool = False) -> StatementLine:
    return StatementLine(code=code, label=label, amount=amount, previous_amount=_prev(previous, code), note_no=note_no,
                         drill=drill, level=level, is_total=is_total)


def _visible(acc: _Acc, previous: dict[str, Decimal] | None, code: str) -> bool:
    return acc.amount != ZERO or (previous is not None and previous.get(code, ZERO) != ZERO)


def build_sch3(inp: Sch3Input) -> Sch3Result:
    rules = {r.line_code: r for r in inp.lines}
    for needed in (LINE_RESERVES, LINE_INVENTORIES, LINE_CHANGES):
        if needed not in rules:
            raise ValueError(f"Schedule III rule row '{needed}' is missing from the rule table.")
    findings: list[Finding] = []
    stock_ledgers = [lg for lg in inp.ledgers if lg.group_code == STOCK_GROUP]
    others = [lg for lg in inp.ledgers if lg.group_code != STOCK_GROUP]

    # F-40: the books must balance before any statement is trusted
    open_dr = sum((lg.opening for lg in inp.ledgers if lg.opening > 0), ZERO)
    open_cr = -sum((lg.opening for lg in inp.ledgers if lg.opening < 0), ZERO)
    if open_dr != open_cr:
        findings.append(Finding("F-40", f"Opening balances of the year: Debit {_inr(open_dr)} and Credit {_inr(open_cr)} are not equal "
                                        f"(difference {_inr(abs(open_dr - open_cr))}).", "error"))
    close_dr = sum((lg.closing for lg in inp.ledgers if lg.closing > 0), ZERO)
    close_cr = -sum((lg.closing for lg in inp.ledgers if lg.closing < 0), ZERO)
    if close_dr != close_cr:
        findings.append(Finding("F-40", f"Trial Balance: Debit {_inr(close_dr)} and Credit {_inr(close_cr)} are not equal "
                                        f"(difference {_inr(abs(close_dr - close_cr))}).", "error"))

    # F-41: closing stock
    closing = inp.closing_stock
    if closing is None and inp.stock_required:
        findings.append(Finding("F-41", "Closing stock for this year is not approved. Approve the closing stock before the statements "
                                        "can be prepared.", "error"))
    carrying = closing.carrying_value if closing is not None else ZERO
    opening_stock = sum((lg.opening for lg in stock_ledgers), ZERO)

    # F-44: every active ledger needs a line
    unclassified: list[Any] = []
    defaults: list[Any] = []
    accs: dict[str, _Acc] = {}
    for ledger in others:
        if not has_activity(ledger):
            continue
        if ledger.line_code is None:
            unclassified.append(ledger.ledger_id)
            findings.append(Finding("F-44", f"Ledger '{ledger.name}' is not classified to a Schedule III line. Classify it before the "
                                            "statements can be prepared.", "error", ledger.ledger_id))
            continue
        rule = rules.get(ledger.line_code)
        if rule is None:
            unclassified.append(ledger.ledger_id)
            findings.append(Finding("F-44", f"Ledger '{ledger.name}' is classified to '{ledger.line_code}', which is not a Schedule III "
                                            "line in force on the statement date.", "error", ledger.ledger_id))
            continue
        if ledger.line_is_default:
            defaults.append(ledger.ledger_id)
            findings.append(Finding("F-44", f"Ledger '{ledger.name}' is on '{rule.label}' only by the group default. Confirm its "
                                            "classification.", "warning", ledger.ledger_id))
        accs.setdefault(rule.line_code, _Acc()).add(ledger.ledger_id, ledger.name, _side_amount(ledger, rule))

    # specials: stock replaces the stock ledgers (periodic inventory); the P&L carries the change in inventories
    inv = accs.setdefault(LINE_INVENTORIES, _Acc())
    if carrying != ZERO:
        label = f"Closing stock ({closing.source.replace('_', ' ')})" if closing is not None else "Closing stock"
        inv.add(None, label, carrying)
    chg = accs.setdefault(LINE_CHANGES, _Acc())
    if opening_stock != ZERO:
        chg.add(None, "Opening stock", opening_stock)
    if carrying != ZERO:
        chg.add(None, "Closing stock", -carrying)

    pl_lines = sorted((r for r in inp.lines if r.format_key == PL), key=lambda r: r.sort_order)
    income_total = sum((accs[r.line_code].amount for r in pl_lines if r.section == "income" and r.line_code in accs), ZERO)
    expense_total = sum((accs[r.line_code].amount for r in pl_lines
                         if r.section == "expenses" and r.line_code != LINE_TAX and r.line_code in accs), ZERO)
    tax = accs[LINE_TAX].amount if LINE_TAX in accs else ZERO
    profit_before_tax = income_total - expense_total
    profit_for_year = profit_before_tax - tax

    # reserves and surplus carry the year's result
    accs.setdefault(LINE_RESERVES, _Acc()).add(None, "Surplus / (deficit) in the Statement of Profit and Loss for the year", profit_for_year)

    bs_lines = sorted((r for r in inp.lines if r.format_key == BS), key=lambda r: r.sort_order)

    # note numbers: Balance Sheet lines first, then Profit and Loss lines (one numbering for both statements)
    note_no: dict[str, int] = {}
    for rule in [*bs_lines, *pl_lines]:
        acc = accs.get(rule.line_code, _Acc())
        previous = inp.previous_bs if rule.format_key == BS else inp.previous_pl
        if rule.note_title and _visible(acc, previous, rule.line_code):
            note_no[rule.line_code] = len(note_no) + 1

    # ---- Balance Sheet
    bs_left: list[StatementLine] = []
    section_totals: dict[str, Decimal] = {}
    total_el = ZERO
    total_assets = ZERO
    for group_sections, total_code, total_label in (
        (EQUITY_LIABILITY_SECTIONS, "total_equity_liabilities", "TOTAL EQUITY AND LIABILITIES"),
        (ASSET_SECTIONS, "total_assets", "TOTAL ASSETS"),
    ):
        group_total = ZERO
        for section in group_sections:
            rows = []
            section_total = ZERO
            for rule in (r for r in bs_lines if r.section == section):
                acc = accs.get(rule.line_code, _Acc())
                if not _visible(acc, inp.previous_bs, rule.line_code):
                    continue
                section_total += acc.amount
                rows.append(_line(rule.line_code, rule.label, acc.amount, inp.previous_bs, note_no=note_no.get(rule.line_code),
                                  drill=tuple(acc.drill)))
            section_totals[section] = section_total
            group_total += section_total
            if rows:
                bs_left.append(_line(f"section_{section}", SECTION_LABELS[section], section_total, inp.previous_bs, level=0))
                bs_left.extend(rows)
        bs_left.append(_line(total_code, total_label, group_total, inp.previous_bs, level=0, is_total=True))
        if total_code == "total_assets":
            total_assets = group_total
        else:
            total_el = group_total
    difference = total_assets - total_el
    if difference != ZERO:
        findings_bs_extra = [Finding("F-44b", f"Balance Sheet does not balance: Assets {_inr(total_assets)} and Equity and Liabilities "
                                              f"{_inr(total_el)} differ by {_inr(abs(difference))}. Statements cannot be finalised.", "error")]
    else:
        findings_bs_extra = []

    # ---- Profit and Loss
    pl_left: list[StatementLine] = []

    def pl_rows(section: str, skip_tax: bool) -> tuple[list[StatementLine], Decimal]:
        rows, total = [], ZERO
        for rule in (r for r in pl_lines if r.section == section):
            if skip_tax and rule.line_code == LINE_TAX:
                continue
            acc = accs.get(rule.line_code, _Acc())
            if not _visible(acc, inp.previous_pl, rule.line_code):
                continue
            total += acc.amount
            rows.append(_line(rule.line_code, rule.label, acc.amount, inp.previous_pl, note_no=note_no.get(rule.line_code),
                              drill=tuple(acc.drill)))
        return rows, total

    income_rows, income_sum = pl_rows("income", False)
    pl_left.extend(income_rows)
    pl_left.append(_line("total_revenue", "Total revenue", income_sum, inp.previous_pl, level=0, is_total=True))
    expense_rows, expense_sum = pl_rows("expenses", True)
    pl_left.append(_line("section_expenses", "Expenses", expense_sum, inp.previous_pl, level=0))
    pl_left.extend(expense_rows)
    pl_left.append(_line("total_expenses", "Total expenses", expense_sum, inp.previous_pl, level=0, is_total=True))
    pl_left.append(_line("profit_before_tax", "Profit / (loss) before tax", profit_before_tax, inp.previous_pl, level=0, is_total=True))
    if LINE_TAX in accs and _visible(accs[LINE_TAX], inp.previous_pl, LINE_TAX):
        pl_left.append(_line(LINE_TAX, rules[LINE_TAX].label if LINE_TAX in rules else "Tax expense", tax, inp.previous_pl,
                             drill=tuple(accs[LINE_TAX].drill)))
    pl_left.append(_line("profit_for_year", "Profit / (loss) for the year", profit_for_year, inp.previous_pl, level=0, is_total=True))

    # ---- Notes (F-46)
    notes: list[tuple[int, str, tuple[StatementLine, ...]]] = []
    ppe_findings: list[Finding] = []
    for rule in [*bs_lines, *pl_lines]:
        number = note_no.get(rule.line_code)
        if number is None:
            continue
        acc = accs.get(rule.line_code, _Acc())
        if rule.line_code == LINE_PPE and inp.ppe_register:
            lines, register_net = _ppe_note_lines(inp.ppe_register)
            if register_net != acc.amount:
                ppe_findings.append(Finding("F-46", f"Fixed asset register net block {_inr(register_net)} does not agree with the "
                                                    f"ledgers {_inr(acc.amount)} (difference {_inr(abs(register_net - acc.amount))}). "
                                                    "The note shows the register.", "warning"))
            notes.append((number, rule.note_title or rule.label, tuple(lines)))
            continue
        lines = [StatementLine(code=f"note{number}_{i}", label=d.ledger_name, amount=d.amount, note_no=number, drill=(d,), level=1)
                 for i, d in enumerate(acc.drill, start=1)]
        if rule.line_code == LINE_INVENTORIES and closing is not None and closing.write_down != ZERO:
            lines = [StatementLine(code=f"note{number}_cost", label="Closing stock at cost", amount=closing.cost_value, note_no=number,
                                   level=1),
                     StatementLine(code=f"note{number}_writedown", label="Less: write-down to net realisable value (AS 2)",
                                   amount=-closing.write_down, note_no=number, level=1)]
        lines.append(StatementLine(code=f"note{number}_total", label=f"Total ({rule.label})", amount=acc.amount, note_no=number,
                                   level=0, is_total=True))
        notes.append((number, rule.note_title or rule.label, tuple(lines)))

    # ---- F-45 and finding lists
    common = list(findings)
    bs_findings = common + findings_bs_extra + ppe_findings
    pl_findings = list(common)
    for label, previous, target in (("Balance Sheet", inp.previous_bs, bs_findings), ("Statement of Profit and Loss", inp.previous_pl, pl_findings)):
        if previous is None:
            target.append(Finding("F-45", f"Previous-year figures of the {label} are not available (no signed-off statement and no "
                                          "recomputable previous year); the comparative column shows '-'.", "warning"))

    bs = Statement(
        key="balance_sheet", format=StatementFormat.SCH3, title="Balance Sheet", from_date=inp.from_date, to_date=inp.to_date,
        left=tuple(bs_left),
        totals={"total_equity_liabilities": total_el, "total_assets": total_assets, "difference": difference, **{
            f"section_{k}": v for k, v in section_totals.items()}},
        notes=tuple(notes), findings=tuple(bs_findings), engine_version=ENGINE_VERSION)
    pl = Statement(
        key="profit_loss", format=StatementFormat.SCH3, title="Statement of Profit and Loss", from_date=inp.from_date, to_date=inp.to_date,
        left=tuple(pl_left),
        totals={"total_revenue": income_sum, "total_expenses": expense_sum, "profit_before_tax": profit_before_tax,
                "tax_expense": tax, "profit_for_year": profit_for_year},
        notes=tuple(notes), findings=tuple(pl_findings), engine_version=ENGINE_VERSION)
    return Sch3Result(bs, pl, tuple(unclassified), tuple(defaults))


def _ppe_note_lines(rows: tuple[PpeRow, ...]) -> tuple[list[StatementLine], Decimal]:
    opening_cost = sum((r.opening_cost for r in rows), ZERO)
    additions = sum((r.additions for r in rows), ZERO)
    disposals = sum((r.disposals for r in rows), ZERO)
    closing_cost = opening_cost + additions - disposals
    opening_acc = sum((r.opening_accumulated for r in rows), ZERO)
    dep = sum((r.depreciation_for_year for r in rows), ZERO)
    disposal_acc = sum((r.disposal_accumulated for r in rows), ZERO)
    closing_acc = opening_acc + dep - disposal_acc
    net = closing_cost - closing_acc
    spec = [
        ("ppe_gross_opening", "Gross block: opening", opening_cost, 1, False),
        ("ppe_additions", "Additions", additions, 1, False),
        ("ppe_disposals", "Disposals", -disposals, 1, False),
        ("ppe_gross_closing", "Gross block: closing", closing_cost, 0, True),
        ("ppe_acc_opening", "Accumulated depreciation: opening", opening_acc, 1, False),
        ("ppe_acc_year", "Depreciation for the year", dep, 1, False),
        ("ppe_acc_disposals", "On disposals", -disposal_acc, 1, False),
        ("ppe_acc_closing", "Accumulated depreciation: closing", closing_acc, 0, True),
        ("ppe_net_block", "Net block", net, 0, True),
    ]
    return [StatementLine(code=c, label=lab, amount=amt, level=lv, is_total=tot) for c, lab, amt, lv, tot in spec], net


# ======================================================================================================== snapshots and comparatives (F-45)


def statement_payload(statement: Statement) -> dict[str, Any]:
    """The part of a statement kept in `statement_snapshots.payload`: every line code with its amount (text, 2 decimals)."""
    return {
        "key": statement.key,
        "format": statement.format.value,
        "from_date": statement.from_date.isoformat(),
        "to_date": statement.to_date.isoformat(),
        "engine_version": statement.engine_version,
        "left": [{"code": ln.code, "label": ln.label, "amount": f"{ln.amount:.2f}"} for ln in statement.left],
    }


def amounts_from_payload(payload: dict[str, Any]) -> dict[str, Decimal]:
    return {row["code"]: Decimal(row["amount"]) for row in payload.get("left", [])}


def amounts_of(statement: Statement) -> dict[str, Decimal]:
    return {ln.code: ln.amount for ln in statement.left}


# ======================================================================================================== fixed-asset register for the PPE note (F-46)


@dataclass(frozen=True)
class RegisterEvent:
    asset_id: Any
    kind: str                  # opening | purchase | addition | disposal
    event_date: date
    amount: Decimal            # cost for opening / purchase / addition; sale proceeds for a disposal (not used here)
    accumulated_dep_bf: Decimal = ZERO


@dataclass(frozen=True)
class RegisterDepLine:
    asset_id: Any
    fy_end: date               # end date of the financial year of the (posted) depreciation run
    depreciation: Decimal


def build_ppe_rows(assets: tuple[tuple[Any, str], ...], events: tuple[RegisterEvent, ...], dep_lines: tuple[RegisterDepLine, ...],
                   fy_start: date, fy_end: date) -> tuple[PpeRow, ...]:
    """Book view of the register for the year: opening cost / additions / disposals and accumulated depreciation, per asset.
    An asset disposed before the year starts is left out; one disposed in the year leaves with its whole cost and accumulated
    depreciation (a disposal removes the whole asset, F-21)."""
    rows = []
    for asset_id, name in assets:
        mine = [e for e in events if e.asset_id == asset_id]
        disposal = next((e for e in mine if e.kind == "disposal"), None)
        if disposal is not None and disposal.event_date < fy_start:
            continue
        opening_cost = additions = opening_acc = ZERO
        for e in mine:
            if e.kind == "opening":
                opening_cost += e.amount
                opening_acc += e.accumulated_dep_bf
            elif e.kind in ("purchase", "addition"):
                if e.event_date < fy_start:
                    opening_cost += e.amount
                elif e.event_date <= fy_end:
                    additions += e.amount
        opening_acc += sum((d.depreciation for d in dep_lines if d.asset_id == asset_id and d.fy_end < fy_start), ZERO)
        dep_year = sum((d.depreciation for d in dep_lines if d.asset_id == asset_id and fy_start <= d.fy_end <= fy_end), ZERO)
        disposed_in_year = disposal is not None and disposal.event_date <= fy_end
        rows.append(PpeRow(
            name=name, opening_cost=opening_cost, additions=additions,
            disposals=opening_cost + additions if disposed_in_year else ZERO,
            opening_accumulated=opening_acc, depreciation_for_year=dep_year,
            disposal_accumulated=opening_acc + dep_year if disposed_in_year else ZERO))
    return tuple(rows)
