"""Reads and writes of the Schedule III package (docs/PHASE6_PLAN.md, package D). SQL only; no accounting maths."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.final_sch3 import (
    FsLineRule,
    GroupDefault,
    LedgerOverride,
    RegisterDepLine,
    RegisterEvent,
)
from app.engine.final_types import ClosingStockIn, LedgerBalanceIn

CENTS = Decimal("0.01")


def client_info(conn: Connection, client_id: Any) -> dict | None:
    row = conn.execute(text("SELECT entity_type, business_type FROM clients WHERE id = :c"), {"c": client_id}).first()
    return None if row is None else {"entity_type": row[0], "business_type": row[1]}


def financial_year(conn: Connection, client_id: Any, fy_id: Any) -> tuple[Any, date, date] | None:
    row = conn.execute(text("SELECT id, start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"),
                       {"f": fy_id, "c": client_id}).first()
    return None if row is None else (row[0], row[1], row[2])


def previous_financial_year(conn: Connection, client_id: Any, start: date) -> tuple[Any, date, date] | None:
    row = conn.execute(text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c AND end_date = :d"),
                       {"c": client_id, "d": start - timedelta(days=1)}).first()
    return None if row is None else (row[0], row[1], row[2])


def fs_line_rows(conn: Connection, on: date) -> list[dict]:
    rows = conn.execute(text(
        "SELECT format_key, line_code, label, section, sort_order, note_title, cf_class, verification_status, source_reference, "
        "effective_from FROM fs_lines WHERE effective_from <= :d AND (effective_to IS NULL OR effective_to >= :d) "
        "ORDER BY format_key, sort_order"), {"d": on})
    return [dict(r._mapping) for r in rows]


def to_rules(rows: list[dict]) -> tuple[FsLineRule, ...]:
    return tuple(FsLineRule(r["format_key"], r["line_code"], r["label"], r["section"], r["sort_order"], r["note_title"], r["cf_class"],
                            r["verification_status"], r["source_reference"]) for r in rows)


def group_map_rows(conn: Connection, on: date) -> list[dict]:
    rows = conn.execute(text(
        "SELECT group_code, format_key, line_code, is_firm, verification_status, source_reference FROM fs_group_map "
        "WHERE effective_from <= :d AND (effective_to IS NULL OR effective_to >= :d)"), {"d": on})
    return [dict(r._mapping) for r in rows]


def to_defaults(rows: list[dict]) -> tuple[GroupDefault, ...]:
    return tuple(GroupDefault(r["group_code"], r["format_key"], r["line_code"], r["is_firm"]) for r in rows)


def known_line_formats(conn: Connection) -> dict[str, str]:
    """line_code -> format_key over every row of fs_lines (any date): what a classification may point to."""
    return {r[0]: r[1] for r in conn.execute(text("SELECT DISTINCT line_code, format_key FROM fs_lines"))}


def overrides(conn: Connection, client_id: Any) -> dict[Any, LedgerOverride]:
    rows = conn.execute(text("SELECT ledger_id, line_code, cf_class FROM client_ledger_fs_map WHERE client_id = :c"), {"c": client_id})
    return {r[0]: LedgerOverride(r[1], r[2]) for r in rows}


def override_row(conn: Connection, client_id: Any, ledger_id: Any) -> dict | None:
    row = conn.execute(text("SELECT line_code, cf_class, note FROM client_ledger_fs_map WHERE client_id = :c AND ledger_id = :l"),
                       {"c": client_id, "l": ledger_id}).first()
    return None if row is None else {"line_code": row[0], "cf_class": row[1], "note": row[2]}


def ledger_info(conn: Connection, client_id: Any, ledger_id: Any) -> dict | None:
    row = conn.execute(text("SELECT l.name, g.nature FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
                            "WHERE l.id = :l AND l.client_id = :c"), {"l": ledger_id, "c": client_id}).first()
    return None if row is None else {"name": row[0], "nature": row[1]}


def upsert_override(conn: Connection, client_id: Any, ledger_id: Any, line_code: str | None, cf_class: str | None,
                    note: str | None, actor: str) -> None:
    conn.execute(text(
        "INSERT INTO client_ledger_fs_map (client_id, ledger_id, line_code, cf_class, note, set_by) "
        "VALUES (:c, :l, :line, :cf, :n, :a) ON CONFLICT (client_id, ledger_id) DO UPDATE SET line_code = EXCLUDED.line_code, "
        "cf_class = EXCLUDED.cf_class, note = EXCLUDED.note, set_by = EXCLUDED.set_by, set_at = now()"),
        {"c": client_id, "l": ledger_id, "line": line_code, "cf": cf_class, "n": note, "a": actor})


def delete_override(conn: Connection, client_id: Any, ledger_id: Any) -> None:
    conn.execute(text("DELETE FROM client_ledger_fs_map WHERE client_id = :c AND ledger_id = :l"), {"c": client_id, "l": ledger_id})


def ledger_positions(conn: Connection, client_id: Any, fy_id: Any, as_on: date) -> list[LedgerBalanceIn]:
    """Opening + the year's posted / reversed lines up to `as_on`, EXCLUDING the year-end closing vouchers and their reversals
    (decision 2 of the Phase 6 plan). Debit positive."""
    rows = conn.execute(text(
        "SELECT l.id, l.name, g.code, p.code, g.nature, coalesce(ob.debit, 0) - coalesce(ob.credit, 0), "
        "coalesce(s.dr, 0), coalesce(s.cr, 0), r.role "
        "FROM ledgers l JOIN account_groups g ON g.id = l.group_id LEFT JOIN account_groups p ON p.id = g.parent_id "
        "LEFT JOIN opening_balances ob ON ob.ledger_id = l.id AND ob.financial_year_id = :fy "
        "LEFT JOIN (SELECT vl.ledger_id, sum(vl.debit) AS dr, sum(vl.credit) AS cr FROM voucher_lines vl "
        "  JOIN vouchers v ON v.id = vl.voucher_id WHERE v.client_id = :c AND v.financial_year_id = :fy "
        "  AND v.status IN ('posted', 'reversed') AND v.voucher_date <= :d "
        "  AND v.id NOT IN (SELECT voucher_id FROM year_end_close_vouchers WHERE client_id = :c) GROUP BY vl.ledger_id) s "
        "  ON s.ledger_id = l.id "
        "LEFT JOIN final_ledger_roles r ON r.ledger_id = l.id AND r.client_id = l.client_id "
        "WHERE l.client_id = :c ORDER BY l.name"), {"c": client_id, "fy": fy_id, "d": as_on})
    out = []
    for lid, name, group, parent, nature, opening, dr, cr, role in rows:
        opening, dr, cr = opening.quantize(CENTS), dr.quantize(CENTS), cr.quantize(CENTS)
        out.append(LedgerBalanceIn(ledger_id=lid, name=name, group_code=group, parent_group_code=parent, nature=nature, opening=opening,
                                   debit_total=dr, credit_total=cr, closing=opening + dr - cr, role=role))
    return out


def approved_closing_stock(conn: Connection, client_id: Any, fy_id: Any) -> tuple[ClosingStockIn, str | None] | None:
    row = conn.execute(text(
        "SELECT cost_value, write_down, carrying_value, source, as_on_date, inventory_method FROM final_closing_stock "
        "WHERE client_id = :c AND financial_year_id = :f"), {"c": client_id, "f": fy_id}).first()
    if row is None:
        return None
    return ClosingStockIn(row[0].quantize(CENTS), row[1].quantize(CENTS), row[2].quantize(CENTS), row[3], row[4]), row[5]


def snapshot_payload(conn: Connection, client_id: Any, fy_id: Any, statement_key: str) -> dict | None:
    row = conn.execute(text(
        "SELECT payload FROM statement_snapshots WHERE client_id = :c AND financial_year_id = :f AND statement_key = :k "
        "AND format_key = 'sch3' AND is_final AND superseded_at IS NULL"), {"c": client_id, "f": fy_id, "k": statement_key}).first()
    return None if row is None else row[0]


def year_has_data(conn: Connection, client_id: Any, fy_id: Any) -> bool:
    row = conn.execute(text(
        "SELECT (SELECT count(*) FROM opening_balances WHERE client_id = :c AND financial_year_id = :f) "
        "+ (SELECT count(*) FROM vouchers WHERE client_id = :c AND financial_year_id = :f AND status IN ('posted', 'reversed'))"),
        {"c": client_id, "f": fy_id}).first()
    return bool(row and row[0] > 0)


def register_inputs(conn: Connection, client_id: Any) -> tuple[tuple[tuple[Any, str], ...], tuple[RegisterEvent, ...],
                                                                tuple[RegisterDepLine, ...]]:
    """Assets, their events and the depreciation of POSTED book runs (a reversed or draft run has no effect on the ledgers)."""
    assets = tuple((r[0], r[1]) for r in conn.execute(
        text("SELECT id, name FROM fixed_assets WHERE client_id = :c ORDER BY asset_no"), {"c": client_id}))
    events = tuple(RegisterEvent(r[0], r[1], r[2], r[3].quantize(CENTS), r[4].quantize(CENTS)) for r in conn.execute(
        text("SELECT asset_id, kind, event_date, amount, accumulated_dep_bf FROM fixed_asset_events WHERE client_id = :c"),
        {"c": client_id}))
    dep = tuple(RegisterDepLine(r[0], r[1], r[2].quantize(CENTS)) for r in conn.execute(text(
        "SELECT rl.asset_id, fy.end_date, rl.depreciation FROM depreciation_run_lines rl "
        "JOIN depreciation_runs dr ON dr.id = rl.run_id JOIN financial_years fy ON fy.id = dr.financial_year_id "
        "JOIN vouchers v ON v.id = dr.voucher_id WHERE rl.client_id = :c AND v.status = 'posted'"), {"c": client_id}))
    return assets, events, dep
