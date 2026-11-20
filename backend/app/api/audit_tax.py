"""Tax audit form data (Form 3CD / Form 26) (docs/PHASE8_API_CONTRACT.md, package F). Derived entries are figures for the accountant to check."""

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.services import audit_form

router = APIRouter(tags=["audit_tax"])


class SetIn(BaseModel):
    financial_year_id: str


class DeriveIn(BaseModel):
    run_id: str
    clause_nos: list[str] | None = None


class EntryIn(BaseModel):
    clause_no: str
    field_key: str
    value: Any


def _entry(e: dict) -> dict:
    return {"clause_no": e["clause_no"], "field_key": e["field_key"], "value": e["value"], "origin": e["origin"],
            "run_id": None if e["run_id"] is None else str(e["run_id"]), "entered_by": e["entered_by"],
            "entered_at": e["entered_at"].isoformat()}


@router.get("/clients/{client_id}/audit/forms")
def get_form(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return audit_form.form_for_year(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"))


@router.post("/clients/{client_id}/audit/forms/sets", status_code=201)
def create_set(client_id: str, body: SetIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    out = audit_form.create_set(conn, parse_id(client_id, "Client"), parse_id(body.financial_year_id, "Financial year"), actor=actor)
    return {"id": str(out["id"]), "form_key": out["form_key"], "status": out["status"]}


@router.post("/clients/{client_id}/audit/forms/sets/{set_id}/derive")
def derive(client_id: str, set_id: str, body: DeriveIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return audit_form.derive(conn, parse_id(client_id, "Client"), parse_id(set_id, "Form set"), parse_id(body.run_id, "Audit run"),
                             actor=actor, clause_nos=body.clause_nos)


@router.put("/clients/{client_id}/audit/forms/sets/{set_id}/entries")
def put_entry(client_id: str, set_id: str, body: EntryIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return audit_form.enter_manual(conn, parse_id(client_id, "Client"), parse_id(set_id, "Form set"), body.clause_no, body.field_key,
                                   body.value, actor=actor)


@router.get("/clients/{client_id}/audit/forms/sets/{set_id}")
def get_set(client_id: str, set_id: str, format: str | None = None, conn: Connection = Depends(get_conn)):
    cid, sid = parse_id(client_id, "Client"), parse_id(set_id, "Form set")
    if format == "xlsx":
        content, media, name = audit_form.export_xlsx(conn, cid, sid)
        return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
    s = audit_form.get_set(conn, cid, sid)
    return {"id": str(s["id"]), "financial_year_id": str(s["financial_year_id"]), "form_key": s["form_key"], "status": s["status"],
            "form": s["form"], "clauses": s["clauses"], "entries": [_entry(e) for e in s["entries"]], "created_by": s["created_by"],
            "finalised_by": s["finalised_by"], "finalised_at": None if s["finalised_at"] is None else s["finalised_at"].isoformat()}


@router.post("/clients/{client_id}/audit/forms/sets/{set_id}/finalise")
def finalise(client_id: str, set_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    audit_form.finalise(conn, parse_id(client_id, "Client"), parse_id(set_id, "Form set"), actor=actor)
    return {"ok": True}
