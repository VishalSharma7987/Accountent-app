"""Pydantic v2 schemas of what the language model (or the accountant, typing by hand) returns for an invoice and for a bank statement.

The model returns only what is PRINTED: every value is text with the page / box it was read from and a confidence. Nothing here
computes an amount. `extra="forbid"` everywhere (D-53: only the schema's keys are accepted), wrong types are rejected (D-04): a JSON
number where text is expected, a bare string where a field object is expected. Nothing is repaired except one surrounding Markdown code
fence (docs/decisions_parts/P7.md). A value that is *missing* is not a schema error: it is a null field, which the engine reports as
D-05, so the accountant sees which field to type. More than 2 decimals in an amount is not a schema error either: the text is kept as
printed and the engine reports D-06.

Conversion to the engine's plain types (`doc_types.ExtractedInvoice`, `doc_bank.BankStatement`) is here; the checks are in the engine.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic import Field as PField

from app.engine import doc_bank
from app.engine.doc_types import ExtractedInvoice, ExtractedLine, ExtractedTotals, Field, Source

_ONE = Decimal(1)
_ZERO = Decimal(0)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldValue(_Strict):
    """One printed value: text as printed (or null = not found), where it was read and how sure the reader was."""

    value: StrictStr | None = None
    page: StrictInt | None = PField(default=None, ge=1)
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None = None   # x0, y0, x1, y1 as fractions of the page, 0..1
    confidence: Decimal | None = None                               # 0..1 ("0.97"; a JSON number is accepted too)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v):
        if v is not None and not (_ZERO <= v <= _ONE):
            raise ValueError("confidence must be between 0 and 1")
        return v

    @model_validator(mode="after")
    def _box(self):
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if not all(_ZERO <= c <= _ONE for c in self.bbox):
                raise ValueError("bbox values must be fractions between 0 and 1")
            if x0 > x1 or y0 > y1:
                raise ValueError("bbox must be [x0, y0, x1, y1] with x0 <= x1 and y0 <= y1")
            if self.page is None:
                raise ValueError("bbox needs a page")
        return self


def _null() -> FieldValue:
    return FieldValue()


Fv = Annotated[FieldValue, PField(default_factory=_null)]


class InvoiceLine(_Strict):
    description: Fv
    hsn_sac: Fv
    quantity: Fv
    unit: Fv
    unit_rate: Fv
    discount: Fv
    taxable_value: Fv
    gst_rate: Fv
    cgst: Fv
    sgst: Fv
    igst: Fv
    cess: Fv


class InvoiceTotals(_Strict):
    taxable_total: Fv
    cgst_total: Fv
    sgst_total: Fv
    igst_total: Fv
    cess_total: Fv
    round_off: Fv
    grand_total: Fv


class InvoiceExtraction(_Strict):
    document_kind: Fv
    supplier_name: Fv
    supplier_gstin: Fv
    buyer_name: Fv
    buyer_gstin: Fv
    invoice_no: Fv
    invoice_date: Fv
    place_of_supply: Fv
    original_invoice_no: Fv
    lines: Annotated[list[InvoiceLine], PField(default_factory=list, max_length=500)]
    totals: Annotated[InvoiceTotals, PField(default_factory=InvoiceTotals)]
    currency: StrictStr = "INR"
    notes: Annotated[list[StrictStr], PField(default_factory=list, max_length=50)]


class BankLine(_Strict):
    date: Fv
    narration: Fv
    reference: Fv
    debit: Fv
    credit: Fv
    balance: Fv


class BankStatementExtraction(_Strict):
    bank_name: Fv
    account_ref: Fv           # as given to the model: masked token, never a real account number
    period_from: Fv
    period_to: Fv
    opening_balance: Fv
    closing_balance: Fv
    lines: Annotated[list[BankLine], PField(default_factory=list, max_length=5000)]
    currency: StrictStr = "INR"
    notes: Annotated[list[StrictStr], PField(default_factory=list, max_length=50)]


# ============================================================================================ parsing


@dataclass(frozen=True)
class ParseOutcome:
    """ok -> `model` is set; otherwise `reason` says in plain words why the answer was refused (D-04)."""

    model: BaseModel | None
    reason: str | None

    @property
    def ok(self) -> bool:
        return self.model is not None


_FENCE = re.compile(r"^```[A-Za-z]*\s*\n(.*)\n```$", re.DOTALL)


def strip_single_fence(text: str) -> str:
    """Remove ONE surrounding Markdown code fence (formatting, not content). Anything else is left alone."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    if match and "```" not in match.group(1):
        return match.group(1).strip()
    return stripped


def _reason(error: ValidationError) -> str:
    parts = []
    for e in error.errors()[:5]:
        where = ".".join(str(p) for p in e["loc"]) or "answer"
        parts.append(f"{where}: {e['msg']}")
    more = len(error.errors()) - 5
    return "The answer does not fit the extraction schema (" + "; ".join(parts) + (f"; and {more} more" if more > 0 else "") + ")."


def _parse(model_cls: type[BaseModel], text: str) -> ParseOutcome:
    try:
        data = json.loads(strip_single_fence(text))
    except (ValueError, RecursionError):
        return ParseOutcome(None, "The answer is not valid JSON.")
    if not isinstance(data, dict):
        return ParseOutcome(None, "The answer is valid JSON but not a JSON object.")
    return _validate(model_cls, data)


def _validate(model_cls: type[BaseModel], data: dict) -> ParseOutcome:
    try:
        return ParseOutcome(model_cls.model_validate(data), None)
    except ValidationError as error:
        return ParseOutcome(None, _reason(error))


def parse_invoice_json(text: str) -> ParseOutcome:
    return _parse(InvoiceExtraction, text)


def parse_invoice_payload(payload: dict) -> ParseOutcome:
    """A payload as stored / edited (a dict): the same validation as the model's answer."""
    return _validate(InvoiceExtraction, payload)


def parse_bank_json(text: str) -> ParseOutcome:
    return _parse(BankStatementExtraction, text)


def parse_bank_payload(payload: dict) -> ParseOutcome:
    return _validate(BankStatementExtraction, payload)


def payload_of(model: BaseModel) -> dict:
    """Plain JSON types (decimals as text) for the `extractions.payload` column; stable for a round trip."""
    return model.model_dump(mode="json")


def invoice_payload(model: InvoiceExtraction) -> dict:
    return payload_of(model)


# ============================================================================================ conversion to the engine's types


def _field(fv: FieldValue) -> Field:
    source = None if fv.page is None else Source(fv.page, fv.bbox)
    return Field(fv.value, source, fv.confidence)


def invoice_to_engine(m: InvoiceExtraction) -> ExtractedInvoice:
    lines = tuple(
        ExtractedLine(*(_field(getattr(line, name)) for name in (
            "description", "hsn_sac", "quantity", "unit", "unit_rate", "discount", "taxable_value", "gst_rate",
            "cgst", "sgst", "igst", "cess")))
        for line in m.lines
    )
    totals = ExtractedTotals(*(_field(getattr(m.totals, name)) for name in (
        "taxable_total", "cgst_total", "sgst_total", "igst_total", "cess_total", "round_off", "grand_total")))
    return ExtractedInvoice(
        *(_field(getattr(m, name)) for name in (
            "document_kind", "supplier_name", "supplier_gstin", "buyer_name", "buyer_gstin", "invoice_no", "invoice_date",
            "place_of_supply", "original_invoice_no")),
        lines=lines, totals=totals, currency=m.currency, notes=tuple(m.notes),
    )


def bank_to_engine(m: BankStatementExtraction) -> doc_bank.BankStatement:
    lines = tuple(
        doc_bank.BankLine(*(_field(getattr(line, name)) for name in ("date", "narration", "reference", "debit", "credit", "balance")))
        for line in m.lines
    )
    return doc_bank.BankStatement(
        *(_field(getattr(m, name)) for name in (
            "bank_name", "account_ref", "period_from", "period_to", "opening_balance", "closing_balance")),
        lines=lines, currency=m.currency, notes=tuple(m.notes),
    )
