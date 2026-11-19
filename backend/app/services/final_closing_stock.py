"""Closing stock approval (Phase 6 package C, F-41): the figure the Trading A/c and Balance Sheet use.

`inventory_report` reads the Phase 5 closing-stock report (cost less AS 2 write-down, item by item): the values are never typed.
`manual` needs cost, write-down and a basis note. `none` is zero stock and is allowed only for a service client. Nothing is guessed:
a year without an approval makes every statement carry the F-41 error. Services never commit; every change is audit-logged.
"""

import json
from datetime import date
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_final_statements as frepo
from app.engine.money import MoneyError, format_inr, parse_amount
from app.services import audit, final_hooks, inventory_reports
from app.services.errors import ServiceError, require_actor

SOURCES = ("inventory_report", "manual", "none")


def _m(value: Any) -> str:
    return f"{value:.2f}"


def _row_out(row: frepo.ClosingStockRow) -> dict:
    return {"as_on_date": row.as_on_date.isoformat(), "source": row.source, "inventory_method": row.inventory_method,
            "cost_value": _m(row.cost_value), "write_down": _m(row.write_down), "carrying_value": _m(row.carrying_value),
            "basis_note": row.basis_note, "approved_by": row.approved_by, "approved_at": row.approved_at.isoformat(), "detail": row.detail}


def _year(conn: Connection, client_id: object, fy_id: object) -> repo.FinancialYearRow:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def get_closing_stock(conn: Connection, client_id: object, fy_id: object) -> dict:
    """The approved figure (or null) and, when the client has an inventory policy, the Phase 5 report as a proposal."""
    _year(conn, client_id, fy_id)
    approved = frepo.get_closing_stock(conn, client_id, fy_id)
    proposal = None
    try:
        report = inventory_reports.closing_stock(conn, client_id, fy_id)
        proposal = {"as_on": report["as_on"], "policy": report["policy"], "totals": report["totals"], "rows": report["rows"],
                    "errors": report["errors"], "warnings": report["warnings"], "items_without_nrv": report["items_without_nrv"]}
    except ServiceError as exc:
        if exc.code != "no_policy":
            raise
    return {"approved": None if approved is None else _row_out(approved), "proposal": proposal}


def _money(value: object, what: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ServiceError("closing_stock_missing", f"{what} is required for this source of closing stock (F-41).")
    try:
        return parse_amount(value)
    except MoneyError as exc:
        raise ServiceError("invalid_closing_stock", f"{what}: {exc}") from None


def approve_closing_stock(conn: Connection, client_id: object, fy_id: object, *, source: str, as_on_date: date,
                          cost_value: object = None, write_down: object = None, basis_note: str | None = None,
                          actor: str | None) -> dict:
    who = require_actor(actor)
    fy = _year(conn, client_id, fy_id)
    if final_hooks.year_is_closed(conn, client_id, fy_id):
        raise ServiceError("year_closed", "This financial year is closed; closing stock cannot be changed. Reopen the year first.")
    if source not in SOURCES:
        raise ServiceError("invalid_closing_stock", "The source of closing stock must be inventory_report, manual or none.")
    if not fy.start_date <= as_on_date <= fy.end_date:
        raise ServiceError("invalid_closing_stock",
                           f"The date must lie inside the financial year {fy.start_date:%d-%m-%Y} to {fy.end_date:%d-%m-%Y}.")
    profile = frepo.client_profile(conn, client_id)
    note = (basis_note or "").strip()
    if not note:
        raise ServiceError("closing_stock_missing", "A basis note is required (how the closing stock was arrived at) (F-41).")
    method, detail = None, {}
    if source == "inventory_report":
        if cost_value is not None or write_down is not None:
            raise ServiceError("invalid_closing_stock", "With the inventory report as source the values are read from the report, never typed.")
        report = inventory_reports.closing_stock(conn, client_id, fy_id, as_on=as_on_date)
        if report["errors"]:
            raise ServiceError("invalid_closing_stock", "The closing stock report has errors; fix them first: "
                               + "; ".join(e["message"] for e in report["errors"]), report["errors"])
        cost, wd = parse_amount(report["totals"]["cost_value"]), parse_amount(report["totals"]["write_down"])
        method = report["policy"]["valuation_method"]
        detail = {"rows": report["rows"], "items_without_nrv": report["items_without_nrv"], "warnings": report["warnings"]}
    elif source == "manual":
        cost, wd = _money(cost_value, "Cost of closing stock"), _money(write_down, "Write-down")
    else:
        if profile is not None and profile.business_type != "service":
            raise ServiceError("invalid_closing_stock", "'No closing stock' is allowed only for a service business; a trading or "
                               "manufacturing client must record its closing stock (F-41).")
        if cost_value not in (None, "") or write_down not in (None, ""):
            raise ServiceError("invalid_closing_stock", "'No closing stock' carries no values.")
        cost, wd = parse_amount("0"), parse_amount("0")
    if wd > cost:
        raise ServiceError("invalid_closing_stock", f"The write-down {format_inr(wd)} is more than the cost {format_inr(cost)}.")
    carrying = cost - wd
    old = frepo.get_closing_stock(conn, client_id, fy_id)
    frepo.upsert_closing_stock(conn, client_id, fy_id, as_on=as_on_date, source=source, method=method, cost=cost, write_down=wd,
                               carrying=carrying, basis_note=note, detail=json.dumps(detail, default=str), actor=who)
    new = frepo.get_closing_stock(conn, client_id, fy_id)
    audit.log(conn, audit.AuditEntry(
        client_id, who, "approve_closing_stock" if old is None else "change_closing_stock", "final_closing_stock", fy_id,
        None if old is None else _row_out(old) | {"detail": "(stored)"}, _row_out(new) | {"detail": "(stored)"}))
    return {"ok": True, "carrying_value": _m(carrying)}
