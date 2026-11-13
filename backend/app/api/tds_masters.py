"""TDS masters API (docs/PHASE4_API_CONTRACT.md "Masters"): deductor TAN and 194Q flags, deductee master, lower-deduction
certificates, ledger roles, and the read-only rule tables (each with the status roll-up of its rows, T-50)."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_tds_masters import (
    CertCreated,
    CertIn,
    CertOut,
    CertUpdate,
    DeducteeIn,
    DeducteeOut,
    DeducteeSaved,
    FyFlagIn,
    FyFlagOut,
    LedgerRolesIn,
    LedgerRolesOut,
    ProfileOut,
    RoleOut,
    RuleStatusOut,
    RuleSummaryOut,
    RuleTableOut,
    TanIn,
    cert_out,
    deductee_out,
    rule_row,
    saved,
)
from app.engine.tds_masters import DEDUCTEE_TYPES
from app.rules import tds_rules
from app.services import tds_masters
from app.services.errors import ServiceError

router = APIRouter(tags=["tds"])


# ------------------------------------------------------------------------------------------- profile


@router.put("/clients/{client_id}/tds/profile", response_model=OkOut)
def set_profile(client_id: str, body: TanIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    tds_masters.set_tan(conn, parse_id(client_id, "Client"), body.tan, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/tds/profile", response_model=ProfileOut)
def get_profile(client_id: str, conn: Connection = Depends(get_conn)):
    p = tds_masters.get_profile(conn, parse_id(client_id, "Client"))
    return ProfileOut(tan=p["tan"], fy_flags=[FyFlagOut(**f) for f in p["fy_flags"]])


@router.put("/clients/{client_id}/tds/fy-flags/{fy_id}", response_model=OkOut)
def set_fy_flag(client_id: str, fy_id: str, body: FyFlagIn, conn: Connection = Depends(get_conn),
                actor: str = Depends(get_actor)):
    tds_masters.set_fy_flag(conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"),
                            body.prev_year_turnover_over_threshold, body.note, actor=actor)
    return OkOut()


# ------------------------------------------------------------------------------------------- deductees


@router.get("/clients/{client_id}/tds/deductees", response_model=list[DeducteeOut])
def list_deductees(client_id: str, q: str | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return [deductee_out(d) for d in tds_masters.list_deductees(conn, parse_id(client_id, "Client"), q)]


@router.put("/clients/{client_id}/tds/deductees/{ledger_id}", response_model=DeducteeSaved)
def set_deductee(client_id: str, ledger_id: str, body: DeducteeIn, conn: Connection = Depends(get_conn),
                 actor: str = Depends(get_actor)):
    warnings = tds_masters.set_deductee(
        conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), pan=body.pan, pan_status=body.pan_status,
        deductee_type=body.deductee_type, default_nature_key=body.default_nature_key, is_active=body.is_active,
        actor=actor)
    return saved(warnings)


@router.post("/clients/{client_id}/tds/deductees/{ledger_id}/certificates", status_code=201, response_model=CertCreated)
def add_certificate(client_id: str, ledger_id: str, body: CertIn, conn: Connection = Depends(get_conn),
                    actor: str = Depends(get_actor)):
    cert_id = tds_masters.add_certificate(
        conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), certificate_no=body.certificate_no,
        nature_key=body.nature_key, rate=body.rate, max_amount=body.max_amount, valid_from=body.valid_from,
        valid_to=body.valid_to, note=body.note, actor=actor)
    return CertCreated(id=cert_id)


@router.put("/clients/{client_id}/tds/deductees/{ledger_id}/certificates/{cert_id}", response_model=OkOut)
def update_certificate(client_id: str, ledger_id: str, cert_id: str, body: CertUpdate,
                       conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    tds_masters.update_certificate(
        conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), parse_id(cert_id, "Certificate"),
        is_active=body.is_active, note=body.note, valid_to=body.valid_to, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/tds/deductees/{ledger_id}/certificates", response_model=list[CertOut])
def list_certificates(client_id: str, ledger_id: str, conn: Connection = Depends(get_conn)):
    return [cert_out(c) for c in tds_masters.list_certificates(
        conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"))]


# ------------------------------------------------------------------------------------------- ledger roles


@router.put("/clients/{client_id}/tds/ledger-roles", response_model=OkOut)
def set_ledger_roles(client_id: str, body: LedgerRolesIn, conn: Connection = Depends(get_conn),
                     actor: str = Depends(get_actor)):
    tds_masters.set_ledger_roles(conn, parse_id(client_id, "Client"),
                                 [(r.role, r.nature_key, r.ledger_id) for r in body.roles], actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/tds/ledger-roles", response_model=LedgerRolesOut)
def get_ledger_roles(client_id: str, conn: Connection = Depends(get_conn)):
    return LedgerRolesOut(roles=[RoleOut(**r) for r in tds_masters.get_ledger_roles(conn, parse_id(client_id, "Client"))])


# ------------------------------------------------------------------------------------------------ rule tables


def _table(name: str, rows: list, on: date) -> RuleTableOut:
    return RuleTableOut(
        on=on, status=RuleStatusOut(**tds_rules.status_summary(rows)),
        rule_status=RuleSummaryOut(**tds_rules.rule_status({name: rows})), rows=[rule_row(r) for r in rows])


@router.get("/tds/natures", response_model=RuleTableOut)
def natures(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table("nature", tds_rules.load_natures(conn), on or date.today())


@router.get("/tds/section-map", response_model=RuleTableOut)
def section_map(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    day = on or date.today()
    refs = tds_rules.load_section_refs(conn)
    rows = tds_rules.section_map(tds_rules.load_natures(conn), refs, day)
    status_rows = [SimpleNamespace(verification_status=r["status"]) for r in rows]
    return RuleTableOut(
        on=day, status=RuleStatusOut(**tds_rules.status_summary(status_rows)),
        rule_status=RuleSummaryOut(**tds_rules.rule_status({"section_ref": refs})), rows=rows)


@router.get("/tds/rates", response_model=RuleTableOut)
def rates(nature_key: str | None = Query(default=None), on: date | None = Query(default=None),
          conn: Connection = Depends(get_conn)):
    day = on or date.today()
    return _table("rate", tds_rules.load_rates(conn, day, nature_key or None), day)


@router.get("/tds/provisions", response_model=RuleTableOut)
def provisions(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    day = on or date.today()
    return _table("provision", tds_rules.load_provisions(conn, day), day)


@router.get("/tds/due-dates", response_model=RuleTableOut)
def due_dates(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    day = on or date.today()
    return _table("due_date", tds_rules.load_due_dates(conn, day), day)


@router.get("/tds/interest-rules", response_model=RuleTableOut)
def interest_rules(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    day = on or date.today()
    return _table("interest", tds_rules.load_interest_rules(conn, day), day)


@router.get("/tds/forms", response_model=RuleTableOut)
def forms(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    day = on or date.today()
    return _table("form", tds_rules.load_forms(conn, day), day)


@router.get("/tds/rates/lookup")
def rate_lookup(nature_key: str, deductee_group: str, on: date | None = Query(default=None),
                conn: Connection = Depends(get_conn)):
    """The rate rule for a nature and deductee group on a date; `no_rule` (422, T-02) when none is in force.
    `deductee_group` is individual_huf / others / any, or a deductee type (mapped through T-04)."""
    day = on or date.today()
    group = tds_rules.deductee_group(deductee_group) if deductee_group in DEDUCTEE_TYPES else deductee_group
    if group not in ("individual_huf", "others", "any"):
        raise ServiceError("invalid_group", f"'{deductee_group}' is not a deductee group or deductee type.")
    rule = tds_rules.rate_lookup(conn, nature_key, group, day)
    if rule is None:
        raise ServiceError("no_rule", f"No rate rule for '{nature_key}' ({group}) is in force on {day.strftime('%d-%m-%Y')}.")
    ref = tds_rules.pick_section_ref(tds_rules.load_section_refs(conn), nature_key, rule.act, day)

    def plain(v: Decimal | None) -> str | None:
        return None if v is None else f"{v:f}"

    return {
        "rate_rule_id": rule.id, "act": rule.act, "section_ref": ref.section_ref if ref else None,
        "table_ref": ref.table_ref if ref else None, "rate": plain(rule.rate), "no_pan_rate": plain(rule.no_pan_rate),
        "thresholds": {"single_payment": plain(rule.single_payment_threshold), "monthly": plain(rule.monthly_threshold),
                       "annual": plain(rule.annual_threshold)},
        "threshold_mode": rule.threshold_mode, "verification_status": rule.verification_status,
        "source_reference": rule.source_reference,
        "rule_status": tds_rules.rule_status({"rate": [rule], **({"section_ref": [ref]} if ref else {})}),
    }
