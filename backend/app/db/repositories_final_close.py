"""SQL of the Phase 6 year-end close (package F): the close record, voucher links, snapshots, carried openings, next year. No accounting
maths. Services never commit."""

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

CENTS = Decimal("0.01")


def lock_year(conn: Connection, client_id: object, fy_id: object) -> None:
    conn.execute(text("SELECT id FROM financial_years WHERE id = :f AND client_id = :c FOR UPDATE"), {"f": fy_id, "c": client_id}).all()


def get_close(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any] | None:
    """The current close row of the year: the 'closed' one, else the latest 'reopened' one."""
    row = conn.execute(
        text("SELECT id, status, next_financial_year_id, net_profit, appropriation, carried, closed_by, closed_at, reopened_by, reopened_at, "
             "reopen_reason FROM year_end_closes WHERE client_id = :c AND financial_year_id = :f "
             "ORDER BY (status = 'closed') DESC, closed_at DESC LIMIT 1"), {"c": client_id, "f": fy_id}).first()
    if row is None:
        return None
    keys = ("id", "status", "next_financial_year_id", "net_profit", "appropriation", "carried", "closed_by", "closed_at", "reopened_by",
            "reopened_at", "reopen_reason")
    out = dict(zip(keys, row, strict=True))
    out["net_profit"] = out["net_profit"].quantize(CENTS)
    return out


def get_close_by_id(conn: Connection, client_id: object, close_id: object) -> tuple[dict[str, Any], object] | None:
    row = conn.execute(text("SELECT financial_year_id FROM year_end_closes WHERE id = :i AND client_id = :c"), {"i": close_id, "c": client_id}).first()
    if row is None:
        return None
    close = get_close_row(conn, client_id, close_id)
    return close, row[0]


def get_close_row(conn: Connection, client_id: object, close_id: object) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT id, status, next_financial_year_id, net_profit, appropriation, carried FROM year_end_closes WHERE id = :i AND client_id = :c"),
        {"i": close_id, "c": client_id}).one()
    return {"id": row[0], "status": row[1], "next_financial_year_id": row[2], "net_profit": row[3].quantize(CENTS), "appropriation": row[4], "carried": row[5]}


def insert_close(conn: Connection, client_id: object, fy_id: object, next_fy_id: object, net_profit: Decimal, appropriation: dict, carried: dict,
                 actor: str) -> object:
    cid = uuid.uuid4()
    conn.execute(
        text("INSERT INTO year_end_closes (id, client_id, financial_year_id, next_financial_year_id, status, net_profit, appropriation, carried, "
             "closed_by) VALUES (:i, :c, :f, :n, 'closed', :p, CAST(:a AS jsonb), CAST(:r AS jsonb), :by)"),
        {"i": cid, "c": client_id, "f": fy_id, "n": next_fy_id, "p": net_profit, "a": json.dumps(appropriation, default=str),
         "r": json.dumps(carried, default=str), "by": actor})
    return cid


def link_voucher(conn: Connection, close_id: object, client_id: object, step: str, kind: str, voucher_id: object) -> None:
    conn.execute(text("INSERT INTO year_end_close_vouchers (close_id, client_id, step, kind, voucher_id) VALUES (:i, :c, :s, :k, :v)"),
                 {"i": close_id, "c": client_id, "s": step, "k": kind, "v": voucher_id})


def close_vouchers(conn: Connection, close_id: object, kind: str) -> dict[str, object]:
    rows = conn.execute(text("SELECT step, voucher_id FROM year_end_close_vouchers WHERE close_id = :i AND kind = :k"), {"i": close_id, "k": kind})
    return {r[0]: r[1] for r in rows}


def mark_reopened(conn: Connection, close_id: object, actor: str, reason: str) -> None:
    conn.execute(text("UPDATE year_end_closes SET status = 'reopened', reopened_by = :by, reopened_at = now(), reopen_reason = :r WHERE id = :i"),
                 {"by": actor, "r": reason, "i": close_id})


