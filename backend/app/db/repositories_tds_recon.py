"""SQL for 26AS / AIS imports, their rows, links and the books read (Phase 4, package E).
SQL only: no rules, no maths. Every function takes a SQLAlchemy Connection owned by the caller.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.tds_recon import BookEntry, RecLink, Row26
from app.importers.form26as import ParsedRow

_ROW_COLUMNS = (
    "id, row_no, deductor_tan, deductor_name, deductee_pan, section_ref, transaction_date, booking_date, booking_status, "
    "amount_paid, tax_deducted, tax_deposited"
)


def client_tan(conn: Connection, client_id: object) -> str | None:
    return conn.execute(text("SELECT tan FROM clients WHERE id = :c"), {"c": client_id}).scalar()


def import_id_by_hash(conn: Connection, client_id: object, file_hash: str) -> uuid.UUID | None:
    return conn.execute(
        text("SELECT id FROM tds_26as_imports WHERE client_id = :c AND file_hash = :h"), {"c": client_id, "h": file_hash}
    ).scalar()


def insert_import(conn: Connection, *, client_id, fy_id, source: str, side: str, file_name: str, file_hash: str, row_count: int,
                  actor: str) -> uuid.UUID:
    return conn.execute(
        text(
            "INSERT INTO tds_26as_imports (client_id, financial_year_id, source, side, file_name, file_hash, row_count, imported_by) "
            "VALUES (:c, :f, :s, :d, :n, :h, :r, :a) RETURNING id"
        ),
        {"c": client_id, "f": fy_id, "s": source, "d": side, "n": file_name, "h": file_hash, "r": row_count, "a": actor},
    ).scalar_one()


def insert_rows(conn: Connection, client_id: object, import_id: object, rows: list[ParsedRow]) -> None:
    if not rows:
        return
    conn.execute(
        text(
            "INSERT INTO tds_26as_rows (client_id, import_id, row_no, deductor_tan, deductor_name, deductee_pan, section_ref, "
            "transaction_date, booking_date, booking_status, amount_paid, tax_deducted, tax_deposited) VALUES (:c, :i, :row_no, "
            ":deductor_tan, :deductor_name, :deductee_pan, :section_ref, :transaction_date, :booking_date, :booking_status, "
            ":amount_paid, :tax_deducted, :tax_deposited)"
        ),
        [{"c": client_id, "i": import_id, **{k: getattr(r, k) for k in r.__dataclass_fields__}} for r in rows],
    )


def import_totals(conn: Connection, client_id: object, import_id: object) -> dict:
    row = conn.execute(
        text(
            "SELECT COALESCE(sum(amount_paid), 0) AS amount_paid, COALESCE(sum(tax_deducted), 0) AS tax_deducted, "
            "COALESCE(sum(tax_deposited), 0) AS tax_deposited FROM tds_26as_rows WHERE import_id = :i AND client_id = :c"
        ),
        {"i": import_id, "c": client_id},
    ).mappings().one()
    return dict(row)


def list_imports(conn: Connection, client_id: object, fy_id: object | None) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, financial_year_id, source, side, file_name, row_count, imported_by, imported_at FROM tds_26as_imports "
            "WHERE client_id = :c AND (CAST(:f AS uuid) IS NULL OR financial_year_id = :f) ORDER BY imported_at DESC, id"
        ),
        {"c": client_id, "f": fy_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_import(conn: Connection, client_id: object, import_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT id, financial_year_id, source, side, file_name, row_count FROM tds_26as_imports WHERE id = :i AND client_id = :c"),
        {"i": import_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def latest_import(conn: Connection, client_id: object, fy_id: object) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, financial_year_id, source, side, file_name, row_count FROM tds_26as_imports "
            "WHERE client_id = :c AND financial_year_id = :f ORDER BY imported_at DESC, id LIMIT 1"
        ),
        {"c": client_id, "f": fy_id},
    ).mappings().first()
    return None if row is None else dict(row)


def list_rows(conn: Connection, client_id: object, import_id: object) -> list[dict]:
    rows = conn.execute(
        text(f"SELECT {_ROW_COLUMNS} FROM tds_26as_rows WHERE import_id = :i AND client_id = :c ORDER BY row_no"),
        {"i": import_id, "c": client_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def rows26(conn: Connection, client_id: object, import_id: object) -> list[Row26]:
    return [
        Row26(r["id"], r["row_no"], r["deductor_tan"], r["deductor_name"], r["deductee_pan"], r["section_ref"],
              r["transaction_date"], r["amount_paid"], r["tax_deducted"], r["tax_deposited"])
        for r in list_rows(conn, client_id, import_id)
    ]


def section_rows(conn: Connection) -> list[dict]:
    """The old <-> new section table (rule data): printed section -> nature, with the status and source of each row."""
    rows = conn.execute(
        text("SELECT nature_key, section_ref, verification_status, source_reference FROM tds_section_refs ORDER BY nature_key, act")
    ).mappings().all()
    return [dict(r) for r in rows]


def known_pans(conn: Connection, client_id: object) -> set[str]:
    rows = conn.execute(text("SELECT pan FROM tds_deductees WHERE client_id = :c AND pan IS NOT NULL"), {"c": client_id}).all()
    return {r[0] for r in rows}


def deduction_items(conn: Connection, client_id: object, fy_id: object) -> list[BookEntry]:
    """Deduction items of POSTED vouchers (a reversed voucher drops out) that carry tax; the register of the books."""
    rows = conn.execute(
        text(
            "SELECT i.id, i.voucher_id, v.voucher_number, d.pan, i.nature_key, l.name, i.section_ref, i.event_date, "
            "i.payment_amount, i.tds_amount FROM tds_voucher_items i "
            "JOIN vouchers v ON v.id = i.voucher_id AND v.client_id = i.client_id "
            "JOIN ledgers l ON l.id = i.deductee_ledger_id AND l.client_id = i.client_id "
            "LEFT JOIN tds_deductees d ON d.ledger_id = i.deductee_ledger_id AND d.client_id = i.client_id "
            "WHERE i.client_id = :c AND i.financial_year_id = :f AND v.status = 'posted' AND i.tds_amount > 0 "
            "ORDER BY i.event_date, i.id"
        ),
        {"c": client_id, "f": fy_id},
    ).mappings().all()
    return [
        BookEntry(r["id"], r["pan"], r["nature_key"], r["name"], r["section_ref"], r["event_date"], r["payment_amount"],
                  r["tds_amount"], r["voucher_id"], r["voucher_number"])
        for r in rows
    ]


def receivable_vouchers(conn: Connection, client_id: object, fy_id: object) -> list[BookEntry]:
    """Posted vouchers that debited a TDS / TCS receivable ledger (role map); amount = the debit to those ledgers."""
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_number, v.voucher_date, sum(vl.debit) AS tax FROM vouchers v "
            "JOIN voucher_lines vl ON vl.voucher_id = v.id AND vl.client_id = v.client_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :f AND v.status = 'posted' AND vl.debit > 0 "
            "AND vl.ledger_id IN (SELECT ledger_id FROM tds_ledger_roles WHERE client_id = :c AND role IN ('tds_receivable', 'tcs_receivable')) "
            "GROUP BY v.id, v.voucher_number, v.voucher_date ORDER BY v.voucher_date, v.id"
        ),
        {"c": client_id, "f": fy_id},
    ).mappings().all()
    return [BookEntry(r["id"], None, None, None, None, r["voucher_date"], Decimal("0.00"), r["tax"], r["id"], r["voucher_number"]) for r in rows]


# ------------------------------------------------------------------------------------------------------ links


def list_links(conn: Connection, client_id: object, import_id: object) -> list[RecLink]:
    rows = conn.execute(
        text(
            "SELECT k.id, k.row_id, COALESCE(k.item_id, k.voucher_id), k.link_kind, k.note FROM tds_26as_links k "
            "JOIN tds_26as_rows r ON r.id = k.row_id WHERE k.client_id = :c AND r.import_id = :i ORDER BY k.created_at, k.id"
        ),
        {"c": client_id, "i": import_id},
    ).all()
    return [RecLink(*r) for r in rows]


def row_for_link(conn: Connection, client_id: object, row_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT r.id, i.side, i.financial_year_id FROM tds_26as_rows r JOIN tds_26as_imports i ON i.id = r.import_id "
             "WHERE r.id = :r AND r.client_id = :c"),
        {"r": row_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def item_for_link(conn: Connection, client_id: object, item_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT i.id, i.financial_year_id, v.status FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id "
             "WHERE i.id = :i AND i.client_id = :c"),
        {"i": item_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def voucher_for_link(conn: Connection, client_id: object, voucher_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT id, financial_year_id, status FROM vouchers WHERE id = :v AND client_id = :c"),
        {"v": voucher_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def link_exists(conn: Connection, row_id: object, item_id: object, voucher_id: object) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM tds_26as_links WHERE row_id = :r OR (item_id IS NOT NULL AND item_id = :i) "
             "OR (voucher_id IS NOT NULL AND voucher_id = :v) LIMIT 1"),
        {"r": row_id, "i": item_id, "v": voucher_id},
    ).first())


def insert_link(conn: Connection, *, client_id, row_id, item_id, voucher_id, link_kind: str, note: str, actor: str) -> uuid.UUID:
    return conn.execute(
        text("INSERT INTO tds_26as_links (client_id, row_id, item_id, voucher_id, link_kind, note, created_by) "
             "VALUES (:c, :r, :i, :v, :k, :n, :a) RETURNING id"),
        {"c": client_id, "r": row_id, "i": item_id, "v": voucher_id, "k": link_kind, "n": note, "a": actor},
    ).scalar_one()


def get_link(conn: Connection, client_id: object, link_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT id, row_id, item_id, voucher_id, link_kind, note FROM tds_26as_links WHERE id = :l AND client_id = :c"),
        {"l": link_id, "c": client_id},
    ).mappings().first()
    return None if row is None else dict(row)


def delete_link(conn: Connection, client_id: object, link_id: object) -> None:
    conn.execute(text("DELETE FROM tds_26as_links WHERE id = :l AND client_id = :c"), {"l": link_id, "c": client_id})


def fy_dates(conn: Connection, client_id: object, fy_id: object) -> tuple[date, date] | None:
    row = conn.execute(
        text("SELECT start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"), {"f": fy_id, "c": client_id}
    ).first()
    return None if row is None else (row[0], row[1])
