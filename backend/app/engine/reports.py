"""Ledger statement and Trial Balance from posted vouchers. Pure Decimal arithmetic, no database.

Balances come only from vouchers with status 'posted' or 'reversed': drafts and approved vouchers never count.
A reversed voucher and its reversal voucher both count, so they cancel out.
Internal sign convention: debit positive, credit negative (CLAUDE.md section 5).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.models import Balance, Group, Ledger, OpeningBalance, PostedLine
from app.engine.validation import group_chain

COUNTED_STATUSES = frozenset({"posted", "reversed"})
CENTS = Decimal("0.01")
ZERO = Decimal("0.00")
AS_PER_DETAILS = "(as per details)"

# Display order of the primary groups (CLAUDE.md section 5); anything else follows, by name.
PRIMARY_ORDER = (
    "capital_account", "loans_liability", "current_liabilities", "fixed_assets", "investments",
    "current_assets", "sales_accounts", "direct_incomes", "indirect_incomes", "purchase_accounts",
    "direct_expenses", "indirect_expenses", "suspense",
)


def _counted(lines: Iterable[PostedLine]) -> list[PostedLine]:
    return [x for x in lines if x.status in COUNTED_STATUSES]


def _signed(line: PostedLine) -> Decimal:
    return line.debit - line.credit


def _opening_signed(opening: OpeningBalance) -> Decimal:
    return opening.debit - opening.credit


# ============================================================================================ ledger statement


@dataclass(frozen=True)
class StatementRow:
    kind: str  # opening | entry | closing
    date: date
    voucher_number: str | None
    voucher_type: str | None
    narration: str | None
    particulars: str  # "To <ledger>", "By <ledger>", "(as per details)", "Opening Balance", "Closing Balance"
    debit: Decimal
    credit: Decimal
    balance: Balance  # running balance after this row


@dataclass(frozen=True)
class LedgerStatement:
    ledger_id: object
    ledger_name: str
    from_date: date
    to_date: date
    rows: tuple[StatementRow, ...]
    opening: Balance  # balance on from_date, before the period's entries
    closing: Balance  # balance after the period's entries
    total_debit: Decimal  # entries of the period only
    total_credit: Decimal


def ledger_statement(
    ledger: Ledger,
    opening: OpeningBalance,
    lines: Sequence[PostedLine],
    from_date: date,
    to_date: date,
) -> LedgerStatement:
    """Statement of one ledger from from_date to to_date (both inclusive).

    opening   the ledger's opening balance for the financial year
    lines     every line of the vouchers that touch this ledger (other ledgers' lines give the counter names).
              Entries dated before from_date are folded into the opening row.
    """
    if to_date < from_date:
        raise ValueError(f"to_date {to_date} is before from_date {from_date}")

    counted = _counted(lines)
    others_by_voucher: dict[object, list[str]] = {}
    for line in counted:
        if line.ledger_id != ledger.id:
            names = others_by_voucher.setdefault(line.voucher_id, [])
            if line.ledger_name not in names:
                names.append(line.ledger_name)

    own = [x for x in counted if x.ledger_id == ledger.id]
    running = _opening_signed(opening) + sum((_signed(x) for x in own if x.voucher_date < from_date), ZERO)
    opening_balance = Balance.from_signed(running)

    rows = [StatementRow(
        "opening", from_date, None, None, None, "Opening Balance",
        opening_balance.amount if opening_balance.side == "Dr" else ZERO,
        opening_balance.amount if opening_balance.side == "Cr" else ZERO,
        opening_balance,
    )]
    in_period = sorted(
        (x for x in own if from_date <= x.voucher_date <= to_date),
        key=lambda x: (x.voucher_date, x.voucher_number or "", x.line_no),
    )
    total_debit = total_credit = ZERO
    for line in in_period:
        running += _signed(line)
        total_debit += line.debit
        total_credit += line.credit
        counters = others_by_voucher.get(line.voucher_id, [])
        if len(counters) == 1:
            particulars = f"{'To' if line.debit > 0 else 'By'} {counters[0]}"
        else:
            particulars = AS_PER_DETAILS
        rows.append(StatementRow(
            "entry", line.voucher_date, line.voucher_number, line.voucher_type, line.narration,
            particulars, line.debit.quantize(CENTS), line.credit.quantize(CENTS), Balance.from_signed(running),
        ))
    closing_balance = Balance.from_signed(running)
    rows.append(StatementRow("closing", to_date, None, None, None, "Closing Balance", ZERO, ZERO, closing_balance))
    return LedgerStatement(
        ledger.id, ledger.name, from_date, to_date, tuple(rows), opening_balance, closing_balance,
        total_debit.quantize(CENTS), total_credit.quantize(CENTS),
    )


# ================================================================================================ opening check


@dataclass(frozen=True)
class OpeningCheck:
    total_debit: Decimal
    total_credit: Decimal
    difference: Balance  # side of the bigger total; nil when balanced
    is_balanced: bool


def check_openings(openings: Iterable[OpeningBalance]) -> OpeningCheck:
    """Total opening debits against total opening credits. Posting stays blocked until they are equal."""
    rows = list(openings)
    total_debit = sum((x.debit for x in rows), ZERO).quantize(CENTS)
    total_credit = sum((x.credit for x in rows), ZERO).quantize(CENTS)
    difference = Balance.from_signed(total_debit - total_credit)
    return OpeningCheck(total_debit, total_credit, difference, difference.side is None)


# ============================================================================================== trial balance


@dataclass(frozen=True)
class TrialBalanceRow:
    group_path: tuple[str, ...]  # from the primary group down to the ledger's own group
    ledger_id: object
    ledger_name: str
    debit: Decimal  # closing balance, on one side only
    credit: Decimal


@dataclass(frozen=True)
class GroupSection:
    group_code: str
    group_name: str  # the primary group
    rows: tuple[TrialBalanceRow, ...]
    debit: Decimal  # subtotal
    credit: Decimal


@dataclass(frozen=True)
class TrialBalance:
    as_on: date
    sections: tuple[GroupSection, ...]
    total_debit: Decimal
    total_credit: Decimal
    difference: Balance  # side of the bigger total; nil when balanced
    is_balanced: bool


def trial_balance(
    ledgers: Sequence[Ledger],
    groups: Mapping[str, Group],
    openings: Mapping[object, OpeningBalance],
    lines: Sequence[PostedLine],
    as_on_date: date,
    *,
    hide_zero: bool = False,
) -> TrialBalance:
    """Closing balance of every ledger as on a date, grouped by primary group, with subtotals and totals.

    If total debit and total credit differ, `difference` says by how much and on which side: it is never hidden.
    hide_zero drops ledgers whose closing balance is nil (for screens); packs list every ledger.
    """
    net: dict[object, Decimal] = {
        x.id: _opening_signed(openings[x.id]) if x.id in openings else ZERO for x in ledgers
    }
    for line in _counted(lines):
        if line.ledger_id not in net:
            raise ValueError(
                f"voucher {line.voucher_number or line.voucher_id} has a line for unknown ledger {line.ledger_id!r}"
            )
        if line.voucher_date <= as_on_date:
            net[line.ledger_id] += _signed(line)

    by_primary: dict[str, list[TrialBalanceRow]] = {}
    primary_names: dict[str, str] = {}
    for ledger in ledgers:
        balance = Balance.from_signed(net[ledger.id])
        if hide_zero and balance.side is None:
            continue
        chain = group_chain(ledger.group_code, groups)
        path = tuple(groups[code].name if code in groups else code for code in reversed(chain))
        primary = chain[-1]
        primary_names[primary] = path[0]
        by_primary.setdefault(primary, []).append(TrialBalanceRow(
            path, ledger.id, ledger.name,
            balance.amount if balance.side == "Dr" else ZERO,
            balance.amount if balance.side == "Cr" else ZERO,
        ))

    def order(code: str) -> tuple[int, str]:
        if code in PRIMARY_ORDER:
            return (PRIMARY_ORDER.index(code), "")
        return (len(PRIMARY_ORDER), primary_names[code])

    sections = []
    for code in sorted(by_primary, key=order):
        rows = sorted(by_primary[code], key=lambda r: (r.group_path, r.ledger_name.lower()))
        sections.append(GroupSection(
            code, primary_names[code], tuple(rows),
            sum((r.debit for r in rows), ZERO), sum((r.credit for r in rows), ZERO),
        ))
    total_debit = sum((s.debit for s in sections), ZERO)
    total_credit = sum((s.credit for s in sections), ZERO)
    difference = Balance.from_signed(total_debit - total_credit)
    return TrialBalance(as_on_date, tuple(sections), total_debit, total_credit, difference, difference.side is None)
