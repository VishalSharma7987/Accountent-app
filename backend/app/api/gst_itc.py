"""ITC register endpoints (Phase 3, package C). Contract: docs/PHASE3_API_CONTRACT.md section "ITC"."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_gst_itc import (
    ConfirmIn,
    EvidenceIn,
    ReclaimIn,
    ReversalsIn,
    TagBlockedIn,
    jsonable,
)
from app.services import gst_itc

router = APIRouter(tags=["gst"])


def _opt_id(value: str | None, what: str) -> uuid.UUID | None:
    return None if value is None else parse_id(value, what)


@router.get("/clients/{client_id}/gst/itc")
def list_itc(
    client_id: str, registration_id: str | None = None, status: str | None = None, period: date | None = None,
    supplier_ledger_id: str | None = None, conn: Connection = Depends(get_conn),
):
    return jsonable(gst_itc.list_register(
        conn, parse_id(client_id, "Client"), registration_id=_opt_id(registration_id, "Registration"), status=status,
        period=period, supplier_ledger_id=_opt_id(supplier_ledger_id, "Supplier"),
    ))


# fixed paths before the {id} paths
@router.get("/clients/{client_id}/gst/itc/exposure-180")
def exposure_180(client_id: str, as_on: date, registration_id: str | None = None, conn: Connection = Depends(get_conn)):
    return jsonable(gst_itc.exposure_180(conn, parse_id(client_id, "Client"), _opt_id(registration_id, "Registration"), as_on))


@router.get("/clients/{client_id}/gst/itc/register-tie")
def register_tie(client_id: str, registration_id: str, as_on: date, conn: Connection = Depends(get_conn)):
    return jsonable(gst_itc.register_tie(conn, parse_id(client_id, "Client"), parse_id(registration_id, "Registration"), as_on))


@router.post("/clients/{client_id}/gst/itc/reversals", status_code=201)
def create_reversals(client_id: str, body: ReversalsIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    created = gst_itc.create_reversals(
        conn, parse_id(client_id, "Client"), body.registration_id, body.as_on, body.itc_entry_ids, actor=actor
    )
    return JSONResponse(status_code=201, content={"created": jsonable(created)})


@router.get("/clients/{client_id}/gst/itc/reversals")
def list_reversals(client_id: str, status: str | None = None, conn: Connection = Depends(get_conn)):
    return jsonable(gst_itc.list_reversals(conn, parse_id(client_id, "Client"), status))


@router.post("/clients/{client_id}/gst/itc/reversals/{reversal_id}/reclaim", status_code=201)
def reclaim(client_id: str, reversal_id: str, body: ReclaimIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    result = gst_itc.reclaim(conn, parse_id(client_id, "Client"), parse_id(reversal_id, "ITC reversal"), body.as_on, actor=actor)
    return JSONResponse(status_code=201, content=jsonable(result))


@router.get("/clients/{client_id}/gst/itc/{entry_id}")
def get_itc(client_id: str, entry_id: str, conn: Connection = Depends(get_conn)):
    return jsonable(gst_itc.get_entry(conn, parse_id(client_id, "Client"), parse_id(entry_id, "ITC entry")))


@router.put("/clients/{client_id}/gst/itc/{entry_id}/evidence")
def put_evidence(client_id: str, entry_id: str, body: EvidenceIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return jsonable(gst_itc.update_evidence(
        conn, parse_id(client_id, "Client"), parse_id(entry_id, "ITC entry"), tax_document_held=body.tax_document_held,
        goods_services_received=body.goods_services_received, received_date=body.received_date,
        supplier_tax_paid=body.supplier_tax_paid, evidence_note=body.evidence_note, actor=actor,
    ))


@router.post("/clients/{client_id}/gst/itc/{entry_id}/confirm")
def confirm(client_id: str, entry_id: str, body: ConfirmIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return jsonable(gst_itc.confirm(conn, parse_id(client_id, "Client"), parse_id(entry_id, "ITC entry"), reason=body.reason, actor=actor))


@router.get("/clients/{client_id}/gst/itc/{entry_id}/events")
def events(client_id: str, entry_id: str, conn: Connection = Depends(get_conn)):
    rows = gst_itc.events(conn, parse_id(client_id, "Client"), parse_id(entry_id, "ITC entry"))
    return [{**jsonable({k: v for k, v in r.items() if k != "created_at"}), "created_at": r["created_at"].isoformat()} for r in rows]


@router.post("/clients/{client_id}/gst/itc/{entry_id}/tag-blocked")
def tag_blocked(client_id: str, entry_id: str, body: TagBlockedIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return jsonable(gst_itc.tag_blocked(
        conn, parse_id(client_id, "Client"), parse_id(entry_id, "ITC entry"), category_key=body.category_key, note=body.note, actor=actor
    ))
