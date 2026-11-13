"""26AS / AIS import and books reconciliation use-cases (Phase 4, package E; rules T-40 .. T-43, T-50).

The matching is the pure engine (engine/tds_recon.py); the file reading is importers/form26as.py. Services take a Connection
and never commit; every check runs before the first write; every change is written to the audit log.
Reconciliation is computed on demand and writes nothing.
"""

import hashlib
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import Connection

from app.db import repositories_tds_recon as repo
from app.db.repositories import client_exists
from app.engine import tds_recon as engine
from app.importers import form26as
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

SOURCES = ("form_26as", "ais", "tis")
SIDES = ("deductee", "deductor")
_STATUS_ORDER = {"pending": 0, "secondary_verified": 1, "verified": 2}


def tolerance() -> Decimal:
    """TDS_RECON_TOLERANCE (default 1.00; configuration, not law; reported with every reconciliation)."""
    raw = os.environ.get("TDS_RECON_TOLERANCE", "1.00").strip()
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ServiceError("invalid_tolerance", f"TDS_RECON_TOLERANCE {raw!r} is not a number.") from None
    if value < 0 or value != value.quantize(Decimal("0.01")):
        raise ServiceError("invalid_tolerance", f"TDS_RECON_TOLERANCE {raw!r} must be a non-negative amount with 2 decimals.")
    return value


def _require_client(conn: Connection, client_id: object) -> None:
    if not client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


# ============================================================================================== import


@dataclass(frozen=True)
class ImportResult:
    import_id: object
    row_count: int
    totals: dict


