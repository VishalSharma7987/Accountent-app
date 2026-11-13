"""Inventory masters endpoints (docs/PHASE5_API_CONTRACT.md, package A): godowns, stock items, policy, opening stock."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_inventory_masters import (
    GodownCreated,
    GodownIn,
    GodownOut,
    GodownUpdate,
    OpeningIn,
    OpeningOut,
    OpeningSaved,
    PolicyCopyIn,
    PolicyIn,
    PolicyOut,
    StockItemIn,
    StockItemOut,
    godown_out,
    opening_out,
    policy_out,
    stock_item_out,
)
from app.engine.inventory_masters import OpeningInput
from app.services import inventory_masters as svc

router = APIRouter(tags=["inventory"])


@router.get("/clients/{client_id}/godowns", response_model=list[GodownOut])
def list_godowns(client_id: str, conn: Connection = Depends(get_conn)):
    return [godown_out(g) for g in svc.list_godowns(conn, parse_id(client_id, "Client"))]


@router.post("/clients/{client_id}/godowns", status_code=201, response_model=GodownCreated)
def create_godown(client_id: str, body: GodownIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return GodownCreated(id=svc.create_godown(conn, parse_id(client_id, "Client"), name=body.name, actor=actor))


@router.put("/clients/{client_id}/godowns/{godown_id}", response_model=OkOut)
def update_godown(client_id: str, godown_id: str, body: GodownUpdate, conn: Connection = Depends(get_conn),
                  actor: str = Depends(get_actor)):
    svc.update_godown(conn, parse_id(client_id, "Client"), parse_id(godown_id, "Godown"), name=body.name,
                      is_active=body.is_active, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/stock-items", response_model=list[StockItemOut])
def list_stock_items(client_id: str, q: str | None = None, active: bool | None = None,
                     financial_year_id: str | None = Query(default=None), conn: Connection = Depends(get_conn)):
    fy = None if financial_year_id is None else parse_id(financial_year_id, "Financial year")
    return [stock_item_out(s) for s in svc.list_stock_items(
        conn, parse_id(client_id, "Client"), q=q, active=active, financial_year_id=fy)]


@router.put("/clients/{client_id}/stock-items/{item_id}", response_model=OkOut)
def put_stock_item(client_id: str, item_id: str, body: StockItemIn, conn: Connection = Depends(get_conn),
                   actor: str = Depends(get_actor)):
    svc.put_stock_item(conn, parse_id(client_id, "Client"), parse_id(item_id, "Item"), sku=body.sku,
                       default_godown_id=body.default_godown_id, is_active=body.is_active, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/inventory/policy", response_model=PolicyOut)
def get_policy(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return policy_out(svc.get_policy(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year")))


@router.put("/clients/{client_id}/inventory/policy", response_model=OkOut)
def put_policy(client_id: str, body: PolicyIn, financial_year_id: str, conn: Connection = Depends(get_conn),
               actor: str = Depends(get_actor)):
    svc.put_policy(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"),
                   valuation_method=body.valuation_method, negative_stock_mode=body.negative_stock_mode, actor=actor)
    return OkOut()


@router.post("/clients/{client_id}/inventory/policy/copy", response_model=OkOut)
def copy_policy(client_id: str, body: PolicyCopyIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.copy_policy(conn, parse_id(client_id, "Client"),
                    from_financial_year_id=parse_id(body.from_financial_year_id, "Financial year"),
                    to_financial_year_id=parse_id(body.to_financial_year_id, "Financial year"), actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/inventory/opening", response_model=OpeningOut)
def get_opening(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return opening_out(svc.get_opening(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year")))


@router.put("/clients/{client_id}/inventory/opening/{financial_year_id}", response_model=OpeningSaved)
def put_opening(client_id: str, financial_year_id: str, body: OpeningIn, conn: Connection = Depends(get_conn),
                actor: str = Depends(get_actor)):
    total = svc.replace_opening(
        conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"),
        [OpeningInput(r.item_id, r.godown_id, r.quantity, r.value) for r in body.rows], actor=actor)
    return OpeningSaved(total_value=f"{total:.2f}")
