"""Audit log writes (CLAUDE.md principle 7): who, when, what, old value, new value. The table is append-only."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

_INSERT = text(
    "INSERT INTO audit_log (client_id, actor, action, entity, entity_id, old_data, new_data) "
    "VALUES (:client_id, :actor, :action, :entity, :entity_id, CAST(:old_data AS jsonb), CAST(:new_data AS jsonb))"
)


@dataclass(frozen=True)
class AuditEntry:
    client_id: object
    actor: str
    action: str
    entity: str
    entity_id: object
    old: dict[str, Any] | None = None
    new: dict[str, Any] | None = None


def _params(entry: AuditEntry) -> dict[str, Any]:
    return {
        "client_id": entry.client_id,
        "actor": entry.actor,
        "action": entry.action,
        "entity": entry.entity,
        "entity_id": entry.entity_id,
        "old_data": None if entry.old is None else json.dumps(entry.old, default=str),
        "new_data": None if entry.new is None else json.dumps(entry.new, default=str),
    }


def log(conn: Connection, entry: AuditEntry) -> None:
    conn.execute(_INSERT, _params(entry))


def log_many(conn: Connection, entries: Sequence[AuditEntry]) -> None:
    if entries:
        conn.execute(_INSERT, [_params(e) for e in entries])
