"""SQL for GSTR-2B imports, their documents, books <-> 2B links and the purchase register read (Phase 3, package D).
SQL only: no rules, no maths. Every function takes a SQLAlchemy Connection owned by the caller.
"""

import uuid
from datetime import date

from sqlalchemy import Connection, text

from app.engine.gst_recon import BookDoc, Doc2B, Link
from app.importers.gstr2b import ParsedDocument

# the register of the books that can appear in a GSTR-2B: posted purchase / debit-note vouchers of the registration whose
# supplier has a GSTIN and whose document is a tax invoice (bills of supply and composition suppliers are not in a 2B)
_BOOKS = text(
    """
    SELECT v.id, v.voucher_number, g.counterparty_gstin, COALESCE(v.reference_no, '') AS doc_no, g.invoice_date, v.voucher_type,
           COALESCE(sum(i.taxable_value), 0) AS taxable_value, COALESCE(sum(i.igst), 0) AS igst,
           COALESCE(sum(i.cgst), 0) AS cgst, COALESCE(sum(i.sgst), 0) AS sgst, COALESCE(sum(i.cess), 0) AS cess,
           (SELECT string_agg(DISTINCT e.status, ',') FROM itc_entries e WHERE e.voucher_id = v.id) AS itc_status
      FROM vouchers v
      JOIN voucher_gst g ON g.voucher_id = v.id AND g.client_id = v.client_id
      LEFT JOIN voucher_item_lines i ON i.voucher_id = v.id
     WHERE v.client_id = :client_id AND g.gst_registration_id = :registration_id AND v.status = 'posted'
       AND v.voucher_type IN ('purchase', 'debit_note') AND g.document_kind = 'tax_invoice'
       AND g.counterparty_gstin IS NOT NULL AND g.supply_category <> 'composition_supplier'
       AND v.voucher_date BETWEEN :start AND :end
     GROUP BY v.id, v.voucher_number, g.counterparty_gstin, v.reference_no, g.invoice_date, v.voucher_type
    """
)

_DOC_COLUMNS = (
    "id, supplier_gstin, doc_no, doc_date, taxable_value, igst, cgst, sgst, cess, doc_type, itc_available, ims_status"
)


def registration_gstin(conn: Connection, client_id: object, registration_id: object) -> str | None:
    return conn.execute(
        text("SELECT gstin FROM gst_registrations WHERE id = :r AND client_id = :c"), {"r": registration_id, "c": client_id}
    ).scalar()


def import_id_by_hash(conn: Connection, client_id: object, file_hash: str) -> uuid.UUID | None:
    return conn.execute(
        text("SELECT id FROM gstr2b_imports WHERE client_id = :c AND file_hash = :h"), {"c": client_id, "h": file_hash}
    ).scalar()


def insert_import(conn: Connection, *, client_id, registration_id, kind: str, period: date, source_format: str,
                  file_name: str, file_hash: str, generated_on: date | None, document_count: int, actor: str) -> uuid.UUID:
    return conn.execute(
        text(
            "INSERT INTO gstr2b_imports (client_id, gst_registration_id, kind, return_period, source_format, file_name, "
            "file_hash, generated_on, document_count, created_by) VALUES (:c, :r, :k, :p, :f, :n, :h, :g, :d, :a) RETURNING id"
        ),
        {"c": client_id, "r": registration_id, "k": kind, "p": period, "f": source_format, "n": file_name, "h": file_hash,
         "g": generated_on, "d": document_count, "a": actor},
    ).scalar_one()


def insert_documents(conn: Connection, client_id: object, import_id: object, documents: list[ParsedDocument]) -> None:
    if not documents:
        return
    conn.execute(
        text(
            "INSERT INTO gstr2b_documents (client_id, import_id, row_no, section, supplier_gstin, supplier_name, doc_type, doc_no, "
            "doc_date, place_of_supply, reverse_charge, taxable_value, igst, cgst, sgst, cess, doc_value, itc_available, "
            "itc_reason, supplier_return_period, supplier_filing_date) VALUES (:c, :i, :row_no, :section, :supplier_gstin, "
            ":supplier_name, :doc_type, :doc_no, :doc_date, :place_of_supply, :reverse_charge, :taxable_value, :igst, :cgst, "
            ":sgst, :cess, :doc_value, :itc_available, :itc_reason, :supplier_return_period, :supplier_filing_date)"
        ),
        [{"c": client_id, "i": import_id, **{k: getattr(d, k) for k in d.__dataclass_fields__}} for d in documents],
    )


