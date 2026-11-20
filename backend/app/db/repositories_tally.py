"""SQL of the Tally import / export (Phase 7 package B). Plain functions over a Connection; no accounting decisions here."""

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class LedgerInfo:
    id: Any
    name: str
    group_id: Any
    group_code: str
    group_name: str
    nature: str


def document_row(conn: Connection, client_id: Any, document_id: Any) -> dict | None:
    row = conn.execute(text("SELECT id, doc_type FROM documents WHERE id = :d AND client_id = :c"),
                       {"d": document_id, "c": client_id}).mappings().first()
    return dict(row) if row else None


def client_name(conn: Connection, client_id: Any) -> str | None:
    row = conn.execute(text("SELECT name FROM clients WHERE id = :c"), {"c": client_id}).first()
    return row[0] if row else None


def system_groups(conn: Connection) -> dict[str, Any]:
    """code -> id of the system groups."""
    return {code: gid for gid, code in conn.execute(text("SELECT id, code FROM account_groups WHERE client_id IS NULL"))}


def group_info(conn: Connection, client_id: Any, group_id: Any) -> dict | None:
    row = conn.execute(
        text("SELECT id, code, name, nature FROM account_groups WHERE id = :g AND (client_id IS NULL OR client_id = :c)"),
        {"g": group_id, "c": client_id}).mappings().first()
    return dict(row) if row else None


def ledgers_by_name(conn: Connection, client_id: Any) -> dict[str, LedgerInfo]:
    """lower(name) -> ledger with its group."""
    rows = conn.execute(
        text("SELECT l.id, l.name, g.id, g.code, g.name, g.nature FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
             "WHERE l.client_id = :c"), {"c": client_id})
    return {name.lower(): LedgerInfo(lid, name, gid, code, gname, nature) for lid, name, gid, code, gname, nature in rows}


def ledger_info(conn: Connection, client_id: Any, ledger_id: Any) -> LedgerInfo | None:
    row = conn.execute(
        text("SELECT l.id, l.name, g.id, g.code, g.name, g.nature FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
             "WHERE l.id = :l AND l.client_id = :c"), {"l": ledger_id, "c": client_id}).first()
    return LedgerInfo(*row) if row else None


def ledger_groups(conn: Connection, client_id: Any, ledger_ids: list) -> dict[Any, str]:
    """ledger id -> group code."""
    if not ledger_ids:
        return {}
    rows = conn.execute(
        text("SELECT l.id, g.code FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
             "WHERE l.client_id = :c AND l.id = ANY(:ids)"), {"c": client_id, "ids": list(ledger_ids)})
    return dict(rows.all())


def items_by_name(conn: Connection, client_id: Any) -> dict[str, Any]:
    return {name.lower(): iid for iid, name in conn.execute(text("SELECT id, name FROM gst_items WHERE client_id = :c"), {"c": client_id})}


def item_exists(conn: Connection, client_id: Any, item_id: Any) -> bool:
    return conn.execute(text("SELECT 1 FROM gst_items WHERE id = :i AND client_id = :c"), {"i": item_id, "c": client_id}).first() is not None


# ------------------------------------------------------------------------------------------------ imports


def import_for_document(conn: Connection, client_id: Any, document_id: Any) -> Any | None:
    row = conn.execute(text("SELECT id FROM tally_imports WHERE client_id = :c AND document_id = :d"),
                       {"c": client_id, "d": document_id}).first()
    return row[0] if row else None


def insert_import(conn: Connection, client_id: Any, document_id: Any, company: str | None, counts: dict, report: dict, actor: str) -> Any:
    return conn.execute(
        text("INSERT INTO tally_imports (client_id, document_id, company_name, counts, mapping_report, created_by) "
             "VALUES (:c, :d, :n, CAST(:counts AS jsonb), CAST(:report AS jsonb), :by) RETURNING id"),
        {"c": client_id, "d": document_id, "n": company, "counts": json.dumps(counts), "report": json.dumps(report, default=str), "by": actor},
    ).scalar_one()


def set_import_report(conn: Connection, import_id: Any, counts: dict, report: dict) -> None:
    conn.execute(text("UPDATE tally_imports SET counts = CAST(:c AS jsonb), mapping_report = CAST(:r AS jsonb) WHERE id = :i"),
                 {"c": json.dumps(counts), "r": json.dumps(report, default=str), "i": import_id})


def get_import(conn: Connection, client_id: Any, import_id: Any) -> dict | None:
    row = conn.execute(
        text("SELECT id, document_id, status, company_name, counts, mapping_report, created_by, created_at FROM tally_imports "
             "WHERE id = :i AND client_id = :c"), {"i": import_id, "c": client_id}).mappings().first()
    return dict(row) if row else None


def list_imports(conn: Connection, client_id: Any) -> list[dict]:
    rows = conn.execute(
        text("SELECT id, document_id, status, company_name, counts, created_by, created_at FROM tally_imports "
             "WHERE client_id = :c ORDER BY created_at DESC"), {"c": client_id}).mappings()
    return [dict(r) for r in rows]