def import_file(conn: Connection, client_id, fy_id, source: str, side: str, file_name: str, content: bytes, actor: str) -> ImportResult:
    actor = require_actor(actor)
    _require_client(conn, client_id)
    fy = repo.fy_dates(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    if source not in SOURCES:
        raise ServiceError("invalid_source", f"Source {source!r} must be one of: {', '.join(SOURCES)}.")
    if side not in SIDES:
        raise ServiceError("invalid_side", f"Side {side!r} must be deductee (tax deducted from this client) or deductor "
                           "(tax deducted by this client).")
    try:
        parsed = form26as.parse_26as(content)
    except form26as.Form26asFileError as e:
        raise ServiceError("import_invalid", f"The file is rejected: {e}",
                           [{"row": p.row, "message": p.message} for p in e.problems]) from None
    problems = _check_for_side(parsed.rows, side, fy, repo.client_tan(conn, client_id))
    if problems:
        raise ServiceError("import_invalid", "The file is rejected: " + "; ".join(f"row {r}: {m}" for r, m in problems),
                           [{"row": r, "message": m} for r, m in problems])
    file_hash = hashlib.sha256(content).hexdigest()
    existing = repo.import_id_by_hash(conn, client_id, file_hash)
    if existing is not None:
        raise ServiceError("import_duplicate", "This exact file was already imported for this client.", {"import_id": str(existing)})
    import_id = repo.insert_import(conn, client_id=client_id, fy_id=fy_id, source=source, side=side, file_name=file_name,
                                   file_hash=file_hash, row_count=len(parsed.rows), actor=actor)
    repo.insert_rows(conn, client_id, import_id, parsed.rows)
    totals = repo.import_totals(conn, client_id, import_id)
    audit.log(conn, AuditEntry(client_id, actor, "import", "tds_26as_import", import_id, None, {
        "file_name": file_name, "file_hash": file_hash, "source": source, "side": side, "rows": len(parsed.rows),
        "financial_year_id": str(fy_id), "format": parsed.source_format}))
    return ImportResult(import_id, len(parsed.rows), totals)


def _check_for_side(rows, side: str, fy: tuple, client_tan: str | None) -> list[tuple[int, str]]:
    """Row-wise checks that need the side, the year and the client (T-40): nothing is skipped silently."""
    problems: list[tuple[int, str]] = []
    for r in rows:
        line = r.row_no + 1  # file row, header = 1
        if side == "deductee" and not r.deductor_tan:
            problems.append((line, "deductor TAN is missing (needed when the statement is the client's own credit)"))
        if side == "deductor":
            if not r.deductee_pan:
                problems.append((line, "deductee PAN is missing (needed when the statement lists tax deducted by the client)"))
            if client_tan and r.deductor_tan and r.deductor_tan != client_tan:
                problems.append((line, f"deductor TAN {r.deductor_tan} is not this client's TAN {client_tan}"))
        if not fy[0] <= r.transaction_date <= fy[1]:
            problems.append((line, f"transaction date {r.transaction_date:%d-%m-%Y} is outside the financial year "
                                   + f"{fy[0]:%d-%m-%Y} to {fy[1]:%d-%m-%Y}"))
    return problems


def list_imports(conn: Connection, client_id, fy_id=None) -> list[dict]:
    _require_client(conn, client_id)
    return repo.list_imports(conn, client_id, fy_id)


def list_rows(conn: Connection, client_id, import_id) -> list[dict]:
    if repo.get_import(conn, client_id, import_id) is None:
        raise ServiceError("not_found", "Import not found.")
    return repo.list_rows(conn, client_id, import_id)


# ======================================================================================= reconciliation


@dataclass(frozen=True)
class Reconciliation:
    import_id: object
    side: str
    tolerance: Decimal
    result: engine.ReconResult
    rule_status: dict


def _rule_status(printed_sections: set[str], section_rows: list[dict]) -> dict:
    """T-50: worst verification status of the section-table rows the printed sections were mapped through."""
    used = [r for r in section_rows if engine.normalise_section(r["section_ref"]) in printed_sections]
    if not used:
        return {"worst": "verified", "tables": {}, "pending_sources": []}
    worst = min((r["verification_status"] for r in used), key=_STATUS_ORDER.__getitem__)
    pending = sorted({r["source_reference"] for r in used if r["verification_status"] == "pending"})
    return {"worst": worst, "tables": {"section_map": worst}, "pending_sources": pending}


def reconcile(conn: Connection, client_id, fy_id, import_id=None) -> Reconciliation:
    _require_client(conn, client_id)
    imported = repo.get_import(conn, client_id, import_id) if import_id else repo.latest_import(conn, client_id, fy_id)
    if imported is None or imported["financial_year_id"] != fy_id:
        raise ServiceError("not_found", "No 26AS / AIS import was found for this financial year.")
    side = imported["side"]
    rows = repo.rows26(conn, client_id, imported["id"])
    section_rows = repo.section_rows(conn)
    sections = [engine.SectionMap(r["nature_key"], r["section_ref"]) for r in section_rows]
    if side == "deductor":
        books = repo.deduction_items(conn, client_id, fy_id)
        known = repo.known_pans(conn, client_id)
    else:
        books = repo.receivable_vouchers(conn, client_id, fy_id)
        known = set()
    links = repo.list_links(conn, client_id, imported["id"])
    tol = tolerance()
    result = engine.reconcile(side, rows, books, sections, known, links, tol)
    printed = {engine.normalise_section(r.section_ref) for r in rows} if side == "deductor" else set()
    return Reconciliation(imported["id"], side, tol, result, _rule_status(printed, section_rows))


# ============================================================================================== links


def create_link(conn: Connection, client_id, row_id, item_id, voucher_id, link_kind: str, note: str, actor: str):
    """One-to-one hand link of a statement row with a posted deduction item (deductor side) or voucher (deductee side) (T-43)."""
    actor = require_actor(actor)
    if link_kind not in ("manual", "accepted_difference"):
        raise ServiceError("invalid_link_kind", "link_kind must be manual or accepted_difference.")
    if not note or not note.strip():
        raise ServiceError("reason_required", "A note saying why this statement row and the books entry belong together is required.")
    if (item_id is None) == (voucher_id is None):
        raise ServiceError("invalid_link_target", "Give exactly one of item_id (deductor side) or voucher_id (deductee side).")
    row = repo.row_for_link(conn, client_id, row_id)
    if row is None:
        raise ServiceError("not_found", "The statement row was not found for this client.")
    if row["side"] == "deductor" and item_id is None or row["side"] == "deductee" and voucher_id is None:
        raise ServiceError("link_invalid", "A deductor-side row links to a deduction item; a deductee-side row links to a voucher.")
    target = repo.item_for_link(conn, client_id, item_id) if item_id is not None else repo.voucher_for_link(conn, client_id, voucher_id)
    if target is None:
        raise ServiceError("not_found", "The deduction item or voucher was not found for this client.")
    if target["status"] != "posted" or target["financial_year_id"] != row["financial_year_id"]:
        raise ServiceError("link_invalid", "Only a posted voucher of the same financial year can be linked.")
    if repo.link_exists(conn, row_id, item_id, voucher_id):
        raise ServiceError("link_exists", "The statement row or the books entry is already linked to something else (one to one).")
    link_id = repo.insert_link(conn, client_id=client_id, row_id=row_id, item_id=item_id, voucher_id=voucher_id,
                               link_kind=link_kind, note=note.strip(), actor=actor)
    audit.log(conn, AuditEntry(client_id, actor, "link", "tds_26as_link", link_id, None, {
        "row_id": str(row_id), "item_id": None if item_id is None else str(item_id),
        "voucher_id": None if voucher_id is None else str(voucher_id), "link_kind": link_kind, "note": note.strip()}))
    return link_id


def delete_link(conn: Connection, client_id, link_id, actor: str) -> None:
    actor = require_actor(actor)
    link = repo.get_link(conn, client_id, link_id)
    if link is None:
        raise ServiceError("not_found", "Link not found.")
    repo.delete_link(conn, client_id, link_id)
    audit.log(conn, AuditEntry(client_id, actor, "unlink", "tds_26as_link", link_id, {
        k: None if link[k] is None else str(link[k]) for k in ("row_id", "item_id", "voucher_id", "link_kind", "note")}, None))
