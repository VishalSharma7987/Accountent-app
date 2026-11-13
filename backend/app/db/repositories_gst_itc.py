"""SQL for the ITC register (package C): entries, events, reversals, the rule rows it needs, GST ledger roles.

Plain functions over a SQLAlchemy Connection; no business rules here (those are in engine/gst_itc.py and services/gst_itc.py).
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.gst_types import BlockedRule, ItcCondition

HEADS = ("igst", "cgst", "sgst", "cess")

_ENTRY_SELECT = (
    "SELECT e.*, v.voucher_number, v.status AS voucher_status, v.voucher_date, l.name AS supplier_name, "
    "i.itc_category_key, i.itc_exception_claimed, i.itc_exception_note "
    "FROM itc_entries e JOIN vouchers v ON v.id = e.voucher_id "
    "JOIN voucher_item_lines i ON i.voucher_id = e.voucher_id AND i.item_line_no = e.item_line_no "
    "LEFT JOIN ledgers l ON l.id = e.supplier_ledger_id "
)


def _row(r) -> dict[str, Any]:
    return dict(r._mapping)


# ---- rule rows ---------------------------------------------------------------------------------------------


def blocked_rules(conn: Connection) -> list[BlockedRule]:
    """Every Section 17(5) rule row (the engine picks the one in force on the invoice date)."""
    rows = conn.execute(
        text(
            "SELECT category_key, clause_ref, description, has_exception, exception_text, effective_from, effective_to, "
            "source_reference, verification_status FROM gst_blocked_credit_rules"
        )
    )
    return [BlockedRule(*r) for r in rows]


def itc_condition(conn: Connection, key: str, on: date) -> ItcCondition | None:
    r = conn.execute(
        text(
            "SELECT condition_key, clause_ref, description, evidence_field, parameter_days, deadline_month, deadline_day, "
            "effective_from, effective_to, source_reference, verification_status FROM gst_itc_conditions "
            "WHERE condition_key = :k AND effective_from <= :d AND (effective_to IS NULL OR effective_to >= :d) "
            "ORDER BY effective_from DESC LIMIT 1"
        ),
        {"k": key, "d": on},
    ).first()
    return None if r is None else ItcCondition(*r)


def ledger_roles(conn: Connection, client_id: object, registration_id: object) -> dict[str, object]:
    rows = conn.execute(
        text("SELECT role, ledger_id FROM gst_ledger_roles WHERE client_id = :c AND registration_id = :r"),
        {"c": client_id, "r": registration_id},
    )
    return {r[0]: r[1] for r in rows}


# ---- vouchers (read only) ----------------------------------------------------------------------------------


def voucher_header(conn: Connection, voucher_id: object) -> dict[str, Any] | None:
    r = conn.execute(
        text(
            "SELECT v.id, v.client_id, v.voucher_type, v.voucher_date, v.reference_no, v.party_ledger_id, v.status, "
            "g.gst_registration_id, g.invoice_date, g.counterparty_gstin, g.original_invoice_no "
            "FROM vouchers v LEFT JOIN voucher_gst g ON g.voucher_id = v.id WHERE v.id = :v"
        ),
        {"v": voucher_id},
    ).first()
    return None if r is None else _row(r)


def taxed_item_lines(conn: Connection, voucher_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT item_line_no, igst, cgst, sgst, cess, rcm, itc_category_key, itc_exception_claimed, itc_exception_note "
            "FROM voucher_item_lines "
            "WHERE voucher_id = :v AND (igst + cgst + sgst + cess) > 0 ORDER BY item_line_no"
        ),
        {"v": voucher_id},
    )
    return [_row(r) for r in rows]


def voucher_debit_by_ledger(conn: Connection, voucher_id: object) -> dict[object, Decimal]:
    rows = conn.execute(
        text("SELECT ledger_id, sum(debit) FROM voucher_lines WHERE voucher_id = :v GROUP BY ledger_id"), {"v": voucher_id}
    )
    return {r[0]: Decimal(r[1]).quantize(Decimal("0.01")) for r in rows}


# ---- entries -----------------------------------------------------------------------------------------------


def insert_entry(conn: Connection, values: dict[str, Any]) -> object:
    return conn.execute(
        text(
            "INSERT INTO itc_entries (client_id, gst_registration_id, voucher_id, item_line_no, doc_type, source, "
            "supplier_ledger_id, supplier_gstin, supplier_invoice_no, supplier_invoice_date, igst, cgst, sgst, cess, "
            "status, pending_reason, blocked_category_key, claim_deadline) "
            "VALUES (:client_id, :gst_registration_id, :voucher_id, :item_line_no, :doc_type, :source, :supplier_ledger_id, "
            ":supplier_gstin, :supplier_invoice_no, :supplier_invoice_date, :igst, :cgst, :sgst, :cess, :status, "
            ":pending_reason, :blocked_category_key, :claim_deadline) "
            "ON CONFLICT (voucher_id, item_line_no) DO NOTHING RETURNING id"
        ),
        values,
    ).scalar()


def get_entry(conn: Connection, client_id: object, entry_id: object, *, lock: bool = False) -> dict[str, Any] | None:
    # FOR UPDATE cannot be applied to the outer-joined ledgers row, so lock the entry row first
    if lock:
        conn.execute(text("SELECT 1 FROM itc_entries WHERE id = :i AND client_id = :c FOR UPDATE"), {"i": entry_id, "c": client_id})
    r = conn.execute(text(_ENTRY_SELECT + "WHERE e.id = :i AND e.client_id = :c"), {"i": entry_id, "c": client_id}).first()
    return None if r is None else _row(r)


def entries_of_voucher(conn: Connection, voucher_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(text(_ENTRY_SELECT + "WHERE e.voucher_id = :v ORDER BY e.item_line_no"), {"v": voucher_id})
    return [_row(r) for r in rows]


def list_entries(
    conn: Connection, client_id: object, *, registration_id=None, status=None, period=None, supplier_ledger_id=None,
    as_on: date | None = None,
) -> list[dict[str, Any]]:
    sql = _ENTRY_SELECT + "WHERE e.client_id = :c AND v.status IN ('posted', 'reversed')"
    p: dict[str, Any] = {"c": client_id}
    for column, name, value in (
        ("e.gst_registration_id", "r", registration_id), ("e.status", "s", status),
        ("e.claimed_in_period", "p", period), ("e.supplier_ledger_id", "l", supplier_ledger_id),
    ):
        if value is not None:
            sql += f" AND {column} = :{name}"
            p[name] = value
    if as_on is not None:
        sql += " AND v.voucher_date <= :a"
        p["a"] = as_on
    rows = conn.execute(text(sql + " ORDER BY e.supplier_invoice_date, e.voucher_id, e.item_line_no"), p)
    return [_row(r) for r in rows]


def update_entry(conn: Connection, entry_id: object, changes: dict[str, Any]) -> None:
    allowed = {
        "status", "pending_reason", "blocked_category_key", "tax_document_held", "goods_services_received", "received_date",
        "supplier_tax_paid", "evidence_note", "evidence_by", "evidence_at", "claim_deadline", "claimed_in_period",
    }
    if not changes or not set(changes) <= allowed:
        raise ValueError(f"cannot update columns {sorted(set(changes) - allowed)}")
    sets = ", ".join(f"{k} = :{k}" for k in changes)
    conn.execute(text(f"UPDATE itc_entries SET {sets}, updated_at = now() WHERE id = :_id"), {**changes, "_id": entry_id})


def insert_event(conn: Connection, client_id: object, entry_id: object, from_status: str | None, to_status: str, reason: str, actor: str) -> None:
    conn.execute(
        text(
            "INSERT INTO itc_status_events (client_id, itc_entry_id, from_status, to_status, reason, actor, created_at) "
            "VALUES (:c, :e, :f, :t, :r, :a, clock_timestamp())"
        ),
        {"c": client_id, "e": entry_id, "f": from_status, "t": to_status, "r": reason, "a": actor},
    )


def events_of(conn: Connection, client_id: object, entry_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT from_status, to_status, reason, actor, created_at FROM itc_status_events "
            "WHERE client_id = :c AND itc_entry_id = :e ORDER BY created_at, id"
        ),
        {"c": client_id, "e": entry_id},
    )
    return [_row(r) for r in rows]


# ---- reversals ---------------------------------------------------------------------------------------------


def insert_reversal(conn: Connection, values: dict[str, Any]) -> object:
    return conn.execute(
        text(
            "INSERT INTO itc_reversals (client_id, itc_entry_id, reason, as_on_date, unpaid_fraction_note, igst, cgst, sgst, "
            "cess, reversal_voucher_id, status, created_by) VALUES (:client_id, :itc_entry_id, :reason, :as_on_date, "
            ":unpaid_fraction_note, :igst, :cgst, :sgst, :cess, :reversal_voucher_id, 'drafted', :created_by) RETURNING id"
        ),
        values,
    ).scalar()


def get_reversal(conn: Connection, client_id: object, reversal_id: object, *, lock: bool = False) -> dict[str, Any] | None:
    r = conn.execute(
        text("SELECT * FROM itc_reversals WHERE id = :i AND client_id = :c" + (" FOR UPDATE" if lock else "")),
        {"i": reversal_id, "c": client_id},
    ).first()
    return None if r is None else _row(r)


def reversals_of_entry(conn: Connection, entry_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(text("SELECT * FROM itc_reversals WHERE itc_entry_id = :e ORDER BY created_at, id"), {"e": entry_id})
    return [_row(r) for r in rows]


def reversals_for_entries(conn: Connection, entry_ids: list[object]) -> dict[object, list[dict[str, Any]]]:
    out: dict[object, list[dict[str, Any]]] = {}
    if entry_ids:
        rows = conn.execute(text("SELECT * FROM itc_reversals WHERE itc_entry_id = ANY(:ids) ORDER BY created_at, id"), {"ids": entry_ids})
        for r in rows:
            d = _row(r)
            out.setdefault(d["itc_entry_id"], []).append(d)
    return out


def list_reversals(conn: Connection, client_id: object, status: str | None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM itc_reversals WHERE client_id = :c"
    p: dict[str, Any] = {"c": client_id}
    if status is not None:
        sql += " AND status = :s"
        p["s"] = status
    return [_row(r) for r in conn.execute(text(sql + " ORDER BY created_at, id"), p)]


def reversal_by_voucher(conn: Connection, voucher_id: object) -> dict[str, Any] | None:
    r = conn.execute(
        text("SELECT * FROM itc_reversals WHERE reversal_voucher_id = :v OR reclaim_voucher_id = :v FOR UPDATE"), {"v": voucher_id}
    ).first()
    return None if r is None else _row(r)


def update_reversal(conn: Connection, reversal_id: object, changes: dict[str, Any]) -> None:
    allowed = {
        "status", "reclaim_voucher_id", "reclaimed_on", "reclaimed_igst", "reclaimed_cgst", "reclaimed_sgst", "reclaimed_cess",
    }
    if not changes or not set(changes) <= allowed:
        raise ValueError(f"cannot update columns {sorted(set(changes) - allowed)}")
    sets = ", ".join(f"{k} = :{k}" for k in changes)
    conn.execute(text(f"UPDATE itc_reversals SET {sets} WHERE id = :_id"), {**changes, "_id": reversal_id})


# ---- register tie ------------------------------------------------------------------------------------------


def register_sums(conn: Connection, client_id: object, registration_id: object, as_on: date) -> list[dict[str, Any]]:
    """Regular-source entries of posted purchases / debit notes up to a date, with their status and amounts."""
    rows = conn.execute(
        text(
            "SELECT e.id, e.doc_type, e.status, e.igst, e.cgst, e.sgst, e.cess FROM itc_entries e "
            "JOIN vouchers v ON v.id = e.voucher_id WHERE e.client_id = :c AND e.gst_registration_id = :r "
            "AND e.source = 'regular' AND v.voucher_date <= :a AND v.status IN ('posted', 'reversed')"
        ),
        {"c": client_id, "r": registration_id, "a": as_on},
    )
    return [_row(r) for r in rows]
