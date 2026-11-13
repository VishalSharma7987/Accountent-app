"""SQL for the TDS masters (deductees, lower-deduction certificates, ledger roles, TAN, 194Q flags) and the TDS rule
tables (Phase 4, package A). SQL only: no rules, no maths. Every function takes a Connection owned by the caller.

Rule-table readers return plain tuples in the field order of the dataclasses of engine/tds_types.py, filtered to the
rows in force on the given date (natures and section references are not date-filtered: see rules/tds_rules.py).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

_IN_FORCE = "effective_from <= :on AND (effective_to IS NULL OR effective_to >= :on)"


def _rows(conn: Connection, sql: str, params: dict | None = None) -> list:
    return [tuple(r) for r in conn.execute(text(sql), params or {})]


# ============================================================================================ rule tables


def nature_rows(conn: Connection) -> list:
    return _rows(conn, "SELECT nature_key, kind, description, rate_mode, verification_status FROM tds_natures "
                       "ORDER BY sort_order, nature_key")


def section_ref_rows(conn: Connection) -> list:
    return _rows(conn, "SELECT nature_key, act, section_ref, table_ref, payment_code, effective_from, effective_to, "
                       "source_reference, verification_status FROM tds_section_refs "
                       "ORDER BY nature_key, act, effective_from")


def rate_rows(conn: Connection, on: date, nature_key: str | None = None) -> list:
    return _rows(
        conn,
        "SELECT id::text, nature_key, act, deductee_group, rate, no_pan_rate, single_payment_threshold, "
        "monthly_threshold, annual_threshold, threshold_mode, effective_from, effective_to, source_reference, "
        f"verification_status FROM tds_rates WHERE {_IN_FORCE} AND (CAST(:nature AS text) IS NULL OR nature_key = :nature) "
        "ORDER BY nature_key, deductee_group",
        {"on": on, "nature": nature_key},
    )


def provision_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT provision_key, act, section_ref, description, effective_from, effective_to, "
                       f"source_reference, verification_status FROM tds_provisions WHERE {_IN_FORCE} "
                       "ORDER BY provision_key", {"on": on})


def due_date_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT due_key, event, kind, quarter, month_of_year, due_day, month_offset, days_after_return, "
                       f"effective_from, effective_to, verification_status FROM tds_due_dates WHERE {_IN_FORCE} "
                       "ORDER BY event, kind, quarter NULLS FIRST, month_of_year NULLS FIRST, due_key", {"on": on})


def interest_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT interest_key, monthly_rate, part_month_counts_full, section_ref, effective_from, "
                       f"effective_to, verification_status FROM tds_interest_rules WHERE {_IN_FORCE} "
                       "ORDER BY interest_key", {"on": on})


def form_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT form_key, act, form_no, description, rule_ref, effective_from, effective_to, "
                       f"verification_status FROM tds_forms WHERE {_IN_FORCE} ORDER BY form_key, act", {"on": on})


# ============================================================================================ TAN and flags


def client_tan(conn: Connection, client_id: object) -> tuple[str | None] | None:
    """(tan,) of the client; None when the client does not exist."""
    row = conn.execute(text("SELECT tan FROM clients WHERE id = :c"), {"c": client_id}).first()
    return (row[0],) if row else None


def set_client_tan(conn: Connection, client_id: object, tan: str | None) -> None:
    conn.execute(text("UPDATE clients SET tan = :t WHERE id = :c"), {"t": tan, "c": client_id})


def fy_exists(conn: Connection, client_id: object, fy_id: object) -> bool:
    return conn.execute(text("SELECT 1 FROM financial_years WHERE id = :f AND client_id = :c"),
                        {"f": fy_id, "c": client_id}).first() is not None


def fy_flag_rows(conn: Connection, client_id: object) -> list[tuple]:
    return _rows(conn, "SELECT financial_year_id, prev_year_turnover_over_threshold, note FROM tds_client_fy_flags "
                       "WHERE client_id = :c ORDER BY financial_year_id", {"c": client_id})


def fy_flag(conn: Connection, client_id: object, fy_id: object) -> tuple[bool, str | None] | None:
    row = conn.execute(text("SELECT prev_year_turnover_over_threshold, note FROM tds_client_fy_flags "
                            "WHERE client_id = :c AND financial_year_id = :f"), {"c": client_id, "f": fy_id}).first()
    return (row[0], row[1]) if row else None


def upsert_fy_flag(conn: Connection, client_id: object, fy_id: object, over: bool, note: str | None, actor: str) -> None:
    conn.execute(text(
        "INSERT INTO tds_client_fy_flags (client_id, financial_year_id, prev_year_turnover_over_threshold, note, entered_by) "
        "VALUES (:c, :f, :o, :n, :a) ON CONFLICT (client_id, financial_year_id) DO UPDATE SET "
        "prev_year_turnover_over_threshold = EXCLUDED.prev_year_turnover_over_threshold, note = EXCLUDED.note, "
        "entered_by = EXCLUDED.entered_by, entered_at = now()"),
        {"c": client_id, "f": fy_id, "o": over, "n": note, "a": actor})


# ============================================================================================ deductees


@dataclass(frozen=True)
class DeducteeRow:
    ledger_id: uuid.UUID
    ledger_name: str
    pan: str | None
    pan_status: str
    deductee_type: str
    default_nature_key: str | None
    is_active: bool


_DEDUCTEE_SELECT = (
    "SELECT d.ledger_id, l.name, d.pan, d.pan_status, d.deductee_type, d.default_nature_key, d.is_active "
    "FROM tds_deductees d JOIN ledgers l ON l.id = d.ledger_id AND l.client_id = d.client_id"
)


def deductee_row(conn: Connection, client_id: object, ledger_id: object) -> DeducteeRow | None:
    row = conn.execute(text(f"{_DEDUCTEE_SELECT} WHERE d.client_id = :c AND d.ledger_id = :l"),
                       {"c": client_id, "l": ledger_id}).first()
    return DeducteeRow(*row) if row else None


def deductee_rows(conn: Connection, client_id: object, q: str | None = None) -> list[DeducteeRow]:
    rows = conn.execute(
        text(f"{_DEDUCTEE_SELECT} WHERE d.client_id = :c AND (CAST(:q AS text) IS NULL OR "
             "lower(l.name) LIKE '%' || lower(:q) || '%' OR lower(coalesce(d.pan, '')) LIKE '%' || lower(:q) || '%') "
             "ORDER BY lower(l.name)"),
        {"c": client_id, "q": q})
    return [DeducteeRow(*r) for r in rows]


def nature_kind(conn: Connection, nature_key: str) -> str | None:
    row = conn.execute(text("SELECT kind FROM tds_natures WHERE nature_key = :n"), {"n": nature_key}).first()
    return row[0] if row else None


def nature_kinds(conn: Connection) -> dict[str, str]:
    return {k: v for k, v in conn.execute(text("SELECT nature_key, kind FROM tds_natures"))}


def upsert_deductee(conn: Connection, client_id: object, ledger_id: object, *, pan: str | None, pan_status: str,
                    deductee_type: str, default_nature_key: str | None, is_active: bool) -> None:
    conn.execute(text(
        "INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type, default_nature_key, is_active) "
        "VALUES (:l, :c, :pan, :ps, :dt, :dn, :a) ON CONFLICT (ledger_id) DO UPDATE SET pan = EXCLUDED.pan, "
        "pan_status = EXCLUDED.pan_status, deductee_type = EXCLUDED.deductee_type, "
        "default_nature_key = EXCLUDED.default_nature_key, is_active = EXCLUDED.is_active"),
        {"l": ledger_id, "c": client_id, "pan": pan, "ps": pan_status, "dt": deductee_type, "dn": default_nature_key,
         "a": is_active})


# ============================================================================================ certificates


@dataclass(frozen=True)
class CertRow:
    id: uuid.UUID
    deductee_ledger_id: uuid.UUID
    certificate_no: str
    nature_key: str | None
    rate: Decimal
    max_amount: Decimal
    valid_from: date
    valid_to: date
    note: str | None
    is_active: bool
    amount_used: Decimal


# used amount = payment amounts of items of POSTED (not reversed) vouchers that used the certificate
_CERT_SELECT = (
    "SELECT c.id, c.deductee_ledger_id, c.certificate_no, c.nature_key, c.rate, c.max_amount, c.valid_from, c.valid_to, "
    "c.note, c.is_active, coalesce((SELECT sum(i.payment_amount) FROM tds_voucher_items i "
    "JOIN vouchers v ON v.id = i.voucher_id WHERE i.lower_cert_id = c.id AND v.status = 'posted'), 0) "
    "FROM tds_lower_deduction_certs c"
)


def cert_row(conn: Connection, client_id: object, ledger_id: object, cert_id: object) -> CertRow | None:
    row = conn.execute(text(f"{_CERT_SELECT} WHERE c.client_id = :c AND c.deductee_ledger_id = :l AND c.id = :id"),
                       {"c": client_id, "l": ledger_id, "id": cert_id}).first()
    return CertRow(*row) if row else None


def cert_rows(conn: Connection, client_id: object, ledger_ids: list | None = None, ledger_id: object | None = None) -> list[CertRow]:
    sql = f"{_CERT_SELECT} WHERE c.client_id = :c"
    params: dict = {"c": client_id}
    if ledger_id is not None:
        sql += " AND c.deductee_ledger_id = :l"
        params["l"] = ledger_id
    rows = conn.execute(text(sql + " ORDER BY c.valid_from, c.certificate_no"), params)
    out = [CertRow(*r) for r in rows]
    return [c for c in out if ledger_ids is None or c.deductee_ledger_id in ledger_ids]


def cert_exists(conn: Connection, client_id: object, certificate_no: str, valid_from: date) -> bool:
    return conn.execute(text("SELECT 1 FROM tds_lower_deduction_certs WHERE client_id = :c AND certificate_no = :n "
                             "AND valid_from = :f"), {"c": client_id, "n": certificate_no, "f": valid_from}).first() is not None


def insert_cert(conn: Connection, client_id: object, cert_id: object, ledger_id: object, *, certificate_no: str,
                nature_key: str | None, rate: Decimal, max_amount: Decimal, valid_from: date, valid_to: date,
                note: str | None) -> None:
    conn.execute(text(
        "INSERT INTO tds_lower_deduction_certs (id, client_id, deductee_ledger_id, certificate_no, nature_key, rate, "
        "max_amount, valid_from, valid_to, note) VALUES (:id, :c, :l, :no, :n, :r, :m, :f, :t, :note)"),
        {"id": cert_id, "c": client_id, "l": ledger_id, "no": certificate_no, "n": nature_key, "r": rate,
         "m": max_amount, "f": valid_from, "t": valid_to, "note": note})


def update_cert(conn: Connection, client_id: object, cert_id: object, *, is_active: bool, note: str | None,
                valid_to: date) -> None:
    conn.execute(text("UPDATE tds_lower_deduction_certs SET is_active = :a, note = :n, valid_to = :t "
                      "WHERE client_id = :c AND id = :id"),
                 {"a": is_active, "n": note, "t": valid_to, "c": client_id, "id": cert_id})


# ============================================================================================ ledger roles


def ledger_role_rows(conn: Connection, client_id: object) -> list[tuple]:
    """(role, nature_key, ledger_id, ledger_name) ordered by role, default first."""
    return _rows(conn, "SELECT r.role, r.nature_key, r.ledger_id, l.name FROM tds_ledger_roles r "
                       "JOIN ledgers l ON l.id = r.ledger_id AND l.client_id = r.client_id WHERE r.client_id = :c "
                       "ORDER BY r.role, r.nature_key NULLS FIRST", {"c": client_id})


def replace_ledger_roles(conn: Connection, client_id: object, entries: list[tuple[str, str | None, object]]) -> None:
    conn.execute(text("DELETE FROM tds_ledger_roles WHERE client_id = :c"), {"c": client_id})
    if entries:
        conn.execute(
            text("INSERT INTO tds_ledger_roles (client_id, role, nature_key, ledger_id) VALUES (:c, :r, :n, :l)"),
            [{"c": client_id, "r": r, "n": n, "l": lid} for r, n, lid in entries])
