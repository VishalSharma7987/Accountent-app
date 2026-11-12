from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import ClientCreate, ClientCreated, ClientDetail, ClientOut
from app.services import client_setup, queries
from app.services.client_setup import ClientProfile

router = APIRouter(tags=["clients"])


@router.post("/clients", status_code=201, response_model=ClientCreated)
def create_client(body: ClientCreate, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    profile = ClientProfile(
        name=body.name, entity_type=body.entity_type, business_type=body.business_type, gst_type=body.gst_type,
        legal_name=body.legal_name, pan=body.pan, state_code=body.state_code, books_begin_date=body.books_begin_date,
    )
    created = client_setup.create_client(
        conn, profile, fy_start=body.fy_start, actor=actor, proprietor_name=body.proprietor_name,
        partners=body.partners,
    )
    return ClientCreated(
        client_id=created.client_id, financial_year_id=created.financial_year_id, ledger_ids=created.ledger_ids
    )


@router.get("/clients", response_model=list[ClientOut])
def list_clients(conn: Connection = Depends(get_conn)):
    return [ClientOut(**row) for row in queries.list_clients(conn)]


@router.get("/clients/{client_id}", response_model=ClientDetail)
def get_client(client_id: str, conn: Connection = Depends(get_conn)):
    return ClientDetail(**queries.get_client(conn, parse_id(client_id, "Client")))