def list_imports(conn: Connection, client_id: object, registration_id: object | None) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, kind, return_period, file_name, generated_on, document_count, created_at, gst_registration_id "
            "FROM gstr2b_imports WHERE client_id = :c AND (CAST(:r AS uuid) IS NULL OR gst_registration_id = :r) "
            "ORDER BY return_period DESC, created_at DESC"
        ),
        {"c": client_id, "r": registration_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_import(conn: Connection, client_id: object, import_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT id, kind, return_period, gst_registration_id FROM gstr2b_imports WHERE id = :i AND client_id = :c"),
        {"i": import_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def list_documents(conn: Connection, client_id: object, import_id: object) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, section, supplier_gstin, supplier_name, doc_type, doc_no, doc_date, taxable_value, igst, cgst, sgst, "
            "cess, itc_available, itc_reason, ims_status, supplier_return_period FROM gstr2b_documents "
            "WHERE import_id = :i AND client_id = :c ORDER BY row_no"
        ),
        {"i": import_id, "c": client_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def import_totals(conn: Connection, client_id: object, import_id: object) -> dict:
    row = conn.execute(
        text(
            "SELECT COALESCE(sum(taxable_value), 0) AS taxable_value, COALESCE(sum(igst), 0) AS igst, COALESCE(sum(cgst), 0) AS cgst, "
            "COALESCE(sum(sgst), 0) AS sgst, COALESCE(sum(cess), 0) AS cess FROM gstr2b_documents "
            "WHERE import_id = :i AND client_id = :c"
        ),
        {"i": import_id, "c": client_id},
    ).mappings().one()
    return dict(row)


def _doc2b(row) -> Doc2B:
    return Doc2B(row["id"], row["supplier_gstin"], row["doc_no"], row["doc_date"], row["taxable_value"], row["igst"], row["cgst"],
                 row["sgst"], row["cess"], row["doc_type"], row["itc_available"], row["ims_status"])


def latest_imports_by_period(conn: Connection, client_id: object, registration_id: object) -> dict[date, uuid.UUID]:
    """The newest GSTR-2B import of each period (a later generation supersedes an older one, G-41)."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (return_period) return_period, id FROM gstr2b_imports "
            "WHERE client_id = :c AND gst_registration_id = :r AND kind = 'gstr2b' ORDER BY return_period, created_at DESC, id"
        ),
        {"c": client_id, "r": registration_id},
    ).all()
    return {r[0]: r[1] for r in rows}


def documents_of(conn: Connection, client_id: object, import_ids: list[object]) -> list[Doc2B]:
    if not import_ids:
        return []
    rows = conn.execute(
        text(f"SELECT {_DOC_COLUMNS} FROM gstr2b_documents WHERE client_id = :c AND import_id = ANY(:ids) ORDER BY import_id, row_no"),
        {"c": client_id, "ids": list(import_ids)},
    ).mappings().all()
    return [_doc2b(r) for r in rows]


def book_docs(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[BookDoc]:
    rows = conn.execute(_BOOKS, {"client_id": client_id, "registration_id": registration_id, "start": start, "end": end}).mappings().all()
    return [
        BookDoc(r["id"], r["voucher_number"], r["counterparty_gstin"], r["doc_no"], r["invoice_date"], r["taxable_value"], r["igst"],
                r["cgst"], r["sgst"], r["cess"], "credit_note" if r["voucher_type"] == "debit_note" else "invoice", r["itc_status"])
        for r in rows
    ]


# ------------------------------------------------------------------------------------------------------ links


def list_links(conn: Connection, client_id: object, registration_id: object) -> list[Link]:
    rows = conn.execute(
        text(
            "SELECT id, document_id, voucher_id, link_kind, note FROM gstr2b_links "
            "WHERE client_id = :c AND gst_registration_id = :r ORDER BY created_at, id"
        ),
        {"c": client_id, "r": registration_id},
    ).all()
    return [Link(*r) for r in rows]


def document_for_link(conn: Connection, client_id: object, document_id: object) -> dict | None:
    row = conn.execute(
        text(
            "SELECT d.id, i.gst_registration_id FROM gstr2b_documents d JOIN gstr2b_imports i ON i.id = d.import_id "
            "WHERE d.id = :d AND d.client_id = :c"
        ),
        {"d": document_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def voucher_for_link(conn: Connection, client_id: object, voucher_id: object) -> dict | None:
    row = conn.execute(
        text(
            "SELECT v.id, v.status, v.voucher_type, g.gst_registration_id FROM vouchers v "
            "LEFT JOIN voucher_gst g ON g.voucher_id = v.id WHERE v.id = :v AND v.client_id = :c"
        ),
        {"v": voucher_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def link_exists(conn: Connection, document_id: object, voucher_id: object) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM gstr2b_links WHERE document_id = :d OR voucher_id = :v LIMIT 1"), {"d": document_id, "v": voucher_id}
    ).first())


def insert_link(conn: Connection, *, client_id, registration_id, document_id, voucher_id, link_kind: str, note: str,
                actor: str) -> uuid.UUID:
    return conn.execute(
        text(
            "INSERT INTO gstr2b_links (client_id, gst_registration_id, document_id, voucher_id, link_kind, note, created_by) "
            "VALUES (:c, :r, :d, :v, :k, :n, :a) RETURNING id"
        ),
        {"c": client_id, "r": registration_id, "d": document_id, "v": voucher_id, "k": link_kind, "n": note, "a": actor},
    ).scalar_one()


def get_link(conn: Connection, client_id: object, link_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT id, document_id, voucher_id, link_kind, note FROM gstr2b_links WHERE id = :i AND client_id = :c"),
        {"i": link_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def delete_link(conn: Connection, client_id: object, link_id: object) -> None:
    conn.execute(text("DELETE FROM gstr2b_links WHERE id = :i AND client_id = :c"), {"i": link_id, "c": client_id})
