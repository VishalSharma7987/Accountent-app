"""GST masters API (docs/PHASE3_API_CONTRACT.md "GST masters"): registrations and their ledger roles, the GSTIN live
check, the item master, and the read-only rule tables (each with the status roll-up of its rows)."""

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_gst_masters import (
    GstinCheckIn,
    GstinCheckOut,
    ItemCreated,
    ItemIn,
    ItemOut,
    LedgerRolesIn,
    RegistrationCreated,
    RegistrationIn,
    RegistrationOut,
    RegistrationUpdate,
    RuleStatusOut,
    RuleTableOut,
    gstin_check_out,
    item_out,
    registration_out,
    rule_row,
)
from app.rules import gst_rules
from app.services import gst_items, gst_registrations

router = APIRouter(tags=["gst"])


# ------------------------------------------------------------------------------------------- registrations


@router.get("/clients/{client_id}/gst/registrations", response_model=list[RegistrationOut])
def list_registrations(client_id: str, conn: Connection = Depends(get_conn)):
    return [registration_out(r) for r in gst_registrations.list_registrations(conn, parse_id(client_id, "Client"))]


@router.get("/clients/{client_id}/gst/registrations/{registration_id}", response_model=RegistrationOut)
def get_registration(client_id: str, registration_id: str, conn: Connection = Depends(get_conn)):
    return registration_out(gst_registrations.get_registration(
        conn, parse_id(client_id, "Client"), parse_id(registration_id, "Registration")))


@router.post("/clients/{client_id}/gst/registrations", status_code=201, response_model=RegistrationCreated)
def create_registration(client_id: str, body: RegistrationIn, conn: Connection = Depends(get_conn),
                        actor: str = Depends(get_actor)):
    reg_id = gst_registrations.create_registration(
        conn, parse_id(client_id, "Client"), gstin=body.gstin, registration_type=body.registration_type,
        return_frequency=body.return_frequency, composition_category=body.composition_category,
        trade_name=body.trade_name, effective_from=body.effective_from, effective_to=body.effective_to, actor=actor,
    )
    return RegistrationCreated(id=reg_id)


@router.put("/clients/{client_id}/gst/registrations/{registration_id}", response_model=OkOut)
def update_registration(client_id: str, registration_id: str, body: RegistrationUpdate,
                        conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    gst_registrations.update_registration(
        conn, parse_id(client_id, "Client"), parse_id(registration_id, "Registration"),
        registration_type=body.registration_type, return_frequency=body.return_frequency,
        composition_category=body.composition_category, trade_name=body.trade_name,
        effective_from=body.effective_from, effective_to=body.effective_to, is_active=body.is_active, actor=actor,
    )
    return OkOut()


@router.put("/clients/{client_id}/gst/registrations/{registration_id}/ledger-roles", response_model=OkOut)
def set_ledger_roles(client_id: str, registration_id: str, body: LedgerRolesIn, conn: Connection = Depends(get_conn),
                     actor: str = Depends(get_actor)):
    gst_registrations.set_ledger_roles(
        conn, parse_id(client_id, "Client"), parse_id(registration_id, "Registration"), body.roles, actor=actor)
    return OkOut()


@router.post("/gst/validate-gstin", response_model=GstinCheckOut)
def validate_gstin(body: GstinCheckIn, conn: Connection = Depends(get_conn)):
    return gstin_check_out(gst_registrations.check_gstin(conn, body.gstin, body.on_date or date.today()))


# ----------------------------------------------------------------------------------------------- item master


@router.get("/clients/{client_id}/gst/items", response_model=list[ItemOut])
def list_items(client_id: str, q: str | None = Query(default=None), kind: str | None = Query(default=None),
               conn: Connection = Depends(get_conn)):
    return [item_out(i) for i in gst_items.list_items(conn, parse_id(client_id, "Client"), q, kind or None)]


@router.post("/clients/{client_id}/gst/items", status_code=201, response_model=ItemCreated)
def create_item(client_id: str, body: ItemIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    item_id = gst_items.create_item(
        conn, parse_id(client_id, "Client"), name=body.name, item_kind=body.item_kind, hsn_sac=body.hsn_sac,
        uqc=body.uqc, sales_ledger_id=body.sales_ledger_id, purchase_ledger_id=body.purchase_ledger_id,
        default_itc_category_key=body.default_itc_category_key,
        default_rcm_category_key=body.default_rcm_category_key, actor=actor,
    )
    return ItemCreated(id=item_id)


@router.put("/clients/{client_id}/gst/items/{item_id}", response_model=OkOut)
def update_item(client_id: str, item_id: str, body: ItemIn, conn: Connection = Depends(get_conn),
                actor: str = Depends(get_actor)):
    gst_items.update_item(
        conn, parse_id(client_id, "Client"), parse_id(item_id, "Item"), name=body.name, item_kind=body.item_kind,
        hsn_sac=body.hsn_sac, uqc=body.uqc, sales_ledger_id=body.sales_ledger_id,
        purchase_ledger_id=body.purchase_ledger_id, default_itc_category_key=body.default_itc_category_key,
        default_rcm_category_key=body.default_rcm_category_key, is_active=body.is_active, actor=actor,
    )
    return OkOut()


# ------------------------------------------------------------------------------------------------ rule tables


def _table(load: Callable[[Connection, date], list], on: date, conn: Connection, **row_kw) -> RuleTableOut:
    rows = load(conn, on)
    summary = gst_rules.status_summary(rows)
    return RuleTableOut(on=on, status=RuleStatusOut(**summary), rows=[rule_row(r, **row_kw) for r in rows])


@router.get("/gst/state-codes", response_model=RuleTableOut)
def state_codes(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.state_codes, on or date.today(), conn)


@router.get("/gst/uqc", response_model=RuleTableOut)
def uqc(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.uqc_list, on or date.today(), conn)


@router.get("/gst/rate-slabs", response_model=RuleTableOut)
def rate_slabs(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.slabs, on or date.today(), conn)


@router.get("/gst/rcm-categories", response_model=RuleTableOut)
def rcm_categories(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.rcm_rules, on or date.today(), conn)


@router.get("/gst/blocked-credit-categories", response_model=RuleTableOut)
def blocked_credit_categories(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.blocked_rules, on or date.today(), conn)


@router.get("/gst/itc-conditions", response_model=RuleTableOut)
def itc_conditions(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.itc_conditions, on or date.today(), conn)


@router.get("/gst/composition-rules", response_model=RuleTableOut)
def composition_rules(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return _table(gst_rules.composition_rules, on or date.today(), conn, inr_fields=("turnover_limit",))


@router.get("/gst/thresholds", response_model=RuleTableOut)
def thresholds(on: date | None = Query(default=None), conn: Connection = Depends(get_conn)):
    day = on or date.today()
    rows = gst_rules.thresholds(conn, day)
    return RuleTableOut(
        on=day, status=RuleStatusOut(**gst_rules.status_summary(rows)),
        rows=[rule_row(r, inr_fields=("numeric_value",) if r.unit == "inr" else ()) for r in rows],
    )
