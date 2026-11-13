"""GSTR-2B import and reconciliation endpoints (docs/PHASE3_API_CONTRACT.md, package D)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_gst_recon import (
    LinkIn,
    apply_out,
    document_out,
    import_out,
    import_row_out,
    reconciliation_out,
)
from app.services import gst_recon
from app.services.errors import ServiceError

router = APIRouter(tags=["gst"])

Conn = Annotated[Connection, Depends(get_conn)]
Actor = Annotated[str, Depends(get_actor)]
MAX_FILE_BYTES = 10 * 1024 * 1024


@router.post("/clients/{client_id}/gst/2b/import", status_code=201)
def import_2b(client_id: str, conn: Conn, actor: Actor, file: Annotated[UploadFile, File()],
              registration_id: Annotated[str, Form()], period: Annotated[str, Form()], kind: Annotated[str, Form()] = "gstr2b"):
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ServiceError("import_invalid", "The file is larger than 10 MB.")
    result = gst_recon.import_file(
        conn, parse_id(client_id, "Client"), parse_id(registration_id, "GST registration"), kind, period,
        file.filename or "upload", content, actor,
    )
    return import_out(result)


@router.get("/clients/{client_id}/gst/2b/imports")
def imports(client_id: str, conn: Conn, registration_id: str | None = None):
    rows = gst_recon.list_imports(conn, parse_id(client_id, "Client"),
                                  parse_id(registration_id, "GST registration") if registration_id else None)
    return [import_row_out(r) for r in rows]


@router.get("/clients/{client_id}/gst/2b/imports/{import_id}/documents")
def documents(client_id: str, import_id: str, conn: Conn):
    rows = gst_recon.list_documents(conn, parse_id(client_id, "Client"), parse_id(import_id, "Import"))
    return [document_out(d) for d in rows]


@router.get("/clients/{client_id}/gst/2b/reconciliation")
def reconciliation(client_id: str, registration_id: str, period: str, conn: Conn):
    return reconciliation_out(
        gst_recon.reconcile(conn, parse_id(client_id, "Client"), parse_id(registration_id, "GST registration"), period)
    )


@router.post("/clients/{client_id}/gst/2b/links", status_code=201)
def create_link(client_id: str, body: LinkIn, conn: Conn, actor: Actor):
    link_id = gst_recon.create_link(
        conn, parse_id(client_id, "Client"), parse_id(body.document_id, "2B document"), parse_id(body.voucher_id, "Voucher"),
        body.link_kind, body.note, actor,
    )
    return {"link_id": str(link_id)}


@router.delete("/clients/{client_id}/gst/2b/links/{link_id}", status_code=204)
def delete_link(client_id: str, link_id: str, conn: Conn, actor: Actor) -> Response:
    gst_recon.delete_link(conn, parse_id(client_id, "Client"), parse_id(link_id, "Link"), actor)
    return Response(status_code=204)


@router.post("/clients/{client_id}/gst/2b/apply")
def apply(client_id: str, registration_id: str, period: str, conn: Conn, actor: Actor):
    return apply_out(
        gst_recon.apply(conn, parse_id(client_id, "Client"), parse_id(registration_id, "GST registration"), period, actor)
    )
