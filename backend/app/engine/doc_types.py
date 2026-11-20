"""Plain data types and the rule catalogue of the document / AI intake (Phase 7). Pure Python: no DB, web, LLM or OCR imports.

Frozen dataclasses only. Packages A..G import these; nobody changes a signature without the main agent (add optional fields at the
end if a package really needs one). Amounts that come from outside (an LLM answer, an OCR text, a Tally file) are carried as TEXT
(`str`) exactly as printed and are turned into Decimal only by the engine, which rejects more than 2 decimals instead of rounding
(CLAUDE.md 2.4). Nothing in this module computes an amount.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

DOC_ENGINE_VERSION = "doc-1"
SCHEMA_VERSION = "invoice-extract-1"
ZERO = Decimal("0.00")

# Printed-versus-recomputed differences up to this size are a WARNING (rounding on a printed invoice), larger ones are an ERROR (D-10, D-13).
# This is an accounting judgement, not law: it is a parameter of the check (default here), recorded in docs/decisions_parts/P7.md,
# and the owner may change it.
ROUND_TOLERANCE = Decimal("1.00")


class DocType(str, Enum):
    PURCHASE_INVOICE = "purchase_invoice"
    SALES_INVOICE = "sales_invoice"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    EXPENSE_BILL = "expense_bill"
    BANK_STATEMENT = "bank_statement"
    TALLY_XML = "tally_xml"
    TALLY_EXPORT = "tally_export"
    OTHER = "other"


# the voucher type an invoice-like document type is drafted as (the document types that can be drafted at all)
DRAFTABLE_VOUCHER_TYPE = {
    DocType.PURCHASE_INVOICE: "purchase",
    DocType.SALES_INVOICE: "sales",
    DocType.CREDIT_NOTE: "credit_note",
    DocType.DEBIT_NOTE: "debit_note",
}


class Severity(str, Enum):
    """error   = the data is wrong or inconsistent: the accountant must correct it (cannot be acknowledged)
    review  = the system will not guess (unknown party, ledger, place of supply): the accountant must decide / map
    warning = looks unusual or low confidence: accept only after acknowledging it
    info    = shown, no action"""

    ERROR = "error"
    REVIEW = "review"
    WARNING = "warning"
    INFO = "info"


BLOCKING = (Severity.ERROR, Severity.REVIEW)


class QueueStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class QueueKind(str, Enum):
    INVOICE = "invoice"
    TALLY_VOUCHER = "tally_voucher"


# allowed moves (mirrors approval_queue_items_guard in migration 0018); accepted and rejected are terminal
QUEUE_TRANSITIONS = {
    QueueStatus.PENDING: (QueueStatus.IN_REVIEW, QueueStatus.ACCEPTED, QueueStatus.REJECTED),
    QueueStatus.IN_REVIEW: (QueueStatus.PENDING, QueueStatus.ACCEPTED, QueueStatus.REJECTED),
    QueueStatus.ACCEPTED: (),
    QueueStatus.REJECTED: (),
}


def can_move(old: QueueStatus, new: QueueStatus) -> bool:
    return new == old or new in QUEUE_TRANSITIONS[old]


class LlmPurpose(str, Enum):
    INVOICE_EXTRACTION = "invoice_extraction"
    NARRATION_SUGGESTION = "narration_suggestion"


# ============================================================================================ findings


@dataclass(frozen=True)
class DocFinding:
    """One thing the engine or a service found. `field_path` points into the extraction payload ("lines[1].taxable_value",
    "totals.grand_total") so the screen can highlight it next to the document image. `printed` / `computed` are text: what the document
    says and what the engine worked out (both shown to the accountant in Indian format by the caller)."""

    rule_id: str
    severity: Severity
    message: str
    field_path: str | None = None
    printed: str | None = None
    computed: str | None = None

    def as_dict(self) -> dict:
        return {"rule_id": self.rule_id, "severity": self.severity.value, "message": self.message, "field_path": self.field_path,
                "printed": self.printed, "computed": self.computed}


def count_findings(findings) -> tuple[int, int]:
    """(blocking, warnings) as stored in approval_queue_items.blocking_count / warning_count."""
    blocking = sum(1 for f in findings if f.severity in BLOCKING)
    warnings = sum(1 for f in findings if f.severity == Severity.WARNING)
    return blocking, warnings


# ============================================================================================ extraction (what the engine reads)


@dataclass(frozen=True)
class Source:
    """Where on the document a value was read: page (1-based) and an optional box [x0, y0, x1, y1] in page fractions 0..1."""

    page: int
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None = None


@dataclass(frozen=True)
class Field:
    """A value exactly as printed (text), where it came from, and how sure the reader was (0..1). `value` None = not found."""

    value: str | None
    source: Source | None = None
    confidence: Decimal | None = None


@dataclass(frozen=True)
class ExtractedLine:
    description: Field
    hsn_sac: Field
    quantity: Field
    unit: Field
    unit_rate: Field
    discount: Field
    taxable_value: Field      # as printed
    gst_rate: Field           # as printed, percent
    cgst: Field               # tax amounts AS PRINTED
    sgst: Field
    igst: Field
    cess: Field


@dataclass(frozen=True)
class ExtractedTotals:
    taxable_total: Field
    cgst_total: Field
    sgst_total: Field
    igst_total: Field
    cess_total: Field
    round_off: Field
    grand_total: Field


@dataclass(frozen=True)
class ExtractedInvoice:
    """The engine's view of a validated extraction (the Pydantic schema in app/ai/schemas.py converts to this)."""

    document_kind: Field          # purchase_invoice | sales_invoice | credit_note | debit_note, as the document calls itself
    supplier_name: Field
    supplier_gstin: Field
    buyer_name: Field
    buyer_gstin: Field
    invoice_no: Field
    invoice_date: Field           # text as printed; the engine parses (dd-mm-yyyy, dd/mm/yyyy, yyyy-mm-dd)
    place_of_supply: Field
    original_invoice_no: Field    # credit / debit notes
    lines: tuple[ExtractedLine, ...]
    totals: ExtractedTotals
    currency: str = "INR"
    notes: tuple[str, ...] = field(default_factory=tuple)


