"""The per-client AI switch (D-51, D-54). A client with no row, or `llm_enabled = false`, never reaches a model.

Enabling is an explicit, explained act: who (the actor), when (now), which class of data (synthetic / anonymised / real_acknowledged,
D-54) and a note saying why. Every change is audit-logged with the old and new values. Services never commit.
"""

from typing import Any

from sqlalchemy import Connection

from app import config
from app.db import repositories_ai as repo
from app.services import audit, queries
from app.services.errors import ServiceError, require_actor

DATA_CLASSES = ("synthetic", "anonymised", "real_acknowledged")


def _public(row: dict | None) -> dict:
    row = row or {}
    return {
        "llm_enabled": bool(row.get("llm_enabled", False)),
        "data_class": row.get("data_class", "synthetic"),
        "enabled_by": row.get("enabled_by"),
        "enabled_at": row.get("enabled_at"),
        "note": row.get("note"),
    }


def get_settings(conn: Connection, client_id: Any) -> dict:
    """The switch plus whether a model and a key are configured. Neither the key nor any part of it is returned; the model name is."""
    queries.require_client(conn, client_id)
    out = _public(repo.get_settings(conn, client_id))
    model = config.llm_model()
    out["model"] = model
    out["model_configured"] = model is not None
    out["key_configured"] = config.openrouter_api_key() is not None
    return out


def set_settings(conn: Connection, client_id: Any, *, llm_enabled: bool, data_class: str, note: str | None, actor: str) -> None:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    if data_class not in DATA_CLASSES:
        raise ServiceError("invalid_data_class", "The data class must be synthetic, anonymised or real_acknowledged.")
    note = (note or "").strip() or None
    if llm_enabled and note is None:
        raise ServiceError(
            "reason_required",
            "Say why AI reading is being switched on for this client (for example: 'synthetic test data only'). The note is kept in the audit log.",
        )
    old_row = repo.get_settings(conn, client_id)
    old = _public(old_row)
    unchanged_enable = bool(old["llm_enabled"] and llm_enabled and old["data_class"] == data_class)
    repo.upsert_settings(
        conn, client_id, llm_enabled=llm_enabled, data_class=data_class,
        enabled_by=(old["enabled_by"] if unchanged_enable else actor) if llm_enabled else None,
        note=note, updated_by=actor, keep_enabled_at=unchanged_enable,
    )
    new = _public(repo.get_settings(conn, client_id))
    audit.log(conn, audit.AuditEntry(client_id, actor, "ai_settings_changed", "client_ai_settings", client_id, old, new))
