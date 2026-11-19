"""SQL of the fixed asset register, the Companies Act depreciation runs and the income-tax block working (Phase 6, package B).
Reads and plain writes only: no accounting rules and no accounting maths here. Every function takes a Connection owned by the caller.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.final_assets import Sched2Rule
from app.engine.final_types import AssetEvent, EventKind

CENTS = Decimal("0.01")


# ------------------------------------------------------------------------------------------------ rule tables


@dataclass(frozen=True)
class ItRateRow:
    block_key: str
    description: str
    act: str
    rate: Decimal
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


@dataclass(frozen=True)
class ItScalarRow:
    rule_key: str
    act: str
    rule_value: Decimal
    effective_from: date
    effective_to: date | None
    source_reference: str
    verification_status: str


def sched2_rows(conn: Connection, class_key: str | None = None) -> list[Sched2Rule]:
    rows = conn.execute(
        text("SELECT class_key, description, useful_life_years, max_residual_percent, effective_from, effective_to, "
             "verification_status, source_reference FROM dep_sched2_classes WHERE (CAST(:k AS text) IS NULL OR class_key = :k) "
             "ORDER BY class_key, effective_from"), {"k": class_key})
    return [Sched2Rule(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows]


def it_rate_rows(conn: Connection, block_key: str | None = None) -> list[ItRateRow]:
    rows = conn.execute(
        text("SELECT block_key, description, act, rate, effective_from, effective_to, source_reference, verification_status "
             "FROM dep_it_block_rates WHERE (CAST(:k AS text) IS NULL OR block_key = :k) ORDER BY block_key, effective_from"),
        {"k": block_key})
    return [ItRateRow(*r) for r in rows]


def it_scalar_rows(conn: Connection) -> list[ItScalarRow]:
    rows = conn.execute(
        text("SELECT rule_key, act, rule_value, effective_from, effective_to, source_reference, verification_status "
             "FROM dep_it_rules ORDER BY rule_key, effective_from"))
    return [ItScalarRow(*r) for r in rows]


# ------------------------------------------------------------------------------------------------ ledgers and roles


def ledger_role(conn: Connection, client_id: object, role: str) -> object | None:
    row = conn.execute(text("SELECT ledger_id FROM final_ledger_roles WHERE client_id = :c AND role = :r"), {"c": client_id, "r": role}).first()
    return row[0] if row else None


# ------------------------------------------------------------------------------------------------ assets


_ASSET_COLS = ("id, asset_no, name, asset_ledger_id, accumulated_dep_ledger_id, is_depreciable, it_block_key, sched2_class_key, "
               "useful_life_years, life_override_reason, residual_value, book_method, is_active")


def _asset(r) -> dict[str, Any]:
    return {"id": r[0], "asset_no": r[1], "name": r[2], "asset_ledger_id": r[3], "accumulated_dep_ledger_id": r[4],
            "is_depreciable": r[5], "it_block_key": r[6], "sched2_class_key": r[7], "useful_life_years": r[8],
            "life_override_reason": r[9], "residual_value": r[10].quantize(CENTS), "book_method": r[11], "is_active": r[12]}


def list_assets(conn: Connection, client_id: object, q: str | None = None, active: bool | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(f"SELECT {_ASSET_COLS} FROM fixed_assets WHERE client_id = :c "
             "AND (CAST(:q AS text) IS NULL OR asset_no ILIKE :like OR name ILIKE :like) "
             "AND (CAST(:a AS boolean) IS NULL OR is_active = :a) ORDER BY asset_no"),
        {"c": client_id, "q": q, "like": f"%{q}%" if q else None, "a": active})
    return [_asset(r) for r in rows]


def get_asset(conn: Connection, client_id: object, asset_id: object, *, lock: bool = False) -> dict[str, Any] | None:
    row = conn.execute(text(f"SELECT {_ASSET_COLS} FROM fixed_assets WHERE client_id = :c AND id = :id{' FOR UPDATE' if lock else ''}"),
                       {"c": client_id, "id": asset_id}).first()
    return _asset(row) if row else None


def asset_no_exists(conn: Connection, client_id: object, asset_no: str, except_id: object | None = None) -> bool:
    return conn.execute(
        text("SELECT 1 FROM fixed_assets WHERE client_id = :c AND lower(btrim(asset_no)) = lower(btrim(:n)) "
             "AND (CAST(:x AS uuid) IS NULL OR id <> :x)"), {"c": client_id, "n": asset_no, "x": except_id}).first() is not None


def insert_asset(conn: Connection, client_id: object, v: dict[str, Any], actor: str) -> object:
    return conn.execute(
        text("INSERT INTO fixed_assets (client_id, asset_no, name, asset_ledger_id, accumulated_dep_ledger_id, is_depreciable, it_block_key, "
             "sched2_class_key, useful_life_years, life_override_reason, residual_value, book_method, created_by) "
             "VALUES (:c, :asset_no, :name, :asset_ledger_id, :accumulated_dep_ledger_id, :is_depreciable, :it_block_key, :sched2_class_key, "
             ":useful_life_years, :life_override_reason, :residual_value, :book_method, :actor) RETURNING id"),
        {"c": client_id, "actor": actor, **v}).scalar_one()


def update_asset(conn: Connection, client_id: object, asset_id: object, v: dict[str, Any]) -> None:
    conn.execute(
        text("UPDATE fixed_assets SET asset_no = :asset_no, name = :name, asset_ledger_id = :asset_ledger_id, "
             "accumulated_dep_ledger_id = :accumulated_dep_ledger_id, is_depreciable = :is_depreciable, it_block_key = :it_block_key, "
             "sched2_class_key = :sched2_class_key, useful_life_years = :useful_life_years, life_override_reason = :life_override_reason, "
             "residual_value = :residual_value, book_method = :book_method, is_active = :is_active WHERE client_id = :c AND id = :id"),
        {"c": client_id, "id": asset_id, **v})


def asset_has_posted_depreciation(conn: Connection, client_id: object, asset_id: object) -> bool:
    """A depreciation run line of this asset whose voucher is no longer a draft, or whose year is closed."""
    return conn.execute(
        text("SELECT 1 FROM depreciation_run_lines l JOIN vouchers v ON v.id = l.voucher_id "
             "WHERE l.client_id = :c AND l.asset_id = :a AND v.status <> 'draft' LIMIT 1"), {"c": client_id, "a": asset_id}).first() is not None


# ------------------------------------------------------------------------------------------------ events


def _event(r) -> dict[str, Any]:
    return {"id": r[0], "asset_id": r[1], "kind": r[2], "event_date": r[3], "put_to_use_date": r[4], "amount": r[5].quantize(CENTS),
            "accumulated_dep_bf": r[6].quantize(CENTS), "voucher_id": r[7], "note": r[8]}


_EVENT_COLS = "id, asset_id, kind, event_date, put_to_use_date, amount, accumulated_dep_bf, voucher_id, note"


def events_of_asset(conn: Connection, client_id: object, asset_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(text(f"SELECT {_EVENT_COLS} FROM fixed_asset_events WHERE client_id = :c AND asset_id = :a ORDER BY event_date, CASE kind WHEN 'opening' THEN 0 WHEN 'purchase' THEN 1 WHEN 'addition' THEN 2 ELSE 3 END, created_at"),
                        {"c": client_id, "a": asset_id})
    return [_event(r) for r in rows]


def events_of_client(conn: Connection, client_id: object) -> dict[object, list[dict[str, Any]]]:
    rows = conn.execute(text(f"SELECT {_EVENT_COLS} FROM fixed_asset_events WHERE client_id = :c ORDER BY asset_id, event_date, CASE kind WHEN 'opening' THEN 0 WHEN 'purchase' THEN 1 WHEN 'addition' THEN 2 ELSE 3 END, created_at"),
                        {"c": client_id})
    out: dict[object, list[dict[str, Any]]] = {}
    for r in rows:
        e = _event(r)
        out.setdefault(e["asset_id"], []).append(e)
    return out


def get_event(conn: Connection, client_id: object, asset_id: object, event_id: object) -> dict[str, Any] | None:
    row = conn.execute(text(f"SELECT {_EVENT_COLS} FROM fixed_asset_events WHERE client_id = :c AND asset_id = :a AND id = :id"),
                       {"c": client_id, "a": asset_id, "id": event_id}).first()
    return _event(row) if row else None


def insert_event(conn: Connection, client_id: object, asset_id: object, v: dict[str, Any], actor: str) -> object:
    return conn.execute(
        text("INSERT INTO fixed_asset_events (client_id, asset_id, kind, event_date, put_to_use_date, amount, accumulated_dep_bf, "
             "voucher_id, note, created_by) VALUES (:c, :a, :kind, :event_date, :put_to_use_date, :amount, :accumulated_dep_bf, "
             ":voucher_id, :note, :actor) RETURNING id"), {"c": client_id, "a": asset_id, "actor": actor, **v}).scalar_one()


def delete_event(conn: Connection, client_id: object, event_id: object) -> None:
    conn.execute(text("DELETE FROM fixed_asset_events WHERE client_id = :c AND id = :id"), {"c": client_id, "id": event_id})


def to_engine_event(e: dict[str, Any]) -> AssetEvent:
    return AssetEvent(EventKind(e["kind"]), e["event_date"], e["amount"], e["put_to_use_date"], e["accumulated_dep_bf"])


def voucher_in_client(conn: Connection, client_id: object, voucher_id: object) -> bool:
    return conn.execute(text("SELECT 1 FROM vouchers WHERE id = :v AND client_id = :c"), {"v": voucher_id, "c": client_id}).first() is not None


# ------------------------------------------------------------------------------------------------ depreciation runs


def active_run(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any] | None:
    """The run of the year whose voucher is draft, approved or posted (the one allowed by the database guard)."""
    r = conn.execute(
        text("SELECT r.id, r.voucher_id, v.status FROM depreciation_runs r JOIN vouchers v ON v.id = r.voucher_id "
             "WHERE r.client_id = :c AND r.financial_year_id = :fy AND v.status IN ('draft', 'approved', 'posted')"),
        {"c": client_id, "fy": fy_id}).first()
    return {"run_id": r[0], "voucher_id": r[1], "voucher_status": r[2]} if r else None


def runs_of_year(conn: Connection, client_id: object, fy_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT r.id, r.voucher_id, v.status, r.total_depreciation, r.created_at FROM depreciation_runs r "
             "JOIN vouchers v ON v.id = r.voucher_id WHERE r.client_id = :c AND r.financial_year_id = :fy ORDER BY r.created_at"),
        {"c": client_id, "fy": fy_id})
    return [{"run_id": r[0], "voucher_id": r[1], "voucher_status": r[2], "total": r[3].quantize(CENTS), "created_at": r[4]} for r in rows]


def get_run(conn: Connection, client_id: object, run_id: object) -> dict[str, Any] | None:
    r = conn.execute(
        text("SELECT r.id, r.voucher_id, v.status, r.total_depreciation, r.financial_year_id FROM depreciation_runs r "
             "JOIN vouchers v ON v.id = r.voucher_id WHERE r.client_id = :c AND r.id = :id"), {"c": client_id, "id": run_id}).first()
    return ({"run_id": r[0], "voucher_id": r[1], "voucher_status": r[2], "total": r[3].quantize(CENTS), "financial_year_id": r[4]}
            if r else None)


def active_run_dates(conn: Connection, client_id: object) -> list[tuple[date, date]]:
    """(start, end) of every financial year that has an active run: asset inputs dated in those years are frozen."""
    rows = conn.execute(
        text("SELECT f.start_date, f.end_date FROM depreciation_runs r JOIN vouchers v ON v.id = r.voucher_id "
             "JOIN financial_years f ON f.id = r.financial_year_id WHERE r.client_id = :c AND v.status IN ('draft', 'approved', 'posted')"),
        {"c": client_id})
    return [(r[0], r[1]) for r in rows]


def insert_run(conn: Connection, client_id: object, fy_id: object, as_on: date, total: Decimal, voucher_id: object,
               rule_snapshot: dict[str, Any], engine_version: str, actor: str) -> object:
    return conn.execute(
        text("INSERT INTO depreciation_runs (client_id, financial_year_id, as_on_date, total_depreciation, voucher_id, rule_snapshot, "
             "engine_version, created_by) VALUES (:c, :fy, :on, :t, :v, CAST(:snap AS jsonb), :ev, :actor) RETURNING id"),
        {"c": client_id, "fy": fy_id, "on": as_on, "t": total, "v": voucher_id, "snap": json.dumps(rule_snapshot, default=str),
         "ev": engine_version, "actor": actor}).scalar_one()


def insert_run_line(conn: Connection, client_id: object, run_id: object, voucher_id: object, line: dict[str, Any]) -> None:
    conn.execute(
        text("INSERT INTO depreciation_run_lines (run_id, voucher_id, client_id, asset_id, method, cost, opening_accumulated, wdv_rate_percent, "
             "days_used, days_in_year, depreciation, closing_accumulated, details) VALUES (:run, :v, :c, :asset_id, :method, :cost, "
             ":opening_accumulated, :wdv_rate_percent, :days_used, :days_in_year, :depreciation, :closing_accumulated, CAST(:details AS jsonb))"),
        {"run": run_id, "v": voucher_id, "c": client_id, "details": json.dumps(line["details"], default=str),
         **{k: line[k] for k in ("asset_id", "method", "cost", "opening_accumulated", "wdv_rate_percent", "days_used", "days_in_year",
                                 "depreciation", "closing_accumulated")}})


def delete_run(conn: Connection, client_id: object, run_id: object) -> None:
    conn.execute(text("DELETE FROM depreciation_run_lines WHERE client_id = :c AND run_id = :r"), {"c": client_id, "r": run_id})
    conn.execute(text("DELETE FROM depreciation_runs WHERE client_id = :c AND id = :r"), {"c": client_id, "r": run_id})


# ------------------------------------------------------------------------------------------------ income-tax block working


def it_openings(conn: Connection, client_id: object, fy_id: object) -> dict[str, dict[str, Any]]:
    rows = conn.execute(text("SELECT block_key, opening_wdv, source FROM it_block_openings WHERE client_id = :c AND financial_year_id = :fy"),
                        {"c": client_id, "fy": fy_id})
    return {r[0]: {"opening_wdv": r[1].quantize(CENTS), "source": r[2]} for r in rows}


def upsert_it_opening(conn: Connection, client_id: object, fy_id: object, block_key: str, wdv: Decimal, actor: str) -> None:
    conn.execute(
        text("INSERT INTO it_block_openings (client_id, financial_year_id, block_key, opening_wdv, source, set_by) "
             "VALUES (:c, :fy, :b, :w, 'entered', :a) ON CONFLICT (client_id, financial_year_id, block_key) "
             "DO UPDATE SET opening_wdv = EXCLUDED.opening_wdv, source = 'entered', set_by = EXCLUDED.set_by, set_at = now()"),
        {"c": client_id, "fy": fy_id, "b": block_key, "w": wdv, "a": actor})


def final_workings(conn: Connection, client_id: object, fy_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT block_key, act, rate, rate_verification, opening_wdv, additions_full, additions_half, disposals, depreciation, "
             "closing_wdv, details FROM it_depreciation_workings WHERE client_id = :c AND financial_year_id = :fy AND status = 'final' "
             "AND superseded_at IS NULL ORDER BY block_key"), {"c": client_id, "fy": fy_id})
    return [{"block_key": r[0], "act": r[1], "rate": r[2], "rate_verification": r[3], "opening_wdv": r[4].quantize(CENTS),
             "additions_full": r[5].quantize(CENTS), "additions_half": r[6].quantize(CENTS), "disposals": r[7].quantize(CENTS),
             "depreciation": r[8].quantize(CENTS), "closing_wdv": r[9].quantize(CENTS), "details": r[10]} for r in rows]


def insert_final_working(conn: Connection, client_id: object, fy_id: object, w: dict[str, Any], engine_version: str, actor: str) -> None:
    conn.execute(
        text("INSERT INTO it_depreciation_workings (client_id, financial_year_id, block_key, status, act, rate, rate_verification, "
             "opening_wdv, additions_full, additions_half, disposals, depreciation, closing_wdv, details, engine_version, computed_by) "
             "VALUES (:c, :fy, :block_key, 'final', :act, :rate, :rate_verification, :opening_wdv, :additions_full, :additions_half, "
             ":disposals, :depreciation, :closing_wdv, CAST(:details AS jsonb), :ev, :actor)"),
        {"c": client_id, "fy": fy_id, "ev": engine_version, "actor": actor, "details": json.dumps(w["details"], default=str),
         **{k: w[k] for k in ("block_key", "act", "rate", "rate_verification", "opening_wdv", "additions_full", "additions_half",
                              "disposals", "depreciation", "closing_wdv")}})
