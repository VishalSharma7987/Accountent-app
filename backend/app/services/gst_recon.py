"""GSTR-2B import and books <-> 2B reconciliation use-cases (Phase 3, package D).

The matching is the pure engine (engine/gst_recon.py); the file reading is importers/gstr2b.py. Services take a Connection
and never commit; every check runs before the first write; every change is written to the audit log.

Dependency: `apply` hands the effects to package C's `services.gst_itc.apply_2b_result(conn, client_id, registration_id,
period, effects, actor) -> list[{itc_entry_id, from_status, to_status}]`. Until that function exists the effects are returned
without side effects (applied = False).
"""

import calendar
import hashlib
import importlib
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import Connection

from app.db import repositories_gst_recon as repo
from app.db.repositories import client_exists
from app.engine import gst_recon as engine
from app.importers import gstr2b
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def tolerance() -> Decimal:
    """GST_RECON_TOLERANCE (default 0.00; configuration, not law)."""
    raw = os.environ.get("GST_RECON_TOLERANCE", "0.00").strip()
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ServiceError("invalid_tolerance", f"GST_RECON_TOLERANCE {raw!r} is not a number.") from None
    if value < 0 or value != value.quantize(Decimal("0.01")):
        raise ServiceError("invalid_tolerance", f"GST_RECON_TOLERANCE {raw!r} must be a non-negative amount with 2 decimals.")
    return value


def parse_period(value: str) -> date:
    match = _PERIOD.match(value or "")
    if not match:
        raise ServiceError("invalid_period", f"Period {value!r} must be a month written YYYY-MM, e.g. 2026-04.")
    return date(int(match.group(1)), int(match.group(2)), 1)


def _month_end(start: date) -> date:
    return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def _require(conn: Connection, client_id: object, registration_id: object) -> str:
    if not client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    gstin = repo.registration_gstin(conn, client_id, registration_id)
    if gstin is None:
        raise ServiceError("not_found", "GST registration not found for this client.")
    return gstin


# ============================================================================================== import


@dataclass(frozen=True)
class ImportResult:
    import_id: object
    document_count: int
    period: date
    generated_on: date | None
    totals: dict


def import_file(conn: Connection, client_id, registration_id, kind: str, period_text: str, file_name: str, content: bytes,
                actor: str) -> ImportResult:
    actor = require_actor(actor)
    registration_gstin = _require(conn, client_id, registration_id)
    period = parse_period(period_text)
    if kind != "gstr2b":
        raise ServiceError("import_invalid", "Only GSTR-2B files can be imported at present: the IMS file layout is not yet "
                           "available, a real IMS file from the portal is needed.")
    try:
        parsed = gstr2b.parse_gstr2b(content)
    except gstr2b.Gstr2bFileError as e:
        raise ServiceError("import_invalid", f"The file is rejected: {e}",
                           [{"row": p.row, "message": p.message} for p in e.problems]) from None
    if parsed.recipient_gstin != registration_gstin:
        raise ServiceError("import_invalid", f"The file is for GSTIN {parsed.recipient_gstin}, but this registration is "
                           f"{registration_gstin}.", [{"row": 0, "message": "recipient GSTIN differs"}])
    if parsed.period is not None and parsed.period != period:
        raise ServiceError("import_invalid", f"The file is for {parsed.period:%Y-%m}, but the period given is {period:%Y-%m}.",
                           [{"row": 0, "message": "period differs"}])
    file_hash = hashlib.sha256(content).hexdigest()
    existing = repo.import_id_by_hash(conn, client_id, file_hash)
    if existing is not None:
        raise ServiceError("import_duplicate", "This exact file was already imported for this client.", {"import_id": str(existing)})
    import_id = repo.insert_import(
        conn, client_id=client_id, registration_id=registration_id, kind=kind, period=period, source_format=parsed.source_format,
        file_name=file_name, file_hash=file_hash, generated_on=parsed.generated_on, document_count=len(parsed.documents), actor=actor,
    )
    repo.insert_documents(conn, client_id, import_id, parsed.documents)
    totals = repo.import_totals(conn, client_id, import_id)
    audit.log(conn, AuditEntry(client_id, actor, "import", "gstr2b_import", import_id, None, {
        "file_name": file_name, "file_hash": file_hash, "period": period.isoformat(), "documents": len(parsed.documents),
        "format": parsed.source_format, "registration_id": str(registration_id),
    }))
    return ImportResult(import_id, len(parsed.documents), period, parsed.generated_on, totals)


