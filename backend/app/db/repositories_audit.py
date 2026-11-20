"""SQL for the audit runs, findings and the audit rule / check catalogue (Phase 8, package A). Reads the books never; writes only audit_* tables."""

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.engine.audit_types import LimitRule

CENTS = Decimal("0.01")


def financial_year(conn: Connection, client_id: object, fy_id: object) -> tuple[date, date] | None:
    row = conn.execute(text("SELECT start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"),
                       {"f": fy_id, "c": client_id}).first()
    return (row[0], row[1]) if row else None


def catalogue(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(text(
        "SELECT check_id, title, description, rule_text, severity, category, evidence_query, rule_key, active "
        "FROM audit_checks ORDER BY sort_order, check_id")).mappings()
    return [dict(r) for r in rows]


def rule_limits(conn: Connection) -> list[LimitRule]:
    rows = conn.execute(text(
        "SELECT rule_key, law, section_ref, amount, breach_when, disallow_percent, effective_from, effective_to, verification_status "
        "FROM audit_rule_limits ORDER BY rule_key, effective_from"))
    return [LimitRule(r[0], r[1], r[2], r[3].quantize(CENTS), r[4],
                      None if r[5] is None else r[5].quantize(CENTS), r[6], r[7], r[8]) for r in rows]


def rule_rows(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(text(
        "SELECT rule_key, law, section_ref, amount, breach_when, disallow_percent, effective_from, effective_to, source_reference, "
        "verification_status, notes FROM audit_rule_limits ORDER BY rule_key, effective_from")).mappings()
    return [dict(r) for r in rows]


def insert_run(conn: Connection, client_id: object, fy_id: object, from_date: date, to_date: date, check_ids: list[str], params: dict,
               rules_used: list[dict], engine_version: str, status: str, finding_count: int, summary: dict, error: str | None,
               actor: str) -> object:
    return conn.execute(text(
        "INSERT INTO audit_runs (client_id, financial_year_id, from_date, to_date, check_ids, params, rules_used, engine_version, status, "
        "finding_count, summary, error_message, created_by) VALUES (:c, :fy, :f, :t, :ids, CAST(:p AS jsonb), CAST(:r AS jsonb), :ev, :st, :n, "
        "CAST(:s AS jsonb), :err, :by) RETURNING id"),
        {"c": client_id, "fy": fy_id, "f": from_date, "t": to_date, "ids": check_ids, "p": json.dumps(params), "r": json.dumps(rules_used),
         "ev": engine_version, "st": status, "n": finding_count, "s": json.dumps(summary), "err": error, "by": actor}).scalar_one()


def insert_finding(conn: Connection, client_id: object, run_id: object, row: dict[str, Any]) -> None:
    conn.execute(text(
        "INSERT INTO audit_findings (client_id, run_id, check_id, finding_key, severity, subject_kind, subject_id, subject_ref, finding_date, "
        "amount, disallowance_amount, message, evidence) VALUES (:c, :run, :check_id, :finding_key, :severity, :subject_kind, :subject_id, "
        ":subject_ref, :finding_date, :amount, :disallowance_amount, :message, CAST(:evidence AS jsonb))"),
        {**row, "c": client_id, "run": run_id, "evidence": json.dumps(row["evidence"]), "subject_id": _uuid_or_none(row["subject_id"])})


def _uuid_or_none(value: object) -> object:
    """audit_findings.subject_id is a uuid column; a subject without a uuid (e.g. a period or a document key) is kept in subject_ref only."""
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


_RUN_COLUMNS = ("id, financial_year_id, from_date, to_date, check_ids, finding_count, status, created_by, created_at, params, rules_used, "
                "engine_version, summary, error_message")


def list_runs(conn: Connection, client_id: object) -> list[dict[str, Any]]:
    rows = conn.execute(text(f"SELECT {_RUN_COLUMNS} FROM audit_runs WHERE client_id = :c ORDER BY created_at DESC, id"), {"c": client_id}).mappings()
    return [dict(r) for r in rows]


def get_run(conn: Connection, client_id: object, run_id: object) -> dict[str, Any] | None:
    row = conn.execute(text(f"SELECT {_RUN_COLUMNS} FROM audit_runs WHERE client_id = :c AND id = :r"), {"c": client_id, "r": run_id}).mappings().first()
    return dict(row) if row else None


def list_findings(conn: Connection, client_id: object, run_id: object, check_id: str | None = None, severity: str | None = None,
                  subject_id: object | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT id, run_id, check_id, finding_key, severity, subject_kind, subject_id, subject_ref, finding_date, amount, "
           "disallowance_amount, message, evidence FROM audit_findings WHERE client_id = :c AND run_id = :r")
    params: dict[str, Any] = {"c": client_id, "r": run_id}
    for column, value in (("check_id", check_id), ("severity", severity), ("subject_id", subject_id)):
        if value is not None:
            sql += f" AND {column} = :{column}"
            params[column] = value
    rows = conn.execute(text(sql + " ORDER BY check_id, finding_date NULLS LAST, finding_key"), params).mappings()
    return [dict(r) for r in rows]
