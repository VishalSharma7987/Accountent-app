"""TDS masters use-cases (Phase 4, package A): deductor TAN and 194Q flags, deductee master, lower-deduction
certificates, ledger roles. Rules T-09 .. T-12, T-14, T-30 come from the pure engine (engine/tds_masters.py).
Services take a Connection and never commit; checks run before the first write; every change is audit-logged.

Other packages read masters through `load_deductee`, `load_certificate`, `load_certificates_of` and `ledger_for_role`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_tds_masters as tds_repo
from app.engine import tds_masters as engine
from app.engine.models import ValidationError
from app.engine.parties import normalise_id, party_nature
from app.engine.tds_types import Deductee, LowerDeductionCert
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


@dataclass(frozen=True)
class CertView:
    id: uuid.UUID
    certificate_no: str
    nature_key: str | None
    rate: Decimal
    max_amount: Decimal
    valid_from: date
    valid_to: date
    amount_used: Decimal
    amount_left: Decimal
    is_active: bool
    note: str | None = None


@dataclass(frozen=True)
class DeducteeView:
    ledger_id: uuid.UUID
    ledger_name: str
    pan: str | None
    pan_status: str
    deductee_type: str
    default_nature_key: str | None
    is_active: bool
    lower_certs: list[CertView] = field(default_factory=list)
    pan_warning: str | None = None


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _require_client(conn: Connection, client_id: object) -> None:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


# ============================================================================================ TAN and flags


def get_profile(conn: Connection, client_id: object) -> dict:
    row = tds_repo.client_tan(conn, client_id)
    if row is None:
        raise ServiceError("not_found", "Client not found.")
    flags = [{"financial_year_id": fy, "prev_year_turnover_over_threshold": over, "note": note}
             for fy, over, note in tds_repo.fy_flag_rows(conn, client_id)]
    return {"tan": row[0], "fy_flags": flags}


def set_tan(conn: Connection, client_id: object, tan: str, *, actor: str) -> None:
    """T-30: the deductor's TAN (capitals, AAAA99999A)."""
    actor = require_actor(actor)
    old = tds_repo.client_tan(conn, client_id)
    if old is None:
        raise ServiceError("not_found", "Client not found.")
    text = normalise_id(tan) or ""
    errors = engine.validate_tan(text)
    if errors:
        raise VoucherRuleError(errors)
    tds_repo.set_client_tan(conn, client_id, text)
    audit.log(conn, AuditEntry(client_id, actor, "update", "tds_profile", client_id, old={"tan": old[0]}, new={"tan": text}))


def set_fy_flag(conn: Connection, client_id: object, fy_id: object, over: bool, note: str | None, *, actor: str) -> None:
    """The Section 194Q buyer condition for a financial year: entered by the accountant, never guessed."""
    actor = require_actor(actor)
    _require_client(conn, client_id)
    if not tds_repo.fy_exists(conn, client_id, fy_id):
        raise ServiceError("not_found", "Financial year not found for this client.")
    old = tds_repo.fy_flag(conn, client_id, fy_id)
    tds_repo.upsert_fy_flag(conn, client_id, fy_id, over, _clean(note), actor)
    audit.log(conn, AuditEntry(
        client_id, actor, "update" if old else "create", "tds_fy_flag", fy_id,
        old=None if old is None else {"prev_year_turnover_over_threshold": old[0], "note": old[1]},
        new={"prev_year_turnover_over_threshold": over, "note": _clean(note)}))


def fy_flag(conn: Connection, client_id: object, fy_id: object) -> bool | None:
    """For package B (T-15): the flag of the year, None when the accountant has not entered it (never a default)."""
    row = tds_repo.fy_flag(conn, client_id, fy_id)
    return None if row is None else row[0]


# ============================================================================================ deductees


def _cert_view(c: tds_repo.CertRow) -> CertView:
    return CertView(c.id, c.certificate_no, c.nature_key, c.rate, c.max_amount, c.valid_from, c.valid_to, c.amount_used,
                    engine.available_amount(c.max_amount, c.amount_used), c.is_active, c.note)


def _view(row: tds_repo.DeducteeRow, certs: list[tds_repo.CertRow]) -> DeducteeView:
    _, warnings = engine.validate_deductee(row.pan, row.pan_status, row.deductee_type)
    return DeducteeView(row.ledger_id, row.ledger_name, row.pan, row.pan_status, row.deductee_type,
                        row.default_nature_key, row.is_active,
                        [_cert_view(c) for c in certs if c.deductee_ledger_id == row.ledger_id],
                        warnings[0].message if warnings else None)


def list_deductees(conn: Connection, client_id: object, q: str | None = None) -> list[DeducteeView]:
    _require_client(conn, client_id)
    certs = tds_repo.cert_rows(conn, client_id)
    return [_view(r, certs) for r in tds_repo.deductee_rows(conn, client_id, _clean(q))]


def get_deductee(conn: Connection, client_id: object, ledger_id: object) -> DeducteeView:
    row = tds_repo.deductee_row(conn, client_id, ledger_id)
    if row is None:
        raise ServiceError("not_found", "Deductee not found for this client.")
    return _view(row, tds_repo.cert_rows(conn, client_id, ledger_id=ledger_id))


