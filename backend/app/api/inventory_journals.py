"""Stock journal endpoints (docs/PHASE5_API_CONTRACT.md, package D): transfer between godowns and write-off."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_inventory_journals import JournalIn, JournalOut, ReverseIn, journal_out
from app.engine.inventory_journals import JournalLineInput
from app.services import inventory_journals as svc

router = APIRouter(tags=["inventory"])


def _lines(body: JournalIn) -> list[JournalLineInput]:
    return [JournalLineInput(x.item_id, x.from_godown_id, x.to_godown_id, x.quantity) for x in body.lines]


@router.get("/clients/{client_id}/stock-journals", response_model=list[JournalOut])
def list_journals(client_id: str, financial_year_id: str | None = None, journal_type: str | None = None,
                  status: str | None = None, from_: date | None = Query(default=None, alias="from"), to: date | None = None,
                  conn: Connection = Depends(get_conn)):
    fy = None if financial_year_id is None else parse_id(financial_year_id, "Financial year")
    return [journal_out(v) for v in svc.list_journals(conn, parse_id(client_id, "Client"), financial_year_id=fy,
                                                      journal_type=journal_type, status=status, from_date=from_, to_date=to)]


@router.post("/clients/{client_id}/stock-journals", status_code=201, response_model=JournalOut)
def create_journal(client_id: str, body: JournalIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return journal_out(svc.create_journal(
        conn, parse_id(client_id, "Client"), journal_type=body.journal_type, journal_date=body.journal_date,
        narration=body.narration, reason_code=body.reason_code, reason_note=body.reason_note, lines=_lines(body), actor=actor))


@router.get("/clients/{client_id}/stock-journals/{journal_id}", response_model=JournalOut)
def get_journal(client_id: str, journal_id: str, conn: Connection = Depends(get_conn)):
    return journal_out(svc.get_journal(conn, parse_id(client_id, "Client"), parse_id(journal_id, "Stock journal")))


@router.put("/clients/{client_id}/stock-journals/{journal_id}", response_model=JournalOut)
def update_journal(client_id: str, journal_id: str, body: JournalIn, conn: Connection = Depends(get_conn),
                   actor: str = Depends(get_actor)):
    return journal_out(svc.update_journal(
        conn, parse_id(client_id, "Client"), parse_id(journal_id, "Stock journal"), journal_type=body.journal_type,
        journal_date=body.journal_date, narration=body.narration, reason_code=body.reason_code, reason_note=body.reason_note,
        lines=_lines(body), actor=actor))


@router.delete("/clients/{client_id}/stock-journals/{journal_id}", response_model=OkOut)
def delete_journal(client_id: str, journal_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.delete_journal(conn, parse_id(client_id, "Client"), parse_id(journal_id, "Stock journal"), actor=actor)
    return OkOut()


@router.post("/clients/{client_id}/stock-journals/{journal_id}/approve", response_model=JournalOut)
def approve_journal(client_id: str, journal_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return journal_out(svc.approve_journal(conn, parse_id(client_id, "Client"), parse_id(journal_id, "Stock journal"), actor=actor))


@router.post("/clients/{client_id}/stock-journals/{journal_id}/post", response_model=JournalOut)
def post_journal(client_id: str, journal_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return journal_out(svc.post_journal(conn, parse_id(client_id, "Client"), parse_id(journal_id, "Stock journal"), actor=actor))


@router.post("/clients/{client_id}/stock-journals/{journal_id}/reverse", response_model=JournalOut)
def reverse_journal(client_id: str, journal_id: str, body: ReverseIn, conn: Connection = Depends(get_conn),
                    actor: str = Depends(get_actor)):
    return journal_out(svc.reverse_journal(conn, parse_id(client_id, "Client"), parse_id(journal_id, "Stock journal"),
                                           reason=body.reason, reversal_date=body.reversal_date, actor=actor))
