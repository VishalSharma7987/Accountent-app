"""SQL for TDS challans, allocations, deduction items and the rule rows package C uses (Phase 4).

Plain functions over a SQLAlchemy Connection; no business rules here (those are in engine/tds_challan.py and services/tds_challans.py).
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.tds_types import DueDateRule, InterestRule


def _row(r) -> dict[str, Any]:
    return dict(r._mapping)


def _d(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ---- rule rows (source references kept for T-50) ------------------------------------------------------------


def due_date_rules(conn: Connection) -> tuple[list[DueDateRule], dict[tuple, str]]:
    rows = conn.execute(text(
        "SELECT due_key, event, kind, quarter, month_of_year, due_day, month_offset, days_after_return, effective_from, effective_to, "
        "verification_status, source_reference FROM tds_due_dates"
    )).fetchall()
    sources = {(r[0], r[2], r[8]): r[11] for r in rows}
    return [DueDateRule(*r[:11]) for r in rows], sources


def interest_rules(conn: Connection) -> tuple[list[InterestRule], dict[tuple, str]]:
    rows = conn.execute(text(
        "SELECT interest_key, monthly_rate, part_month_counts_full, section_ref, effective_from, effective_to, verification_status, "
        "source_reference FROM tds_interest_rules"
    )).fetchall()
    sources = {(r[0], r[4]): r[7] for r in rows}
    return [InterestRule(r[0], Decimal(str(r[1])), r[2], r[3], r[4], r[5], r[6]) for r in rows], sources


# ---- financial year ------------------------------------------------------------------------------------------


def financial_year(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any] | None:
    r = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"), {"f": fy_id, "c": client_id}
    ).first()
    return _row(r) if r else None


def voucher_of_client(conn: Connection, client_id: object, voucher_id: object) -> dict[str, Any] | None:
    r = conn.execute(
        text("SELECT id, status, voucher_type FROM vouchers WHERE id = :v AND client_id = :c"), {"v": voucher_id, "c": client_id}
    ).first()
    return _row(r) if r else None


# ---- deduction items (posted, non-reversed vouchers; zero-tax items have nothing to deposit) -----------------


_ITEM_SELECT = (
    "SELECT i.id AS item_id, i.voucher_id, v.voucher_number, v.voucher_date, v.status AS voucher_status, i.kind, "
    "i.deductee_ledger_id, l.name AS deductee_name, i.nature_key, i.section_ref, i.financial_year_id, i.event_date, i.tds_amount "
    "FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id AND v.client_id = i.client_id "
    "JOIN ledgers l ON l.id = i.deductee_ledger_id AND l.client_id = i.client_id "
)


def items_for_year(conn: Connection, client_id: object, fy_id: object, kind: str | None = None) -> list[dict[str, Any]]:
    sql = _ITEM_SELECT + "WHERE i.client_id = :c AND i.financial_year_id = :f AND v.status = 'posted' AND i.tds_amount > 0 "
    params: dict[str, Any] = {"c": client_id, "f": fy_id}
    if kind:
        sql += "AND i.kind = :k "
        params["k"] = kind
    sql += "ORDER BY i.event_date, v.voucher_number, i.item_no"
    return [_row(r) for r in conn.execute(text(sql), params)]


def items_by_ids(conn: Connection, client_id: object, item_ids: list[object], *, lock: bool = False) -> list[dict[str, Any]]:
    """Items of the client with these ids, whatever their voucher status (the engine refuses unposted ones with a reason)."""
    if not item_ids:
        return []
    sql = _ITEM_SELECT + "WHERE i.client_id = :c AND i.id = ANY(:ids) ORDER BY i.id"
    if lock:
        sql += " FOR UPDATE OF i"
    return [_row(r) for r in conn.execute(text(sql), {"c": client_id, "ids": list(item_ids)})]


# ---- challans ------------------------------------------------------------------------------------------------


def challan_by_cin(conn: Connection, client_id: object, bsr: str, deposit_date: date, serial: str) -> dict[str, Any] | None:
    r = conn.execute(
        text("SELECT id FROM tds_challans WHERE client_id = :c AND bsr_code = :b AND deposit_date = :d AND challan_serial_no = :s"),
        {"c": client_id, "b": bsr, "d": deposit_date, "s": serial},
    ).first()
    return _row(r) if r else None


def insert_challan(conn: Connection, values: dict[str, Any]) -> object:
    return conn.execute(
        text(
            "INSERT INTO tds_challans (client_id, kind, financial_year_id, quarter, bsr_code, deposit_date, challan_serial_no, tax_amount, "
            "interest_amount, fee_amount, other_amount, total_amount, payment_voucher_id, note, created_by) VALUES "
            "(:client_id, :kind, :financial_year_id, :quarter, :bsr_code, :deposit_date, :challan_serial_no, :tax_amount, "
            ":interest_amount, :fee_amount, :other_amount, :total_amount, :payment_voucher_id, :note, :created_by) RETURNING id"
        ),
        values,
    ).scalar_one()


def update_challan(conn: Connection, challan_id: object, values: dict[str, Any]) -> None:
    conn.execute(
        text(
            "UPDATE tds_challans SET financial_year_id = :financial_year_id, quarter = :quarter, bsr_code = :bsr_code, "
            "deposit_date = :deposit_date, challan_serial_no = :challan_serial_no, tax_amount = :tax_amount, interest_amount = :interest_amount, "
            "fee_amount = :fee_amount, other_amount = :other_amount, total_amount = :total_amount, payment_voucher_id = :payment_voucher_id, "
            "note = :note WHERE id = :id"
        ),
        {**values, "id": challan_id},
    )


_CHALLAN_SELECT = (
    "SELECT c.*, coalesce((SELECT sum(a.amount) FROM tds_challan_allocations a WHERE a.challan_id = c.id), 0) AS allocated FROM tds_challans c "
)


def get_challan(conn: Connection, client_id: object, challan_id: object, *, lock: bool = False) -> dict[str, Any] | None:
    if lock:  # lock the challan row alone (FOR UPDATE cannot sit on a query with an aggregate sub-select in the select list)
        conn.execute(text("SELECT id FROM tds_challans WHERE id = :i AND client_id = :c FOR UPDATE"), {"i": challan_id, "c": client_id})
    r = conn.execute(text(_CHALLAN_SELECT + "WHERE c.id = :i AND c.client_id = :c"), {"i": challan_id, "c": client_id}).first()
    return _row(r) if r else None


def list_challans(conn: Connection, client_id: object, fy_id: object | None, quarter: int | None, kind: str | None) -> list[dict[str, Any]]:
    sql = _CHALLAN_SELECT + "WHERE c.client_id = :c "
    params: dict[str, Any] = {"c": client_id}
    for column, key, value in (("financial_year_id", "f", fy_id), ("quarter", "q", quarter), ("kind", "k", kind)):
        if value is not None:
            sql += f"AND c.{column} = :{key} "
            params[key] = value
    sql += "ORDER BY c.deposit_date, c.challan_serial_no"
    return [_row(r) for r in conn.execute(text(sql), params)]


# ---- allocations ---------------------------------------------------------------------------------------------


def allocations_of_challan(conn: Connection, challan_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(text("SELECT id, item_id, amount FROM tds_challan_allocations WHERE challan_id = :c ORDER BY created_at, id"), {"c": challan_id})
    return [_row(r) for r in rows]


def allocations_for_year(conn: Connection, client_id: object, fy_id: object) -> list[dict[str, Any]]:
    """Every allocation of challans of the year, with the deposit date of its challan."""
    rows = conn.execute(
        text(
            "SELECT a.item_id, a.challan_id, a.amount, c.deposit_date, c.bsr_code, c.challan_serial_no "
            "FROM tds_challan_allocations a JOIN tds_challans c ON c.id = a.challan_id AND c.client_id = a.client_id "
            "WHERE a.client_id = :c AND c.financial_year_id = :f ORDER BY c.deposit_date, c.challan_serial_no"
        ),
        {"c": client_id, "f": fy_id},
    )
    return [_row(r) for r in rows]


def allocated_on_other_challans(conn: Connection, client_id: object, item_ids: list[object], except_challan: object | None) -> dict[str, Decimal]:
    if not item_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT item_id, sum(amount) FROM tds_challan_allocations WHERE client_id = :c AND item_id = ANY(:ids) "
            "AND (CAST(:x AS uuid) IS NULL OR challan_id <> :x) GROUP BY item_id"
        ),
        {"c": client_id, "ids": list(item_ids), "x": except_challan},
    )
    return {str(r[0]): _d(r[1]) for r in rows}


def delete_allocations(conn: Connection, challan_id: object) -> None:
    conn.execute(text("DELETE FROM tds_challan_allocations WHERE challan_id = :c"), {"c": challan_id})


def insert_allocations(conn: Connection, client_id: object, challan_id: object, rows: list[tuple[object, Decimal]], actor: str) -> None:
    if rows:
        conn.execute(
            text(
                "INSERT INTO tds_challan_allocations (client_id, challan_id, item_id, amount, created_by) "
                "VALUES (:client_id, :challan_id, :item_id, :amount, :actor)"
            ),
            [{"client_id": client_id, "challan_id": challan_id, "item_id": i, "amount": a, "actor": actor} for i, a in rows],
        )


def allocation_on_voucher(conn: Connection, client_id: object, voucher_id: object) -> list[dict[str, Any]]:
    """Allocations (with their challan numbers) on the deduction items of a voucher: they block its reversal (T-25)."""
    rows = conn.execute(
        text(
            "SELECT a.challan_id, a.amount, c.bsr_code, c.challan_serial_no, c.deposit_date FROM tds_challan_allocations a "
            "JOIN tds_voucher_items i ON i.id = a.item_id AND i.client_id = a.client_id "
            "JOIN tds_challans c ON c.id = a.challan_id AND c.client_id = a.client_id "
            "WHERE a.client_id = :c AND i.voucher_id = :v"
        ),
        {"c": client_id, "v": voucher_id},
    )
    return [_row(r) for r in rows]


# ---- calendar inputs -----------------------------------------------------------------------------------------


def returns_filed(conn: Connection, client_id: object, fy_id: object) -> set[tuple[str, int]]:
    rows = conn.execute(text("SELECT return_kind, quarter FROM tds_filed_returns WHERE client_id = :c AND financial_year_id = :f"), {"c": client_id, "f": fy_id})
    return {("tcs" if k == "tcs" else "tds", q) for k, q in rows}


def certificates_issued(conn: Connection, client_id: object, fy_id: object) -> set[tuple[str, int | None]]:
    rows = conn.execute(
        text("SELECT DISTINCT certificate_kind, quarter FROM tds_certificates WHERE client_id = :c AND financial_year_id = :f"),
        {"c": client_id, "f": fy_id},
    )
    return {("tcs" if k == "tcs" else "tds", q) for k, q in rows}
