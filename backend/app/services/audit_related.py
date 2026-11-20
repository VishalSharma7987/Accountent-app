"""Related-party flag management for check A-18 (Phase 8, package D). A flag is never deleted: it is set inactive (the database refuses a
delete and a change of ledger). Every change is audit-logged with old and new values. This module never touches vouchers or ledgers."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from app.services import audit_hooks
from app.services.errors import ServiceError, require_actor

_COLUMNS = "r.id, r.ledger_id, l.name AS ledger_name, r.relationship, r.active, r.flagged_by, r.flagged_at, r.note"
_FROM = "FROM audit_related_parties r JOIN ledgers l ON l.id = r.ledger_id AND l.client_id = r.client_id"


@dataclass(frozen=True)
class RelatedFlag:
    id: uuid.UUID
    ledger_id: uuid.UUID
    ledger_name: str
    relationship: str
    active: bool
    flagged_by: str
    flagged_at: datetime
    note: str | None


def _flag(row) -> RelatedFlag:
    return RelatedFlag(row.id, row.ledger_id, row.ledger_name, row.relationship, row.active, row.flagged_by, row.flagged_at, row.note)


def _snapshot(f: RelatedFlag) -> dict:
    return {"ledger_id": str(f.ledger_id), "ledger": f.ledger_name, "relationship": f.relationship, "active": f.active, "note": f.note}


def list_flags(conn: Connection, client_id: object, active: bool | None = None) -> list[RelatedFlag]:
    sql = f"SELECT {_COLUMNS} {_FROM} WHERE r.client_id = :c" + ("" if active is None else " AND r.active = :a") + " ORDER BY l.name, r.id"
    params: dict = {"c": client_id}
    if active is not None:
        params["a"] = active
    return [_flag(r) for r in conn.execute(text(sql), params).all()]


def get_flag(conn: Connection, client_id: object, flag_id: object) -> RelatedFlag:
    row = conn.execute(text(f"SELECT {_COLUMNS} {_FROM} WHERE r.client_id = :c AND r.id = :i"), {"c": client_id, "i": flag_id}).first()
    if row is None:
        raise ServiceError("not_found", "Related-party flag not found.")
    return _flag(row)


def flag_ledger(conn: Connection, client_id: object, ledger_id: object, relationship: str, note: str | None, actor: str) -> uuid.UUID:
    actor = require_actor(actor)
    relationship = (relationship or "").strip()
    if not relationship:
        raise ServiceError("invalid_relationship", "Say how the party is related (for example Director, Relative, Associate concern).")
    ledger = conn.execute(text("SELECT name FROM ledgers WHERE id = :l AND client_id = :c"), {"l": ledger_id, "c": client_id}).first()
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    existing = conn.execute(text("SELECT id, active FROM audit_related_parties WHERE client_id = :c AND ledger_id = :l"),
                            {"c": client_id, "l": ledger_id}).first()
    if existing is not None:
        state = "active" if existing.active else "inactive; reactivate it instead"
        raise ServiceError("already_flagged", f"{ledger.name} is already flagged as a related party ({state}).", {"id": str(existing.id)})
    flag_id = uuid.uuid4()
    conn.execute(text("INSERT INTO audit_related_parties (id, client_id, ledger_id, relationship, flagged_by, note) "
                      "VALUES (:i, :c, :l, :r, :a, :n)"),
                 {"i": flag_id, "c": client_id, "l": ledger_id, "r": relationship, "a": actor, "n": (note or None)})
    audit_hooks.log_action(conn, client_id, actor, "flag", "audit_related_party", flag_id, None,
                           {"ledger_id": str(ledger_id), "ledger": ledger.name, "relationship": relationship, "active": True, "note": note or None})
    return flag_id


def update_flag(conn: Connection, client_id: object, flag_id: object, actor: str, *, relationship: str | None = None,
                active: bool | None = None, note: str | None = None) -> None:
    actor = require_actor(actor)
    old = get_flag(conn, client_id, flag_id)
    new_rel = old.relationship if relationship is None else relationship.strip()
    if not new_rel:
        raise ServiceError("invalid_relationship", "Say how the party is related (for example Director, Relative, Associate concern).")
    new_active = old.active if active is None else active
    new_note = old.note if note is None else (note or None)
    if (new_rel, new_active, new_note) == (old.relationship, old.active, old.note):
        return
    conn.execute(text("UPDATE audit_related_parties SET relationship = :r, active = :a, note = :n WHERE id = :i AND client_id = :c"),
                 {"r": new_rel, "a": new_active, "n": new_note, "i": flag_id, "c": client_id})
    new = _snapshot(old) | {"relationship": new_rel, "active": new_active, "note": new_note}
    action = "reactivate" if (new_active and not old.active) else "deactivate" if (old.active and not new_active) else "update"
    audit_hooks.log_action(conn, client_id, actor, action, "audit_related_party", flag_id, _snapshot(old), new)