# ---------------------------------------------------------------------------------------------- snapshots / workings


def insert_snapshot(conn: Connection, client_id: object, fy_id: object, key: str, fmt: str, payload: dict, engine_version: str, actor: str) -> None:
    body = json.dumps(payload, sort_keys=True, default=str)
    conn.execute(
        text("INSERT INTO statement_snapshots (client_id, financial_year_id, statement_key, format_key, payload, payload_sha256, engine_version, "
             "is_final, generated_by) VALUES (:c, :f, :k, :fm, CAST(:p AS jsonb), :h, :ev, true, :by)"),
        {"c": client_id, "f": fy_id, "k": key, "fm": fmt, "p": body, "h": hashlib.sha256(body.encode()).hexdigest(), "ev": engine_version, "by": actor})


def supersede_final(conn: Connection, client_id: object, fy_id: object) -> tuple[int, int]:
    s = conn.execute(text("UPDATE statement_snapshots SET superseded_at = now() WHERE client_id = :c AND financial_year_id = :f AND is_final "
                          "AND superseded_at IS NULL"), {"c": client_id, "f": fy_id}).rowcount
    w = conn.execute(text("UPDATE it_depreciation_workings SET superseded_at = now() WHERE client_id = :c AND financial_year_id = :f "
                          "AND status = 'final' AND superseded_at IS NULL"), {"c": client_id, "f": fy_id}).rowcount
    return s, w


# ---------------------------------------------------------------------------------------------- prerequisites


def open_voucher_count(conn: Connection, client_id: object, start: date, end: date) -> int:
    return conn.execute(text("SELECT count(*) FROM vouchers WHERE client_id = :c AND status IN ('draft', 'approved') "
                             "AND voucher_date BETWEEN :s AND :e"), {"c": client_id, "s": start, "e": end}).scalar_one()


def has_depreciable_assets(conn: Connection, client_id: object, start: date, end: date) -> bool:
    return conn.execute(
        text("SELECT 1 FROM fixed_assets a WHERE a.client_id = :c AND a.is_depreciable AND a.is_active "
             "AND EXISTS (SELECT 1 FROM fixed_asset_events e WHERE e.asset_id = a.id AND e.kind <> 'disposal' AND e.event_date <= :e) "
             "AND NOT EXISTS (SELECT 1 FROM fixed_asset_events d WHERE d.asset_id = a.id AND d.kind = 'disposal' AND d.event_date < :s) LIMIT 1"),
        {"c": client_id, "s": start, "e": end}).first() is not None


def has_posted_depreciation_run(conn: Connection, client_id: object, fy_id: object) -> bool:
    return conn.execute(
        text("SELECT 1 FROM depreciation_runs r JOIN vouchers v ON v.id = r.voucher_id WHERE r.client_id = :c AND r.financial_year_id = :f "
             "AND v.status = 'posted' LIMIT 1"), {"c": client_id, "f": fy_id}).first() is not None


def next_year(conn: Connection, client_id: object, fy_end: date) -> tuple[object, date, date] | None:
    row = conn.execute(text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c AND start_date = :s"),
                       {"c": client_id, "s": date.fromordinal(fy_end.toordinal() + 1)}).first()
    return None if row is None else (row[0], row[1], row[2])


def insert_year(conn: Connection, client_id: object, start: date, end: date, periods: list[tuple[date, date]]) -> object:
    fy_id = uuid.uuid4()
    conn.execute(text("INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (:i, :c, :s, :e)"),
                 {"i": fy_id, "c": client_id, "s": start, "e": end})
    conn.execute(text("INSERT INTO periods (id, client_id, financial_year_id, period_start, period_end) VALUES (:i, :c, :f, :s, :e)"),
                 [{"i": uuid.uuid4(), "c": client_id, "f": fy_id, "s": s, "e": e} for s, e in periods])
    return fy_id


def posted_voucher_in_year(conn: Connection, client_id: object, fy_id: object) -> bool:
    return conn.execute(text("SELECT 1 FROM vouchers WHERE client_id = :c AND financial_year_id = :f AND status IN ('posted', 'reversed') LIMIT 1"),
                        {"c": client_id, "f": fy_id}).first() is not None