def set_import_status(conn: Connection, import_id: Any, status: str) -> None:
    conn.execute(text("UPDATE tally_imports SET status = :s WHERE id = :i"), {"s": status, "i": import_id})


# ------------------------------------------------------------------------------------------------ master map

MAP_COLUMNS = ("id, kind, source_name, source_name_key, source_parent, import_id, target_group_id, target_ledger_id, target_item_id, "
               "decision, reason, decided_by, decided_at")


def master_rows(conn: Connection, client_id: Any, *, kind: str | None = None, decision: str | None = None,
                import_id: Any = None) -> list[dict]:
    sql = f"SELECT {MAP_COLUMNS} FROM tally_master_map WHERE client_id = :c"
    params: dict[str, Any] = {"c": client_id}
    for column, value in (("kind", kind), ("decision", decision), ("import_id", import_id)):
        if value is not None:
            sql += f" AND {column} = :{column}"
            params[column] = value
    return [dict(r) for r in conn.execute(text(sql + " ORDER BY kind, source_name_key"), params).mappings()]


def master_row(conn: Connection, client_id: Any, master_id: Any) -> dict | None:
    row = conn.execute(text(f"SELECT {MAP_COLUMNS} FROM tally_master_map WHERE id = :i AND client_id = :c"),
                       {"i": master_id, "c": client_id}).mappings().first()
    return dict(row) if row else None


def insert_master(conn: Connection, client_id: Any, import_id: Any, kind: str, name: str, key: str, parent: str | None,
                  target_group_id: Any, target_ledger_id: Any, target_item_id: Any, reason: str) -> None:
    conn.execute(
        text("INSERT INTO tally_master_map (client_id, kind, source_name, source_name_key, source_parent, import_id, target_group_id, "
             "target_ledger_id, target_item_id, decision, reason) VALUES (:c, :k, :n, :key, :p, :i, :g, :l, :t, 'suggested', :r)"),
        {"c": client_id, "k": kind, "n": name, "key": key, "p": parent, "i": import_id, "g": target_group_id, "l": target_ledger_id,
         "t": target_item_id, "r": reason})


def refresh_suggested_master(conn: Connection, master_id: Any, import_id: Any, parent: str | None, target_group_id: Any,
                             target_ledger_id: Any, target_item_id: Any, reason: str) -> None:
    conn.execute(
        text("UPDATE tally_master_map SET import_id = :i, source_parent = :p, target_group_id = :g, target_ledger_id = :l, "
             "target_item_id = :t, reason = :r WHERE id = :m"),
        {"i": import_id, "p": parent, "g": target_group_id, "l": target_ledger_id, "t": target_item_id, "r": reason, "m": master_id})


def touch_decided_master(conn: Connection, master_id: Any, import_id: Any, parent: str | None) -> None:
    conn.execute(text("UPDATE tally_master_map SET import_id = :i, source_parent = :p WHERE id = :m"),
                 {"i": import_id, "p": parent, "m": master_id})


def decide_master(conn: Connection, master_id: Any, *, decision: str, target_group_id: Any, target_ledger_id: Any, target_item_id: Any,
                  reason: str, actor: str) -> None:
    conn.execute(
        text("UPDATE tally_master_map SET decision = :d, target_group_id = :g, target_ledger_id = :l, target_item_id = :t, "
             "reason = :r, decided_by = :by, decided_at = now() WHERE id = :m"),
        {"d": decision, "g": target_group_id, "l": target_ledger_id, "t": target_item_id, "r": reason, "by": actor, "m": master_id})


def set_created_target(conn: Connection, master_id: Any, *, ledger_id: Any = None, item_id: Any = None) -> None:
    conn.execute(text("UPDATE tally_master_map SET target_ledger_id = COALESCE(:l, target_ledger_id), "
                      "target_item_id = COALESCE(:t, target_item_id) WHERE id = :m"), {"l": ledger_id, "t": item_id, "m": master_id})


def exact_ledger_matches(conn: Connection, client_id: Any, import_id: Any) -> list[Any]:
    """Suggested ledger rows whose existing ledger sits in exactly the suggested group."""
    rows = conn.execute(
        text("SELECT m.id FROM tally_master_map m JOIN ledgers l ON l.id = m.target_ledger_id AND l.group_id = m.target_group_id "
             "WHERE m.client_id = :c AND m.import_id = :i AND m.kind = 'ledger' AND m.decision = 'suggested'"),
        {"c": client_id, "i": import_id})
    return [r[0] for r in rows]


# ------------------------------------------------------------------------------------------------ queue


