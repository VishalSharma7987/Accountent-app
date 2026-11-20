"""Extraction service (Phase 7, package D; docs/PHASE7_PLAN.md): document text -> prompt -> gateway (masking, switch, audit; package C)
-> schema validation (D-04) -> engine checks (D-03, D-05 .. D-17) -> an immutable `extractions` row.

Expected failures are RESULTS, not exceptions (plan decision 7): `ExtractionOutcome.status` is "ok", "blocked" (the client's switch is off,
D-51), "invalid" (the answer is not JSON / does not fit the schema; the invalid row is stored, nothing is drafted, D-04) or "error" (the
provider failed). Only bad requests raise ServiceError (unknown document, unsupported type, no text yet, previous extraction still live).
Services never commit and write nothing before the checks that can refuse the request.

The gateway is INJECTED (`LlmGateway`): package C's `services/llm_gateway` satisfies it; tests use a double over `ai/fake.py`. This
service passes it the ORIGINAL page text inside the prompt; the gateway masks it before any call and restores tokens in the answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import Connection

from app import config
from app.ai import prompts, schemas
from app.ai.llm import LlmRequest
from app.db import repositories_extractions as repo
from app.db import repositories_gst_invoice as gst_ctx
from app.engine import doc_bank, doc_check
from app.engine.doc_types import SCHEMA_VERSION, DocFinding, DocType, Severity
from app.engine.gst_types import GstRegistration
from app.rules import gst_rules
from app.services import audit
from app.services.errors import ServiceError, require_actor

INVOICE_TYPES = frozenset({DocType.PURCHASE_INVOICE.value, DocType.SALES_INVOICE.value, DocType.CREDIT_NOTE.value,
                           DocType.DEBIT_NOTE.value, DocType.EXPENSE_BILL.value})
BANK_TYPE = DocType.BANK_STATEMENT.value
BANK_SCHEMA_VERSION = "bank-extract-1"


class LlmGateway(Protocol):
    """What this service needs from package C's gateway. The result carries `status` ("ok" | "blocked" | "error"), `llm_call_id`
    (the stored audit row; also for a blocked or failed call), `text` (the answer with masking tokens restored; only when ok) and
    `message` (plain words for the accountant)."""

    def call(self, conn: Connection, *, client_id: Any, document_id: Any, request: LlmRequest, prompt_version: str, actor: str) -> Any: ...


@dataclass(frozen=True)
class ExtractionOutcome:
    status: str                         # ok | blocked | invalid | error
    message: str
    extraction_id: Any = None
    llm_call_id: Any = None
    version: int | None = None
    findings: tuple[DocFinding, ...] = ()


@dataclass(frozen=True)
class CheckOutput:
    findings: tuple[DocFinding, ...]
    recomputed: dict = field(default_factory=dict)
    direction: str | None = None
    place_of_supply: str | None = None


# ============================================================================================ context for the engine


def _registrations(conn: Connection, client_id: Any) -> tuple[GstRegistration, ...]:
    from app.db import repositories_gst_masters as masters

    return tuple(
        GstRegistration(str(r.id), r.gstin, r.state_code, r.registration_type, r.return_frequency, r.composition_category,
                        r.effective_from, r.effective_to, r.is_active, r.trade_name)
        for r in masters.registration_rows(conn, client_id)
    )


def build_context(conn: Connection, client_id: Any, doc: repo.DocumentRow, payload_date: date | None, *, source: str,
                  invoice_no: str | None = None, place_of_supply_override: str | None = None,
                  today: date | None = None) -> doc_check.DocCheckContext:
    """Everything the pure check needs, loaded once. `payload_date` selects the rule rows (the invoice date, else today)."""
    now = today or date.today()
    on = payload_date or now
    rows = gst_ctx.load_context(conn, client_id, None, None, on, on)
    dups = ()
    if invoice_no and invoice_no.strip():
        dups = tuple(doc_check.DuplicateCandidate(s, ref, gstin, name, no)
                     for s, ref, gstin, name, no in repo.duplicate_rows(conn, client_id, doc.id, invoice_no))
    return doc_check.DocCheckContext(
        registrations=_registrations(conn, client_id), rules=rows.rules, state_codes=tuple(gst_rules.state_codes(conn, on)),
        today=now, doc_type=DocType(doc.doc_type), financial_years=tuple(repo.financial_years(conn, client_id)),
        locked_periods=tuple(repo.locked_periods(conn, client_id)), min_confidence=Decimal(config.ai_min_confidence()),
        require_source=(source == "llm"), page_count=doc.page_count, place_of_supply_override=place_of_supply_override, duplicates=dups,
    )


def _invoice_date(inv) -> date | None:
    try:
        return doc_check.parse_date_text(inv.invoice_date.value) if inv.invoice_date.value and inv.invoice_date.value.strip() else None
    except ValueError:
        return None


def _recomputed_out(res: doc_check.DocCheckResult) -> dict:
    def line(x):
        return None if x is None else {"taxable_value": f"{x.taxable_value:.2f}", "rate": str(x.gst_rate), "cgst": f"{x.cgst:.2f}",
                                       "sgst": f"{x.sgst:.2f}", "igst": f"{x.igst:.2f}", "cess": f"{x.cess:.2f}"}

    return {"lines": [line(x) for x in res.lines], "totals": {k: f"{v:.2f}" for k, v in res.totals.items()}}


def check_model(conn: Connection, client_id: Any, doc: repo.DocumentRow, model, *, source: str,
                place_of_supply_override: str | None = None, today: date | None = None) -> CheckOutput:
    """Run the engine checks of a validated schema model (invoice or bank statement). Reads only."""
    if doc.doc_type == BANK_TYPE:
        st = schemas.bank_to_engine(model)
        res = doc_bank.check_bank_statement(
            st, doc_bank.BankCheckContext(today or date.today(), Decimal(config.ai_min_confidence()), source == "llm", doc.page_count))
        return CheckOutput(res.findings)
    inv = schemas.invoice_to_engine(model)
    ctx = build_context(conn, client_id, doc, _invoice_date(inv), source=source, invoice_no=inv.invoice_no.value,
                        place_of_supply_override=place_of_supply_override, today=today)
    res = doc_check.check_invoice(inv, ctx)
    return CheckOutput(res.findings, _recomputed_out(res), res.direction, res.place_of_supply)


def check_payload(conn: Connection, client_id: Any, document_id: Any, payload: dict, *, source: str = "llm",
                  place_of_supply_override: str | None = None, today: date | None = None) -> CheckOutput:
    """The check the approval queue runs again on every edit (D-61): the payload (an original or edited extraction) is validated against
    the schema and checked. A payload that does not fit the schema is returned as one D-04 error. Writes nothing."""
    doc = _document(conn, client_id, document_id)
    parsed = _parse_payload(doc, payload)
    if not parsed.ok:
        return CheckOutput((DocFinding("D-04", Severity.ERROR, parsed.reason or "Invalid extraction."),))
    return check_model(conn, client_id, doc, parsed.model, source=source, place_of_supply_override=place_of_supply_override, today=today)


def check_extraction(conn: Connection, client_id: Any, extraction_id: Any, *, today: date | None = None) -> CheckOutput:
    row = repo.extraction_row(conn, client_id, extraction_id)
    if row is None:
        raise ServiceError("not_found", "Extraction not found.")
    if row.status != "valid":
        raise ServiceError("extraction_invalid", row.invalid_reason or "This extraction is invalid (D-04).", {"extraction_id": str(row.id)})
    return check_payload(conn, client_id, row.document_id, row.payload, source=row.source, today=today)


# ============================================================================================ the two ways in


def _document(conn: Connection, client_id: Any, document_id: Any) -> repo.DocumentRow:
    doc = repo.document_row(conn, client_id, document_id)
    if doc is None:
        raise ServiceError("not_found", "Document not found for this client.")
    if doc.doc_type not in INVOICE_TYPES and doc.doc_type != BANK_TYPE:
        raise ServiceError("invalid_document_type", f"A document of type '{doc.doc_type}' cannot be read as an invoice or a bank statement.")
    return doc


def _parse_payload(doc: repo.DocumentRow, payload: dict) -> schemas.ParseOutcome:
    return schemas.parse_bank_payload(payload) if doc.doc_type == BANK_TYPE else schemas.parse_invoice_payload(payload)


def _require_free_to_extract(conn: Connection, client_id: Any, doc: repo.DocumentRow) -> repo.ExtractionRow | None:
    """A new extraction replaces the live one only when its queue item is rejected (or it never had one)."""
    live = repo.live_extraction(conn, client_id, doc.id)
    if live is not None and repo.open_queue_items(conn, client_id, live.id) > 0:
        raise ServiceError(
            "queue_state",
            "This document's extraction is already in the approval queue. Reject that item first if you want to read the document again.",
        )
    return live


def _store(conn: Connection, client_id: Any, doc: repo.DocumentRow, actor: str, *, source: str, llm_call_id: Any, payload: dict,
           status: str, reason: str | None, previous: repo.ExtractionRow | None) -> tuple[Any, int]:
    version = repo.next_version(conn, doc.id)
    schema_version = BANK_SCHEMA_VERSION if doc.doc_type == BANK_TYPE else SCHEMA_VERSION
    ext_id = repo.insert_extraction(conn, client_id=client_id, document_id=doc.id, version=version, source=source,
                                    llm_call_id=llm_call_id, schema_version=schema_version, payload=payload, status=status,
                                    invalid_reason=reason, created_by=actor)
    if previous is not None:
        repo.supersede(conn, previous.id)
    audit.log(conn, audit.AuditEntry(client_id, actor, "extraction_created", "extraction", ext_id, None,
                                     {"document_id": str(doc.id), "version": version, "source": source, "status": status,
                                      "supersedes": None if previous is None else str(previous.id)}))
    return ext_id, version


def _finish(conn: Connection, client_id: Any, doc: repo.DocumentRow, actor: str, *, source: str, llm_call_id: Any,
            parsed: schemas.ParseOutcome, previous: repo.ExtractionRow | None) -> ExtractionOutcome:
    if not parsed.ok:
        ext_id, version = _store(conn, client_id, doc, actor, source=source, llm_call_id=llm_call_id, payload={}, status="invalid",
                                 reason=parsed.reason, previous=previous)
        return ExtractionOutcome("invalid", f"{parsed.reason} Nothing was drafted (D-04).", ext_id, llm_call_id, version,
                                 (DocFinding("D-04", Severity.ERROR, parsed.reason or "Invalid extraction."),))
    payload = schemas.payload_of(parsed.model)
    ext_id, version = _store(conn, client_id, doc, actor, source=source, llm_call_id=llm_call_id, payload=payload, status="valid",
                             reason=None, previous=previous)
    out = check_model(conn, client_id, doc, parsed.model, source=source)
    blocking = sum(1 for f in out.findings if f.severity in (Severity.ERROR, Severity.REVIEW))
    message = "Extraction stored; no blocking finding." if not blocking else f"Extraction stored with {blocking} finding(s) to resolve before a draft can be built."
    return ExtractionOutcome("ok", message, ext_id, llm_call_id, version, out.findings)


def run_llm_extraction(conn: Connection, *, client_id: Any, document_id: Any, actor: str, gateway: LlmGateway) -> ExtractionOutcome:
    actor = require_actor(actor)
    doc = _document(conn, client_id, document_id)
    previous = _require_free_to_extract(conn, client_id, doc)
    pages = repo.page_texts(conn, client_id, doc.id)
    if not pages:
        raise ServiceError("no_text", "The text of this document has not been read yet. Read the text first (or enter the invoice by hand).")
    bank = doc.doc_type == BANK_TYPE
    model = config.llm_model() or ""
    request = (prompts.bank_request if bank else prompts.invoice_request)(pages, model=model)
    version = prompts.BANK_PROMPT_VERSION if bank else prompts.INVOICE_PROMPT_VERSION
    result = gateway.call(conn, client_id=client_id, document_id=doc.id, request=request, prompt_version=version, actor=actor)
    call_id = getattr(result, "llm_call_id", None)
    status = getattr(result, "status", "error")
    if status != "ok" or getattr(result, "text", None) is None:
        shown = "blocked" if status == "blocked" else "error"
        return ExtractionOutcome(shown, getattr(result, "message", None) or "The model call did not return an answer.", None, call_id)
    parsed = schemas.parse_bank_json(result.text) if bank else schemas.parse_invoice_json(result.text)
    return _finish(conn, client_id, doc, actor, source="llm", llm_call_id=call_id, parsed=parsed, previous=previous)


def enter_manual(conn: Connection, *, client_id: Any, document_id: Any, actor: str, payload: dict) -> ExtractionOutcome:
    """The accountant types what the document says (same schema, same engine checks; no model, no switch needed)."""
    actor = require_actor(actor)
    doc = _document(conn, client_id, document_id)
    previous = _require_free_to_extract(conn, client_id, doc)
    return _finish(conn, client_id, doc, actor, source="manual", llm_call_id=None, parsed=_parse_payload(doc, payload), previous=previous)


# ============================================================================================ reads


def list_versions(conn: Connection, client_id: Any, document_id: Any) -> Sequence[repo.ExtractionRow]:
    _document(conn, client_id, document_id)
    return repo.extraction_rows(conn, client_id, document_id)


def get_extraction(conn: Connection, client_id: Any, extraction_id: Any) -> repo.ExtractionRow:
    row = repo.extraction_row(conn, client_id, extraction_id)
    if row is None:
        raise ServiceError("not_found", "Extraction not found.")
    return row
