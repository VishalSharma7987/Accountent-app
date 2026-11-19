"""Plain data types of the final-accounts engine (Phase 6). Pure Python: no DB, web or AI imports.

Frozen dataclasses only. Packages A..G import these; nobody changes a signature without the main agent (add optional fields at the
end if a package really needs one). Money is Decimal with 2 decimals (rounded half-up through app.engine.money.round_half_up where the
law or the accounting method requires rounding), percentages are Decimal, never float. Ids are opaque values (uuid or str).
Sign convention of ledger balances follows engine/reports.py: debit positive, credit negative.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

ENGINE_VERSION = "fin-1"
ZERO = Decimal("0.00")


# ============================================================================================ adjustments (package A)


class AdjustmentType(str, Enum):
    OUTSTANDING_EXPENSE = "outstanding_expense"            # Dr expense, Cr outstanding expenses (liability)
    PREPAID_EXPENSE = "prepaid_expense"                    # Dr prepaid expenses (asset), Cr expense
    ACCRUED_INCOME = "accrued_income"                      # Dr accrued income (asset), Cr income
    INCOME_IN_ADVANCE = "income_in_advance"                # Dr income, Cr income received in advance (liability)
    PROVISION = "provision"                                # Dr expense, Cr provision (Provisions group)
    BAD_DEBT = "bad_debt"                                  # Dr bad debts, Cr debtor
    PROVISION_DOUBTFUL_DEBTS = "provision_doubtful_debts"  # Dr / Cr expense against the provision ledger (the CHANGE in the provision)
    INTEREST_ON_CAPITAL = "interest_on_capital"            # partnership / LLP: Dr interest on capital, Cr partner
    INTEREST_ON_DRAWINGS = "interest_on_drawings"          # partnership / LLP: Dr partner, Cr interest on drawings (income)
    PARTNER_REMUNERATION = "partner_remuneration"          # partnership / LLP: Dr remuneration, Cr partner


@dataclass(frozen=True)
class AdjustmentInput:
    """What the accountant gives. `amount` is typed for the simple types; for PROVISION_DOUBTFUL_DEBTS / interest / remuneration the
    engine computes it from the other fields and `amount` must be None (a typed amount there is rejected: F-05, F-07, F-08)."""

    adj_type: AdjustmentType
    as_on_date: date
    basis_note: str
    amount: Decimal | None = None
    debit_ledger_id: Any = None        # the two ledgers are chosen by the accountant (F-02), never guessed
    credit_ledger_id: Any = None
    party_ledger_id: Any = None        # bad debt: the debtor; provision for doubtful debts: not used
    rate_percent: Decimal | None = None   # provision for doubtful debts, interest (deed rate)
    partner_id: Any = None
    auto_reverse_on: date | None = None   # first day of the next FY when the accrual should be reversed


@dataclass(frozen=True)
class JournalLineDraft:
    """One line of a draft journal the helper hands to the voucher service (exactly one side > 0, V-02)."""

    ledger_id: Any
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    narration: str | None = None


@dataclass(frozen=True)
class AdjustmentResult:
    adj_type: AdjustmentType
    amount: Decimal
    lines: tuple[JournalLineDraft, ...]
    narration: str
    params: dict[str, Any] = field(default_factory=dict)   # the inputs used (base, rate, days ...), stored with the entry


# ============================================================================================ fixed assets (package B)


class EventKind(str, Enum):
    OPENING = "opening"
    PURCHASE = "purchase"
    ADDITION = "addition"
    DISPOSAL = "disposal"


@dataclass(frozen=True)
class AssetEvent:
    kind: EventKind
    event_date: date
    amount: Decimal                       # cost for opening / purchase / addition; sale proceeds for a disposal
    put_to_use_date: date | None = None
    accumulated_dep_bf: Decimal = ZERO    # opening only (book books)


@dataclass(frozen=True)
class AssetBookSetup:
    asset_id: Any
    asset_no: str
    name: str
    is_depreciable: bool
    method: str | None                    # 'slm' | 'wdv'
    useful_life_years: Decimal | None
    residual_value: Decimal
    it_block_key: str | None
    events: tuple[AssetEvent, ...]


@dataclass(frozen=True)
class BookDepreciationLine:
    asset_id: Any
    method: str
    cost: Decimal
    opening_accumulated: Decimal
    wdv_rate_percent: Decimal | None      # WDV only, 2 decimals
    days_used: int
    days_in_year: int
    depreciation: Decimal
    closing_accumulated: Decimal
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ItBlockInput:
    """One income-tax block for one financial year (a working only; nothing is posted)."""

    block_key: str
    rate_percent: Decimal                 # resolved from dep_it_block_rates by the financial year end date
    rate_verification: str                # copied to the working: 'pending' is shown on the report
    half_rate_days: int                   # from dep_it_rules (180)
    half_rate_percent: Decimal            # from dep_it_rules (50)
    opening_wdv: Decimal
    additions: tuple[tuple[Any, Decimal, date], ...]   # (asset_id, cost, put_to_use_date) of the year
    disposals: tuple[tuple[Any, Decimal], ...]         # (asset_id, sale proceeds)
    fy_end: date = date(2000, 1, 1)


@dataclass(frozen=True)
class ItBlockResult:
    block_key: str
    rate_percent: Decimal
    opening_wdv: Decimal
    additions_full: Decimal
    additions_half: Decimal
    disposals: Decimal
    depreciation: Decimal
    closing_wdv: Decimal
    flags: tuple[str, ...] = ()           # e.g. 'negative_block' (short-term capital gain for the CA), 'terminal_depreciation_review'
    details: dict[str, Any] = field(default_factory=dict)


# ============================================================================================ statements (packages C, D, E)


class EntityType(str, Enum):
    PROPRIETORSHIP = "proprietorship"
    PARTNERSHIP = "partnership"
    LLP = "llp"
    COMPANY = "company"


class StatementFormat(str, Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    SCH3 = "sch3"


@dataclass(frozen=True)
class LedgerBalanceIn:
    """One ledger's position for the statements. `closing` = opening + the FY's entries excluding the year-end closing vouchers."""

    ledger_id: Any
    name: str
    group_code: str
    parent_group_code: str | None
    nature: str                           # asset | liability | income | expense (from the group)
    opening: Decimal                      # signed, debit positive
    debit_total: Decimal                  # sum of the year's debits
    credit_total: Decimal
    closing: Decimal                      # signed
    role: str | None = None               # final_ledger_roles role of this ledger, if any
    line_code: str | None = None          # Schedule III line (override or group default), None = unclassified
    line_is_default: bool = False         # classified by a non-firm group default (warning F-44w)
    cf_class: str | None = None


@dataclass(frozen=True)
class ClosingStockIn:
    cost_value: Decimal
    write_down: Decimal
    carrying_value: Decimal
    source: str                           # inventory_report | manual | none
    as_on_date: date


@dataclass(frozen=True)
class Drill:
    """Drill-down reference of a statement line: which ledgers and what each contributed (opens the ledger statement)."""

    ledger_id: Any
    ledger_name: str
    amount: Decimal                       # positive, shown on the line's own side


@dataclass(frozen=True)
class StatementLine:
    code: str                             # stable code ('opening_stock', 'sales', 'ppe' ...)
    label: str
    amount: Decimal                       # positive; sign is given by the side / section
    previous_amount: Decimal | None = None   # previous-year comparative; None = not available (never guessed)
    note_no: int | None = None
    drill: tuple[Drill, ...] = ()
    level: int = 0                        # indentation (0 = group, 1 = ledger under it)
    is_total: bool = False


@dataclass(frozen=True)
class Finding:
    rule_id: str
    message: str                          # accountant language, Indian number format
    severity: str                         # 'error' blocks finalising / exporting, 'warning' is shown
    ledger_id: Any = None
    line_no: int | None = None


@dataclass(frozen=True)
class Statement:
    key: str                              # trading | profit_loss | balance_sheet | cash_flow
    format: StatementFormat
    title: str
    from_date: date
    to_date: date
    left: tuple[StatementLine, ...] = ()  # horizontal: debit / liabilities side; vertical and Schedule III use `left` only
    right: tuple[StatementLine, ...] = ()
    totals: dict[str, Decimal] = field(default_factory=dict)   # e.g. gross_profit, net_profit, total_assets
    notes: tuple[tuple[int, str, tuple[StatementLine, ...]], ...] = ()   # (note_no, title, lines) Schedule III
    findings: tuple[Finding, ...] = ()
    engine_version: str = ENGINE_VERSION


# ============================================================================================ year-end close (package F)


@dataclass(frozen=True)
class PartnerShare:
    partner_id: Any
    name: str
    profit_ledger_id: Any                 # current ledger if the partner has one, else the capital ledger
    share_percent: Decimal                # 4 decimals; the shares of all partners must add to exactly 100


@dataclass(frozen=True)
class ClosingEntryLine:
    ledger_id: Any
    debit: Decimal = ZERO
    credit: Decimal = ZERO


@dataclass(frozen=True)
class ClosingVoucherDraft:
    step: str                             # trading | profit_loss | appropriation
    voucher_date: date
    narration: str
    reference_no: str
    lines: tuple[ClosingEntryLine, ...]


@dataclass(frozen=True)
class CarryForward:
    """What goes into the next financial year: one opening balance per balance-sheet ledger with a non-zero closing balance."""

    ledger_openings: tuple[tuple[Any, Decimal, Decimal], ...]   # (ledger_id, debit, credit)
    total_debit: Decimal
    total_credit: Decimal                 # equal to total_debit, else the close is refused (F-65)
