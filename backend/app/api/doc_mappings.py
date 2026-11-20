"""Saved party / line mappings and draft building (docs/PHASE7_API_CONTRACT.md, package E)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_doc_mappings import (
    BuildDraftIn,
    BuildDraftOut,
    IdOut,
    LineMappingIn,
    LineMappingOut,
    PartyMappingIn,
    PartyMappingOut,
)
from app.services import doc_drafts, doc_mappings

router = APIRouter(tags=["mappings"])


@router.get("/clients/{client_id}/mappings/parties", response_model=list[PartyMappingOut])
def list_party_mappings(client_id: str, q: str | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return doc_mappings.list_party_mappings(conn, parse_id(client_id, "Client"), q)


@router.put("/clients/{client_id}/mappings/parties", response_model=IdOut)
def put_party_mapping(client_id: str, body: PartyMappingIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    new_id = doc_mappings.put_party_mapping(
        conn, parse_id(client_id, "Client"), match_kind=body.match_kind, match_key=body.match_key,
        party_ledger_id=body.party_ledger_id, replace=body.replace, actor=actor)
    return IdOut(id=new_id)


@router.delete("/clients/{client_id}/mappings/parties/{mapping_id}", response_model=OkOut)
def delete_party_mapping(client_id: str, mapping_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    doc_mappings.delete_party_mapping(conn, parse_id(client_id, "Client"), parse_id(mapping_id, "Mapping"), actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/mappings/lines", response_model=list[LineMappingOut])
def list_line_mappings(client_id: str, q: str | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return doc_mappings.list_line_mappings(conn, parse_id(client_id, "Client"), q)


@router.put("/clients/{client_id}/mappings/lines", response_model=IdOut)
def put_line_mapping(client_id: str, body: LineMappingIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    new_id = doc_mappings.put_line_mapping(
        conn, parse_id(client_id, "Client"), match_kind=body.match_kind, match_key=body.match_key, ledger_id=body.ledger_id,
        party_ledger_id=body.party_ledger_id, item_id=body.item_id, replace=body.replace, actor=actor)
    return IdOut(id=new_id)


@router.delete("/clients/{client_id}/mappings/lines/{mapping_id}", response_model=OkOut)
def delete_line_mapping(client_id: str, mapping_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    doc_mappings.delete_line_mapping(conn, parse_id(client_id, "Client"), parse_id(mapping_id, "Mapping"), actor=actor)
    return OkOut()


@router.post("/clients/{client_id}/documents/{document_id}/build-draft", response_model=BuildDraftOut)
def build_draft(client_id: str, document_id: str, body: BuildDraftIn, conn: Connection = Depends(get_conn),
                actor: str = Depends(get_actor)):
    out = doc_drafts.build_for_document(conn, parse_id(client_id, "Client"), parse_id(document_id, "Document"), body.extraction_id,
                                        actor=actor)
    return BuildDraftOut(queue_item_id=out.queue_item_id, status=out.status, findings=[f.as_dict() for f in out.findings],
                         draft_voucher_id=out.draft_voucher_id)
