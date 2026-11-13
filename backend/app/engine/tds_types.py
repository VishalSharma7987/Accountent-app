"""Plain data types of the TDS / TCS engine (Phase 4). Pure Python: no DB, web or AI imports.

Frozen dataclasses only. Packages A..F import these; nobody changes a signature without the main agent
(add optional fields at the end if a package really needs one). Money and rates are Decimal, never float.
Rule rows carry `verification_status` so every output can list pending rules (T-50).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

ENGINE_VERSION = "tds-1"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    SECONDARY_VERIFIED = "secondary_verified"
    PENDING = "pending"


class Act(str, Enum):
    IT_1961 = "it_act_1961"
    IT_2025 = "it_act_2025"


class DeducteeType(str, Enum):
    INDIVIDUAL = "individual"
    HUF = "huf"
    COMPANY = "company"
    FIRM = "firm"
    LLP = "llp"
    AOP_BOI = "aop_boi"
    CO_OPERATIVE_SOCIETY = "co_operative_society"
    LOCAL_AUTHORITY = "local_authority"
    TRUST = "trust"
    OTHER = "other"


class PanStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    APPLIED_FOR = "applied_for"


class RateReason(str, Enum):
    NORMAL = "normal"
    NO_PAN = "no_pan"
    LOWER_CERTIFICATE = "lower_certificate"
    NIL_CERTIFICATE = "nil_certificate"
    BELOW_THRESHOLD = "below_threshold"
    MANUAL_SALARY = "manual_salary"


# ---- rule rows (loaded by rules/tds_rules.py) ---------------------------------------------------------------


@dataclass(frozen=True)
class Nature:
    nature_key: str
    kind: str  # tds | tcs
    description: str
    rate_mode: str  # flat | slab_manual
    verification_status: str


@dataclass(frozen=True)
class SectionRef:
    nature_key: str
    act: str
    section_ref: str
    table_ref: str | None
    payment_code: str | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class RateRule:
    id: str
    nature_key: str
    act: str
    deductee_group: str  # any | individual_huf | others
    rate: Decimal
    no_pan_rate: Decimal
    single_payment_threshold: Decimal | None
    monthly_threshold: Decimal | None
    annual_threshold: Decimal | None
    threshold_mode: str  # whole_amount | excess_only
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class Provision:
    provision_key: str
    act: str
    section_ref: str
    description: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class DueDateRule:
    due_key: str
    event: str  # challan | return | certificate
    kind: str  # tds | tcs
    quarter: int | None
    month_of_year: int | None
    due_day: int | None
    month_offset: int | None
    days_after_return: int | None
    effective_from: date
    effective_to: date | None
    verification_status: str


@dataclass(frozen=True)
class InterestRule:
    interest_key: str  # late_deduction | late_deposit
    monthly_rate: Decimal
    part_month_counts_full: bool
    section_ref: str
    effective_from: date
    effective_to: date | None
    verification_status: str


@dataclass(frozen=True)
class FormRule:
    form_key: str
    act: str
    form_no: str
    description: str
    rule_ref: str | None
    effective_from: date
    effective_to: date | None
    verification_status: str


# ---- masters -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Deductee:
    ledger_id: str
    pan: str | None
    pan_status: str
    deductee_type: str
    default_nature_key: str | None = None


@dataclass(frozen=True)
class LowerDeductionCert:
    id: str
    deductee_ledger_id: str
    certificate_no: str
    nature_key: str | None
    rate: Decimal
    max_amount: Decimal
    valid_from: date
    valid_to: date
    amount_used: Decimal = Decimal(0)  # payment amounts already covered by this certificate (posted items)


# ---- engine input / output ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class TdsLineIn:
    """One payment / credit the accountant marks as subject to tax (the amount is typed, never read from a bill by AI)."""

    deductee_ledger_id: str
    nature_key: str
    amount: Decimal  # the base the nature applies to (GST shown separately is excluded by the accountant)
    credit_date: date | None
    payment_date: date | None
    lower_cert_id: str | None = None  # the accountant picks the certificate; the engine checks validity and limit
    manual_tax: Decimal | None = None  # salary (slab_manual) only


@dataclass(frozen=True)
class PriorPosition:
    """What the books already hold for one deductee + nature + financial year (posted, not reversed vouchers)."""

    cumulative_amount: Decimal = Decimal(0)
    tax_deducted: Decimal = Decimal(0)
    monthly_amounts: dict[str, Decimal] = field(default_factory=dict)  # 'YYYY-MM' -> amount (rent)


@dataclass(frozen=True)
class TdsItemResult:
    item_no: int
    deductee_ledger_id: str
    nature_key: str
    act: str
    section_ref: str
    table_ref: str | None
    rate_rule_id: str | None
    event_date: date
    payment_amount: Decimal
    cumulative_before: Decimal
    cumulative_after: Decimal
    threshold_crossed: bool
    taxable_base: Decimal
    rate_applied: Decimal
    rate_reason: str
    lower_cert_id: str | None
    tax_already_on_base: Decimal
    tds_amount: Decimal
    verification_status: str
    warnings: tuple[str, ...] = ()
