"""SQL for documents, their page texts and voucher links (Phase 7, package A). No rules here."""

from typing import Any

from sqlalchemy import Connection, text

DOC_COLUMNS = ("id, client_id, financial_year_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, "
               "page_count, status, status_note, uploaded_by, uploaded_at")


def find_by_hash(conn: Connection, client_id: Any, sha256: str) -> Any:
    return conn.execute(text("SELECT id FROM documents WHERE client_id = :c AND sha256 = :h"), {"c": client_id, "h": sha256}).first()


def year_belongs(conn: Connection, client_id: Any, fy_id: Any) -> bool:
    return conn.execute(text("SELECT 1 FROM financial_years WHERE id = :f AND client_id = :c"), {"f": fy_id, "c": client_id}).first() is not None


def insert(conn: Connection, **values: Any) -> Any:
    return conn.execute(
        text(
            "INSERT INTO documents (client_id, financial_year_id, doc_type, original_filename, content_type, size_bytes, sha256, "
            "storage_key, page_count, uploaded_by) VALUES (:client_id, :financial_year_id, :doc_type, :original_filename, :content_type, "
            "CAST(:size_bytes AS bigint), :sha256, :storage_key, :page_count, :uploaded_by) RETURNING " + DOC_COLUMNS
        ),
        values,
    ).mappings().one()


def get(conn: Connection, client_id: Any, doc_id: Any) -> Any:
    return conn.execute(text(f"SELECT {DOC_COLUMNS} FROM documents WHERE id = :d AND client_id = :c"), {"d": doc_id, "c": client_id}).mappings().first()


def list_documents(conn: Connection, client_id: Any, doc_type: str | None, status: str | None, q: str | None) -> list[Any]:
    return list(conn.execute(
        text(
            "SELECT d.id, d.doc_type, d.original_filename, d.size_bytes, d.status, d.uploaded_by, d.uploaded_at, "
            "COALESCE((SELECT array_agg(dv.voucher_id ORDER BY dv.linked_at) FROM document_vouchers dv WHERE dv.document_id = d.id), "
            "ARRAY[]::uuid[]) AS linked_voucher_ids "
            "FROM documents d WHERE d.client_id = :c AND (CAST(:t AS text) IS NULL OR d.doc_type = :t) "
            "AND (CAST(:s AS text) IS NULL OR d.status = :s) "
            "AND (CAST(:q AS text) IS NULL OR d.original_filename ILIKE '%' || :q || '%') ORDER BY d.uploaded_at DESC, d.id"
        ),
        {"c": client_id, "t": doc_type, "s": status, "q": q},
    ).mappings())


def texts_summary(conn: Connection, doc_id: Any) -> list[Any]:
    return list(conn.execute(
        text("SELECT page_no, method, engine_version, mean_confidence, char_length(text) AS char_count FROM document_texts "
             "WHERE document_id = :d ORDER BY page_no, method"), {"d": doc_id}).mappings())


def get_page_text(conn: Connection, doc_id: Any, page_no: int, method: str | None) -> Any:
    return conn.execute(
        text("SELECT page_no, method, text, blocks FROM document_texts WHERE document_id = :d AND page_no = :p "
             "AND (CAST(:m AS text) IS NULL OR method = :m) ORDER BY created_at DESC LIMIT 1"),
        {"d": doc_id, "p": page_no, "m": method}).mappings().first()


def existing_text_pages(conn: Connection, doc_id: Any, method: str) -> set[int]:
    return {r[0] for r in conn.execute(text("SELECT page_no FROM document_texts WHERE document_id = :d AND method = :m"), {"d": doc_id, "m": method})}


def insert_text(conn: Connection, client_id: Any, doc_id: Any, page: Any, blocks_json: str | None) -> None:
    conn.execute(
        text("INSERT INTO document_texts (client_id, document_id, page_no, method, engine_version, text, blocks, mean_confidence) "
             "VALUES (:c, :d, :p, :m, :v, :t, CAST(:b AS jsonb), :conf) ON CONFLICT (document_id, page_no, method) DO NOTHING"),
        {"c": client_id, "d": doc_id, "p": page.page_no, "m": page.method, "v": page.engine_version, "t": page.text, "b": blocks_json,
         "conf": page.mean_confidence})


def set_status(conn: Connection, doc_id: Any, status: str, page_count: int | None) -> None:
    conn.execute(text("UPDATE documents SET status = :s, page_count = COALESCE(page_count, :n) WHERE id = :d"), {"s": status, "n": page_count, "d": doc_id})


def extractions_of(conn: Connection, doc_id: Any) -> list[Any]:
    return list(conn.execute(
        text("SELECT id, version, source, status, created_at, superseded_at IS NOT NULL AS superseded FROM extractions "
             "WHERE document_id = :d ORDER BY version"), {"d": doc_id}).mappings())


def queue_item_of(conn: Connection, doc_id: Any) -> Any:
    row = conn.execute(
        text("SELECT id FROM approval_queue_items WHERE document_id = :d AND status IN ('pending', 'in_review', 'accepted') "
             "ORDER BY created_at DESC LIMIT 1"), {"d": doc_id}).first()
    return None if row is None else row[0]


def voucher_status(conn: Connection, client_id: Any, voucher_id: Any) -> str | None:
    row = conn.execute(text("SELECT status FROM vouchers WHERE id = :v AND client_id = :c"), {"v": voucher_id, "c": client_id}).first()
    return None if row is None else row[0]


def insert_link(conn: Connection, client_id: Any, doc_id: Any, voucher_id: Any, kind: str, actor: str) -> Any:
    return conn.execute(
        text("INSERT INTO document_vouchers (client_id, document_id, voucher_id, link_kind, linked_by) VALUES (:c, :d, :v, :k, :a) "
             "ON CONFLICT (document_id, voucher_id) DO NOTHING RETURNING id"),
        {"c": client_id, "d": doc_id, "v": voucher_id, "k": kind, "a": actor}).first()


def delete_link(conn: Connection, doc_id: Any, voucher_id: Any) -> Any:
    return conn.execute(text("DELETE FROM document_vouchers WHERE document_id = :d AND voucher_id = :v RETURNING id, link_kind"),
                        {"d": doc_id, "v": voucher_id}).first()


def linked_vouchers(conn: Connection, doc_id: Any) -> list[Any]:
    return [r[0] for r in conn.execute(text("SELECT voucher_id FROM document_vouchers WHERE document_id = :d ORDER BY linked_at"), {"d": doc_id})]
