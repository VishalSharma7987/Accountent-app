"""Request and response models of the GST masters (registrations, item master, GSTIN check, rule tables).

Rates and rule numbers are strings with up to 4 decimals (never floats); INR amounts are 2-decimal strings.
"""

import uuid
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.api.schemas import money
from app.engine.gst_types import GstItem
from app.services.gst_registrations import GstinCheck, Registration

# ------------------------------------------------------------------------------------------- registrations


class RegistrationIn(BaseModel):
    gstin: str
    registration_type: str  # regular | composition
    return_frequency: str = "monthly"  # monthly | qrmp
    composition_category: str | None = None
    trade_name: str | None = None
    effective_from: date
    effective_to: date | None = None


class RegistrationUpdate(BaseModel):
    registration_type: str
    return_frequency: str = "monthly"
    composition_category: str | None = None
    trade_name: str | None = None
    effective_from: date
    effective_to: date | None = None
    is_active: bool = True


class LedgerRoleOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str


class RegistrationOut(BaseModel):
    id: uuid.UUID
    gstin: str
    state_code: str
    state_name: str
    registration_type: str
    return_frequency: str
    composition_category: str | None
    trade_name: str | None
    effective_from: date
    effective_to: date | None
    is_active: bool
    ledger_roles: dict[str, LedgerRoleOut]


def registration_out(r: Registration) -> RegistrationOut:
    return RegistrationOut(
        id=r.id, gstin=r.gstin, state_code=r.state_code, state_name=r.state_name,
        registration_type=r.registration_type, return_frequency=r.return_frequency,
        composition_category=r.composition_category, trade_name=r.trade_name, effective_from=r.effective_from,
        effective_to=r.effective_to, is_active=r.is_active,
        ledger_roles={k: LedgerRoleOut(ledger_id=lid, ledger_name=name) for k, (lid, name) in r.ledger_roles.items()},
    )


class RegistrationCreated(BaseModel):
    id: uuid.UUID


class LedgerRolesIn(BaseModel):
    roles: dict[str, uuid.UUID | str | None]  # role -> ledger_id (replaces the whole map)


class GstinCheckIn(BaseModel):
    gstin: str
    on_date: date | None = None


class GstinErrorOut(BaseModel):
    rule_id: str
    message: str


class GstinCheckOut(BaseModel):
    valid: bool
    errors: list[GstinErrorOut]
    state_code: str | None
    state_name: str | None
    pan: str | None
    expected_check_char: str | None


def gstin_check_out(c: GstinCheck) -> GstinCheckOut:
    return GstinCheckOut(
        valid=c.valid, errors=[GstinErrorOut(rule_id=e.rule_id, message=e.message) for e in c.errors],
        state_code=c.state_code, state_name=c.state_name, pan=c.pan, expected_check_char=c.expected_check_char,
    )


# ----------------------------------------------------------------------------------------------- item master


class ItemIn(BaseModel):
    name: str
    item_kind: str  # goods | service
    hsn_sac: str
    uqc: str | None = None
    sales_ledger_id: uuid.UUID | None = None
    purchase_ledger_id: uuid.UUID | None = None
    default_itc_category_key: str | None = None
    default_rcm_category_key: str | None = None
    is_active: bool = True  # used by PUT only


class ItemOut(BaseModel):
    id: uuid.UUID
    name: str
    item_kind: str
    hsn_sac: str
    uqc: str | None
    sales_ledger_id: uuid.UUID | None
    purchase_ledger_id: uuid.UUID | None
    default_itc_category_key: str | None
    default_rcm_category_key: str | None
    is_active: bool


def item_out(i: GstItem) -> ItemOut:
    return ItemOut(**asdict(i))


class ItemCreated(BaseModel):
    id: uuid.UUID


# ------------------------------------------------------------------------------------------------ rule tables


class RuleStatusOut(BaseModel):
    overall: str  # verified | secondary_verified | pending (the weakest row)
    counts: dict[str, int]


class RuleTableOut(BaseModel):
    on: date
    status: RuleStatusOut
    rows: list[dict]


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, date):
        return value.isoformat()
    return value


def rule_row(row: object, *, inr_fields: tuple[str, ...] = ()) -> dict:
    """A rule dataclass as a JSON row: Decimals as strings (INR fields with 2 decimals), dates as ISO text."""
    out = {}
    for key, value in (asdict(row) if is_dataclass(row) else dict(row)).items():  # type: ignore[arg-type]
        out[key] = money(value) if key in inr_fields and isinstance(value, Decimal) else _plain(value)
    return out