# ---------------------------------------------------------------------------------------------- carried openings


def count_openings(conn: Connection, client_id: object, fy_id: object) -> dict[str, int]:
    out = {}
    for name, table in (("ledgers", "opening_balances"), ("bills", "opening_bills"), ("stock", "stock_opening"), ("it_blocks", "it_block_openings")):
        out[name] = conn.execute(text(f"SELECT count(*) FROM {table} WHERE client_id = :c AND financial_year_id = :f"), {"c": client_id, "f": fy_id}).scalar_one()
    return out


def insert_ledger_openings(conn: Connection, client_id: object, fy_id: object, rows: list[tuple]) -> None:
    if rows:
        conn.execute(text("INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) VALUES (:c, :l, :f, :d, :cr)"),
                     [{"c": client_id, "l": lid, "f": fy_id, "d": d, "cr": cr} for lid, d, cr in rows])


def insert_bills(conn: Connection, client_id: object, fy_id: object, bills: list[Any]) -> None:
    if bills:
        conn.execute(text("INSERT INTO opening_bills (client_id, financial_year_id, party_ledger_id, bill_ref, bill_date, due_date, debit, credit) "
                          "VALUES (:c, :f, :p, :r, :bd, :dd, :d, :cr)"),
                     [{"c": client_id, "f": fy_id, "p": b.party_ledger_id, "r": b.bill_ref, "bd": b.bill_date, "dd": b.due_date,
                       "d": max(b.amount, Decimal(0)), "cr": max(-b.amount, Decimal(0))} for b in bills])


def insert_stock(conn: Connection, client_id: object, fy_id: object, rows: list[Any], actor: str) -> None:
    if rows:
        conn.execute(text("INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
                          "VALUES (:c, :f, :i, :g, :q, :v, :by)"),
                     [{"c": client_id, "f": fy_id, "i": r.item_id, "g": r.godown_id, "q": r.quantity, "v": r.value, "by": actor} for r in rows])


def insert_it_openings(conn: Connection, client_id: object, fy_id: object, rows: list[tuple[str, Decimal]], actor: str) -> None:
    if rows:
        conn.execute(text("INSERT INTO it_block_openings (client_id, financial_year_id, block_key, opening_wdv, source, set_by) "
                          "VALUES (:c, :f, :b, :w, 'carried', :by)"),
                     [{"c": client_id, "f": fy_id, "b": b, "w": w, "by": actor} for b, w in rows])


def current_ledger_openings(conn: Connection, client_id: object, fy_id: object) -> dict[object, tuple[Decimal, Decimal]]:
    rows = conn.execute(text("SELECT ledger_id, debit, credit FROM opening_balances WHERE client_id = :c AND financial_year_id = :f"),
                        {"c": client_id, "f": fy_id})
    return {r[0]: (r[1].quantize(CENTS), r[2].quantize(CENTS)) for r in rows}


def delete_openings(conn: Connection, client_id: object, fy_id: object) -> None:
    for table in ("opening_balances", "opening_bills", "stock_opening", "it_block_openings"):
        conn.execute(text(f"DELETE FROM {table} WHERE client_id = :c AND financial_year_id = :f"), {"c": client_id, "f": fy_id})


def lock_periods(conn: Connection, client_id: object, fy_id: object) -> list[object]:
    return [r[0] for r in conn.execute(text("SELECT id FROM periods WHERE client_id = :c AND financial_year_id = :f AND status = 'open' ORDER BY period_start"),
                                       {"c": client_id, "f": fy_id})]


def locked_periods(conn: Connection, client_id: object, fy_id: object) -> list[object]:
    return [r[0] for r in conn.execute(text("SELECT id FROM periods WHERE client_id = :c AND financial_year_id = :f AND status = 'locked' ORDER BY period_start"),
                                       {"c": client_id, "f": fy_id})]

