"""GSTR-1 / GSTR-3B workings, tie-out, composition, saved versions, filed figures, exports (Phase 3, package E)."""

import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_gst_returns import FiledReturnIn, PeriodKind, WorkingIn
from app.services import gst_export, gst_returns
from app.services.errors import ServiceError

router = APIRouter(tags=["gst"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(content: bytes, media: str, name: str, env: dict, json_file: bool = False) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "X-Rule-Status": env["rule_status"]["worst"]}
    if json_file:
        headers["X-Format-Status"] = gst_export.FORMAT_STATUS
    return Response(content=content, media_type=media, headers=headers)


def _ids(client_id: str, registration_id: str):
    return parse_id(client_id, "Client"), parse_id(registration_id, "Registration")


def _gstr1(conn, client_id, registration_id, period_start, period_kind) -> dict:
    c, r = _ids(client_id, registration_id)
    return gst_returns.jsonable(gst_returns.gstr1_working(conn, c, r, period_kind, period_start))


def _gstr3b(conn, client_id, registration_id, period_start, period_kind) -> dict:
    c, r = _ids(client_id, registration_id)
    return gst_returns.jsonable(gst_returns.gstr3b_working(conn, c, r, period_kind, period_start))


def _tie_out(conn, client_id, registration_id, period_start, period_kind) -> dict:
    c, r = _ids(client_id, registration_id)
    return gst_returns.jsonable(gst_returns.tie_out(conn, c, r, period_kind, period_start))


@router.get("/clients/{client_id}/gst/gstr1")
def gstr1(client_id: str, registration_id: str, period_start: date, period_kind: PeriodKind = "month",
          conn: Connection = Depends(get_conn)):
    return _gstr1(conn, client_id, registration_id, period_start, period_kind)


@router.get("/clients/{client_id}/gst/gstr1/export.{fmt}")
def gstr1_export(client_id: str, fmt: Literal["xlsx", "json"], registration_id: str, period_start: date,
                 period_kind: PeriodKind = "month", conn: Connection = Depends(get_conn)):
    env = _gstr1(conn, client_id, registration_id, period_start, period_kind)
    if fmt == "xlsx":
        return _file(gst_export.working_to_xlsx(env, "GSTR-1 working"), XLSX, f"gstr1-{period_start:%Y-%m}.xlsx", env)
    return _file(json.dumps(gst_export.gstr1_json(env), indent=1).encode(), "application/json",
                 f"gstr1-{period_start:%Y-%m}.json", env, json_file=True)


@router.get("/clients/{client_id}/gst/gstr3b")
def gstr3b(client_id: str, registration_id: str, period_start: date, period_kind: PeriodKind = "month",
           conn: Connection = Depends(get_conn)):
    return _gstr3b(conn, client_id, registration_id, period_start, period_kind)


@router.get("/clients/{client_id}/gst/gstr3b/export.{fmt}")
def gstr3b_export(client_id: str, fmt: Literal["xlsx", "json"], registration_id: str, period_start: date,
                  period_kind: PeriodKind = "month", conn: Connection = Depends(get_conn)):
    env = _gstr3b(conn, client_id, registration_id, period_start, period_kind)
    if fmt == "xlsx":
        return _file(gst_export.working_to_xlsx(env, "GSTR-3B working"), XLSX, f"gstr3b-{period_start:%Y-%m}.xlsx", env)
    return _file(json.dumps(gst_export.gstr3b_json(env), indent=1).encode(), "application/json",
                 f"gstr3b-{period_start:%Y-%m}.json", env, json_file=True)


@router.get("/clients/{client_id}/gst/tie-out")
def tie_out(client_id: str, registration_id: str, period_start: date, period_kind: PeriodKind = "month",
            conn: Connection = Depends(get_conn)):
    env = _tie_out(conn, client_id, registration_id, period_start, period_kind)
    return {**env, **env["tables"]}


@router.get("/clients/{client_id}/gst/tie-out/export.xlsx")
def tie_out_export(client_id: str, registration_id: str, period_start: date, period_kind: PeriodKind = "month",
                   conn: Connection = Depends(get_conn)):
    env = _tie_out(conn, client_id, registration_id, period_start, period_kind)
    return _file(gst_export.working_to_xlsx(env, "GST tie-out"), XLSX, f"gst-tie-out-{period_start:%Y-%m}.xlsx", env)


@router.get("/clients/{client_id}/gst/composition")
def composition(client_id: str, registration_id: str, period_start: date, conn: Connection = Depends(get_conn)):
    c, r = _ids(client_id, registration_id)
    return gst_returns.jsonable(gst_returns.composition_working(conn, c, r, period_start))


@router.post("/clients/{client_id}/gst/workings", status_code=201)
def save_working(client_id: str, body: WorkingIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    c, r = _ids(client_id, body.registration_id)
    working_id, version = gst_returns.save_working(conn, c, r, body.return_type, body.period_kind, body.period_start, actor)
    return {"working_id": str(working_id), "version": version}


@router.get("/clients/{client_id}/gst/workings")
def list_workings(client_id: str, registration_id: str | None = None, return_type: str | None = None,
                  conn: Connection = Depends(get_conn)):
    rows = gst_returns.list_workings(
        conn, parse_id(client_id, "Client"), parse_id(registration_id, "Registration") if registration_id else None, return_type)
    return [{"id": str(r["id"]), "registration_id": str(r["gst_registration_id"]), "return_type": r["return_type"],
             "period_kind": r["period_kind"], "period_start": r["period_start"].isoformat(), "version": r["version"],
             "status": r["status"], "data_hash": r["data_hash"], "created_by": r["created_by"],
             "created_at": r["created_at"].isoformat()} for r in rows]


def _working_body(w: dict) -> dict:
    return {"id": str(w["id"]), "client_id": str(w["client_id"]), "registration_id": str(w["gst_registration_id"]),
            "return_type": w["return_type"], "period_kind": w["period_kind"], "period_start": w["period_start"].isoformat(),
            "period_end": w["period_end"].isoformat(), "version": w["version"], "status": w["status"],
            "data_hash": w["data_hash"], "rule_status": w["rule_statuses"], "created_by": w["created_by"],
            "created_at": w["created_at"].isoformat(), "data": w["data"]}


@router.get("/gst/workings/{working_id}")
def get_working(working_id: str, conn: Connection = Depends(get_conn)):
    return _working_body(gst_returns.get_working(conn, parse_id(working_id, "Working")))


@router.post("/gst/workings/{working_id}/finalise")
def finalise(working_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    gst_returns.finalise_working(conn, parse_id(working_id, "Working"), actor)
    return {"ok": True}


@router.get("/gst/workings/{working_id}/export.xlsx")
def working_export(working_id: str, conn: Connection = Depends(get_conn)):
    w = gst_returns.get_working(conn, parse_id(working_id, "Working"))
    title = f"{w['return_type'].upper()} working v{w['version']} ({w['status']})"
    name = f"{w['return_type']}-{w['period_start']:%Y-%m}-v{w['version']}.xlsx"
    return _file(gst_export.working_to_xlsx(w["data"], title), XLSX, name, w["data"])


@router.put("/clients/{client_id}/gst/filed-returns")
def put_filed(client_id: str, body: FiledReturnIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    c, r = _ids(client_id, body.registration_id)
    gst_returns.put_filed_return(conn, c, r, body.return_type, body.period_start, body.arn, body.filed_on, body.data, actor)
    return {"ok": True}


@router.get("/clients/{client_id}/gst/filed-returns")
def get_filed(client_id: str, registration_id: str, return_type: str, period_start: date = Query(),
              conn: Connection = Depends(get_conn)):
    c, r = _ids(client_id, registration_id)
    f = gst_returns.get_filed_return(conn, c, r, return_type, period_start)
    if f is None:
        raise ServiceError("not_found", "No filed figures were entered for this return and period.")
    return {"registration_id": registration_id, "return_type": f["return_type"], "period_start": f["period_start"].isoformat(),
            "arn": f["arn"], "filed_on": f["filed_on"].isoformat() if f["filed_on"] else None, "data": f["data"],
            "entered_by": f["entered_by"], "entered_at": f["entered_at"].isoformat()}
