"""Trading A/c, Profit and Loss, Appropriation and Balance Sheet of a non-company client (Phase 6 package C).

Read-only computations over posted / reversed vouchers. This module loads data (the Phase 1 Trial Balance inputs, the approved closing
stock, ledger roles, partner shares) and calls the pure engine `app/engine/final_statements.py`; it computes no amount (principle 1).
The year-end closing vouchers (and their reversals) are left out, so a closed year still shows its trading and profit (F-40).
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_final_statements as frepo
from app.engine import final_statements as engine
from app.engine.final_types import (
    ClosingStockIn,
    EntityType,
    LedgerBalanceIn,
    Statement,
    StatementFormat,
    StatementLine,
)
from app.services.errors import ServiceError


def _m(value: Decimal) -> str:
    return f"{value:.2f}"


def _year(conn: Connection, client_id: object, fy_id: object) -> repo.FinancialYearRow:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def _as_on(fy: repo.FinancialYearRow, as_on: date | None) -> date:
    on = as_on or fy.end_date
    if not fy.start_date <= on <= fy.end_date:
        raise ServiceError("invalid_period", f"The date must lie inside the financial year {fy.start_date:%d-%m-%Y} to {fy.end_date:%d-%m-%Y}.")
    return on


def ledger_positions(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None) -> list[LedgerBalanceIn]:
    """Every ledger's opening, year debit / credit totals and closing as on `as_on` (default the FY end), excluding the closing vouchers
    of a closed year. Also the input of the Schedule III and cash flow statements (packages D, E)."""
    fy = _year(conn, client_id, fy_id)
    on = _as_on(fy, as_on)
    skip = frepo.closing_voucher_ids(conn, client_id)
    lines = [x for x in repo.all_posted_lines(conn, client_id, fy_id) if x.voucher_id not in skip]
    return engine.ledger_positions(
        repo.ledgers_of_client(conn, client_id), repo.groups_for_client(conn, client_id), repo.openings_for_year(conn, client_id, fy_id),
        lines, on, frepo.ledger_roles(conn, client_id))


def _drill_out(x: Any) -> dict:
    return {"ledger_id": None if x.ledger_id is None else str(x.ledger_id), "ledger_name": x.ledger_name, "amount": _m(x.amount)}


def _line_out(x: StatementLine) -> dict:
    return {"code": x.code, "label": x.label, "amount": _m(x.amount), "previous_amount": None if x.previous_amount is None else _m(x.previous_amount),
            "note_no": x.note_no, "level": x.level, "is_total": x.is_total, "drill": [_drill_out(d) for d in x.drill]}


def statement_out(s: Statement, *, entity_type: str, stock: ClosingStockIn | None) -> dict:
    return {
        "key": s.key, "format": s.format.value, "title": s.title, "from_date": s.from_date.isoformat(), "to_date": s.to_date.isoformat(),
        "left": [_line_out(x) for x in s.left], "right": [_line_out(x) for x in s.right],
        "totals": {k: _m(v) for k, v in s.totals.items()}, "notes": [],
        "findings": [{"rule_id": f.rule_id, "message": f.message, "severity": f.severity,
                      "ledger_id": None if f.ledger_id is None else str(f.ledger_id), "line_no": f.line_no} for f in s.findings],
        "engine_version": s.engine_version, "rule_status": [],
        "basis": {"closing_stock_method": None if stock is None else stock.source, "closing_stock_source": None if stock is None else stock.source,
                  "entity_type": entity_type},
    }


def _load(conn: Connection, client_id: object, fy_id: object, as_on: date | None):
    fy = _year(conn, client_id, fy_id)
    on = _as_on(fy, as_on)
    profile = frepo.client_profile(conn, client_id)
    if profile.entity_type == EntityType.COMPANY.value:
        raise ServiceError("invalid_company_use_sch3", "This client is a company: its statements follow Schedule III. "
                           "Use the /final/sch3/ statements (F-47).")
    positions = ledger_positions(conn, client_id, fy_id, on)
    row = frepo.get_closing_stock(conn, client_id, fy_id)
    stock = None if row is None else ClosingStockIn(row.cost_value, row.write_down, row.carrying_value, row.source, row.as_on_date)
    entity = EntityType(profile.entity_type)
    partners = frepo.partner_shares(conn, client_id, fy_id) if entity in (EntityType.PARTNERSHIP, EntityType.LLP) else ()
    names = {code: g.name for code, g in repo.groups_for_client(conn, client_id).items()}
    ctx = engine.StatementContext(entity, fy.start_date, on, stock, partners, names)
    return positions, ctx, profile


def _format(value: str | None) -> StatementFormat:
    if value is None:
        return StatementFormat.HORIZONTAL           # F-47: the default for a non-company client
    try:
        fmt = StatementFormat(value)
    except ValueError:
        raise ServiceError("invalid_format", "The format must be vertical or horizontal.") from None
    if fmt == StatementFormat.SCH3:
        raise ServiceError("invalid_format", "The format must be vertical or horizontal.")
    return fmt


def trading(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None) -> dict:
    positions, ctx, profile = _load(conn, client_id, fy_id, as_on)
    return statement_out(engine.build_trading(positions, ctx), entity_type=profile.entity_type, stock=ctx.stock)


def profit_loss(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None, fmt: str | None = None) -> dict:
    positions, ctx, profile = _load(conn, client_id, fy_id, as_on)
    return statement_out(engine.build_profit_loss(positions, ctx, _format(fmt)), entity_type=profile.entity_type, stock=ctx.stock)


def balance_sheet(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None, fmt: str | None = None) -> dict:
    positions, ctx, profile = _load(conn, client_id, fy_id, as_on)
    return statement_out(engine.build_balance_sheet(positions, ctx, _format(fmt)), entity_type=profile.entity_type, stock=ctx.stock)


def appropriation(conn: Connection, client_id: object, fy_id: object) -> dict:
    positions, ctx, profile = _load(conn, client_id, fy_id, None)
    if profile.entity_type not in (EntityType.PARTNERSHIP.value, EntityType.LLP.value):
        raise ServiceError("invalid_not_a_firm", "The appropriation account exists only for a partnership or an LLP.")
    return statement_out(engine.build_appropriation(positions, ctx), entity_type=profile.entity_type, stock=ctx.stock)


def ledger_positions_out(conn: Connection, client_id: object, fy_id: object, as_on: date | None = None) -> list[dict]:
    return [{"ledger_id": str(x.ledger_id), "name": x.name, "group_code": x.group_code, "opening": _m(x.opening),
             "debit_total": _m(x.debit_total), "credit_total": _m(x.credit_total), "closing": _m(x.closing)}
            for x in ledger_positions(conn, client_id, fy_id, as_on)]
