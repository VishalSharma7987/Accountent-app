"""SQL for the extraction service (Phase 7, package D): documents' text, extraction rows, and the lookups the engine checks need
(registrations, financial years, locked periods, possible duplicates). No business logic."""

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

# preference when a page was read by more than one method: a text layer beats OCR, OCR beats typed-in text of the same page
_METHOD_ORDER = "CASE method WHEN 'pdf_text' THEN 1 WHEN 'paddleocr' THEN 2 WHEN 'tesseract' THEN 3 ELSE 4 END"


@dataclass(frozen=True)
class DocumentRow:
    id: object
    doc_type: str
    status: str
    page_count: int | None
    financial_year_id: object | None


def document_row(conn: Connection, client_id: object, document_id: object) -> DocumentRow | None:
    row = conn.execute(
        text("SELECT id, doc_type, status, page_count, financial_year_id FROM documents WHERE id = :d AND client_id = :c"),
        {"d": document_id, "c": client_id},
    ).first()
    return DocumentRow(*row) if row else None


def page_texts(conn: Connection, client_id: object, document_id: object) -> list[tuple[int, str]]:
    """(page_no, text) one per page, best method first."""
    rows = conn.execute(
        text(f"SELECT DISTINCT ON (page_no) page_no, text FROM document_texts WHERE document_id = :d AND client_id = :c "
             f"ORDER BY page_no, {_METHOD_ORDER}"),
        {"d": document_id, "c": client_id},
    )
    return [(r[0], r[1]) for r in rows]


@dataclass(frozen=True)
class ExtractionRow:
    id: object
    document_id: object
    version: int
    source: str
    llm_call_id: object | None
    schema_version: str
    payload: dict
    status: str
    invalid_reason: str | None
    created_by: str
    created_at: object
    superseded_at: object | None


_COLS = ("id, document_id, version, source, llm_call_id, schema_version, payload, status, invalid_reason, created_by, created_at, "
         "superseded_at")


def extraction_row(conn: Connection, client_id: object, extraction_id: object) -> ExtractionRow | None:
    row = conn.execute(text(f"SELECT {_COLS} FROM extractions WHERE id = :e AND client_id = :c"),
                       {"e": extraction_id, "c": client_id}).first()
    return ExtractionRow(*row) if row else None


def extraction_rows(conn: Connection, client_id: object, document_id: object) -> list[ExtractionRow]:
    rows = conn.execute(text(f"SELECT {_COLS} FROM extractions WHERE document_id = :d AND client_id = :c ORDER BY version"),
                        {"d": document_id, "c": client_id})
    return [ExtractionRow(*r) for r in rows]


def live_extraction(conn: Connection, client_id: object, document_id: object) -> ExtractionRow | None:
    """The newest extraction not yet superseded."""
    row = conn.execute(
        text(f"SELECT {_COLS} FROM extractions WHERE document_id = :d AND client_id = :c AND superseded_at IS NULL "
             "ORDER BY version DESC LIMIT 1"),
        {"d": document_id, "c": client_id},
    ).first()
    return ExtractionRow(*row) if row else None


def open_queue_items(conn: Connection, client_id: object, extraction_id: object) -> int:
    """Queue items of this extraction that are not rejected (pending, in review or accepted)."""
    return conn.execute(
        text("SELECT count(*) FROM approval_queue_items WHERE client_id = :c AND extraction_id = :e AND status <> 'rejected'"),
        {"c": client_id, "e": extraction_id},
    ).scalar_one()


def next_version(conn: Connection, document_id: object) -> int:
    return conn.execute(text("SELECT coalesce(max(version), 0) + 1 FROM extractions WHERE document_id = :d"),
                        {"d": document_id}).scalar_one()


def insert_extraction(conn: Connection, *, client_id: object, document_id: object, version: int, source: str,
                      llm_call_id: object | None, schema_version: str, payload: dict, status: str,
                      invalid_reason: str | None, created_by: str) -> object:
    return conn.execute(
        text("INSERT INTO extractions (client_id, document_id, version, source, llm_call_id, schema_version, payload, status, "
             "invalid_reason, created_by) VALUES (:c, :d, :v, :s, :call, :sv, CAST(:p AS jsonb), :st, :why, :by) RETURNING id"),
        {"c": client_id, "d": document_id, "v": version, "s": source, "call": llm_call_id, "sv": schema_version,
         "p": json.dumps(payload), "st": status, "why": invalid_reason, "by": created_by},
    ).scalar_one()


def supersede(conn: Connection, extraction_id: object) -> None:
    conn.execute(text("UPDATE extractions SET superseded_at = now() WHERE id = :e AND superseded_at IS NULL"), {"e": extraction_id})


# ---------------------------------------------------------------------------------------------- context rows for the checks


def financial_years(conn: Connection, client_id: object) -> list[tuple[date, date]]:
    rows = conn.execute(text("SELECT start_date, end_date FROM financial_years WHERE client_id = :c ORDER BY start_date"), {"c": client_id})
    return [(r[0], r[1]) for r in rows]


def locked_periods(conn: Connection, client_id: object) -> list[tuple[date, date]]:
    rows = conn.execute(text("SELECT period_start, period_end FROM periods WHERE client_id = :c AND status = 'locked'"), {"c": client_id})
    return [(r[0], r[1]) for r in rows]


def duplicate_rows(conn: Connection, client_id: object, document_id: object, invoice_no: str) -> list[tuple]:
    """(source, ref, supplier_gstin, supplier_name, invoice_no) of vouchers (not reversed, not drafted from this document) and of live
    valid extractions of OTHER documents that carry the same invoice number (case and outer spaces ignored)."""
    rows = conn.execute(
        text(
            "SELECT 'voucher', coalesce(v.voucher_number, 'draft voucher ' || left(v.id::text, 8)), p.gstin, l.name, v.reference_no "
            "FROM vouchers v LEFT JOIN parties p ON p.ledger_id = v.party_ledger_id AND p.client_id = v.client_id "
            "LEFT JOIN ledgers l ON l.id = v.party_ledger_id AND l.client_id = v.client_id "
            "WHERE v.client_id = :c AND v.status <> 'reversed' AND lower(btrim(v.reference_no)) = lower(btrim(:no)) "
            "AND v.id NOT IN (SELECT draft_voucher_id FROM approval_queue_items WHERE document_id = :d AND draft_voucher_id IS NOT NULL) "
            "AND v.id NOT IN (SELECT voucher_id FROM document_vouchers WHERE document_id = :d) "
            "UNION ALL "
            "SELECT 'extraction', 'another document (extraction version ' || e.version || ')', "
            "e.payload -> 'supplier_gstin' ->> 'value', e.payload -> 'supplier_name' ->> 'value', e.payload -> 'invoice_no' ->> 'value' "
            "FROM extractions e WHERE e.client_id = :c AND e.document_id <> :d AND e.status = 'valid' AND e.superseded_at IS NULL "
            "AND lower(btrim(e.payload -> 'invoice_no' ->> 'value')) = lower(btrim(:no))"
        ),
        {"c": client_id, "d": document_id, "no": invoice_no},
    )
    return [tuple(r) for r in rows]
