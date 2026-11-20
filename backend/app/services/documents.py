"""Documents: upload with hash duplicate check, private storage, text reading, voucher links (Phase 7, package A).

Services take a SQLAlchemy Connection and never commit; every change is audit-logged. The file is written to the private store only
after the checks pass, and a database failure after that rolls the row back (the stored file is named by its hash, so a leftover file
is harmless and is reused by the next identical upload).
"""

import json
from typing import Any

from sqlalchemy import Connection

from app import config
from app.ai import ocr
from app.ai.storage import PrivateStore
from app.db import repositories_documents as repo
from app.engine import doc_files
from app.engine.doc_types import DocType
from app.services import audit
from app.services.errors import ServiceError
from app.services.queries import require_client

IMAGE_PAGES = {"image/png": 1, "image/jpeg": 1}


def _document(conn: Connection, client_id: Any, doc_id: Any) -> Any:
    row = repo.get(conn, client_id, doc_id)
    if row is None:
        raise ServiceError("not_found", "Document not found.")
    return row


def register(
    conn: Connection, store: PrivateStore, client_id: Any, *, data: bytes, filename: str | None, doc_type: str,
    financial_year_id: Any = None, actor: str, max_bytes: int | None = None,
) -> dict:
    """D-01 file type by content and size, D-02 same file never stored twice. Returns the new document row as a dict."""
    require_client(conn, client_id)
    if doc_type not in {t.value for t in DocType}:
        raise ServiceError("invalid_doc_type", f"Unknown document type '{doc_type}'.")
    checked = doc_files.check_upload(data, doc_type, max_bytes if max_bytes is not None else config.max_upload_bytes())
    if not checked.ok:
        raise ServiceError("file_rejected", checked.reason or "The file was rejected.")
    if financial_year_id is not None and not repo.year_belongs(conn, client_id, financial_year_id):
        raise ServiceError("not_found", "Financial year not found for this client.")
    sha = doc_files.sha256_hex(data)
    existing = repo.find_by_hash(conn, client_id, sha)
    if existing is not None:
        raise ServiceError("duplicate_document", "This file was already uploaded for this client (D-02). The existing document is shown instead.",
                           {"document_id": existing[0]})
    page_count = ocr.pdf_page_count(data) if checked.content_type == "application/pdf" else IMAGE_PAGES.get(checked.content_type or "")
    key = doc_files.storage_key(client_id, sha, checked.extension or "bin")
    row = repo.insert(
        conn, client_id=client_id, financial_year_id=financial_year_id, doc_type=doc_type,
        original_filename=doc_files.clean_filename(filename), content_type=checked.content_type, size_bytes=len(data), sha256=sha,
        storage_key=key, page_count=page_count, uploaded_by=actor)
    store.save(key, data)
    audit.log(conn, audit.AuditEntry(client_id, actor, "document_uploaded", "document", row["id"], None,
                                     {"doc_type": doc_type, "sha256": sha, "size_bytes": len(data), "content_type": checked.content_type,
                                      "original_filename": row["original_filename"]}))
    return dict(row)


def get_document(conn: Connection, client_id: Any, doc_id: Any) -> dict:
    """The document with its page texts, extractions and queue item."""
    row = dict(_document(conn, client_id, doc_id))
    row["texts"] = [dict(r) for r in repo.texts_summary(conn, doc_id)]
    row["extractions"] = [dict(r) for r in repo.extractions_of(conn, doc_id)]
    row["linked_voucher_ids"] = repo.linked_vouchers(conn, doc_id)
    row["queue_item_id"] = repo.queue_item_of(conn, doc_id)
    return row


def list_documents(conn: Connection, client_id: Any, *, doc_type: str | None = None, status: str | None = None, q: str | None = None) -> list[dict]:
    require_client(conn, client_id)
    return [dict(r) for r in repo.list_documents(conn, client_id, doc_type, status, (q or "").strip() or None)]


def read_bytes(conn: Connection, store: PrivateStore, client_id: Any, doc_id: Any) -> bytes:
    return store.read(_document(conn, client_id, doc_id)["storage_key"])


def open_file(conn: Connection, store: PrivateStore, client_id: Any, doc_id: Any) -> tuple[Any, Any]:
    """(document row, chunk iterator) for a download. The client check is the lookup by (id, client_id)."""
    row = _document(conn, client_id, doc_id)
    return row, store.open(row["storage_key"])


def page_text(conn: Connection, client_id: Any, doc_id: Any, page_no: int, method: str | None = None) -> dict:
    _document(conn, client_id, doc_id)
    row = repo.get_page_text(conn, doc_id, page_no, method)
    if row is None:
        raise ServiceError("not_found", "No text has been read for that page yet. Use read-text first.")
    return dict(row)


