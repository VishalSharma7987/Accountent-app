from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_bills import PartyIn, PartyOut, party_out
from app.services import parties

router = APIRouter(tags=["parties"])


@router.get("/clients/{client_id}/parties", response_model=list[PartyOut])
def list_parties(client_id: str, nature: str | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return [party_out(p) for p in parties.list_parties(conn, parse_id(client_id, "Client"), nature or None)]


@router.get("/clients/{client_id}/parties/{ledger_id}", response_model=PartyOut)
def get_party(client_id: str, ledger_id: str, conn: Connection = Depends(get_conn)):
    return party_out(parties.get_party(conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger")))


@router.put("/clients/{client_id}/parties/{ledger_id}", response_model=OkOut)
def set_party(client_id: str, ledger_id: str, body: PartyIn, conn: Connection = Depends(get_conn),
              actor: str = Depends(get_actor)):
    parties.set_party(
        conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), gstin=body.gstin, pan=body.pan,
        state_code=body.state_code, credit_days=body.credit_days, msme_category=body.msme_category,
        udyam_no=body.udyam_no, msme_written_agreement=body.msme_written_agreement, bill_wise=body.bill_wise,
        msme_activity=body.msme_activity, udyam_registration_date=body.udyam_registration_date,
        msme_agreed_days=body.msme_agreed_days, gst_registration_type=body.gst_registration_type,
        actor=actor,
    )
    return OkOut()
