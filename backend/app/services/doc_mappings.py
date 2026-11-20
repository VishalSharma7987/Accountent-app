"""Saved party / line mappings: CRUD, loading for the draft builder, and learning from an accepted queue item (Phase 7 package E).

Services take a SQLAlchemy Connection, never commit and audit-log every change. A mapping is only ever written by a person's
request (the API) or by `learn_*` at queue acceptance from the FINAL values (D-26); this module never reads model output and
never creates a ledger, party or item.
"""

from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_doc_mappings as db
from app.engine.doc_map import LineMap, MappingKeyError, PartyMap, line_key, party_key
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, require_actor


def _client(conn: Connection, client_id: Any) -> None:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


def _ledger(conn: Connection, client_id: Any, ledger_id: Any, what: str) -> None:
    row = db.ledger_row(conn, client_id, ledger_id)
    if row is None:
        raise ServiceError("not_found", f"{what} ledger not found for this client.")
    if not row[1]:
        raise ServiceError("invalid_mapping", f"The ledger '{row[0]}' is inactive; map to an active ledger.")


def _key(fn, kind: str, raw: str | None) -> str:
    try:
        return fn(kind, raw)
    except MappingKeyError as exc:
        raise ServiceError("invalid_mapping", str(exc)) from None


def _party_out(r: tuple) -> dict:
    return {"id": r[0], "match_kind": r[1], "match_key": r[2], "party_ledger_id": r[3], "party_ledger_name": r[4], "use_count": r[5]}


def _line_out(r: tuple) -> dict:
    return {"id": r[0], "match_kind": r[1], "match_key": r[2], "party_ledger_id": r[3], "party_ledger_name": r[4],
            "ledger_id": r[5], "ledger_name": r[6], "item_id": r[7], "item_name": r[8], "use_count": r[9]}


def _snap(out: dict) -> dict:
    return {k: (None if v is None else str(v)) for k, v in out.items()}


# ============================================================================================ party mappings


def list_party_mappings(conn: Connection, client_id: Any, q: str | None = None) -> list[dict]:
    _client(conn, client_id)
    return [_party_out(r) for r in db.party_rows(conn, client_id, (q or "").strip() or None)]


def put_party_mapping(conn: Connection, client_id: Any, *, match_kind: str, match_key: str, party_ledger_id: Any,
                      replace: bool = False, actor: str) -> Any:
    """Upsert by (kind, normalised key). A key that already points to ANOTHER ledger is `mapping_exists` unless replace=True."""
    actor = require_actor(actor)
    _client(conn, client_id)
    key = _key(party_key, match_kind, match_key)
    _ledger(conn, client_id, party_ledger_id, "Party")
    existing = db.party_by_key(conn, client_id, match_kind, key)
    if existing is None:
        new_id = db.insert_party(conn, client_id, match_kind, key, party_ledger_id, actor)
        audit.log(conn, AuditEntry(client_id, actor, "create", "party_mapping", new_id, None,
                                   {"match_kind": match_kind, "match_key": key, "party_ledger_id": str(party_ledger_id)}))
        return new_id
    if str(existing[3]) == str(party_ledger_id):
        return existing[0]
    if not replace:
        raise ServiceError("mapping_exists", f"'{key}' is already mapped to the ledger '{existing[4]}'. "
                                              "Send replace = true to point it to the new ledger.", {"mapping_id": str(existing[0])})
    db.set_party_ledger(conn, client_id, existing[0], party_ledger_id)
    audit.log(conn, AuditEntry(client_id, actor, "update", "party_mapping", existing[0],
                               {"party_ledger_id": str(existing[3])}, {"party_ledger_id": str(party_ledger_id)}))
    return existing[0]


def delete_party_mapping(conn: Connection, client_id: Any, mapping_id: Any, *, actor: str) -> None:
    actor = require_actor(actor)
    row = db.party_row(conn, client_id, mapping_id)
    if row is None:
        raise ServiceError("mapping_missing", "This party mapping does not exist.")
    db.delete_party(conn, client_id, mapping_id)
    audit.log(conn, AuditEntry(client_id, actor, "delete", "party_mapping", mapping_id, _snap(_party_out(row)), None))


# ============================================================================================ line mappings


def list_line_mappings(conn: Connection, client_id: Any, q: str | None = None) -> list[dict]:
    _client(conn, client_id)
    return [_line_out(r) for r in db.line_rows(conn, client_id, (q or "").strip() or None)]