# ============================================================================================ rule catalogue
# IDs are used in finding messages, queue findings, test names and docs/PHASE7_PLAN.md. One namespace, ranges by area.

RULES: dict[str, str] = {
    # D-01..D-09 documents and extraction shape
    "D-01": "File type is checked by content, not by name: PDF, PNG, JPEG, TIFF (documents) or XML (Tally); size within the limit",
    "D-02": "The same file (SHA-256) is never stored twice for a client; the existing document is shown instead",
    "D-03": "Possible duplicate invoice: same supplier GSTIN (or name) + invoice no (+ date / total) already in a voucher or another extraction",
    "D-04": "The model's answer is not valid JSON or does not fit the schema: extraction is invalid, nothing is drafted, never repaired silently",
    "D-05": "Every extracted field carries a page / position source and a confidence; a required field that is missing is an error; confidence below the configured minimum is a warning",
    "D-06": "Amounts must be plain decimals with at most 2 places and not negative; dates must parse; otherwise error (rejected, not rounded)",
    "D-07": "Supplier / buyer GSTIN must be valid (format, state code, check character)",
    "D-08": "For a purchase the buyer GSTIN must be one of the client's registrations; for a sale the supplier GSTIN must be; else error",
    "D-09": "Direction cannot be decided (client GSTIN on neither side, or on both) or differs from the type chosen at upload: review",
    # D-10..D-19 engine recomputation
    "D-10": "Line taxable value recomputed (quantity x rate - discount) differs from the printed taxable value",
    "D-11": "Tax recomputed by the GST engine from the rate table (HSN, date) differs from the printed tax amount, or the printed rate differs from the table",
    "D-12": "Tax type does not fit the place of supply (CGST+SGST on an inter-state supply, IGST on an intra-state one)",
    "D-13": "Printed totals (taxable, each tax, grand total with round-off) differ from the sum recomputed from the lines",
    "D-14": "Invoice date outside the client's financial years, in a locked period, or in the future (the voucher service's V-06 / V-07 remain the authority)",
    "D-15": "Printed rate is not a rate of the rate table on that date (rate table gap is reported as pending, never filled in)",
    "D-16": "Line has no HSN / SAC, or an HSN not in the item master where the rate rule needs it: review",
    "D-17": "Printed line sum and printed lines count disagree with the lines extracted (a line was probably missed)",
    # D-20..D-29 mapping and drafting
    "D-20": "Supplier / buyer not mapped to a party ledger: review (never auto-created)",
    "D-21": "A line has no saved ledger mapping: review",
    "D-22": "Party GSTIN on the document differs from the GSTIN saved on the mapped party ledger: error",
    "D-23": "Place of supply cannot be determined from the document (and the party master has no state): review",
    "D-24": "Mapping is ambiguous (one key points to several ledgers): review, no choice is made",
    "D-25": "Draft was built through the voucher service; its own rules (V-01..V-15, B-xx, G-xx, T-xx, S-xx) are returned as findings unchanged",
    "D-26": "A mapping is saved only from the accountant's accepted values (never from the model's output)",
    "D-27": "Draft already exists for this queue item: it is rebuilt in place while the item is open, never duplicated",
    # D-30..D-39 Tally import / export
    "D-30": "Tally XML must be well-formed and contain no DTD / entities; encoding (UTF-8 / UTF-16) and illegal character references handled; else the import fails with the reason",
    "D-31": "Tally group maps to a system or client group: predefined Tally groups by table, custom groups by their parent chain; unknown -> suggested, accountant confirms",
    "D-32": "Tally ledger whose name already exists in another group (or under another mapping) is not overwritten: review",
    "D-33": "Opening balances in the Tally file are REPORTED in the mapping report and never applied by the import",
    "D-34": "Voucher types: Sales, Purchase, Payment, Receipt, Contra, Journal, Credit Note, Debit Note are drafted; every other type is skipped and listed with the reason",
    "D-35": "Tally debit / credit sign (ISDEEMEDPOSITIVE) is converted to debit / credit lines; the voucher service then enforces Dr = Cr (V-04) and every other voucher rule",
    "D-36": "Cancelled, optional and post-dated vouchers are skipped and listed",
    "D-37": "A Tally voucher already queued (same GUID or same type + date + number + party + total) is skipped, not queued twice",
    "D-38": "Tally export contains posted vouchers only; ledgers / groups used are exported first; names are escaped; the file records client, FY, range and engine version",
    "D-39": "Export refuses a range with unposted vouchers unless the caller says it wants posted-only; ledger names longer than Tally allows or with illegal characters are reported",
    # D-40..D-49 narration suggestion
    "D-40": "Narration key: lower-case, digits / UPI / reference numbers / dates removed, whitespace collapsed (pure function)",
    "D-41": "Rule suggestion: a key learned from the accountant's accepted choices (same direction) points to exactly one ledger: suggest it with the count as the reason",
    "D-42": "Key points to several ledgers: ambiguous, list the candidates with counts, no suggestion is selected",
    "D-43": "LLM fallback only when no rule exists and the client's LLM switch is on; the answer is a suggestion with the reason; a ledger the client does not have is dropped",
    "D-44": "A suggestion never creates a voucher or a ledger; accepting it only tells the accountant which ledger to use and teaches the rule",
    # D-50..D-59 security
    "D-50": "Before any model call the text is masked (PAN, Aadhaar, bank account numbers, GSTIN as reversible placeholders); a final scan refuses to send if anything of those kinds is left",
    "D-51": "No model call unless client_ai_settings.llm_enabled for that client (explicit, with who / why / data class); otherwise the call is refused and recorded as blocked",
    "D-52": "Prompt (masked) and raw answer are stored for audit; API keys and secrets never appear in logs, errors, prompts or stored text",
    "D-53": "Document text is data, never instructions: the model has no tools, its answer is accepted only as JSON of the schema (extra keys rejected)",
    "D-54": "Only synthetic or anonymised data goes to a free model; the data class is recorded per client and shown on every model call",
    # D-60..D-69 approval queue
    "D-60": "A queue item is accepted only by a person, with a draft voucher, with no error / review finding left; warnings only after acknowledgement",
    "D-61": "Every field of the extraction is editable in the queue; each edit re-runs the engine checks; the AI's original answer stays unchanged",
    "D-62": "Accepting never posts: the draft is approved and posted afterwards through the normal voucher actions; the database refuses to approve or post a queued draft before acceptance",
    "D-63": "Rejecting needs a reason and removes the draft through the voucher service; the item and extraction remain as record",
    "D-64": "Every queue action (create, claim, edit, accept, reject, rebuild) is written to audit_log with old and new values",
}


def rule_text(rule_id: str) -> str:
    return RULES[rule_id]
