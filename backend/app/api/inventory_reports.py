"""Inventory report endpoints (docs/PHASE5_API_CONTRACT.md, package E): stock register, item ledger, closing stock
valuation (AS 2), NRV entries, Excel exports."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_inventory_reports import NrvIn
from app.services import inventory_export, inventory_nrv, inventory_reports

router = APIRouter(tags=["inventory"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _opt(value: str | None, what: str):
    return None if value is None else parse_id(value, what)


def _register(conn, client_id, financial_year_id, from_date, to_date, item_id, godown_id) -> dict:
    return inventory_reports.stock_register(
        conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), from_date=from_date, to_date=to_date,
        item_id=_opt(item_id, "Item"), godown_id=_opt(godown_id, "Godown"))


@router.put("/clients/{client_id}/inventory/nrv/{financial_year_id}", response_model=OkOut)
def put_nrv(client_id: str, financial_year_id: str, body: NrvIn, conn: Connection = Depends(get_conn),
            actor: str = Depends(get_actor)):
    rows = [inventory_nrv.NrvInput(r.item_id, r.nrv_per_unit, r.basis_note) for r in body.rows]
    inventory_nrv.put_nrv(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), body.as_on_date,
                          rows, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/inventory/nrv/{financial_year_id}")
def get_nrv(client_id: str, financial_year_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    rows = inventory_nrv.get_nrv(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), as_on)
    return {"rows": [{"item_id": str(r.item_id), "name": r.name, "as_on_date": r.as_on_date.isoformat(),
                      "nrv_per_unit": f"{r.nrv_per_unit:.2f}", "basis_note": r.basis_note, "entered_by": r.entered_by,
                      "entered_at": r.entered_at.isoformat()} for r in rows]}


@router.get("/clients/{client_id}/inventory/stock-register")
def stock_register(client_id: str, financial_year_id: str, from_date: date | None = Query(default=None, alias="from"),
                   to: date | None = None, item_id: str | None = None, godown_id: str | None = None,
                   conn: Connection = Depends(get_conn)):
    return _register(conn, client_id, financial_year_id, from_date, to, item_id, godown_id)


@router.get("/clients/{client_id}/inventory/stock-register/export")
def stock_register_export(client_id: str, financial_year_id: str, from_date: date | None = Query(default=None, alias="from"),
                          to: date | None = None, item_id: str | None = None, godown_id: str | None = None,
                          conn: Connection = Depends(get_conn)):
    report = _register(conn, client_id, financial_year_id, from_date, to, item_id, godown_id)
    return Response(content=inventory_export.register_to_xlsx(report), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="stock-register.xlsx"'})


@router.get("/clients/{client_id}/stock-items/{item_id}/ledger")
def item_ledger(client_id: str, item_id: str, financial_year_id: str, from_date: date | None = Query(default=None, alias="from"),
                to: date | None = None, conn: Connection = Depends(get_conn)):
    return inventory_reports.item_ledger(
        conn, parse_id(client_id, "Client"), parse_id(item_id, "Item"), parse_id(financial_year_id, "Financial year"),
        from_date=from_date, to_date=to)


def _closing(conn, client_id, financial_year_id, as_on) -> dict:
    return inventory_reports.closing_stock(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"),
                                           as_on=as_on)


@router.get("/clients/{client_id}/inventory/closing-stock")
def closing_stock(client_id: str, financial_year_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    return _closing(conn, client_id, financial_year_id, as_on)


@router.get("/clients/{client_id}/inventory/closing-stock/export")
def closing_stock_export(client_id: str, financial_year_id: str, as_on: date | None = None,
                         conn: Connection = Depends(get_conn)):
    report = _closing(conn, client_id, financial_year_id, as_on)
    return Response(content=inventory_export.closing_stock_to_xlsx(report), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="closing-stock.xlsx"'})
