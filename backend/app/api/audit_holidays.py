"""Client holiday calendar for check A-13 (docs/PHASE8_API_CONTRACT.md, package B)."""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_audit_holidays import HolidayCreated, HolidayIn, HolidayOut
from app.services import audit_holidays, queries

router = APIRouter(tags=["audit_holidays"])


@router.get("/clients/{client_id}/audit/holidays", response_model=list[HolidayOut])
def list_holidays(client_id: str, year: int | None = None, conn: Connection = Depends(get_conn)):
    cid = parse_id(client_id, "Client")
    queries.require_client(conn, cid)
    return [HolidayOut(**{**h, "id": str(h["id"])}) for h in audit_holidays.list_holidays(conn, cid, year)]


@router.post("/clients/{client_id}/audit/holidays", response_model=HolidayCreated, status_code=201)
def add_holiday(client_id: str, body: HolidayIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    cid = parse_id(client_id, "Client")
    queries.require_client(conn, cid)
    new_id = audit_holidays.add_holiday(conn, cid, body.holiday_date, body.name, body.kind, body.note, actor=actor)
    return HolidayCreated(id=str(new_id))


@router.delete("/clients/{client_id}/audit/holidays/{holiday_id}", response_model=OkOut)
def delete_holiday(client_id: str, holiday_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    cid = parse_id(client_id, "Client")
    queries.require_client(conn, cid)
    audit_holidays.delete_holiday(conn, cid, parse_id(holiday_id, "Holiday"), actor=actor)
    return OkOut()