def put_line_mapping(conn: Connection, client_id: Any, *, match_kind: str, match_key: str, ledger_id: Any,
                     party_ledger_id: Any | None = None, item_id: Any | None = None, replace: bool = False, actor: str) -> Any:
    actor = require_actor(actor)
    _client(conn, client_id)
    key = _key(line_key, match_kind, match_key)
    _ledger(conn, client_id, ledger_id, "Target")
    if party_ledger_id is not None:
        _ledger(conn, client_id, party_ledger_id, "Party")
    if item_id is not None and not db.item_exists(conn, client_id, item_id):
        raise ServiceError("not_found", "Item not found for this client.")
    existing = db.line_by_key(conn, client_id, match_kind, key, party_ledger_id)
    if existing is None:
        new_id = db.insert_line(conn, client_id, match_kind, key, party_ledger_id, ledger_id, item_id, actor)
        audit.log(conn, AuditEntry(client_id, actor, "create", "line_mapping", new_id, None, {
            "match_kind": match_kind, "match_key": key, "party_ledger_id": None if party_ledger_id is None else str(party_ledger_id),
            "ledger_id": str(ledger_id), "item_id": None if item_id is None else str(item_id)}))
        return new_id
    same = str(existing[5]) == str(ledger_id) and (existing[7] is None) == (item_id is None) \
        and (item_id is None or str(existing[7]) == str(item_id))
    if same:
        return existing[0]
    if not replace:
        raise ServiceError("mapping_exists", f"'{key}' is already mapped to the ledger '{existing[6]}'. "
                                              "Send replace = true to change it.", {"mapping_id": str(existing[0])})
    db.set_line_target(conn, client_id, existing[0], ledger_id, item_id)
    audit.log(conn, AuditEntry(client_id, actor, "update", "line_mapping", existing[0],
                               {"ledger_id": str(existing[5]), "item_id": None if existing[7] is None else str(existing[7])},
                               {"ledger_id": str(ledger_id), "item_id": None if item_id is None else str(item_id)}))
    return existing[0]


def delete_line_mapping(conn: Connection, client_id: Any, mapping_id: Any, *, actor: str) -> None:
    actor = require_actor(actor)
    row = db.line_row(conn, client_id, mapping_id)
    if row is None:
        raise ServiceError("mapping_missing", "This line mapping does not exist.")
    db.delete_line(conn, client_id, mapping_id)
    audit.log(conn, AuditEntry(client_id, actor, "delete", "line_mapping", mapping_id, _snap(_line_out(row)), None))


# ============================================================================================ for the builder and the queue


def load_maps(conn: Connection, client_id: Any) -> tuple[list[PartyMap], list[LineMap]]:
    """Every saved mapping of the client as engine data."""
    parties = [PartyMap(r[0], r[1], r[2], r[3]) for r in db.party_rows(conn, client_id)]
    lines = [LineMap(r[0], r[1], r[2], r[3], r[5], r[7]) for r in db.line_rows(conn, client_id)]
    return parties, lines


def touch(conn: Connection, client_id: Any, *, party_map_ids: list, line_map_ids: list) -> None:
    """Count one more use of the mappings a draft was built from."""
    db.touch_party(conn, client_id, list(dict.fromkeys(party_map_ids)))
    db.touch_line(conn, client_id, list(dict.fromkeys(line_map_ids)))


def learn_party_mapping(conn: Connection, client_id: Any, *, match_kind: str, match_key: str, party_ledger_id: Any, actor: str) -> str:
    """D-26, for the queue's accept: save the mapping from the accountant's FINAL values. Returns 'created', 'unchanged' or
    'conflict' (the key already points to another ledger: it is left alone and the accountant fixes it in the mapping screen)."""
    key = _key(party_key, match_kind, match_key)
    existing = db.party_by_key(conn, client_id, match_kind, key)
    if existing is None:
        put_party_mapping(conn, client_id, match_kind=match_kind, match_key=key, party_ledger_id=party_ledger_id, actor=actor)
        return "created"
    if str(existing[3]) == str(party_ledger_id):
        db.touch_party(conn, client_id, [existing[0]])
        return "unchanged"
    return "conflict"


def learn_line_mapping(conn: Connection, client_id: Any, *, match_kind: str, match_key: str, ledger_id: Any,
                       party_ledger_id: Any | None = None, item_id: Any | None = None, actor: str) -> str:
    key = _key(line_key, match_kind, match_key)
    existing = db.line_by_key(conn, client_id, match_kind, key, party_ledger_id)
    if existing is None:
        put_line_mapping(conn, client_id, match_kind=match_kind, match_key=key, ledger_id=ledger_id, party_ledger_id=party_ledger_id,
                         item_id=item_id, actor=actor)
        return "created"
    if str(existing[5]) == str(ledger_id) and (existing[7] is None) == (item_id is None):
        db.touch_line(conn, client_id, [existing[0]])
        return "unchanged"
    return "conflict"
