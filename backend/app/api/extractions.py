"""Invoice / bank statement extraction and engine checks (docs/PHASE7_API_CONTRACT.md "Extraction", package D).

Expected failures of a model call (switch off, provider error, invalid answer) are answered with status 200 and `status` set, never
raised, so the transaction commits and the audit rows (`llm_calls`, the invalid `extractions` row) are kept (plan decision 7).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_extractions import (
    CheckOut,
    ExtractIn,
    ExtractionOut,
    ExtractionVersionOut,
    ExtractOut,
    finding_out,
)
from app.services import extractions
from app.services.errors import ServiceError

router = APIRouter(tags=["extraction"])


def get_gateway():
    """The real gateway (package C). Resolved only for mode `llm`; tests replace this function."""
    from app.services import llm_extraction_gateway

    return llm_extraction_gateway.LlmGateway()


def _version_out(r) -> dict:
    return {"id": str(r.id), "version": r.version, "source": r.source, "status": r.status, "created_at": r.created_at.isoformat(),
            "superseded": r.superseded_at is not None}


@router.post("/clients/{client_id}/documents/{document_id}/extract", response_model=ExtractOut)
def extract(client_id: str, document_id: str, body: ExtractIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    cid, did = parse_id(client_id, "Client"), parse_id(document_id, "Document")
    if body.mode == "manual":
        if body.payload is None:
            raise ServiceError("invalid_request", "A manual extraction needs the payload (what the document says).")
        out = extractions.enter_manual(conn, client_id=cid, document_id=did, actor=actor, payload=body.payload)
    else:
        out = extractions.run_llm_extraction(conn, client_id=cid, document_id=did, actor=actor, gateway=get_gateway())
    return {"status": out.status, "extraction_id": None if out.extraction_id is None else str(out.extraction_id),
            "llm_call_id": None if out.llm_call_id is None else str(out.llm_call_id),
            "findings": [finding_out(f) for f in out.findings], "message": out.message}


@router.get("/clients/{client_id}/documents/{document_id}/extractions", response_model=list[ExtractionVersionOut])
def list_extractions(client_id: str, document_id: str, conn: Connection = Depends(get_conn)):
    return [_version_out(r) for r in extractions.list_versions(conn, parse_id(client_id, "Client"), parse_id(document_id, "Document"))]


@router.get("/clients/{client_id}/extractions/{extraction_id}", response_model=ExtractionOut)
def get_extraction(client_id: str, extraction_id: str, conn: Connection = Depends(get_conn)):
    r = extractions.get_extraction(conn, parse_id(client_id, "Client"), parse_id(extraction_id, "Extraction"))
    return {"id": str(r.id), "document_id": str(r.document_id), "version": r.version, "source": r.source, "status": r.status,
            "schema_version": r.schema_version, "payload": r.payload, "invalid_reason": r.invalid_reason,
            "llm_call_id": None if r.llm_call_id is None else str(r.llm_call_id), "superseded": r.superseded_at is not None}


@router.post("/clients/{client_id}/extractions/{extraction_id}/check", response_model=CheckOut)
def check_extraction(client_id: str, extraction_id: str, conn: Connection = Depends(get_conn)):
    out = extractions.check_extraction(conn, parse_id(client_id, "Client"), parse_id(extraction_id, "Extraction"))
    return {"findings": [finding_out(f) for f in out.findings], "recomputed": out.recomputed, "direction": out.direction,
            "place_of_supply": out.place_of_supply}