def live_refs(conn: Connection, client_id: Any) -> tuple[set[str], set[str]]:
    """(source_refs, fallback refs) of Tally vouchers that are queued and not rejected (D-37)."""
    refs: set[str] = set()
    fallbacks: set[str] = set()
    rows = conn.execute(
        text("SELECT source_ref, edited_payload ->> 'fallback_ref' FROM approval_queue_items "
             "WHERE client_id = :c AND kind = 'tally_voucher' AND status <> 'rejected'"), {"c": client_id})
    for ref, fb in rows:
        refs.add(ref)
        if fb:
            fallbacks.add(fb)
    return refs, fallbacks


# ------------------------------------------------------------------------------------------------ export


def posted_vouchers(conn: Connection, client_id: Any, start: date | None, end: date | None) -> list[dict]:
    rows = conn.execute(
        text("SELECT v.id, v.voucher_type, v.voucher_date, v.voucher_number, v.narration, v.reference_no, p.name AS party "
             "FROM vouchers v LEFT JOIN ledgers p ON p.id = v.party_ledger_id "
             "WHERE v.client_id = :c AND v.status IN ('posted', 'reversed') AND (CAST(:s AS date) IS NULL OR v.voucher_date >= :s) "
             "AND (CAST(:e AS date) IS NULL OR v.voucher_date <= :e) ORDER BY v.voucher_date, v.voucher_type, v.voucher_number"),
        {"c": client_id, "s": start, "e": end}).mappings()
    return [dict(r) for r in rows]


def voucher_lines(conn: Connection, voucher_ids: list) -> dict[Any, list[tuple[str, Any, Any]]]:
    out: dict[Any, list] = {}
    if not voucher_ids:
        return out
    rows = conn.execute(
        text("SELECT vl.voucher_id, l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
             "WHERE vl.voucher_id = ANY(:ids) ORDER BY vl.voucher_id, vl.line_no"), {"ids": list(voucher_ids)})
    for vid, name, debit, credit in rows:
        out.setdefault(vid, []).append((name, debit, credit))
    return out


def unposted_count(conn: Connection, client_id: Any, start: date | None, end: date | None) -> int:
    return conn.execute(
        text("SELECT count(*) FROM vouchers WHERE client_id = :c AND status IN ('draft', 'approved') "
             "AND (CAST(:s AS date) IS NULL OR voucher_date >= :s) AND (CAST(:e AS date) IS NULL OR voucher_date <= :e)"),
        {"c": client_id, "s": start, "e": end}).scalar_one()


def all_ledgers_with_groups(conn: Connection, client_id: Any) -> list[tuple[str, str, bool]]:
    """(ledger name, group name, group is custom) ordered by name."""
    rows = conn.execute(
        text("SELECT l.name, g.name, g.client_id IS NOT NULL FROM ledgers l JOIN account_groups g ON g.id = l.group_id "
             "WHERE l.client_id = :c ORDER BY lower(l.name)"), {"c": client_id})
    return [(a, b, c) for a, b, c in rows]


def custom_groups(conn: Connection, client_id: Any) -> list[tuple[str, str]]:
    """(group name, parent group name) of the client's own groups, parents before children."""
    rows = conn.execute(
        text("WITH RECURSIVE t AS (SELECT g.id, g.name, p.name AS parent, 1 AS depth FROM account_groups g "
             "JOIN account_groups p ON p.id = g.parent_id WHERE g.client_id = :c AND p.client_id IS NULL "
             "UNION ALL SELECT g.id, g.name, p.name, t.depth + 1 FROM account_groups g JOIN t ON g.parent_id = t.id "
             "JOIN account_groups p ON p.id = g.parent_id WHERE g.client_id = :c) SELECT name, parent FROM t ORDER BY depth, lower(name)"),
        {"c": client_id})
    return [(a, b) for a, b in rows]


def financial_year(conn: Connection, client_id: Any, fy_id: Any) -> tuple[date, date] | None:
    row = conn.execute(text("SELECT start_date, end_date FROM financial_years WHERE id = :i AND client_id = :c"),
                       {"i": fy_id, "c": client_id}).first()
    return (row[0], row[1]) if row else None


def insert_export(conn: Connection, client_id: Any, document_id: Any, kind: str, start: date | None, end: date | None,
                  masters: int, vouchers: int, actor: str) -> Any:
    return conn.execute(
        text("INSERT INTO tally_exports (client_id, document_id, kind, from_date, to_date, master_count, voucher_count, created_by) "
             "VALUES (:c, :d, :k, :s, :e, :m, :v, :by) RETURNING id"),
        {"c": client_id, "d": document_id, "k": kind, "s": start, "e": end, "m": masters, "v": vouchers, "by": actor}).scalar_one()


def list_exports(conn: Connection, client_id: Any) -> list[dict]:
    rows = conn.execute(
        text("SELECT id, document_id, kind, from_date, to_date, master_count, voucher_count, created_by, created_at FROM tally_exports "
             "WHERE client_id = :c ORDER BY created_at DESC"), {"c": client_id}).mappings()
    return [dict(r) for r in rows]
