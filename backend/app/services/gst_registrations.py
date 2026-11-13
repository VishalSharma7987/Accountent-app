"""GST registration use-cases: create, update (also closes / deactivates), ledger-role map, read, list, and the
GSTIN live check. Rules G-01 .. G-06 and G-08 come from the pure engine (engine/gst_masters.py, engine/gstin.py).
Services take a Connection and never commit; checks run before the first write; every change is audit-logged.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_gst_masters as gst_repo
from app.engine import gst_masters as engine
from app.engine.gst_types import GstRegistration
from app.engine.gstin import GSTIN_RE, extract_pan, gstin_check_char, validate_gstin
from app.engine.models import ValidationError
from app.engine.parties import normalise_id
from app.rules import gst_rules
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


@dataclass(frozen=True)
class Registration:
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
    ledger_roles: dict[str, tuple[uuid.UUID, str]] = field(default_factory=dict)  # role -> (ledger_id, ledger_name)


@dataclass(frozen=True)
class GstinCheck:
    valid: bool
    errors: list[ValidationError]
    state_code: str | None
    state_name: str | None
    pan: str | None
    expected_check_char: str | None


def _snapshot(row: gst_repo.RegistrationRow) -> dict:
    return {
        "gstin": row.gstin, "registration_type": row.registration_type, "return_frequency": row.return_frequency,
        "composition_category": row.composition_category, "trade_name": row.trade_name,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None, "is_active": row.is_active,
    }


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def check_gstin(conn: Connection, gstin: str | None, on_date: date) -> GstinCheck:
    """Live GSTIN check for the screens (no write): errors G-01 .. G-03, the state, the PAN and the right check char."""
    text = normalise_id(gstin) or ""
    errors = validate_gstin(text, gst_rules.state_codes(conn, on_date), on_date)
    if GSTIN_RE.match(text) is None:
        return GstinCheck(False, errors, None, None, None, None)
    names = {s.code: s.name for s in gst_rules.state_codes(conn, on_date)}
    return GstinCheck(not errors, errors, text[:2], names.get(text[:2]), extract_pan(text), gstin_check_char(text[:14]))


def _validate(conn: Connection, client_id: object, *, gstin: str, registration_type: str, return_frequency: str,
              composition_category: str | None, effective_from: date, effective_to: date | None,
              exclude_id: object | None) -> None:
    profile = gst_repo.client_gst_profile(conn, client_id)
    if profile is None:
        raise ServiceError("not_found", "Client not found.")
    errors = engine.validate_registration(
        gstin=gstin, registration_type=registration_type, return_frequency=return_frequency,
        composition_category=composition_category, effective_from=effective_from, effective_to=effective_to,
        client_gst_type=profile[0], client_pan=profile[1], state_codes=gst_rules.state_codes(conn, effective_from),
        others=gst_repo.other_periods_of_gstin(conn, client_id, gstin, exclude_id),
    )
    if errors:
        raise VoucherRuleError(errors)


def create_registration(
    conn: Connection, client_id: object, *, gstin: str, registration_type: str, effective_from: date,
    return_frequency: str = "monthly", composition_category: str | None = None, trade_name: str | None = None,
    effective_to: date | None = None, actor: str,
) -> uuid.UUID:
    """Add a registration. The state code is taken from the GSTIN. Raises VoucherRuleError (G-01 .. G-06) or
    ServiceError registration_exists; writes nothing then."""
    actor = require_actor(actor)
    gstin = normalise_id(gstin) or ""
    composition_category = _clean(composition_category)
    if gst_repo.registration_exists(conn, client_id, gstin, effective_from):  # before G-06: same start = duplicate
        raise ServiceError(
            "registration_exists",
            f"GSTIN {gstin} is already registered from {effective_from.strftime('%d-%m-%Y')}.",
        )
    _validate(conn, client_id, gstin=gstin, registration_type=registration_type, return_frequency=return_frequency,
              composition_category=composition_category, effective_from=effective_from, effective_to=effective_to,
              exclude_id=None)
    reg_id = uuid.uuid4()
    gst_repo.insert_registration(
        conn, client_id, reg_id, gstin=gstin, state_code=gstin[:2], registration_type=registration_type,
        return_frequency=return_frequency, composition_category=composition_category, trade_name=_clean(trade_name),
        effective_from=effective_from, effective_to=effective_to,
    )
    audit.log(conn, AuditEntry(client_id, actor, "create", "gst_registration", reg_id,
                               new=_snapshot(gst_repo.registration_row(conn, client_id, reg_id))))  # type: ignore[arg-type]
    return reg_id


def update_registration(
    conn: Connection, client_id: object, registration_id: object, *, registration_type: str, effective_from: date,
    return_frequency: str = "monthly", composition_category: str | None = None, trade_name: str | None = None,
    effective_to: date | None = None, is_active: bool = True, actor: str,
) -> None:
    """Change a registration (the GSTIN never changes). Setting `effective_to` closes it; `is_active=False` switches it
    off. Refused while invoices already issued under it would fall outside the new period."""
    actor = require_actor(actor)
    existing = gst_repo.registration_row(conn, client_id, registration_id)
    if existing is None:
        raise ServiceError("not_found", "Registration not found for this client.")
    composition_category = _clean(composition_category)
    if effective_from != existing.effective_from and gst_repo.registration_exists(
            conn, client_id, existing.gstin, effective_from):
        raise ServiceError(
            "registration_exists",
            f"GSTIN {existing.gstin} is already registered from {effective_from.strftime('%d-%m-%Y')}.",
        )
    _validate(conn, client_id, gstin=existing.gstin, registration_type=registration_type,
              return_frequency=return_frequency, composition_category=composition_category,
              effective_from=effective_from, effective_to=effective_to, exclude_id=existing.id)
    outside = gst_repo.invoice_dates_outside(conn, client_id, existing.id, effective_from, effective_to)
    if outside:
        raise ServiceError(
            "registration_in_use",
            f"{outside} invoice(s) were already issued under this registration outside the new period: "
            "the period cannot exclude them.",
        )
    gst_repo.update_registration(
        conn, client_id, existing.id, registration_type=registration_type, return_frequency=return_frequency,
        composition_category=composition_category, trade_name=_clean(trade_name), effective_from=effective_from,
        effective_to=effective_to, is_active=is_active,
    )
    audit.log(conn, AuditEntry(client_id, actor, "update", "gst_registration", existing.id, old=_snapshot(existing),
                               new=_snapshot(gst_repo.registration_row(conn, client_id, existing.id))))  # type: ignore[arg-type]


def set_ledger_roles(conn: Connection, client_id: object, registration_id: object, roles: Mapping[str, object],
                     *, actor: str) -> None:
    """Replace the whole role -> ledger map of a registration. Rule G-08 (right group, same client, active); an
    unknown role name is a G-08 error too. Writes nothing on errors."""
    actor = require_actor(actor)
    existing = gst_repo.registration_row(conn, client_id, registration_id)
    if existing is None:
        raise ServiceError("not_found", "Registration not found for this client.")
    ledgers = {}
    for role, ledger_id in roles.items():
        try:
            ledgers[role] = repo.get_ledger(conn, client_id, uuid.UUID(str(ledger_id)))
        except ValueError:
            ledgers[role] = None
    errors = engine.validate_ledger_roles(ledgers, repo.groups_for_client(conn, client_id), client_id)
    if errors:
        raise VoucherRuleError(errors)
    old = {role: str(lid) for _, role, lid, _ in gst_repo.ledger_role_rows(conn, client_id, existing.id)}
    new = {role: str(ledger.id) for role, ledger in ledgers.items() if ledger is not None}
    gst_repo.replace_ledger_roles(conn, client_id, existing.id, {r: ledger.id for r, ledger in ledgers.items()  # type: ignore[union-attr]
                                                                  if ledger is not None})
    audit.log(conn, AuditEntry(client_id, actor, "update", "gst_ledger_roles", existing.id, old=old, new=new))


def _build(row: gst_repo.RegistrationRow, role_rows: list[tuple]) -> Registration:
    roles = {role: (lid, name) for rid, role, lid, name in role_rows if rid == row.id}
    return Registration(row.id, row.gstin, row.state_code, row.state_name, row.registration_type, row.return_frequency,
                        row.composition_category, row.trade_name, row.effective_from, row.effective_to, row.is_active,
                        roles)


def get_registration(conn: Connection, client_id: object, registration_id: object) -> Registration:
    row = gst_repo.registration_row(conn, client_id, registration_id)
    if row is None:
        raise ServiceError("not_found", "Registration not found for this client.")
    return _build(row, gst_repo.ledger_role_rows(conn, client_id, row.id))


def list_registrations(conn: Connection, client_id: object) -> list[Registration]:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    role_rows = gst_repo.ledger_role_rows(conn, client_id)
    return [_build(r, role_rows) for r in gst_repo.registration_rows(conn, client_id)]


def load_registration(conn: Connection, client_id: object, registration_id: object) -> GstRegistration:
    """The registration as the engine's plain data type (ledger_roles: role -> ledger_id as text), for other packages."""
    r = get_registration(conn, client_id, registration_id)
    return GstRegistration(
        str(r.id), r.gstin, r.state_code, r.registration_type, r.return_frequency, r.composition_category,
        r.effective_from, r.effective_to, r.is_active, r.trade_name,
        {role: str(lid) for role, (lid, _) in r.ledger_roles.items()},
    )
