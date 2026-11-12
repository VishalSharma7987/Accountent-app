from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.schemas import AuditOut
from app.services import queries

router = APIRouter(tags=["audit"])


@router.get("/clients/{client_id}/audit-log", response_model=list[AuditOut])
def audit_log(client_id: str, entity: str | None = None, entity_id: str | None = None, limit: int = 100,
              conn: Connection = Depends(get_conn)):
    rows = queries.audit_entries(
        conn, parse_id(client_id, "Client"), entity=entity,
        entity_id=parse_id(entity_id, "Entity") if entity_id else None, limit=limit,
    )
    return [AuditOut(**r) for r in rows]
