"""Plain data types of the GST engine (Phase 3). Pure Python: no DB, web or AI imports.

Frozen dataclasses only. Packages A..E import these; nobody changes a signature without the main agent
(add optional fields at the end if a package really needs one). Money and rates are Decimal, never float.
Rule rows carry `verification_status` so every output can list pending rules (G-55).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

ENGINE_VERSION = "gst-1"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    SECONDARY_VERIFIED = "secondary_verified"
    PENDING = "pending"


class Treatment(str, Enum):
    TAXABLE = "taxable"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"
    NIL_RATED = "nil_rated"
    NON_GST = "non_gst"


class DocumentKind(str, Enum):
    TAX_INVOICE = "tax_invoice"
    BILL_OF_SUPPLY = "bill_of_supply"
    SELF_INVOICE = "self_invoice"


class SupplyCategory(str, Enum):
    B2B = "b2b"
    B2C = "b2c"
    SEZ_WITH_PAYMENT = "sez_with_payment"
    SEZ_WITHOUT_PAYMENT = "sez_without_payment"
    EXPORT_WITH_PAYMENT = "export_with_payment"
    EXPORT_WITHOUT_PAYMENT = "export_without_payment"
    DEEMED_EXPORT = "deemed_export"
    UNREGISTERED_SUPPLIER = "unregistered_supplier"
    COMPOSITION_SUPPLIER = "composition_supplier"
    IMPORT_OF_SERVICE = "import_of_service"


class GstRole(str, Enum):
    """Role of a voucher line in an invoice-mode voucher (voucher_gst_line_roles.role)."""

    PARTY = "party"
    TAXABLE = "taxable"
    TAX_CGST = "tax_cgst"
    TAX_SGST = "tax_sgst"
    TAX_IGST = "tax_igst"
    TAX_CESS = "tax_cess"
    RCM_CGST = "rcm_cgst"
    RCM_SGST = "rcm_sgst"
    RCM_IGST = "rcm_igst"
    RCM_CESS = "rcm_cess"
    ROUND_OFF = "round_off"


# ---- rule rows (loaded by rules/gst_rules.py) ---------------------------------------------------------------


@dataclass(frozen=True)
class StateCode:
    code: str
    name: str
    kind: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class RateSlab:
    rate: Decimal
    is_special: bool
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class RateRule:
    id: str
    rule_key: str
    code_kind: str  # hsn | sac | default
    code_prefix: str | None
    supply_kind: str  # goods | services
    treatment: str  # taxable | exempt | nil_rated | non_gst
    rate: Decimal
    cess_rate: Decimal
    cess_specific_amount: Decimal
    cess_uqc: str | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str
    is_example: bool = False


@dataclass(frozen=True)
class RcmRule:
    category_key: str
    section_ref: str
    supply_kind: str
    description: str
    supplier_condition: str  # any | unregistered_only | non_resident_only
    hsn_sac_prefix: str | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str
    is_example: bool = False


@dataclass(frozen=True)
class BlockedRule:
    category_key: str
    clause_ref: str
    description: str
    has_exception: bool
    exception_text: str | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class ItcCondition:
    condition_key: str
    clause_ref: str
    description: str
    evidence_field: str | None
    parameter_days: int | None
    deadline_month: int | None
    deadline_day: int | None
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class Threshold:
    threshold_key: str
    unit: str
    numeric_value: Decimal
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class CompositionRule:
    category: str
    rate: Decimal
    turnover_limit: Decimal
    section_ref: str
    turnover_basis: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


# ---- masters -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GstRegistration:
    id: str
    gstin: str
    state_code: str
    registration_type: str  # regular | composition
    return_frequency: str  # monthly | qrmp
    composition_category: str | None
    effective_from: date
    effective_to: date | None
    is_active: bool = True
    trade_name: str | None = None
    ledger_roles: dict[str, str] = field(default_factory=dict)  # role -> ledger_id


@dataclass(frozen=True)
class GstItem:
    id: str
    name: str
    item_kind: str  # goods | service
    hsn_sac: str
    uqc: str | None
    sales_ledger_id: str | None = None
    purchase_ledger_id: str | None = None
    default_itc_category_key: str | None = None
    default_rcm_category_key: str | None = None
    is_active: bool = True


# ---- invoice in / out (engine/gst_tax.py, engine/gst_invoice.py) --------------------------------------------


@dataclass(frozen=True)
class ItemLineIn:
    description: str
    hsn_sac: str
    quantity: Decimal
    unit_rate: Decimal
    discount: Decimal
    ledger_id: str
    item_id: str | None = None
    uqc: str | None = None
    rcm_category_key: str | None = None
    itc_category_key: str | None = None
    itc_exception_claimed: bool = False
    itc_exception_note: str | None = None


@dataclass(frozen=True)
class InvoiceIn:
    gst_registration_id: str
    document_kind: str
    supply_category: str
    place_of_supply: str
    invoice_date: date
    items: tuple[ItemLineIn, ...]
    counterparty_gstin: str | None = None
    original_invoice_no: str | None = None
    original_invoice_date: date | None = None
    note_reason: str | None = None


@dataclass(frozen=True)
class TaxLine:
    """Engine result for one item line (mirrors voucher_item_lines)."""

    item_line_no: int
    gross_amount: Decimal
    discount: Decimal
    taxable_value: Decimal
    treatment: str
    gst_rate: Decimal
    cess_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    rate_rule_id: str | None = None
    rate_is_default: bool = False
    rcm: bool = False
    tax_in_cost: bool = False
    cess_specific_amount: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class GeneratedLine:
    """A voucher line the engine builds (ledger_id of a tax role comes from the registration's ledger roles)."""

    ledger_id: str
    debit: Decimal
    credit: Decimal
    role: str  # GstRole value
    item_line_no: int | None = None


@dataclass(frozen=True)
class InvoiceResult:
    items: tuple[TaxLine, ...]
    lines: tuple[GeneratedLine, ...]
    invoice_value: Decimal
    invoice_round_off: Decimal
    has_rcm: bool
    engine_version: str = ENGINE_VERSION
    warnings: tuple[tuple[str, str, int | None], ...] = ()  # (rule_id, message, item_line_no)
