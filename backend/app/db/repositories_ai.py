"""SQL for the per-client AI switch (client_ai_settings) and the model-call log (llm_calls, insert only). Phase 7, package C.
SQL only: no rules. Every function takes a Connection owned by the caller.
"""

import json
from typing import Any

from sqlalchemy import Connection, text

SETTINGS_COLUMNS = "llm_enabled, data_class, enabled_by, enabled_at, note, updated_by, updated_at"
CALL_LIST_COLUMNS = ("id, purpose, provider, model, prompt_version, status, masking_applied, masking_report, tokens_in, tokens_out, "
                     "latency_ms, document_id, created_by, created_at")


def get_settings(conn: Connection, client_id: Any) -> dict | None:
    row = conn.execute(text(f"SELECT {SETTINGS_COLUMNS} FROM client_ai_settings WHERE client_id = :c"), {"c": client_id}).mappings().first()
    return dict(row) if row else None


def upsert_settings(conn: Connection, client_id: Any, *, llm_enabled: bool, data_class: str, enabled_by: str | None, note: str | None,
                    updated_by: str, keep_enabled_at: bool) -> None:
    """enabled_at is set to now() when `llm_enabled` and not `keep_enabled_at`, kept when `keep_enabled_at`, NULL when disabled."""
    conn.execute(
        text(
            "INSERT INTO client_ai_settings (client_id, llm_enabled, data_class, enabled_by, enabled_at, note, updated_by, updated_at) "
            "VALUES (:c, :en, :dc, :by, CASE WHEN :en THEN now() END, :note, :upd, now()) "
            "ON CONFLICT (client_id) DO UPDATE SET llm_enabled = EXCLUDED.llm_enabled, data_class = EXCLUDED.data_class, "
            "enabled_by = EXCLUDED.enabled_by, "
            "enabled_at = CASE WHEN NOT EXCLUDED.llm_enabled THEN NULL WHEN :keep THEN client_ai_settings.enabled_at ELSE now() END, "
            "note = EXCLUDED.note, updated_by = EXCLUDED.updated_by, updated_at = now()"
        ),
        {"c": client_id, "en": llm_enabled, "dc": data_class, "by": enabled_by, "note": note, "upd": updated_by, "keep": keep_enabled_at},
    )


def insert_call(conn: Connection, *, client_id: Any, document_id: Any, purpose: str, provider: str, model: str | None,
                prompt_version: str, prompt_masked: str | None, prompt_sha256: str | None, masking_applied: bool,
                masking_report: dict | None, response_raw: str | None, status: str, error_message: str | None,
                tokens_in: int | None, tokens_out: int | None, latency_ms: int | None, created_by: str) -> Any:
    row = conn.execute(
        text(
            "INSERT INTO llm_calls (client_id, document_id, purpose, provider, model, prompt_version, prompt_masked, prompt_sha256, "
            "masking_applied, masking_report, response_raw, status, error_message, tokens_in, tokens_out, latency_ms, created_by) "
            "VALUES (:client_id, :document_id, :purpose, :provider, :model, :prompt_version, :prompt_masked, :prompt_sha256, "
            ":masking_applied, CAST(:masking_report AS jsonb), :response_raw, :status, :error_message, :tokens_in, :tokens_out, "
            ":latency_ms, :created_by) RETURNING id"
        ),
        {"client_id": client_id, "document_id": document_id, "purpose": purpose, "provider": provider, "model": model,
         "prompt_version": prompt_version, "prompt_masked": prompt_masked, "prompt_sha256": prompt_sha256,
         "masking_applied": masking_applied, "masking_report": None if masking_report is None else json.dumps(masking_report),
         "response_raw": response_raw, "status": status, "error_message": error_message, "tokens_in": tokens_in,
         "tokens_out": tokens_out, "latency_ms": latency_ms, "created_by": created_by},
    ).one()
    return row[0]


def usage_since(conn: Connection, client_id: Any, seconds: int) -> tuple[int, int]:
    """(model calls that reached the service, tokens in + out) of this client in the last `seconds`. Refused calls do not count."""
    row = conn.execute(
        text(
            "SELECT count(*), coalesce(sum(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)), 0) FROM llm_calls "
            "WHERE client_id = :c AND status <> 'blocked' AND created_at >= now() - make_interval(secs => :s)"
        ),
        {"c": client_id, "s": seconds},
    ).one()
    return int(row[0]), int(row[1])


def list_calls(conn: Connection, client_id: Any, *, purpose: str | None, status: str | None, document_id: Any, limit: int) -> list[dict]:
    rows = conn.execute(
        text(
            f"SELECT {CALL_LIST_COLUMNS} FROM llm_calls WHERE client_id = :c "
            "AND (CAST(:purpose AS text) IS NULL OR purpose = :purpose) AND (CAST(:status AS text) IS NULL OR status = :status) "
            "AND (CAST(:doc AS uuid) IS NULL OR document_id = :doc) ORDER BY created_at DESC, id LIMIT :limit"
        ),
        {"c": client_id, "purpose": purpose, "status": status, "doc": document_id, "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def get_call(conn: Connection, client_id: Any, call_id: Any) -> dict | None:
    row = conn.execute(
        text(f"SELECT {CALL_LIST_COLUMNS}, prompt_masked, response_raw, error_message FROM llm_calls WHERE client_id = :c AND id = :i"),
        {"c": client_id, "i": call_id},
    ).mappings().first()
    return dict(row) if row else None
