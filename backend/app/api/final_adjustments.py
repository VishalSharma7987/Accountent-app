"""Period-end adjustment helpers (docs/PHASE6_API_CONTRACT.md, package A): partners and deed terms, ledger roles, draft journals."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut, money
from app.api.schemas_final_adjustments import (
    AdjustmentCreated,
    AdjustmentIn,
    AdjustmentOut,
    FindingOut,
    PartnerCreated,
    PartnerIn,
    PartnerOut,
    PartnerUpdate,
    PreviewOut,
    RoleIn,
    RoleRow,
    SetupIn,
    SetupOut,
    SetupRoleRow,
    TermsIn,
    TermsOut,
    lines_out,
    terms_out,
)
from app.services import final_adjustments as svc

router = APIRouter(tags=["final-accounts"])
P = "/clients/{client_id}"


# ------------------------------------------------------------------------------------------------ ledger roles


@router.post(P + "/final/setup-ledgers", response_model=SetupOut)
def setup_ledgers(client_id: str, body: SetupIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    rows = svc.setup_ledgers(conn, parse_id(client_id, "Client"), body.financial_year_id, actor=actor)
    return SetupOut(roles=[SetupRoleRow(**r) for r in rows])


@router.get(P + "/final/ledger-roles", response_model=list[RoleRow])
def get_ledger_roles(client_id: str, conn: Connection = Depends(get_conn)):
    return [RoleRow(**r) for r in svc.get_ledger_roles(conn, parse_id(client_id, "Client"))]


@router.put(P + "/final/ledger-roles/{role}", response_model=OkOut)
def put_ledger_role(client_id: str, role: str, body: RoleIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.set_ledger_role(conn, parse_id(client_id, "Client"), role, body.ledger_id, actor=actor)
    return OkOut()


# ------------------------------------------------------------------------------------------------ partners


@router.get(P + "/partners", response_model=list[PartnerOut])
def list_partners(client_id: str, conn: Connection = Depends(get_conn)):
    return [PartnerOut(**p) for p in svc.list_partners(conn, parse_id(client_id, "Client"))]


@router.post(P + "/partners", status_code=201, response_model=PartnerCreated)
def create_partner(client_id: str, body: PartnerIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    pid = svc.create_partner(conn, parse_id(client_id, "Client"), body.name, body.capital_ledger_id, body.current_ledger_id, actor=actor)
    return PartnerCreated(id=pid)


# the fixed path "terms" is declared before "/partners/{partner_id}"
@router.get(P + "/partners/terms", response_model=TermsOut)
def get_terms(client_id: str, financial_year_id: uuid.UUID = Query(...), conn: Connection = Depends(get_conn)):
    return terms_out(svc.get_terms(conn, parse_id(client_id, "Client"), financial_year_id))


@router.put(P + "/partners/terms/{fy_id}", response_model=OkOut)
def put_terms(client_id: str, fy_id: str, body: TermsIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.put_terms(conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"), [r.model_dump() for r in body.rows], actor=actor)
    return OkOut()


@router.put(P + "/partners/{partner_id}", response_model=OkOut)
def update_partner(client_id: str, partner_id: str, body: PartnerUpdate, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    svc.update_partner(conn, parse_id(client_id, "Client"), parse_id(partner_id, "Partner"), changes, actor=actor)
    return OkOut()


# ------------------------------------------------------------------------------------------------ adjustments


@router.post(P + "/adjustments/preview", response_model=PreviewOut)
def preview(client_id: str, body: AdjustmentIn, conn: Connection = Depends(get_conn)):
    r = svc.preview(conn, parse_id(client_id, "Client"), body.to_request())
    return PreviewOut(amount=money(r["amount"]), lines=lines_out(r["lines"]), narration=r["narration"], params=r["params"],
                      findings=[FindingOut(**f) for f in r["findings"]])


@router.post(P + "/adjustments", status_code=201, response_model=AdjustmentCreated)
def create(client_id: str, body: AdjustmentIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    r = svc.create(conn, parse_id(client_id, "Client"), body.to_request(), actor=actor)
    return AdjustmentCreated(adjustment_id=r["adjustment_id"], voucher_id=r["voucher_id"], auto_reverse_voucher_id=r["auto_reverse_voucher_id"],
                             amount=money(r["amount"]), lines=lines_out(r["lines"]))


@router.get(P + "/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(client_id: str, financial_year_id: uuid.UUID = Query(...), adj_type: str | None = None, conn: Connection = Depends(get_conn)):
    rows = svc.list_adjustments(conn, parse_id(client_id, "Client"), financial_year_id, adj_type)
    return [AdjustmentOut(id=a["id"], adj_type=a["adj_type"], as_on_date=a["as_on_date"], amount=money(a["amount"]), basis_note=a["basis_note"],
                          params=a["params"], voucher_id=a["voucher_id"], voucher_status=a["voucher_status"], voucher_number=a["voucher_number"],
                          auto_reverse_voucher_id=a["auto_reverse_voucher_id"]) for a in rows]


@router.delete(P + "/adjustments/{adjustment_id}", response_model=OkOut)
def delete_adjustment(client_id: str, adjustment_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.delete_adjustment(conn, parse_id(client_id, "Client"), parse_id(adjustment_id, "Adjustment"), actor=actor)
    return OkOut()
