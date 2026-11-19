"""Fixed Asset Register and depreciation (docs/PHASE6_API_CONTRACT.md, package B): assets, events, Companies Act book run, income-tax block working."""

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_final_assets import (
    AssetIn,
    AssetUpdate,
    EventIn,
    FyIn,
    ItFinalizeIn,
    ItOpeningsIn,
    jsonable,
)
from app.services import final_assets

router = APIRouter(tags=["final-accounts"])


def _c(client_id: str):
    return parse_id(client_id, "Client")


def _fy(value: str):
    return parse_id(value, "Financial year")


# ------------------------------------------------------------------------------------------------ assets


@router.get("/clients/{client_id}/fixed-assets")
def list_assets(client_id: str, q: str | None = None, active: bool | None = None, conn: Connection = Depends(get_conn)):
    return jsonable(final_assets.list_assets(conn, _c(client_id), q, active))


@router.post("/clients/{client_id}/fixed-assets", status_code=201)
def create_asset(client_id: str, body: AssetIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    asset_id = final_assets.create_asset(conn, _c(client_id), body.model_dump(), actor=actor)
    return JSONResponse(status_code=201, content={"id": str(asset_id)})


# the fixed paths come before /{asset_id} so "rules" and "register" are not read as ids
@router.get("/clients/{client_id}/fixed-assets/rules")
def asset_rules(client_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    return jsonable(final_assets.rules_in_force(conn, as_on or date.today()))


@router.get("/clients/{client_id}/fixed-assets/register")
def asset_register(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return jsonable(final_assets.register(conn, _c(client_id), _fy(financial_year_id)))


@router.put("/clients/{client_id}/fixed-assets/{asset_id}", response_model=OkOut)
def update_asset(client_id: str, asset_id: str, body: AssetUpdate, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    final_assets.update_asset(conn, _c(client_id), parse_id(asset_id, "Fixed asset"), body.model_dump(), actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/fixed-assets/{asset_id}/events")
def list_events(client_id: str, asset_id: str, conn: Connection = Depends(get_conn)):
    return jsonable(final_assets.list_events(conn, _c(client_id), parse_id(asset_id, "Fixed asset")))


@router.post("/clients/{client_id}/fixed-assets/{asset_id}/events", status_code=201)
def add_event(client_id: str, asset_id: str, body: EventIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    event_id = final_assets.add_event(conn, _c(client_id), parse_id(asset_id, "Fixed asset"), body.model_dump(), actor=actor)
    return JSONResponse(status_code=201, content={"id": str(event_id)})


@router.delete("/clients/{client_id}/fixed-assets/{asset_id}/events/{event_id}", response_model=OkOut)
def delete_event(client_id: str, asset_id: str, event_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    final_assets.delete_event(conn, _c(client_id), parse_id(asset_id, "Fixed asset"), parse_id(event_id, "Asset event"), actor=actor)
    return OkOut()


# ------------------------------------------------------------------------------------------------ Companies Act book depreciation


@router.post("/clients/{client_id}/depreciation/book/preview")
def book_preview(client_id: str, body: FyIn, conn: Connection = Depends(get_conn)):
    return jsonable(final_assets.preview_book(conn, _c(client_id), body.financial_year_id))


@router.post("/clients/{client_id}/depreciation/book/run", status_code=201)
def book_run(client_id: str, body: FyIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return JSONResponse(status_code=201, content=jsonable(final_assets.run_book(conn, _c(client_id), body.financial_year_id, actor=actor)))


@router.get("/clients/{client_id}/depreciation/book/runs")
def book_runs(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    rows = final_assets.list_runs(conn, _c(client_id), _fy(financial_year_id))
    return jsonable([{**r, "created_at": r["created_at"].isoformat()} for r in rows])


@router.delete("/clients/{client_id}/depreciation/book/runs/{run_id}", response_model=OkOut)
def book_run_delete(client_id: str, run_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    final_assets.delete_run(conn, _c(client_id), parse_id(run_id, "Depreciation run"), actor=actor)
    return OkOut()


# ------------------------------------------------------------------------------------------------ income-tax block working


@router.put("/clients/{client_id}/depreciation/it/openings/{fy_id}", response_model=OkOut)
def it_openings(client_id: str, fy_id: str, body: ItOpeningsIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    final_assets.set_it_openings(conn, _c(client_id), _fy(fy_id), [r.model_dump() for r in body.rows], actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/depreciation/it/working")
def it_working(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return jsonable(final_assets.it_working(conn, _c(client_id), _fy(financial_year_id)))


@router.post("/clients/{client_id}/depreciation/it/working/finalize", response_model=OkOut)
def it_finalize(client_id: str, body: ItFinalizeIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    final_assets.finalize_it(conn, _c(client_id), body.financial_year_id, body.acknowledged_flags, actor=actor)
    return OkOut()