def list_imports(conn: Connection, client_id, registration_id=None) -> list[dict]:
    if not client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    return repo.list_imports(conn, client_id, registration_id)


def list_documents(conn: Connection, client_id, import_id) -> list[dict]:
    if repo.get_import(conn, client_id, import_id) is None:
        raise ServiceError("not_found", "Import not found.")
    return repo.list_documents(conn, client_id, import_id)


# ======================================================================================= reconciliation


@dataclass(frozen=True)
class Reconciliation:
    period: date
    tolerance: Decimal
    result: engine.ReconResult
    links: dict  # (document_id, voucher_id) -> link id, for the API


def reconcile(conn: Connection, client_id, registration_id, period_text: str) -> Reconciliation:
    """Computed on demand, nothing is written. The books side is the posted purchase register with voucher date in the month;
    the 2B side is the newest GSTR-2B import of that month (G-41)."""
    _require(conn, client_id, registration_id)
    period = parse_period(period_text)
    latest = repo.latest_imports_by_period(conn, client_id, registration_id)
    if period not in latest:
        raise ServiceError("not_found", f"No GSTR-2B has been imported for {period:%Y-%m}.")
    docs = repo.documents_of(conn, client_id, [latest[period]])
    others = repo.documents_of(conn, client_id, [i for p, i in latest.items() if p != period])
    books = repo.book_docs(conn, client_id, registration_id, period, _month_end(period))
    links = repo.list_links(conn, client_id, registration_id)
    result = engine.reconcile(books, docs, others, links, tolerance())
    return Reconciliation(period, tolerance(), result, {(link.document_id, link.voucher_id): link.link_id for link in links})


def apply(conn: Connection, client_id, registration_id, period_text: str, actor: str) -> dict:
    actor = require_actor(actor)
    recon = reconcile(conn, client_id, registration_id, period_text)
    effects = engine.apply_effects(recon.result)
    try:
        itc = importlib.import_module("app.services.gst_itc")
        hook = getattr(itc, "apply_2b_result", None)
    except ImportError:
        hook = None
    if hook is None:
        return {"updated": [], "effects": effects, "applied": False}
    updated = hook(conn, client_id, registration_id, recon.period, effects, actor)
    return {"updated": list(updated), "effects": effects, "applied": True}


# ============================================================================================== links


def create_link(conn: Connection, client_id, document_id, voucher_id, link_kind: str, note: str, actor: str):
    """One-to-one link of a 2B document with a posted purchase / debit-note voucher of the same registration (G-43)."""
    actor = require_actor(actor)
    if link_kind not in ("manual", "accepted_difference"):
        raise ServiceError("invalid_link_kind", "link_kind must be manual or accepted_difference.")
    if not note or not note.strip():
        raise ServiceError("reason_required", "A note saying why these two documents are the same is required.")
    document = repo.document_for_link(conn, client_id, document_id)
    voucher = repo.voucher_for_link(conn, client_id, voucher_id)
    if document is None or voucher is None:
        raise ServiceError("not_found", "The 2B document or the voucher was not found for this client.")
    if voucher["status"] != "posted" or voucher["voucher_type"] not in ("purchase", "debit_note") \
            or voucher["gst_registration_id"] != document["gst_registration_id"]:
        raise ServiceError("link_invalid", "Only a posted Purchase or Debit Note voucher of the same GST registration can be linked.")
    if repo.link_exists(conn, document_id, voucher_id):
        raise ServiceError("link_exists", "The document or the voucher is already linked to something else (one to one).")
    link_id = repo.insert_link(conn, client_id=client_id, registration_id=document["gst_registration_id"], document_id=document_id,
                               voucher_id=voucher_id, link_kind=link_kind, note=note.strip(), actor=actor)
    audit.log(conn, AuditEntry(client_id, actor, "link", "gstr2b_link", link_id, None, {
        "document_id": str(document_id), "voucher_id": str(voucher_id), "link_kind": link_kind, "note": note.strip()}))
    return link_id


def delete_link(conn: Connection, client_id, link_id, actor: str) -> None:
    actor = require_actor(actor)
    link = repo.get_link(conn, client_id, link_id)
    if link is None:
        raise ServiceError("not_found", "Link not found.")
    repo.delete_link(conn, client_id, link_id)
    audit.log(conn, AuditEntry(client_id, actor, "unlink", "gstr2b_link", link_id, {
        "document_id": str(link["document_id"]), "voucher_id": str(link["voucher_id"]), "link_kind": link["link_kind"],
        "note": link["note"]}, None))
