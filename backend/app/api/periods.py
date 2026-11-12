from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut, PeriodOut, UnlockIn
from app.services import periods, queries

router = APIRouter(tags=["periods"])


@router.get("/clients/{client_id}/periods", response_model=list[PeriodOut])
def list_periods(client_id: str, fy_id: str | None = None, conn: Connection = Depends(get_conn)):
    cid = parse_id(client_id, "Client")
    queries.require_client(conn, cid)
    rows = periods.list_periods(conn, cid, parse_id(fy_id, "Financial year") if fy_id else None)
    return [PeriodOut.model_validate(p, from_attributes=True) for p in rows]


@router.post("/clients/{client_id}/periods/{period_id}/lock", response_model=OkOut)
def lock_period(client_id: str, period_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    periods.lock_period(conn, parse_id(client_id, "Client"), parse_id(period_id, "Period"), actor=actor)
    return OkOut()


@router.post("/clients/{client_id}/periods/{period_id}/unlock", response_model=OkOut)
def unlock_period(client_id: str, period_id: str, body: UnlockIn, conn: Connection = Depends(get_conn),
                  actor: str = Depends(get_actor)):
    periods.unlock_period(conn, parse_id(client_id, "Client"), parse_id(period_id, "Period"), body.reason, actor=actor)
    return OkOut()
