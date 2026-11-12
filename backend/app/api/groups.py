from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.schemas import GroupNode
from app.services import queries

router = APIRouter(tags=["groups"])


@router.get("/clients/{client_id}/groups", response_model=list[GroupNode])
def list_groups(client_id: str, conn: Connection = Depends(get_conn)):
    return [GroupNode(**node) for node in queries.groups_tree(conn, parse_id(client_id, "Client"))]
