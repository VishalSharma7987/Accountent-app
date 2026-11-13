"""SQL for the GST masters (registrations, ledger roles, item master, party GST type) and the GST rule tables
(Phase 3, package A). SQL only: no rules, no maths. Every function takes a Connection owned by the caller.

Rule-table readers return plain tuples in the field order of the dataclasses of engine/gst_types.py, filtered to the
rows in force on the given date.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

_IN_FORCE = "effective_from <= :on AND (effective_to IS NULL OR effective_to >= :on)"


def _rows(conn: Connection, sql: str, params: dict) -> list:
    return [tuple(r) for r in conn.execute(text(sql), params)]


# ============================================================================================ rule tables


def state_code_rows(conn: Connection, on: date) -> list:
    return _rows(conn, f"SELECT code, name, kind, effective_from, effective_to, source_reference, verification_status "
                       f"FROM gst_state_codes WHERE {_IN_FORCE} ORDER BY code", {"on": on})


def uqc_rows(conn: Connection, on: date) -> list:
    return _rows(conn, f"SELECT code, description, effective_from, effective_to, source_reference, verification_status "
                       f"FROM gst_uqc WHERE {_IN_FORCE} ORDER BY code", {"on": on})


def slab_rows(conn: Connection, on: date) -> list:
    return _rows(conn, f"SELECT rate, is_special, effective_from, effective_to, source_reference, verification_status "
                       f"FROM gst_rate_slabs WHERE {_IN_FORCE} ORDER BY rate", {"on": on})


def rate_rule_rows(conn: Connection, hsn_sac: str, supply_kind: str, on: date) -> list:
    """Rules of the supply kind in force on the date whose prefix starts the code, plus the 'default' rule."""
    return _rows(
        conn,
        "SELECT id::text, rule_key, code_kind, code_prefix, supply_kind, treatment, rate, cess_rate, "
        "cess_specific_amount, cess_uqc, effective_from, effective_to, source_reference, verification_status, "
        f"is_example FROM gst_rate_rules WHERE supply_kind = :kind AND {_IN_FORCE} "
        "AND (code_prefix IS NULL OR :code LIKE code_prefix || '%') ORDER BY code_prefix NULLS LAST, rule_key",
        {"on": on, "kind": supply_kind, "code": hsn_sac},
    )


def rcm_rule_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT category_key, section_ref, supply_kind, description, supplier_condition, hsn_sac_prefix, "
                       f"effective_from, effective_to, source_reference, verification_status, is_example "
                       f"FROM gst_rcm_rules WHERE {_IN_FORCE} ORDER BY category_key", {"on": on})


def blocked_rule_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT category_key, clause_ref, description, has_exception, exception_text, effective_from, "
                       "effective_to, source_reference, verification_status "
                       f"FROM gst_blocked_credit_rules WHERE {_IN_FORCE} ORDER BY category_key", {"on": on})


def itc_condition_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT condition_key, clause_ref, description, evidence_field, parameter_days, deadline_month, "
                       "deadline_day, effective_from, effective_to, source_reference, verification_status "
                       f"FROM gst_itc_conditions WHERE {_IN_FORCE} ORDER BY condition_key", {"on": on})


def threshold_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT threshold_key, unit, numeric_value, effective_from, effective_to, source_reference, "
                       f"verification_status FROM gst_thresholds WHERE {_IN_FORCE} ORDER BY threshold_key", {"on": on})


def composition_rule_rows(conn: Connection, on: date) -> list:
    return _rows(conn, "SELECT category, rate, turnover_limit, section_ref, turnover_basis, effective_from, "
                       f"effective_to, source_reference, verification_status FROM gst_composition_rules "
                       f"WHERE {_IN_FORCE} ORDER BY category", {"on": on})


def rule_key_exists(conn: Connection, table: str, column: str, key: str) -> bool:
    """Does the rule table hold the key at any date? (item master default tags). Table/column are fixed constants."""
    if (table, column) not in {("gst_blocked_credit_rules", "category_key"), ("gst_rcm_rules", "category_key")}:
        raise ValueError("unsupported rule table")
    return conn.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :k LIMIT 1"), {"k": key}).first() is not None


# ============================================================================================ registrations


@dataclass(frozen=True)
class RegistrationRow:
    id: uuid.UUID
    gstin: str
    state_code: str
    state_name: str
    registration_type: str
    return_frequency: str
    composition_category: str | None
    trade_name: str | None
    effective_from: date
    effective_to: date | None
    is_active: bool


_REG_SELECT = (
    "SELECT r.id, r.gstin, r.state_code, s.name, r.registration_type, r.return_frequency, r.composition_category, "
    "r.trade_name, r.effective_from, r.effective_to, r.is_active FROM gst_registrations r "
    "JOIN gst_state_codes s ON s.code = r.state_code"
)


def client_gst_profile(conn: Connection, client_id: object) -> tuple[str, str | None] | None:
    """(gst_type, pan) of the client; None when the client does not exist."""
    row = conn.execute(text("SELECT gst_type, pan FROM clients WHERE id = :c"), {"c": client_id}).first()
    return (row[0], row[1]) if row else None


def registration_row(conn: Connection, client_id: object, registration_id: object) -> RegistrationRow | None:
    row = conn.execute(text(f"{_REG_SELECT} WHERE r.client_id = :c AND r.id = :id"),
                       {"c": client_id, "id": registration_id}).first()
    return RegistrationRow(*row) if row else None


def registration_rows(conn: Connection, client_id: object) -> list[RegistrationRow]:
    rows = conn.execute(text(f"{_REG_SELECT} WHERE r.client_id = :c ORDER BY r.effective_from, r.gstin"), {"c": client_id})
    return [RegistrationRow(*r) for r in rows]


def other_periods_of_gstin(conn: Connection, client_id: object, gstin: str, exclude_id: object | None) -> list[tuple]:
    """(id, effective_from, effective_to) of the client's other registrations of the same GSTIN."""
    return _rows(conn, "SELECT id, effective_from, effective_to FROM gst_registrations "
                       "WHERE client_id = :c AND gstin = :g AND (CAST(:x AS uuid) IS NULL OR id <> :x)",
                 {"c": client_id, "g": gstin, "x": exclude_id})


