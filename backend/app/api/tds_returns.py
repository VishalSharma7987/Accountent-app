"""TDS / TCS return working, filed figures, certificates and exports (Phase 4, package D).

Contract: docs/PHASE4_API_CONTRACT.md, "Returns and certificates". The official statement / certificate file formats are
NOT produced: the JSON export is the own structure of the tool and says so (header X-Format-Status).
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_tds_returns import (
    CertificateIn,
    CertificateKind,
    CertificateUpdateIn,
    FiledReturnIn,
    ReturnKind,
    WorkingIn,
)
from app.services import tds_export, tds_returns

router = APIRouter(tags=["tds"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(content: bytes, media: str, name: str, status: str, json_file: bool = False) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "X-Rule-Status": status}
    if json_file:
        headers["X-Format-Status"] = tds_export.FORMAT_STATUS
    return Response(content=content, media_type=media, headers=headers)


def _opt_id(value: str | None, what: str):
    return None if value is None else parse_id(value, what)


@router.get("/clients/{client_id}/tds/return-working")
def return_working(client_id: str, financial_year_id: str, quarter: int, return_kind: ReturnKind, conn: Connection = Depends(get_conn)):
    return tds_returns.return_working(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), quarter, return_kind)


@router.post("/clients/{client_id}/tds/return-workings", status_code=201)
def save_working(client_id: str, body: WorkingIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return tds_returns.save_working(conn, parse_id(client_id, "Client"), parse_id(body.financial_year_id, "Financial year"),
                                    body.quarter, body.return_kind, actor)


@router.get("/clients/{client_id}/tds/return-workings")
def list_workings(client_id: str, financial_year_id: str | None = None, quarter: int | None = Query(default=None, ge=1, le=4),
                  return_kind: ReturnKind | None = None, conn: Connection = Depends(get_conn)):
    return tds_returns.list_workings(conn, parse_id(client_id, "Client"), _opt_id(financial_year_id, "Financial year"), quarter, return_kind)


@router.get("/tds/return-workings/{working_id}")
def get_working(working_id: str, conn: Connection = Depends(get_conn)):
    return tds_returns.get_working(conn, parse_id(working_id, "Return working"))


@router.post("/tds/return-workings/{working_id}/finalise")
def finalise(working_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return tds_returns.finalise_working(conn, parse_id(working_id, "Return working"), actor)


@router.get("/tds/return-workings/{working_id}/export.{fmt}")
def export_working(working_id: str, fmt: Literal["xlsx", "json"], conn: Connection = Depends(get_conn)):
    w = tds_returns.get_working(conn, parse_id(working_id, "Return working"))
    name = f"tds-{w['return_kind']}-{w['financial_year']}-q{w['quarter']}-v{w['version']}"
    status = w["rule_status"]["worst"]
    if fmt == "xlsx":
        return _file(tds_export.working_to_xlsx(w), XLSX, f"{name}.xlsx", status)
    return _file(tds_export.dumps(tds_export.working_json(w)), "application/json", f"{name}.json", status, json_file=True)


@router.put("/clients/{client_id}/tds/filed-returns")
def put_filed(client_id: str, body: FiledReturnIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return tds_returns.put_filed(conn, parse_id(client_id, "Client"), parse_id(body.financial_year_id, "Financial year"), body.quarter,
                                 body.return_kind, body.receipt_no, body.filed_on, body.data, actor)


@router.get("/clients/{client_id}/tds/filed-returns")
def get_filed(client_id: str, financial_year_id: str, quarter: int = Query(ge=1, le=4), return_kind: ReturnKind = "non_salary_resident",
              conn: Connection = Depends(get_conn)):
    return tds_returns.get_filed(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), quarter, return_kind)


@router.get("/clients/{client_id}/tds/certificates/preview")
def certificate_preview(client_id: str, deductee_ledger_id: str, financial_year_id: str, certificate_kind: CertificateKind,
                        quarter: int | None = Query(default=None, ge=1, le=4), conn: Connection = Depends(get_conn)):
    return tds_returns.certificate_preview(conn, parse_id(client_id, "Client"), parse_id(deductee_ledger_id, "Deductee"),
                                           parse_id(financial_year_id, "Financial year"), quarter, certificate_kind)


@router.post("/clients/{client_id}/tds/certificates", status_code=201)
def create_certificate(client_id: str, body: CertificateIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return tds_returns.create_certificate(conn, parse_id(client_id, "Client"), parse_id(body.deductee_ledger_id, "Deductee"),
                                          parse_id(body.financial_year_id, "Financial year"), body.quarter, body.certificate_kind, actor)


@router.get("/clients/{client_id}/tds/certificates")
def list_certificates(client_id: str, financial_year_id: str | None = None, quarter: int | None = Query(default=None, ge=1, le=4),
                      deductee_ledger_id: str | None = None, certificate_kind: CertificateKind | None = None,
                      conn: Connection = Depends(get_conn)):
    return tds_returns.list_certificates(conn, parse_id(client_id, "Client"), _opt_id(financial_year_id, "Financial year"), quarter,
                                         _opt_id(deductee_ledger_id, "Deductee"), certificate_kind)


@router.get("/clients/{client_id}/tds/certificates/{certificate_id}")
def get_certificate(client_id: str, certificate_id: str, conn: Connection = Depends(get_conn)):
    return tds_returns.get_certificate(conn, parse_id(client_id, "Client"), parse_id(certificate_id, "Certificate"))


@router.put("/clients/{client_id}/tds/certificates/{certificate_id}")
def update_certificate(client_id: str, certificate_id: str, body: CertificateUpdateIn, conn: Connection = Depends(get_conn),
                       actor: str = Depends(get_actor)):
    return tds_returns.update_certificate(conn, parse_id(client_id, "Client"), parse_id(certificate_id, "Certificate"),
                                          body.certificate_no, body.issued_on, actor)


@router.get("/clients/{client_id}/tds/certificates/{certificate_id}/export.xlsx")
def export_certificate(client_id: str, certificate_id: str, conn: Connection = Depends(get_conn)):
    c = tds_returns.get_certificate(conn, parse_id(client_id, "Client"), parse_id(certificate_id, "Certificate"))
    name = f"tds-certificate-{c['certificate_kind']}-v{c['version']}.xlsx"
    return _file(tds_export.certificate_to_xlsx(c), XLSX, name, c["rule_status"]["worst"])
