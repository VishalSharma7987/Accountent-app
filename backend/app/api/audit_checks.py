"""Audit runs, check catalogue, findings, report (docs/PHASE8_API_CONTRACT.md, package A). The audit only reads the books."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_audit_checks import (
    CheckOut,
    FindingOut,
    RuleOut,
    RunCreate,
    RunCreated,
    RunDetailOut,
    RunOut,
)
from app.services import audit_report, audit_runs

router = APIRouter(tags=["audit_checks"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _money(value) -> str | None:
    return None if value is None else f"{value:.2f}"


def _finding_out(f: dict) -> FindingOut:
    return FindingOut(**{**f, "amount": _money(f["amount"]), "disallowance_amount": _money(f["disallowance_amount"]),
                         "evidence": f["evidence"], "rule_status": audit_report.rule_status_of(f["evidence"])})


@router.get("/audit/checks", response_model=list[CheckOut])
def list_checks(conn: Connection = Depends(get_conn)):
    return audit_runs.list_checks(conn)


@router.get("/audit/rules", response_model=list[RuleOut])
def list_rules(conn: Connection = Depends(get_conn)):
    return [{**r, "amount": _money(r["amount"]), "disallow_percent": _money(r["disallow_percent"])} for r in audit_runs.list_rules(conn)]


@router.post("/clients/{client_id}/audit/runs", response_model=RunCreated, status_code=201)
def create_run(client_id: str, body: RunCreate, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    params = body.params.model_dump(exclude_none=True) if body.params else None
    return audit_runs.create_run(conn, parse_id(client_id, "Client"), actor, body.financial_year_id, body.from_date, body.to_date,
                                 body.check_ids, params)


@router.get("/clients/{client_id}/audit/runs", response_model=list[RunOut])
def list_runs(client_id: str, conn: Connection = Depends(get_conn)):
    return audit_runs.list_runs(conn, parse_id(client_id, "Client"))


@router.get("/clients/{client_id}/audit/runs/{run_id}", response_model=RunDetailOut)
def get_run(client_id: str, run_id: str, conn: Connection = Depends(get_conn)):
    return audit_runs.get_run(conn, parse_id(client_id, "Client"), parse_id(run_id, "Audit run"))


@router.get("/clients/{client_id}/audit/runs/{run_id}/findings", response_model=list[FindingOut])
def list_findings(client_id: str, run_id: str, check_id: str | None = None, severity: str | None = None, subject_id: uuid.UUID | None = None,
                  conn: Connection = Depends(get_conn)):
    rows = audit_runs.list_findings(conn, parse_id(client_id, "Client"), parse_id(run_id, "Audit run"), check_id, severity, subject_id)
    return [_finding_out(f) for f in rows]


@router.get("/clients/{client_id}/audit/runs/{run_id}/report")
def get_report(client_id: str, run_id: str, format: Literal["json", "xlsx"] = "json", conn: Connection = Depends(get_conn)):
    rep = audit_runs.build_report(conn, parse_id(client_id, "Client"), parse_id(run_id, "Audit run"))
    if format == "xlsx":
        return Response(audit_report.report_xlsx(rep), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="audit-run-{run_id}.xlsx"'})
    return rep
