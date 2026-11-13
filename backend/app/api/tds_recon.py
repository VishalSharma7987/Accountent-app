"""26AS / AIS import and reconciliation endpoints (docs/PHASE4_API_CONTRACT.md, package E)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_tds_recon import (
    LinkIn,
    import_out,
    import_row_out,
    reconciliation_out,
    statement_row_out,
)
from app.services import tds_recon
from app.services.errors import ServiceError

router = APIRouter(tags=["tds"])

Conn = Annotated[Connection, Depends(get_conn)]
Actor = Annotated[str, Depends(get_actor)]
MAX_FILE_BYTES = 10 * 1024 * 1024


@router.post("/clients/{client_id}/tds/26as/import", status_code=201)
def import_26as(client_id: str, conn: Conn, actor: Actor, file: Annotated[UploadFile, File()],
                financial_year_id: Annotated[str, Form()], source: Annotated[str, Form()] = "form_26as",
                side: Annotated[str, Form()] = "deductee"):
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ServiceError("import_invalid", "The file is larger than 10 MB.")
    result = tds_recon.import_file(
        conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), source, side,
        file.filename or "upload", content, actor,
    )
    return import_out(result)


@router.get("/clients/{client_id}/tds/26as/imports")
def imports(client_id: str, conn: Conn, financial_year_id: str | None = None):
    rows = tds_recon.list_imports(conn, parse_id(client_id, "Client"),
                                  parse_id(financial_year_id, "Financial year") if financial_year_id else None)
    return [import_row_out(r) for r in rows]


@router.get("/clients/{client_id}/tds/26as/imports/{import_id}/rows")
def import_rows(client_id: str, import_id: str, conn: Conn):
    rows = tds_recon.list_rows(conn, parse_id(client_id, "Client"), parse_id(import_id, "Import"))
    return [statement_row_out(r) for r in rows]


@router.get("/clients/{client_id}/tds/26as/reconciliation")
def reconciliation(client_id: str, financial_year_id: str, conn: Conn, import_id: str | None = None):
    return reconciliation_out(tds_recon.reconcile(
        conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"),
        parse_id(import_id, "Import") if import_id else None,
    ))


@router.post("/clients/{client_id}/tds/26as/links", status_code=201)
def create_link(client_id: str, body: LinkIn, conn: Conn, actor: Actor):
    link_id = tds_recon.create_link(
        conn, parse_id(client_id, "Client"), parse_id(body.row_id, "Statement row"),
        parse_id(body.item_id, "Deduction item") if body.item_id else None,
        parse_id(body.voucher_id, "Voucher") if body.voucher_id else None, body.link_kind, body.note, actor,
    )
    return {"link_id": str(link_id)}


@router.delete("/clients/{client_id}/tds/26as/links/{link_id}", status_code=204)
def delete_link(client_id: str, link_id: str, conn: Conn, actor: Actor) -> Response:
    tds_recon.delete_link(conn, parse_id(client_id, "Client"), parse_id(link_id, "Link"), actor)
    return Response(status_code=204)
