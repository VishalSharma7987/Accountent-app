"""Tally export use-case (Phase 7 package B, D-38, D-39): posted vouchers and the masters they use as Tally-importable XML.

Reads only; the XML is stored as a document through the injected `store_document` (the documents package of this phase) and one
`tally_exports` row records the export. A reversed original and its reversal voucher are both posted entries, so both are exported.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo_main
from app.db import repositories_tally as repo
from app.engine.tally_export import (
    ExportGroup,
    ExportHeader,
    ExportLedger,
    ExportLine,
    ExportVoucher,
    build_export,
)
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor

KINDS = ("masters", "vouchers", "both")
# store_document(conn, client_id, doc_type, filename, data, actor) -> document id
StoreDocument = Callable[[Connection, Any, str, str, bytes, str], Any]


@dataclass(frozen=True)
class ExportOut:
    export_id: Any
    document_id: Any
    master_count: int
    voucher_count: int
    warnings: list[str]


def _label(start: date) -> str:
    return f"{start.year}-{str(start.year + 1)[2:]}"


def export(
    conn: Connection, client_id: Any, *, kind: str, from_date: date | None = None, to_date: date | None = None,
    financial_year_id: Any = None, posted_only: bool = False, store_document: StoreDocument, actor: str,
) -> ExportOut:
    actor = require_actor(actor)
    if kind not in KINDS:
        raise ServiceError("invalid_kind", "kind must be masters, vouchers or both.")
    name = repo.client_name(conn, client_id)
    if name is None or not repo_main.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    label = "any"
    if financial_year_id is not None:
        window = repo.financial_year(conn, client_id, financial_year_id)
        if window is None:
            raise ServiceError("not_found", "Financial year not found for this client.")
        from_date = max(from_date, window[0]) if from_date else window[0]
        to_date = min(to_date, window[1]) if to_date else window[1]
        label = _label(window[0])
    if from_date and to_date and to_date < from_date:
        raise ServiceError("invalid_range", "The end date is before the start date.")

    warnings: list[str] = []
    voucher_rows: list[dict] = []
    if kind in ("vouchers", "both"):
        unposted = repo.unposted_count(conn, client_id, from_date, to_date)
        if unposted and not posted_only:
            raise ServiceError(
                "unposted_vouchers",
                f"{unposted} voucher(s) in this range are not posted yet. Post them first, or ask for posted vouchers only (D-39).",
                {"unposted": unposted})
        if unposted:
            warnings.append(f"{unposted} unposted voucher(s) in the range were not exported (posted only was requested).")
        voucher_rows = repo.posted_vouchers(conn, client_id, from_date, to_date)
    lines = repo.voucher_lines(conn, [r["id"] for r in voucher_rows])
    vouchers = [
        ExportVoucher(r["voucher_type"], r["voucher_date"], r["voucher_number"], r["narration"], r["reference_no"], r["party"],
                      tuple(ExportLine(n, Decimal(d), Decimal(c)) for n, d, c in lines.get(r["id"], [])))
        for r in voucher_rows
    ]

    used = {x.ledger_name.lower() for v in vouchers for x in v.lines}
    all_ledgers = repo.all_ledgers_with_groups(conn, client_id)
    chosen = [(n, g, custom) for n, g, custom in all_ledgers if kind in ("masters", "both") or n.lower() in used]
    custom_groups = repo.custom_groups(conn, client_id)
    needed = {g for _, g, custom in chosen if custom}
    parents = dict(custom_groups)
    for g in list(needed):  # a custom group's custom parents are needed too
        while parents.get(g) in parents and parents[g] not in needed:
            needed.add(parents[g])
            g = parents[g]
    groups = [ExportGroup(g, p) for g, p in custom_groups if kind in ("masters", "both") or g in needed]

    result = build_export(ExportHeader(name, label, from_date, to_date, kind, datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")), groups, [ExportLedger(n, g) for n, g, _ in chosen], vouchers)
    warnings += list(result.warnings)
    filename = f"tally_export_{kind}_{from_date or 'start'}_{to_date or 'end'}.xml"
    document_id = store_document(conn, client_id, "tally_export", filename, result.xml.encode("utf-8"), actor)
    export_id = repo.insert_export(conn, client_id, document_id, kind, from_date, to_date, result.master_count, result.voucher_count, actor)
    audit.log(conn, AuditEntry(client_id, actor, "tally_export", "tally_export", export_id, None, {
        "kind": kind, "from": str(from_date), "to": str(to_date), "masters": result.master_count, "vouchers": result.voucher_count,
        "document_id": str(document_id), "warnings": len(warnings)}))
    return ExportOut(export_id, document_id, result.master_count, result.voucher_count, warnings)


def list_exports(conn: Connection, client_id: Any) -> list[dict]:
    return repo.list_exports(conn, client_id)
