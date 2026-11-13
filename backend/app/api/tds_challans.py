"""TDS / TCS challan endpoints (Phase 4, package C). Contract: docs/PHASE4_API_CONTRACT.md section "Challans, due dates, interest"."""

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_tds_challans import (
    AllocationsIn,
    AutoMatchIn,
    ChallanFields,
    ChallanIn,
    jsonable,
)
from app.services import tds_challans

router = APIRouter(tags=["tds"])


def _fy(value: str):
    return parse_id(value, "Financial year")


@router.post("/clients/{client_id}/tds/challans", status_code=201)
def create_challan(client_id: str, body: ChallanIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    challan_id = tds_challans.create_challan(conn, parse_id(client_id, "Client"), body.model_dump(), actor=actor)
    return JSONResponse(status_code=201, content={"id": str(challan_id)})


@router.get("/clients/{client_id}/tds/challans")
def list_challans(
    client_id: str, financial_year_id: str | None = None, quarter: int | None = None, kind: str | None = None, conn: Connection = Depends(get_conn)
):
    fy = _fy(financial_year_id) if financial_year_id else None
    return jsonable(tds_challans.list_challans(conn, parse_id(client_id, "Client"), fy, quarter, kind))


@router.get("/clients/{client_id}/tds/challans/{challan_id}")
def get_challan(client_id: str, challan_id: str, conn: Connection = Depends(get_conn)):
    return jsonable(tds_challans.get_challan(conn, parse_id(client_id, "Client"), parse_id(challan_id, "Challan")))


@router.put("/clients/{client_id}/tds/challans/{challan_id}")
def update_challan(client_id: str, challan_id: str, body: ChallanFields, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return jsonable(tds_challans.update_challan(conn, parse_id(client_id, "Client"), parse_id(challan_id, "Challan"), body.model_dump(), actor=actor))


@router.put("/clients/{client_id}/tds/challans/{challan_id}/allocations")
def put_allocations(client_id: str, challan_id: str, body: AllocationsIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return jsonable(tds_challans.replace_allocations(
        conn, parse_id(client_id, "Client"), parse_id(challan_id, "Challan"), body.model_dump()["allocations"], actor=actor))


@router.get("/clients/{client_id}/tds/challan-matching")
def challan_matching(
    client_id: str, financial_year_id: str, quarter: int | None = None, kind: str | None = None, as_on: date | None = None,
    conn: Connection = Depends(get_conn),
):
    return jsonable(tds_challans.matching(conn, parse_id(client_id, "Client"), _fy(financial_year_id), quarter, kind, as_on))


@router.post("/clients/{client_id}/tds/challan-matching/auto")
def challan_matching_auto(client_id: str, body: AutoMatchIn, conn: Connection = Depends(get_conn)):
    return jsonable(tds_challans.propose(conn, parse_id(client_id, "Client"), body.financial_year_id, body.quarter, body.kind))


@router.get("/clients/{client_id}/tds/interest")
def tds_interest(client_id: str, financial_year_id: str, as_on: date | None = None, kind: str | None = None, conn: Connection = Depends(get_conn)):
    return jsonable(tds_challans.interest(conn, parse_id(client_id, "Client"), _fy(financial_year_id), as_on, kind))


@router.get("/clients/{client_id}/tds/due-calendar")
def tds_due_calendar(client_id: str, financial_year_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    return jsonable(tds_challans.due_calendar(conn, parse_id(client_id, "Client"), _fy(financial_year_id), as_on))
