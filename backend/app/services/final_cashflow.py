"""Cash Flow Statement (docs/PHASE6_API_CONTRACT.md, package E; rules F-49, F-50).

Loads the statements of packages C / D (their Statement objects and ledger positions), calls the pure engine
`app/engine/final_cashflow.py` and shapes the answer like the other statements. No amount is computed here (principle 1).
"""

from dataclasses import replace
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_final_sch3 as sch3_repo
from app.db import repositories_final_statements as frepo
from app.engine import final_cashflow as engine
from app.engine import final_statements as stmt_engine
from app.engine.final_types import ClosingStockIn, EntityType, Statement, StatementFormat
from app.services import final_sch3, final_statements
from app.services.errors import ServiceError


def _stock(conn: Connection, client_id: Any, fy_id: Any) -> ClosingStockIn | None:
    row = frepo.get_closing_stock(conn, client_id, fy_id)
    return None if row is None else ClosingStockIn(row.cost_value, row.write_down, row.carrying_value, row.source, row.as_on_date)


def build(conn: Connection, client_id: Any, fy_id: Any, required: bool = False) -> tuple[Statement, dict]:
    """(statement, basis + rule status dict). A company always requires the F-50 cash check (F-50)."""
    fy = final_statements._year(conn, client_id, fy_id)
    profile = frepo.client_profile(conn, client_id)
    entity = EntityType(profile.entity_type)
    stock = _stock(conn, client_id, fy_id)
    if entity == EntityType.COMPANY:
        built = final_sch3._build(conn, client_id, fy_id, None)
        positions = [c.ledger for c in built.classified]
        profit = built.result.profit_loss.totals["profit_before_tax"]
        upstream = (*built.result.profit_loss.findings, *built.result.balance_sheet.findings)
        labels = {r["line_code"]: r["label"] for r in built.ctx.line_rows}
        extra = {"basis": dict(built.basis), "rule_status": built.rule_status}
        required = True
    else:
        positions, sctx, _ = final_statements._load(conn, client_id, fy_id, None)
        overrides = sch3_repo.overrides(conn, client_id)
        positions = [replace(p, cf_class=overrides[p.ledger_id].cf_class) if p.ledger_id in overrides and overrides[p.ledger_id].cf_class
                     else p for p in positions]
        pl = stmt_engine.build_profit_loss(positions, sctx, StatementFormat.HORIZONTAL)
        profit, upstream = pl.totals["net_profit"], pl.findings
        labels = {code: g.name for code, g in repo.groups_for_client(conn, client_id).items()}
        extra = {"basis": {"closing_stock_method": None if stock is None else stock.source,
                           "closing_stock_source": None if stock is None else stock.source, "entity_type": profile.entity_type},
                 "rule_status": []}
    statement = engine.build_cash_flow(positions, profit, engine.CashFlowContext(entity, fy.start_date, fy.end_date, stock, labels, required),
                                       upstream)
    extra["basis"]["required"] = required
    return statement, extra


def cash_flow(conn: Connection, client_id: Any, fy_id: Any, required: bool = False) -> dict:
    statement, extra = build(conn, client_id, fy_id, required)
    body = final_statements.statement_out(statement, entity_type=extra["basis"]["entity_type"], stock=None)
    body["basis"] = extra["basis"]
    body["rule_status"] = extra["rule_status"]
    errors = [f for f in body["findings"] if f["severity"] == "error"]
    if errors:
        raise ServiceError("statement_blocked", f"The cash flow statement has {len(errors)} error(s): " + " ".join(f["message"] for f in errors),
                           {"findings": body["findings"], "statement": body})
    return body