def _snapshot(row: tds_repo.DeducteeRow) -> dict:
    return {"pan": row.pan, "pan_status": row.pan_status, "deductee_type": row.deductee_type,
            "default_nature_key": row.default_nature_key, "is_active": row.is_active}


def set_deductee(conn: Connection, client_id: object, ledger_id: object, *, pan: str | None, pan_status: str,
                 deductee_type: str, default_nature_key: str | None = None, is_active: bool = True,
                 actor: str) -> list[ValidationError]:
    """Create or replace the deductee row of a party ledger (Sundry Debtors / Creditors of the client). Rules T-09,
    T-10; returns the T-11 warnings (never blocks). Writes nothing on errors."""
    actor = require_actor(actor)
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    pan = normalise_id(pan)
    default_nature_key = _clean(default_nature_key)
    errors, warnings = engine.validate_deductee(pan, pan_status, deductee_type)
    groups = repo.groups_for_client(conn, client_id)
    if party_nature(ledger, groups) is None:
        errors.append(ValidationError(
            "T-09", f"'{ledger.name}' is not a party ledger: a deductee must sit under Sundry Debtors or Sundry Creditors."))
    elif not ledger.is_active:
        errors.append(ValidationError("T-09", f"Ledger '{ledger.name}' is inactive."))
    if default_nature_key is not None and tds_repo.nature_kind(conn, default_nature_key) is None:
        errors.append(ValidationError("T-03", f"Nature '{default_nature_key}' does not exist."))
    if errors:
        raise VoucherRuleError(errors)
    old = tds_repo.deductee_row(conn, client_id, ledger.id)
    tds_repo.upsert_deductee(conn, client_id, ledger.id, pan=pan, pan_status=pan_status, deductee_type=deductee_type,
                             default_nature_key=default_nature_key, is_active=is_active)
    new = tds_repo.deductee_row(conn, client_id, ledger.id)
    audit.log(conn, AuditEntry(client_id, actor, "update" if old else "create", "tds_deductee", ledger.id,
                               old=_snapshot(old) if old else None, new=_snapshot(new)))  # type: ignore[arg-type]
    return warnings


def load_deductee(conn: Connection, client_id: object, ledger_id: object) -> Deductee | None:
    """The deductee as the engine's plain data type (None = no deductee row: rule T-09 for package B)."""
    row = tds_repo.deductee_row(conn, client_id, ledger_id)
    if row is None or not row.is_active:
        return None
    return Deductee(str(row.ledger_id), row.pan, row.pan_status, row.deductee_type, row.default_nature_key)


# ============================================================================================ certificates


def _cert_snapshot(c: tds_repo.CertRow) -> dict:
    return {"certificate_no": c.certificate_no, "nature_key": c.nature_key, "rate": str(c.rate),
            "max_amount": str(c.max_amount), "valid_from": c.valid_from.isoformat(),
            "valid_to": c.valid_to.isoformat(), "note": c.note, "is_active": c.is_active}


def add_certificate(conn: Connection, client_id: object, ledger_id: object, *, certificate_no: str,
                    nature_key: str | None, rate: Decimal, max_amount: Decimal, valid_from: date, valid_to: date,
                    note: str | None = None, actor: str) -> uuid.UUID:
    """Record a lower / nil deduction certificate of a deductee. T-12 (master side); `certificate_exists` for the same
    number and start date."""
    actor = require_actor(actor)
    if tds_repo.deductee_row(conn, client_id, ledger_id) is None:
        raise ServiceError("not_found", "Deductee not found for this client.")
    certificate_no = (certificate_no or "").strip()
    nature_key = _clean(nature_key)
    errors = engine.validate_certificate(certificate_no=certificate_no, rate=rate, max_amount=max_amount,
                                         valid_from=valid_from, valid_to=valid_to)
    if nature_key is not None and tds_repo.nature_kind(conn, nature_key) is None:
        errors.append(ValidationError("T-12", f"Nature '{nature_key}' does not exist."))
    if errors:
        raise VoucherRuleError(errors)
    if tds_repo.cert_exists(conn, client_id, certificate_no, valid_from):
        raise ServiceError("certificate_exists", f"Certificate {certificate_no} valid from "
                                                 f"{valid_from.strftime('%d-%m-%Y')} is already recorded.")
    cert_id = uuid.uuid4()
    tds_repo.insert_cert(conn, client_id, cert_id, ledger_id, certificate_no=certificate_no, nature_key=nature_key,
                         rate=rate, max_amount=max_amount, valid_from=valid_from, valid_to=valid_to, note=_clean(note))
    audit.log(conn, AuditEntry(client_id, actor, "create", "tds_certificate", cert_id,
                               new=_cert_snapshot(tds_repo.cert_row(conn, client_id, ledger_id, cert_id))))  # type: ignore[arg-type]
    return cert_id


