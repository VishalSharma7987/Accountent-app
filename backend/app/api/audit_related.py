"""Related-party flags for check A-18 (docs/PHASE8_API_CONTRACT.md, package D). Flags are never deleted: PUT sets them inactive."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_audit_related import (
    IdOut,
    RelatedFlagIn,
    RelatedFlagOut,
    RelatedFlagUpdateIn,
    flag_out,
)
from app.services import audit_related

router = APIRouter(tags=["audit_related"])


@router.get("/clients/{client_id}/audit/related-parties", response_model=list[RelatedFlagOut])
def list_related_parties(client_id: str, active: bool | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return [flag_out(f) for f in audit_related.list_flags(conn, parse_id(client_id, "Client"), active)]


@router.post("/clients/{client_id}/audit/related-parties", response_model=IdOut, status_code=201)
def flag_related_party(client_id: str, body: RelatedFlagIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    flag_id = audit_related.flag_ledger(conn, parse_id(client_id, "Client"), body.ledger_id, body.relationship, body.note, actor)
    return IdOut(id=flag_id)


@router.put("/clients/{client_id}/audit/related-parties/{flag_id}", response_model=OkOut)
def update_related_party(client_id: str, flag_id: str, body: RelatedFlagUpdateIn, conn: Connection = Depends(get_conn),
                         actor: str = Depends(get_actor)):
    audit_related.update_flag(conn, parse_id(client_id, "Client"), parse_id(flag_id, "Related-party flag"), actor,
                              relationship=body.relationship, active=body.active, note=body.note)
    return OkOut()
