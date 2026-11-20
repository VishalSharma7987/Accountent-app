"""Per-client AI switch, model-call log and narration suggestions (docs/PHASE7_API_CONTRACT.md, packages C and F). Routes are added by C and F."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_ai import AiSettingsIn, AiSettingsOut, LlmCallDetailOut, LlmCallOut
from app.db import repositories_ai as repo
from app.services import ai_settings, queries
from app.services.errors import ServiceError

router = APIRouter(tags=["ai"])


@router.get("/clients/{client_id}/ai/settings", response_model=AiSettingsOut)
def get_ai_settings(client_id: str, conn: Connection = Depends(get_conn)):
    return ai_settings.get_settings(conn, parse_id(client_id, "Client"))


@router.put("/clients/{client_id}/ai/settings", response_model=OkOut)
def put_ai_settings(client_id: str, body: AiSettingsIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    ai_settings.set_settings(conn, parse_id(client_id, "Client"), llm_enabled=body.llm_enabled, data_class=body.data_class,
                             note=body.note, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/ai/calls", response_model=list[LlmCallOut])
def list_ai_calls(client_id: str, purpose: str | None = None, status: str | None = None, document_id: str | None = None,
                  limit: int = Query(default=200, ge=1, le=1000), conn: Connection = Depends(get_conn)):
    cid = parse_id(client_id, "Client")
    queries.require_client(conn, cid)
    return repo.list_calls(conn, cid, purpose=purpose, status=status,
                           document_id=parse_id(document_id, "Document") if document_id else None, limit=limit)


@router.get("/clients/{client_id}/ai/calls/{call_id}", response_model=LlmCallDetailOut)
def get_ai_call(client_id: str, call_id: str, conn: Connection = Depends(get_conn)):
    cid = parse_id(client_id, "Client")
    queries.require_client(conn, cid)
    row = repo.get_call(conn, cid, parse_id(call_id, "Model call"))
    if row is None:
        raise ServiceError("not_found", "Model call not found.")
    return row