def registration_exists(conn: Connection, client_id: object, gstin: str, effective_from: date) -> bool:
    return conn.execute(
        text("SELECT 1 FROM gst_registrations WHERE client_id = :c AND gstin = :g AND effective_from = :f"),
        {"c": client_id, "g": gstin, "f": effective_from},
    ).first() is not None


def insert_registration(conn: Connection, client_id: object, reg_id: uuid.UUID, *, gstin: str, state_code: str,
                        registration_type: str, return_frequency: str, composition_category: str | None,
                        trade_name: str | None, effective_from: date, effective_to: date | None) -> None:
    conn.execute(
        text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, return_frequency, "
             "composition_category, trade_name, effective_from, effective_to) "
             "VALUES (:id, :c, :g, :s, :t, :f, :cat, :n, :from, :to)"),
        {"id": reg_id, "c": client_id, "g": gstin, "s": state_code, "t": registration_type, "f": return_frequency,
         "cat": composition_category, "n": trade_name, "from": effective_from, "to": effective_to},
    )


def update_registration(conn: Connection, client_id: object, reg_id: object, *, registration_type: str,
                        return_frequency: str, composition_category: str | None, trade_name: str | None,
                        effective_from: date, effective_to: date | None, is_active: bool) -> None:
    conn.execute(
        text("UPDATE gst_registrations SET registration_type = :t, return_frequency = :f, composition_category = :cat, "
             "trade_name = :n, effective_from = :from, effective_to = :to, is_active = :a "
             "WHERE client_id = :c AND id = :id"),
        {"id": reg_id, "c": client_id, "t": registration_type, "f": return_frequency, "cat": composition_category,
         "n": trade_name, "from": effective_from, "to": effective_to, "a": is_active},
    )


def invoice_dates_outside(conn: Connection, client_id: object, reg_id: object, start: date, end: date | None) -> int:
    """Invoices already issued under the registration whose invoice date falls outside the new period (0 before
    invoice mode has been used)."""
    return conn.execute(
        text("SELECT count(*) FROM voucher_gst WHERE client_id = :c AND gst_registration_id = :r "
             "AND (invoice_date < :s OR (CAST(:e AS date) IS NOT NULL AND invoice_date > :e))"),
        {"c": client_id, "r": reg_id, "s": start, "e": end},
    ).scalar_one()


def ledger_role_rows(conn: Connection, client_id: object, registration_id: object | None = None) -> list[tuple]:
    """(registration_id, role, ledger_id, ledger_name) of one registration, or of every registration of the client."""
    return _rows(conn, "SELECT r.registration_id, r.role, r.ledger_id, l.name FROM gst_ledger_roles r "
                       "JOIN ledgers l ON l.id = r.ledger_id WHERE r.client_id = :c "
                       "AND (CAST(:r AS uuid) IS NULL OR r.registration_id = :r) ORDER BY r.registration_id, r.role",
                 {"c": client_id, "r": registration_id})