def update_certificate(conn: Connection, client_id: object, ledger_id: object, cert_id: object, *,
                       is_active: bool = True, note: str | None = None, valid_to: date | None = None, actor: str) -> None:
    """Switch a certificate off, change its note, or SHORTEN its validity (never extend: a new certificate is a new
    row). Number, rate, limit and start never change, so earlier deductions stay explainable."""
    actor = require_actor(actor)
    existing = tds_repo.cert_row(conn, client_id, ledger_id, cert_id)
    if existing is None:
        raise ServiceError("not_found", "Certificate not found for this deductee.")
    new_to = valid_to or existing.valid_to
    if new_to > existing.valid_to:
        raise VoucherRuleError([ValidationError(
            "T-12", f"The validity can only be shortened (now until {existing.valid_to.strftime('%d-%m-%Y')}); "
                    "record a new certificate instead.")])
    if new_to < existing.valid_from:
        raise VoucherRuleError([ValidationError(
            "T-12", f"The new end date {new_to.strftime('%d-%m-%Y')} is before the start "
                    f"{existing.valid_from.strftime('%d-%m-%Y')}.")])
    tds_repo.update_cert(conn, client_id, existing.id, is_active=is_active, note=_clean(note), valid_to=new_to)
    audit.log(conn, AuditEntry(client_id, actor, "update", "tds_certificate", existing.id, old=_cert_snapshot(existing),
                               new=_cert_snapshot(tds_repo.cert_row(conn, client_id, ledger_id, cert_id))))  # type: ignore[arg-type]


def list_certificates(conn: Connection, client_id: object, ledger_id: object) -> list[CertView]:
    if tds_repo.deductee_row(conn, client_id, ledger_id) is None:
        raise ServiceError("not_found", "Deductee not found for this client.")
    return [_cert_view(c) for c in tds_repo.cert_rows(conn, client_id, ledger_id=ledger_id)]


def _engine_cert(c: tds_repo.CertRow) -> LowerDeductionCert:
    return LowerDeductionCert(str(c.id), str(c.deductee_ledger_id), c.certificate_no, c.nature_key, c.rate,
                              c.max_amount, c.valid_from, c.valid_to, c.amount_used)


def load_certificate(conn: Connection, client_id: object, ledger_id: object, cert_id: object) -> LowerDeductionCert | None:
    """For package B: the certificate as engine data with `amount_used` (posted items only); None = not found for
    this deductee. Whether it is active is for the engine to refuse (`is_active` rows are returned only when active)."""
    row = tds_repo.cert_row(conn, client_id, ledger_id, cert_id)
    return _engine_cert(row) if row is not None and row.is_active else None


def load_certificates_of(conn: Connection, client_id: object, ledger_id: object) -> list[LowerDeductionCert]:
    return [_engine_cert(c) for c in tds_repo.cert_rows(conn, client_id, ledger_id=ledger_id) if c.is_active]


# ============================================================================================ ledger roles


def get_ledger_roles(conn: Connection, client_id: object) -> list[dict]:
    _require_client(conn, client_id)
    return [{"role": role, "nature_key": nature, "ledger_id": lid, "ledger_name": name}
            for role, nature, lid, name in tds_repo.ledger_role_rows(conn, client_id)]


def set_ledger_roles(conn: Connection, client_id: object, entries: list[tuple[str, str | None, object]], *,
                     actor: str) -> None:
    """Replace the whole role map (T-14). Writes nothing on errors."""
    actor = require_actor(actor)
    _require_client(conn, client_id)
    ledgers: dict[object, object] = {}
    parsed: list[tuple[str, str | None, object]] = []
    for role, nature, ledger_id in entries:
        try:
            lid = uuid.UUID(str(ledger_id))
        except ValueError:
            lid = None
        parsed.append((role, _clean(nature), lid))
        if lid is not None and lid not in ledgers:
            ledgers[lid] = repo.get_ledger(conn, client_id, lid)
    errors = engine.validate_ledger_roles(parsed, ledgers, repo.groups_for_client(conn, client_id), client_id,  # type: ignore[arg-type]
                                          tds_repo.nature_kinds(conn))
    if errors:
        raise VoucherRuleError(errors)
    old = [{"role": r, "nature_key": n, "ledger_id": str(lid)} for r, n, lid, _ in tds_repo.ledger_role_rows(conn, client_id)]
    tds_repo.replace_ledger_roles(conn, client_id, parsed)
    audit.log(conn, AuditEntry(client_id, actor, "update", "tds_ledger_roles", client_id, old={"roles": old},
                               new={"roles": [{"role": r, "nature_key": n, "ledger_id": str(lid)} for r, n, lid in parsed]}))


def ledger_for_role(conn: Connection, client_id: object, role: str, nature_key: str | None = None) -> uuid.UUID | None:
    """For package B / C (T-14): the ledger of a role for a nature, falling back to the role's default ledger; None when
    neither is mapped (the caller refuses: never invent a ledger)."""
    rows = {(r, n): lid for r, n, lid, _ in tds_repo.ledger_role_rows(conn, client_id)}
    return rows.get((role, nature_key)) or rows.get((role, None))
