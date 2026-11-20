"""Client holiday calendar for check A-13 (Phase 8, package B). Sundays are computed, never stored. Every change is audit-logged."""

from datetime import date

from sqlalchemy import Connection, text

from app.engine.audit_types import is_sunday
from app.services import audit_hooks
from app.services.errors import ServiceError, require_actor

KINDS = ("national", "state", "local", "client")


def list_holidays(conn: Connection, client_id: object, year: int | None = None) -> list[dict]:
    sql = "SELECT id, holiday_date, name, kind, note FROM audit_holidays WHERE client_id = :c"
    params: dict = {"c": client_id}
    if year is not None:
        sql += " AND holiday_date >= :a AND holiday_date <= :b"
        params |= {"a": date(year, 1, 1), "b": date(year, 12, 31)}
    rows = conn.execute(text(sql + " ORDER BY holiday_date"), params)
    return [{"id": r[0], "holiday_date": r[1], "name": r[2], "kind": r[3], "note": r[4]} for r in rows]


def add_holiday(conn: Connection, client_id: object, holiday_date: date, name: str, kind: str | None, note: str | None, *, actor: str) -> object:
    actor = require_actor(actor)
    name = (name or "").strip()
    kind = kind or "client"
    shown = holiday_date.strftime("%d-%m-%Y")
    if not name:
        raise ServiceError("invalid_holiday", "The holiday needs a name.")
    if kind not in KINDS:
        raise ServiceError("invalid_holiday", f"Holiday kind must be one of {', '.join(KINDS)}.")
    if is_sunday(holiday_date):
        raise ServiceError("invalid_holiday", f"{shown} is a Sunday; Sundays are always checked, do not list them.")
    exists = conn.execute(text("SELECT 1 FROM audit_holidays WHERE client_id = :c AND holiday_date = :d"),
                          {"c": client_id, "d": holiday_date}).first()
    if exists:
        raise ServiceError("duplicate_holiday", f"{shown} is already in the holiday list.")
    new_id = conn.execute(text(
        "INSERT INTO audit_holidays (client_id, holiday_date, name, kind, note, created_by) VALUES (:c, :d, :n, :k, :note, :by) RETURNING id"),
        {"c": client_id, "d": holiday_date, "n": name, "k": kind, "note": note, "by": actor}).scalar_one()
    audit_hooks.log_action(conn, client_id, actor, "create", "audit_holiday", new_id,
                           new={"holiday_date": holiday_date.isoformat(), "name": name, "kind": kind, "note": note})
    return new_id


def delete_holiday(conn: Connection, client_id: object, holiday_id: object, *, actor: str) -> None:
    actor = require_actor(actor)
    row = conn.execute(text("SELECT holiday_date, name, kind, note FROM audit_holidays WHERE id = :i AND client_id = :c"),
                       {"i": holiday_id, "c": client_id}).first()
    if row is None:
        raise ServiceError("not_found", "Holiday not found.")
    conn.execute(text("DELETE FROM audit_holidays WHERE id = :i"), {"i": holiday_id})
    audit_hooks.log_action(conn, client_id, actor, "delete", "audit_holiday", holiday_id,
                           old={"holiday_date": row[0].isoformat(), "name": row[1], "kind": row[2], "note": row[3]})