def extract_text(conn: Connection, store: PrivateStore, client_id: Any, doc_id: Any, *, method: str = "auto", actor: str) -> list[dict]:
    """Read the text of every page. `auto`: the text layer of a PDF, and an OCR engine only for pages that have none.
    Re-reading adds nothing for a (page, method) that is already stored (the table is insert-only)."""
    doc = _document(conn, client_id, doc_id)
    if doc["content_type"] == "application/xml":
        raise ServiceError("invalid_method", "An XML document has no pages to read; it is read by the Tally import.")
    if method not in ("auto", *ocr.METHODS):
        raise ServiceError("invalid_method", f"Unknown method '{method}'. Use auto, pdf_text, tesseract or paddleocr.")
    pages = _read_pages(store.read(doc["storage_key"]), doc["content_type"], method)
    stored: dict[str, set[int]] = {}
    for page in pages:
        if page.method not in stored:
            stored[page.method] = repo.existing_text_pages(conn, doc_id, page.method)
        if page.page_no not in stored[page.method]:
            repo.insert_text(conn, client_id, doc_id, page, None if page.blocks is None else json.dumps(page.blocks))
    if doc["status"] == "uploaded":
        repo.set_status(conn, doc_id, "text_ready", len(pages))
    audit.log(conn, audit.AuditEntry(client_id, actor, "document_text_read", "document", doc_id, None,
                                     {"method": method, "pages": len(pages), "engines": sorted({p.method for p in pages})}))
    return [{"page_no": p.page_no, "method": p.method, "char_count": len(p.text), "mean_confidence": p.mean_confidence} for p in pages]


def _read_pages(data: bytes, content_type: str, method: str) -> list[ocr.PageText]:
    if method == "pdf_text":
        pages = ocr.PdfTextReader().read_pages(data, content_type)
        if not any(p.text for p in pages):
            raise ServiceError("no_text_layer", "This PDF has no text layer (it is a scan). Use an OCR method (tesseract or paddleocr).")
        return [p for p in pages if p.text]
    if method in ("tesseract", "paddleocr"):
        return ocr.ocr_for(method).read_pages(data, content_type)
    if content_type != "application/pdf":  # auto on an image
        return _ocr_any(data, content_type)
    direct = ocr.PdfTextReader().read_pages(data, content_type)
    if all(p.text for p in direct):
        return direct
    scanned = {p.page_no: p for p in _ocr_any(data, content_type)}
    return [p if p.text else scanned[p.page_no] for p in direct]


def _ocr_any(data: bytes, content_type: str) -> list[ocr.PageText]:
    """First usable OCR engine; a clear 'ocr_unavailable' when none is installed."""
    usable = ocr.available_ocr()
    if not usable:
        raise ServiceError(
            "ocr_unavailable",
            "This document has no readable text layer and no OCR engine is installed. Install Tesseract (the program, then "
            "pip install pytesseract Pillow pypdfium2) or PaddleOCR (pip install paddleocr paddlepaddle pypdfium2 Pillow), "
            "or type the invoice in by hand.")
    return ocr.ocr_for(usable[0]).read_pages(data, content_type)


def link_voucher(conn: Connection, client_id: Any, doc_id: Any, voucher_id: Any, *, link_kind: str = "supporting", actor: str) -> Any:
    _document(conn, client_id, doc_id)
    if link_kind not in ("source", "supporting"):
        raise ServiceError("invalid_link_kind", "link_kind must be 'source' or 'supporting'.")
    if repo.voucher_status(conn, client_id, voucher_id) is None:
        raise ServiceError("not_found", "Voucher not found.")
    row = repo.insert_link(conn, client_id, doc_id, voucher_id, link_kind, actor)
    if row is None:
        raise ServiceError("link_exists", "This document is already linked to that voucher.")
    audit.log(conn, audit.AuditEntry(client_id, actor, "document_linked", "document", doc_id, None,
                                     {"voucher_id": str(voucher_id), "link_kind": link_kind}))
    return row[0]


def unlink_voucher(conn: Connection, client_id: Any, doc_id: Any, voucher_id: Any, *, actor: str) -> None:
    _document(conn, client_id, doc_id)
    status = repo.voucher_status(conn, client_id, voucher_id)
    if status is None:
        raise ServiceError("not_found", "Voucher not found.")
    if status != "draft":
        raise ServiceError("voucher_not_draft", "The link of an approved, posted or reversed voucher cannot be removed.")
    row = repo.delete_link(conn, doc_id, voucher_id)
    if row is None:
        raise ServiceError("not_found", "This document is not linked to that voucher.")
    audit.log(conn, audit.AuditEntry(client_id, actor, "document_unlinked", "document", doc_id,
                                     {"voucher_id": str(voucher_id), "link_kind": row[1]}, None))
