"""SQL for audit working papers, their items and notes (Phase 8, package E). SQL only: no rules. Reads audit_runs / audit_findings, never
writes to them or to any books table. Every function takes a Connection owned by the caller."""

import json
from typing import Any

from sqlalchemy import Connection, text

PAPER_COLUMNS = ("id, client_id, financial_year_id, run_id, check_id, status, population_count, population_digest, population_amount, "
                 "sample_method, sample_seed, sample_params, sample_ids, conclusion, created_by, created_at, updated_at, "
                 "signed_off_by, signed_off_at")


def get_run(conn: Connection, client_id: Any, run_id: Any) -> dict | None:
    row = conn.execute(text("SELECT id, financial_year_id, check_ids, summary FROM audit_runs WHERE id = :r AND client_id = :c"),
                       {"r": run_id, "c": client_id}).mappings().first()
    return dict(row) if row else None


def findings_of_check(conn: Connection, run_id: Any, check_id: str) -> list[dict]:
    rows = conn.execute(
        text("SELECT id, finding_key, severity, subject_kind, subject_ref, finding_date, amount, disallowance_amount, message, evidence "
             "FROM audit_findings WHERE run_id = :r AND check_id = :k ORDER BY finding_key"),
        {"r": run_id, "k": check_id}).mappings().all()
    return [dict(r) for r in rows]


def paper_for_run_check(conn: Connection, run_id: Any, check_id: str) -> Any | None:
    return conn.execute(text("SELECT id FROM audit_working_papers WHERE run_id = :r AND check_id = :k"),
                        {"r": run_id, "k": check_id}).scalar()


def insert_paper(conn: Connection, *, client_id: Any, financial_year_id: Any, run_id: Any, check_id: str, population_count: int,
                 population_digest: str | None, population_amount: Any, created_by: str) -> Any:
    return conn.execute(
        text("INSERT INTO audit_working_papers (client_id, financial_year_id, run_id, check_id, population_count, population_digest, "
             "population_amount, created_by) VALUES (:c, :fy, :r, :k, :n, :d, :a, :by) RETURNING id"),
        {"c": client_id, "fy": financial_year_id, "r": run_id, "k": check_id, "n": population_count, "d": population_digest,
         "a": population_amount, "by": created_by}).scalar_one()


def insert_items(conn: Connection, client_id: Any, paper_id: Any, finding_ids: list[Any]) -> None:
    if finding_ids:
        conn.execute(text("INSERT INTO audit_paper_items (client_id, paper_id, finding_id) VALUES (:c, :p, :f)"),
                     [{"c": client_id, "p": paper_id, "f": f} for f in finding_ids])


def get_paper(conn: Connection, client_id: Any, paper_id: Any, *, lock: bool = False) -> dict | None:
    row = conn.execute(text(f"SELECT {PAPER_COLUMNS} FROM audit_working_papers WHERE id = :p AND client_id = :c" + (" FOR UPDATE" if lock else "")),
                       {"p": paper_id, "c": client_id}).mappings().first()
    return dict(row) if row else None


def list_papers(conn: Connection, client_id: Any, *, run_id: Any = None, check_id: str | None = None, status: str | None = None) -> list[dict]:
    rows = conn.execute(
        text(f"SELECT {PAPER_COLUMNS}, (SELECT count(*) FROM audit_paper_items i WHERE i.paper_id = p.id) AS item_count, "
             "(SELECT count(*) FROM audit_paper_items i WHERE i.paper_id = p.id AND i.status = 'open') AS open_count "
             "FROM audit_working_papers p WHERE client_id = :c AND (CAST(:r AS uuid) IS NULL OR run_id = :r) "
             "AND (CAST(:k AS text) IS NULL OR check_id = :k) AND (CAST(:s AS text) IS NULL OR status = :s) ORDER BY created_at, id"),
        {"c": client_id, "r": run_id, "k": check_id, "s": status}).mappings().all()
    return [dict(r) for r in rows]


def list_items(conn: Connection, paper_id: Any) -> list[dict]:
    rows = conn.execute(
        text("SELECT i.id, i.finding_id, i.status, i.reviewer_note, i.decided_by, i.decided_at, f.finding_key, f.severity, f.subject_kind, "
             "f.subject_ref, f.finding_date, f.amount, f.disallowance_amount, f.message, f.evidence "
             "FROM audit_paper_items i JOIN audit_findings f ON f.id = i.finding_id WHERE i.paper_id = :p ORDER BY f.finding_key"),
        {"p": paper_id}).mappings().all()
    return [dict(r) for r in rows]


def get_item(conn: Connection, paper_id: Any, item_id: Any) -> dict | None:
    row = conn.execute(text("SELECT id, status, reviewer_note, decided_by, decided_at FROM audit_paper_items WHERE id = :i AND paper_id = :p"),
                       {"i": item_id, "p": paper_id}).mappings().first()
    return dict(row) if row else None


def item_statuses(conn: Connection, paper_id: Any) -> list[str]:
    return [r[0] for r in conn.execute(text("SELECT status FROM audit_paper_items WHERE paper_id = :p"), {"p": paper_id}).all()]


def decide_item(conn: Connection, item_id: Any, status: str, reviewer_note: str, actor: str) -> None:
    conn.execute(text("UPDATE audit_paper_items SET status = :s, reviewer_note = :n, decided_by = :a, decided_at = now() WHERE id = :i"),
                 {"s": status, "n": reviewer_note, "a": actor, "i": item_id})


def set_status(conn: Connection, paper_id: Any, status: str) -> None:
    conn.execute(text("UPDATE audit_working_papers SET status = :s WHERE id = :p"), {"s": status, "p": paper_id})


def sign_off(conn: Connection, paper_id: Any, conclusion: str, actor: str) -> Any:
    return conn.execute(
        text("UPDATE audit_working_papers SET status = 'signed_off', conclusion = :c, signed_off_by = :a, signed_off_at = now() "
             "WHERE id = :p RETURNING signed_off_at"),
        {"c": conclusion, "a": actor, "p": paper_id}).scalar_one()


def set_sample(conn: Connection, paper_id: Any, *, method: str, seed: int, params: dict, ids: list[str]) -> None:
    conn.execute(
        text("UPDATE audit_working_papers SET sample_method = :m, sample_seed = :s, sample_params = CAST(:pa AS jsonb), "
             "sample_ids = CAST(:ids AS jsonb) WHERE id = :p"),
        {"m": method, "s": seed, "pa": json.dumps(params), "ids": json.dumps(ids), "p": paper_id})


def insert_note(conn: Connection, client_id: Any, paper_id: Any, note: str, actor: str) -> Any:
    return conn.execute(text("INSERT INTO audit_paper_notes (client_id, paper_id, note, created_by) VALUES (:c, :p, :n, :a) RETURNING id"),
                        {"c": client_id, "p": paper_id, "n": note, "a": actor}).scalar_one()


def list_notes(conn: Connection, paper_id: Any) -> list[dict]:
    rows = conn.execute(text("SELECT id, note, created_by, created_at FROM audit_paper_notes WHERE paper_id = :p ORDER BY created_at, id"),
                        {"p": paper_id}).mappings().all()
    return [dict(r) for r in rows]
