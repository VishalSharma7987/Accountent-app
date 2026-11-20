"""Plain data types and the check catalogue of the audit assistant (Phase 8). Pure Python: no DB, web, LLM imports.

The audit is READ-ONLY on the books: a check is a pure function over plain facts (below) that returns findings. Loaders (services) read the
books and build the facts; the engine never reads a database and never changes anything. Frozen dataclasses only; packages A..G import them,
nobody changes a signature without the main agent (add optional fields at the end if a package really needs one). Amounts are Decimal; the
only rounding in this module is none (the checks compare and add exactly). Legal limits are NEVER constants here: they arrive as `LimitRule`
rows from the rule table `audit_rule_limits` and are picked by date (`pick_limit`).
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

AUDIT_ENGINE_VERSION = "audit-1"
ZERO = Decimal("0.00")


class Severity(str, Enum):
    ERROR = "error"      # a legal / accounting breach the books show: must be answered
    REVIEW = "review"    # needs the auditor's judgement
    WARNING = "warning"  # probable problem
    INFO = "info"        # listed for the file, no action implied


class Category(str, Enum):
    BOOKS = "books"
    COMPLIANCE = "compliance"
    ANALYTICAL = "analytical"


class PaperStatus(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    SIGNED_OFF = "signed_off"


class ItemStatus(str, Enum):
    OPEN = "open"
    CLEARED = "cleared"      # reviewer decided: not an issue (reason mandatory)
    CONFIRMED = "confirmed"  # reviewer decided: a real exception (reason mandatory)


class SampleMethod(str, Enum):
    NONE = "none"
    RANDOM = "random"
    SYSTEMATIC = "systematic"
    VALUE = "value"


# allowed moves of a working paper (mirrors audit_working_papers_guard in migration 0019); signed_off is terminal
PAPER_TRANSITIONS = {
    PaperStatus.OPEN: (PaperStatus.IN_REVIEW,),
    PaperStatus.IN_REVIEW: (PaperStatus.OPEN, PaperStatus.SIGNED_OFF),
    PaperStatus.SIGNED_OFF: (),
}


def can_move_paper(old: PaperStatus, new: PaperStatus) -> bool:
    return new in PAPER_TRANSITIONS[old]


@dataclass(frozen=True)
class CheckInfo:
    check_id: str
    title: str
    severity: Severity
    category: Category
    rule_key: str | None = None   # audit_rule_limits.rule_key the check reads
    reuses: str | None = None     # earlier-phase engine the check must reuse instead of re-implementing


# The catalogue. The same IDs, titles, severities and rule keys are seeded in database/seeds/0014_audit_checks_limits.sql and a unit test
# keeps the two in step. The description / rule text / evidence query live in the seed (data), the plan explains each with an example.
CHECKS: dict[str, CheckInfo] = {c.check_id: c for c in (
    CheckInfo("A-01", "Duplicate bills", Severity.WARNING, Category.BOOKS, reuses="engine/duplicates (reference key)"),
    CheckInfo("A-02", "Duplicate payments", Severity.WARNING, Category.BOOKS),
    CheckInfo("A-03", "Missing supporting document", Severity.WARNING, Category.BOOKS, reuses="Phase 7 document_vouchers"),
    CheckInfo("A-04", "Voucher number gap", Severity.ERROR, Category.BOOKS),
    CheckInfo("A-05", "Cash payment above the daily limit", Severity.ERROR, Category.BOOKS, rule_key="cash_payment_daily_limit"),
    CheckInfo("A-06", "Cash receipt above the legal limit", Severity.ERROR, Category.BOOKS, rule_key="cash_receipt_limit"),
    CheckInfo("A-07", "MSME dues past the legal days", Severity.ERROR, Category.COMPLIANCE, reuses="engine/msme.flag_msme_overdue"),
    CheckInfo("A-08", "GST books versus returns", Severity.ERROR, Category.COMPLIANCE, reuses="engine/gst_tieout.build_tieout"),
    CheckInfo("A-09", "TDS not deducted", Severity.ERROR, Category.COMPLIANCE, reuses="engine/tds_calc"),
    CheckInfo("A-10", "TDS short deducted", Severity.ERROR, Category.COMPLIANCE, reuses="engine/tds_calc"),
    CheckInfo("A-11", "TDS late deposited", Severity.ERROR, Category.COMPLIANCE, reuses="engine/tds_challan"),
    CheckInfo("A-12", "Round-amount entries", Severity.INFO, Category.BOOKS),
    CheckInfo("A-13", "Entries on Sundays and holidays", Severity.INFO, Category.BOOKS),
    CheckInfo("A-14", "Entries after the period was locked", Severity.WARNING, Category.BOOKS),
    CheckInfo("A-15", "Unusual ledger movement", Severity.REVIEW, Category.ANALYTICAL),
    CheckInfo("A-16", "Negative cash history", Severity.ERROR, Category.COMPLIANCE, reuses="engine/cash_rules (C-01)"),
    CheckInfo("A-17", "Negative stock history", Severity.ERROR, Category.COMPLIANCE, reuses="Phase 5 inventory valuation"),
    CheckInfo("A-18", "Related-party transactions", Severity.INFO, Category.BOOKS),
)}

# ---- facts: what a loader hands to a pure check -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerFact:
    id: Any
    name: str
    group_code: str            # account_groups.code of the ledger's group (cash_in_hand, bank_accounts, sundry_creditors ...)
    is_transporter: bool = False   # accountant-marked: the transport cash limit applies (never guessed from the name)


@dataclass(frozen=True)
class LineFact:
    ledger_id: Any
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class VoucherFact:
    """One non-draft voucher with its lines. `status` is posted or reversed; reversal vouchers carry reverses_voucher_id."""

    id: Any
    voucher_type: str
    voucher_number: str | None
    voucher_date: date
    status: str
    narration: str
    reference_no: str | None
    party_ledger_id: Any | None
    lines: tuple[LineFact, ...]
    posted_at: Any | None = None       # datetime of posting (A-14)
    reverses_voucher_id: Any | None = None
    reversed_by_voucher_id: Any | None = None

    @property
    def total(self) -> Decimal:
        return sum((ln.debit for ln in self.lines), ZERO)


@dataclass(frozen=True)
class LimitRule:
    """One row of audit_rule_limits."""

    rule_key: str
    law: str
    section_ref: str
    amount: Decimal
    breach_when: str                  # 'above' | 'at_or_above'
    disallow_percent: Decimal | None
    effective_from: date
    effective_to: date | None
    verification_status: str          # verified | secondary_verified | pending


@dataclass(frozen=True)
class Finding:
    """One exception. `evidence` is mandatory and non-empty (database CHECK): voucher ids, ledger id, document ids, the figures used.
    Amounts in `evidence` are strings (jsonb)."""

    check_id: str
    finding_key: str
    severity: Severity
    subject_kind: str                 # voucher | ledger | party | document | return | period | stock_item | bill
    subject_ref: str
    message: str                      # plain accountant language, Indian number format, dd-mm-yyyy dates
    evidence: dict[str, Any]
    subject_id: Any | None = None
    finding_date: date | None = None
    amount: Decimal | None = None
    disallowance_amount: Decimal | None = None
    rule_status: str | None = None    # verification_status of the legal rule used, so a report can say "limit pending verification"


@dataclass(frozen=True)
class AuditParams:
    """Parameters of a run (stored on audit_runs.params). Not law: accounting / audit judgement, recorded with the run."""

    from_date: date
    to_date: date
    duplicate_window_days: int = 7             # A-02
    doc_required_types: tuple[str, ...] = ("purchase", "payment", "debit_note")   # A-03
    doc_min_amount: Decimal = ZERO             # A-03
    round_unit: Decimal = Decimal("1000.00")   # A-12
    round_min_amount: Decimal = Decimal("10000.00")
    late_posting_days: int = 30                # A-14
    variance_min_amount: Decimal = Decimal("100000.00")   # A-15
    variance_band_percent: Decimal = Decimal("50.00")
    sample_seed: int | None = None


# ---- pure helpers shared by the packages -----------------------------------------------------------------------------------------------


def pick_limit(rules: Sequence[LimitRule], rule_key: str, on: date) -> LimitRule | None:
    """The rule of `rule_key` in force on `on` (latest effective_from wins); None when no row covers the date (reported, never guessed)."""
    live = [r for r in rules if r.rule_key == rule_key and r.effective_from <= on and (r.effective_to is None or on <= r.effective_to)]
    return max(live, key=lambda r: r.effective_from) if live else None


def breaches(rule: LimitRule, amount: Decimal) -> bool:
    return amount > rule.amount if rule.breach_when == "above" else amount >= rule.amount


def finding_key(check_id: str, *parts: object) -> str:
    """Deterministic key of a finding inside a run: check id + its subject parts, e.g. ('A-05', party_id, '2026-08-14')."""
    return ":".join([check_id, *[str(p) for p in parts]])


def population_digest(ids: Iterable[object]) -> str:
    """SHA-256 of the sorted string ids: proves which population a sample was drawn from (order-independent)."""
    joined = "\n".join(sorted(str(i) for i in ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def is_sunday(d: date) -> bool:
    return d.weekday() == 6


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    population: tuple[Any, ...] = field(default_factory=tuple)   # ids of the items the check examined (for the working paper)
    population_amount: Decimal | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)        # e.g. "no cash limit row for 14-08-2026: check skipped (pending rule)"
    population_amounts: Mapping[Any, Decimal] | None = None      # id -> amount, only where each examined item has one (value sampling)
