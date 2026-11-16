"""NRV entries for AS 2 (Phase 5, package E): net realisable value per item at a period end (rules S-09, S-15).
Upsert per item and date; a row with no NRV deletes the entry. Every change is audit-logged with old and new values.
Services never commit."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_inventory_reports as rep
from app.engine.inventory_report import validate_nrv_row
from app.engine.models import ValidationError
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


@dataclass(frozen=True)
class NrvInput:
    item_id: object
    nrv_per_unit: Decimal | None   # None = delete the entry
    basis_note: str = ""


def _year(conn: Connection, client_id: object, fy_id: object):
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def get_nrv(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None) -> list[rep.NrvRow]:
    _year(conn, client_id, fy_id)
    return rep.nrv_rows(conn, client_id, fy_id, as_on)


def put_nrv(conn: Connection, client_id: object, fy_id: object, as_on: date, rows: list[NrvInput], *, actor: str) -> None:
    """S-15 / S-09. All rows are checked before the first write."""
    actor = require_actor(actor)
    fy = _year(conn, client_id, fy_id)
    errors: list[ValidationError] = []
    if not (fy.start_date <= as_on <= fy.end_date):
        errors.append(ValidationError(
            "S-15", f"The NRV date {as_on:%d-%m-%Y} is outside the financial year {fy.start_date:%d-%m-%Y} to {fy.end_date:%d-%m-%Y}"))
    stock_items = {i.item_id for i in rep.stock_item_infos(conn, client_id)}
    seen: set = set()
    parsed: list[tuple[uuid.UUID, Decimal | None, str]] = []
    for n, row in enumerate(rows, start=1):
        item_id = _uuid_or_none(row.item_id)
        if item_id is None or item_id not in stock_items:
            errors.append(ValidationError("S-03", f"Row {n}: the item is not a stock item of this client", n))
            continue
        if item_id in seen:
            errors.append(ValidationError("S-15", f"Row {n}: the item appears twice for the same date", n))
            continue
        seen.add(item_id)
        if row.nrv_per_unit is not None:
            errors.extend(ValidationError(e.rule_id, f"Row {n}: {e.message}", n)
                          for e in validate_nrv_row(item_id, row.nrv_per_unit, row.basis_note))
        parsed.append((item_id, row.nrv_per_unit, (row.basis_note or "").strip()))
    if errors:
        raise VoucherRuleError(errors)
    if rep.year_has_locked_period(conn, client_id, fy_id):
        raise ServiceError("period_locked", "A period of this financial year is locked; NRV entries cannot be changed (S-09).")
    for item_id, nrv, note in parsed:
        old = rep.nrv_row(conn, client_id, item_id, as_on)
        old_data = None if old is None else {"item_id": str(item_id), "as_on_date": as_on.isoformat(),
                                             "nrv_per_unit": str(old.nrv_per_unit), "basis_note": old.basis_note}
        if nrv is None:
            if old is not None:
                rep.delete_nrv(conn, old.id)
                audit.log(conn, AuditEntry(client_id, actor, "delete", "stock_nrv", old.id, old=old_data))
            continue
        new_data = {"item_id": str(item_id), "as_on_date": as_on.isoformat(), "nrv_per_unit": str(nrv), "basis_note": note}
        if old is None:
            nrv_id = uuid.uuid4()
            rep.insert_nrv(conn, nrv_id, client_id, fy_id, item_id, as_on, nrv, note, actor)
            audit.log(conn, AuditEntry(client_id, actor, "create", "stock_nrv", nrv_id, new=new_data))
        elif old.nrv_per_unit != nrv or old.basis_note != note:
            rep.update_nrv(conn, old.id, nrv, note, actor)
            audit.log(conn, AuditEntry(client_id, actor, "update", "stock_nrv", old.id, old=old_data, new=new_data))