def replace_ledger_roles(conn: Connection, client_id: object, registration_id: object, roles: dict[str, object]) -> None:
    conn.execute(text("DELETE FROM gst_ledger_roles WHERE client_id = :c AND registration_id = :r"),
                 {"c": client_id, "r": registration_id})
    if roles:
        conn.execute(
            text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
            [{"r": registration_id, "c": client_id, "role": role, "l": ledger} for role, ledger in roles.items()],
        )


# ============================================================================================ item master


@dataclass(frozen=True)
class ItemRow:
    id: uuid.UUID
    name: str
    item_kind: str
    hsn_sac: str
    uqc: str | None
    sales_ledger_id: uuid.UUID | None
    purchase_ledger_id: uuid.UUID | None
    default_itc_category_key: str | None
    default_rcm_category_key: str | None
    is_active: bool


_ITEM_COLUMNS = ("id, name, item_kind, hsn_sac, uqc, sales_ledger_id, purchase_ledger_id, default_itc_category_key, "
                 "default_rcm_category_key, is_active")


def item_row(conn: Connection, client_id: object, item_id: object) -> ItemRow | None:
    row = conn.execute(text(f"SELECT {_ITEM_COLUMNS} FROM gst_items WHERE client_id = :c AND id = :id"),
                       {"c": client_id, "id": item_id}).first()
    return ItemRow(*row) if row else None


def item_rows(conn: Connection, client_id: object, q: str | None, kind: str | None) -> list[ItemRow]:
    """Items sorted by name; `q` matches the name (case-insensitive part) or the start of the HSN/SAC."""
    rows = conn.execute(
        text(f"SELECT {_ITEM_COLUMNS} FROM gst_items WHERE client_id = :c "
             "AND (CAST(:k AS text) IS NULL OR item_kind = :k) "
             "AND (CAST(:q AS text) IS NULL OR lower(name) LIKE '%' || lower(:q) || '%' OR hsn_sac LIKE :q || '%') "
             "ORDER BY lower(name)"),
        {"c": client_id, "k": kind, "q": q},
    )
    return [ItemRow(*r) for r in rows]


def item_name_taken(conn: Connection, client_id: object, name: str, exclude_id: object | None) -> bool:
    return conn.execute(
        text("SELECT 1 FROM gst_items WHERE client_id = :c AND lower(btrim(name)) = lower(btrim(:n)) "
             "AND (CAST(:x AS uuid) IS NULL OR id <> :x)"),
        {"c": client_id, "n": name, "x": exclude_id},
    ).first() is not None


def insert_item(conn: Connection, client_id: object, row: ItemRow) -> None:
    conn.execute(
        text(f"INSERT INTO gst_items (client_id, {_ITEM_COLUMNS}) VALUES (:c, :id, :name, :kind, :hsn, :uqc, :sl, :pl, "
             ":itc, :rcm, :a)"),
        _item_params(client_id, row),
    )


def update_item(conn: Connection, client_id: object, row: ItemRow) -> None:
    conn.execute(
        text("UPDATE gst_items SET name = :name, item_kind = :kind, hsn_sac = :hsn, uqc = :uqc, sales_ledger_id = :sl, "
             "purchase_ledger_id = :pl, default_itc_category_key = :itc, default_rcm_category_key = :rcm, "
             "is_active = :a WHERE client_id = :c AND id = :id"),
        _item_params(client_id, row),
    )


def _item_params(client_id: object, row: ItemRow) -> dict:
    return {"c": client_id, "id": row.id, "name": row.name, "kind": row.item_kind, "hsn": row.hsn_sac, "uqc": row.uqc,
            "sl": row.sales_ledger_id, "pl": row.purchase_ledger_id, "itc": row.default_itc_category_key,
            "rcm": row.default_rcm_category_key, "a": row.is_active}


# ============================================================================================ party GST type


def party_gst_types(conn: Connection, client_id: object) -> dict[uuid.UUID, str | None]:
    """ledger_id -> gst_registration_type for every party of the client."""
    rows = conn.execute(text("SELECT ledger_id, gst_registration_type FROM parties WHERE client_id = :c"), {"c": client_id})
    return {r[0]: r[1] for r in rows}


def set_party_gst_type(conn: Connection, client_id: object, ledger_id: object, value: str | None) -> None:
    conn.execute(text("UPDATE parties SET gst_registration_type = :v WHERE client_id = :c AND ledger_id = :l"),
                 {"v": value, "c": client_id, "l": ledger_id})

