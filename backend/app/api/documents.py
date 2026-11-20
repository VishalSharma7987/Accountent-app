"""Documents, private storage and text reading (docs/PHASE7_API_CONTRACT.md, package A).

Files are never served by a URL: `GET .../download` streams the bytes after the client check (the document is looked up by id AND
client id), and the response is marked `inline` with `nosniff`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import Connection

from app import config
from app.ai.storage import PrivateStore
from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_documents import (
    DocumentCreated,
    DocumentOut,
    DocumentRow,
    LinkCreated,
    LinkIn,
    PageTextOut,
    ReadPage,
    ReadTextIn,
    ReadTextOut,
    confidence,
)
from app.services import documents

router = APIRouter(tags=["documents"])

Conn = Annotated[Connection, Depends(get_conn)]
Actor = Annotated[str, Depends(get_actor)]


def get_store() -> PrivateStore:
    """The private store from DOCUMENT_STORE_DIR; 503 store_unavailable when it is not set. Tests override this dependency."""
    return PrivateStore(config.document_store_dir())


Store = Annotated[PrivateStore, Depends(get_store)]


@router.post("/clients/{client_id}/documents", status_code=201, response_model=DocumentCreated)
def upload(
    client_id: str, file: Annotated[UploadFile, File()], doc_type: Annotated[str, Form()], conn: Conn, actor: Actor, store: Store,
    financial_year_id: Annotated[str | None, Form()] = None,
):
    limit = config.max_upload_bytes()
    row = documents.register(
        conn, store, parse_id(client_id, "Client"), data=file.file.read(limit + 1), filename=file.filename, doc_type=doc_type,
        financial_year_id=parse_id(financial_year_id, "Financial year") if financial_year_id else None, actor=actor, max_bytes=limit)
    return DocumentCreated(id=row["id"], sha256=row["sha256"], size_bytes=row["size_bytes"], content_type=row["content_type"],
                           doc_type=row["doc_type"], status=row["status"], page_count=row["page_count"])


@router.get("/clients/{client_id}/documents", response_model=list[DocumentRow])
def list_documents(client_id: str, conn: Conn, doc_type: str | None = None, status: str | None = None, q: str | None = None):
    return documents.list_documents(conn, parse_id(client_id, "Client"), doc_type=doc_type, status=status, q=q)


@router.get("/clients/{client_id}/documents/{document_id}", response_model=DocumentOut)
def get_document(client_id: str, document_id: str, conn: Conn):
    row = documents.get_document(conn, parse_id(client_id, "Client"), parse_id(document_id, "Document"))
    for t in row["texts"]:
        t["mean_confidence"] = confidence(t["mean_confidence"])
    return row


@router.get("/clients/{client_id}/documents/{document_id}/download")
def download(client_id: str, document_id: str, conn: Conn, store: Store, actor: Actor):
    row, chunks = documents.open_file(conn, store, parse_id(client_id, "Client"), parse_id(document_id, "Document"))
    return StreamingResponse(
        chunks, media_type=row["content_type"],
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Content-Length": str(row["size_bytes"]),
                 "Cache-Control": "private, no-store"})


@router.get("/clients/{client_id}/documents/{document_id}/pages/{page_no}/text", response_model=PageTextOut)
def page_text(client_id: str, document_id: str, page_no: int, conn: Conn, method: str | None = None):
    return documents.page_text(conn, parse_id(client_id, "Client"), parse_id(document_id, "Document"), page_no, method)


@router.post("/clients/{client_id}/documents/{document_id}/read-text", response_model=ReadTextOut)
def read_text(client_id: str, document_id: str, conn: Conn, store: Store, actor: Actor, body: ReadTextIn | None = None):
    pages = documents.extract_text(conn, store, parse_id(client_id, "Client"), parse_id(document_id, "Document"),
                                   method=(body or ReadTextIn()).method, actor=actor)
    return ReadTextOut(pages=[ReadPage(page_no=p["page_no"], method=p["method"], char_count=p["char_count"],
                                       mean_confidence=confidence(p["mean_confidence"])) for p in pages])


@router.post("/clients/{client_id}/documents/{document_id}/links", status_code=201, response_model=LinkCreated)
def link(client_id: str, document_id: str, body: LinkIn, conn: Conn, actor: Actor):
    link_id = documents.link_voucher(conn, parse_id(client_id, "Client"), parse_id(document_id, "Document"), body.voucher_id,
                                     link_kind=body.link_kind, actor=actor)
    return LinkCreated(id=link_id)


@router.delete("/clients/{client_id}/documents/{document_id}/links/{voucher_id}")
def unlink(client_id: str, document_id: str, voucher_id: str, conn: Conn, actor: Actor):
    documents.unlink_voucher(conn, parse_id(client_id, "Client"), parse_id(document_id, "Document"), parse_id(voucher_id, "Voucher"), actor=actor)
    return {"ok": True}

