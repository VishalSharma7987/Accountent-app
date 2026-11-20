"""Audit working papers: population, exceptions, notes, sign-off (docs/PHASE8_API_CONTRACT.md, package E)."""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_audit_papers import (
    DecisionIn,
    NoteIn,
    PaperCreatedOut,
    PaperDetailOut,
    PaperIn,
    PaperListOut,
    SignOffIn,
    SignOffOut,
    amount_out,
)
from app.services import audit_papers as svc

router = APIRouter(tags=["audit_papers"])

BASE = "/clients/{client_id}/audit/papers"


def _list_row(p: dict) -> dict:
    return {**p, "population_amount": amount_out(p["population_amount"])}


def _detail(d: dict) -> dict:
    items = [{"id": i["id"], "status": i["status"], "reviewer_note": i["reviewer_note"], "decided_by": i["decided_by"],
              "decided_at": i["decided_at"],
              "finding": {"id": i["finding_id"], "finding_key": i["finding_key"], "severity": i["severity"], "subject_kind": i["subject_kind"],
                          "subject_ref": i["subject_ref"], "finding_date": i["finding_date"], "amount": amount_out(i["amount"]),
                          "disallowance_amount": amount_out(i["disallowance_amount"]), "message": i["message"], "evidence": i["evidence"]}}
             for i in d["items"]]
    return {**d, "population_amount": amount_out(d["population_amount"]), "items": items}


@router.post(BASE, response_model=PaperCreatedOut, status_code=201)
def create_paper(client_id: str, body: PaperIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return svc.create_paper(conn, parse_id(client_id, "Client"), body.run_id, body.check_id, actor)


@router.get(BASE, response_model=list[PaperListOut])
def list_papers(client_id: str, run_id: str | None = None, check_id: str | None = None, status: str | None = None,
                conn: Connection = Depends(get_conn)):
    rows = svc.list_papers(conn, parse_id(client_id, "Client"), run_id=parse_id(run_id, "Audit run") if run_id else None,
                           check_id=check_id, status=status)
    return [_list_row(r) for r in rows]


@router.get(BASE + "/{paper_id}", response_model=PaperDetailOut)
def get_paper(client_id: str, paper_id: str, conn: Connection = Depends(get_conn)):
    return _detail(svc.get_paper(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper")))


@router.put(BASE + "/{paper_id}/items/{item_id}", response_model=OkOut)
def decide_item(client_id: str, paper_id: str, item_id: str, body: DecisionIn, conn: Connection = Depends(get_conn),
                actor: str = Depends(get_actor)):
    svc.decide_item(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper"), parse_id(item_id, "Working paper item"),
                    body.status, body.reviewer_note, actor)
    return OkOut()


@router.post(BASE + "/{paper_id}/notes", status_code=201)
def add_note(client_id: str, paper_id: str, body: NoteIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return {"id": svc.add_note(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper"), body.note, actor)}


@router.post(BASE + "/{paper_id}/review", response_model=OkOut)
def review(client_id: str, paper_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.send_to_review(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper"), actor)
    return OkOut()


@router.post(BASE + "/{paper_id}/reopen", response_model=OkOut)
def reopen(client_id: str, paper_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.reopen(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper"), actor)
    return OkOut()


@router.post(BASE + "/{paper_id}/sign-off", response_model=SignOffOut)
def sign_off(client_id: str, paper_id: str, body: SignOffIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return svc.sign_off(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper"), body.conclusion, actor)
