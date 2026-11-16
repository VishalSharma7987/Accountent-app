"""Inventory reports (Phase 5, package E): stock register, item ledger, closing stock at the lower of cost and NRV.
Rules S-01, S-13, S-15, S-16. Everything is recomputed from posted movements by the valuation engine; nothing is stored.
Output is plain dicts with amounts as 2-decimal strings, quantities as 3-decimal strings, dates ISO (API contract)."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_inventory_masters as inv
from app.db import repositories_inventory_reports as rep
from app.engine import inventory_report as engine
from app.engine.inventory_types import (
    ENGINE_VERSION,
    InventoryPolicy,
    NegativeStockMode,
    NrvEntry,
    StockError,
    ValuationMethod,
    ValuationResult,
)
from app.engine.inventory_valuation import compute_valuation
from app.services.errors import ServiceError


def _q(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.3f}"


def _m(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


class _Context:
    """Everything one report needs, loaded once."""

    def __init__(self, conn: Connection, client_id: object, fy_id: object, item_id: object | None = None):
        if not repo.client_exists(conn, client_id):
            raise ServiceError("not_found", "Client not found.")
        self.fy = repo.get_financial_year(conn, client_id, fy_id)
        if self.fy is None:
            raise ServiceError("not_found", "Financial year not found for this client.")
        row = inv.policy_row(conn, client_id, fy_id)
        if row is None:
            raise ServiceError("no_policy", "The inventory policy (valuation method) is not set for this financial year (S-04).")
        self.policy_row = row
        self.policy = InventoryPolicy(ValuationMethod(row.valuation_method), NegativeStockMode(row.negative_stock_mode))
        infos = rep.stock_item_infos(conn, client_id)
        self.meta = {i.item_id: engine.ItemMeta(i.sku, i.name, i.uqc or "") for i in infos}
        self.godowns = rep.godown_names(conn, client_id)
        if item_id is not None and item_id not in self.meta:
            raise ServiceError("not_found", "Stock item not found for this client.")
        self.opening = rep.load_opening(conn, client_id, fy_id)
        self.movements, self.numbers = rep.load_movements(conn, client_id, fy_id)
        if item_id is not None:  # S-01 and valuation are per item, so one item's inputs give the same answer
            self.opening = [o for o in self.opening if o.item_id == item_id]
            self.movements = [m for m in self.movements if m.item_id == item_id]

    def policy_out(self) -> dict:
        return {"financial_year_id": str(self.policy_row.financial_year_id),
                "valuation_method": self.policy_row.valuation_method,
                "negative_stock_mode": self.policy_row.negative_stock_mode}

    def error_out(self, e: StockError) -> dict:
        message = e.message
        for key, names in ((e.item_id, {k: v.name for k, v in self.meta.items()}), (e.godown_id, self.godowns)):
            if key is not None and key in names:
                message = message.replace(str(key), names[key])  # readable names instead of ids
        return {"rule_id": e.rule_id, "message": message, "severity": e.severity, "item_id": _s(e.item_id),
                "godown_id": _s(e.godown_id), "date": None if e.on_date is None else e.on_date.isoformat()}

    def split(self, errors: list[StockError]) -> tuple[list[dict], list[dict]]:
        out = [self.error_out(e) for e in errors]
        return [e for e in out if e["severity"] == "error"], [e for e in out if e["severity"] != "error"]


def _window(ctx: _Context, from_date: date | None, to_date: date | None) -> tuple[date, date]:
    start = from_date or ctx.fy.start_date
    end = to_date or ctx.fy.end_date
    if start > end:
        raise ServiceError("invalid_period", "The 'from' date is after the 'to' date.")
    if start < ctx.fy.start_date or end > ctx.fy.end_date:
        raise ServiceError("invalid_period", f"The dates must lie inside the financial year {ctx.fy.start_date:%d-%m-%Y} "
                           f"to {ctx.fy.end_date:%d-%m-%Y}.")
    return start, end


def _by_godown(ctx: _Context, line: engine.RegisterLine) -> list[dict]:
    return [{"godown_id": str(g), "godown_name": ctx.godowns.get(g), "closing_qty": _q(q)}
            for g, q in sorted(line.by_godown.items(), key=lambda kv: (ctx.godowns.get(kv[0]) or "").lower())]


def _register_row(ctx: _Context, x: engine.RegisterLine) -> dict:
    return {"item_id": str(x.item_id), "sku": x.sku, "name": x.name, "uqc": x.uqc,
            "opening_qty": _q(x.opening_qty), "opening_value": _m(x.opening_value),
            "inward_qty": _q(x.inward_qty), "inward_value": _m(x.inward_value),
            "outward_qty": _q(x.outward_qty), "outward_value": _m(x.outward_value),
            "closing_qty": _q(x.closing_qty), "closing_value": _m(x.closing_value), "by_godown": _by_godown(ctx, x)}


def stock_register(conn: Connection, client_id: object, fy_id: object, *, from_date: date | None = None,
                   to_date: date | None = None, item_id: object | None = None, godown_id: object | None = None) -> dict:
    ctx = _Context(conn, client_id, fy_id, item_id)
    start, end = _window(ctx, from_date, to_date)
    if godown_id is not None and godown_id not in ctx.godowns:
        raise ServiceError("not_found", "Godown not found for this client.")
    result = compute_valuation(ctx.policy, start, end, ctx.opening, ctx.movements)
    lines = engine.register_lines(result, ctx.meta, ctx.opening, ctx.movements, start, end, godown_id)
    lines.sort(key=lambda x: (x.name.lower(), x.sku))
    errors, warnings = ctx.split(result.errors)
    totals = engine.register_totals(lines)
    return {"policy": ctx.policy_out(), "from": start.isoformat(), "to": end.isoformat(),
            "godown_id": _s(godown_id), "godown_name": ctx.godowns.get(godown_id) if godown_id else None,
            "rows": [_register_row(ctx, x) for x in lines],
            "totals": None if godown_id is not None else {k: _m(v) for k, v in totals.items()},
            "errors": errors, "warnings": warnings, "engine_version": ENGINE_VERSION}


def item_ledger(conn: Connection, client_id: object, item_id: object, fy_id: object, *, from_date: date | None = None,
                to_date: date | None = None) -> dict:
    ctx = _Context(conn, client_id, fy_id, item_id)
    start, end = _window(ctx, from_date, to_date)
    result = compute_valuation(ctx.policy, start, end, ctx.opening, ctx.movements)
    lines = engine.item_ledger(result, item_id, ctx.numbers)
    errors, warnings = ctx.split(result.errors)
    return {"policy": ctx.policy_out(), "from": start.isoformat(), "to": end.isoformat(),
            "rows": [{"date": x.date.isoformat(), "seq": x.seq, "kind": x.kind.value, "document_number": x.doc_number,
                      "movement_id": str(x.movement_id), "godown_id": str(x.godown_id),
                      "godown_name": ctx.godowns.get(x.godown_id),
                      "in_qty": _q(x.in_qty), "in_value": _m(x.in_value), "out_qty": _q(x.out_qty),
                      "out_value": _m(x.out_value), "balance_qty": _q(x.balance_qty), "balance_value": _m(x.balance_value)}
                     for x in lines],
            "errors": errors, "warnings": warnings}


def _valued(ctx: _Context, as_on: date, entries: list[NrvEntry]) -> ValuationResult:
    return compute_valuation(ctx.policy, ctx.fy.start_date, as_on, ctx.opening, ctx.movements, entries)


def closing_stock(conn: Connection, client_id: object, fy_id: object, *, as_on: date | None = None) -> dict:
    """Closing stock at the lower of cost and NRV, item by item (S-15), with method, date, items without NRV and
    negative-stock findings (S-16). The statutory figure is the whole-year window (FY start to `as_on`)."""
    ctx = _Context(conn, client_id, fy_id)
    on = as_on or ctx.fy.end_date
    _, on = _window(ctx, None, on)
    entries = [NrvEntry(r.item_id, r.as_on_date, r.nrv_per_unit, r.basis_note) for r in rep.nrv_rows(conn, client_id, fy_id, on)]
    result = _valued(ctx, on, entries)
    errors, warnings = ctx.split(result.errors)
    rows = []
    for c in result.closing:
        info = ctx.meta.get(c.item_id) or engine.ItemMeta("", str(c.item_id), "")
        rows.append({"item_id": str(c.item_id), "sku": info.sku, "name": info.name, "uqc": info.uqc,
                     "closing_qty": _q(c.closing_qty), "cost_value": _m(c.cost_value), "nrv_per_unit": _m(c.nrv_per_unit),
                     "nrv_value": _m(c.nrv_value), "write_down": _m(c.write_down), "carrying_value": _m(c.carrying_value)})
    rows.sort(key=lambda r: (r["name"].lower(), r["sku"]))
    zero = Decimal("0.00")
    totals = {"cost_value": _m(sum((c.cost_value for c in result.closing), zero)),
              "write_down": _m(sum((c.write_down for c in result.closing), zero)),
              "carrying_value": _m(sum((c.carrying_value for c in result.closing), zero))}
    # an item with stock and no NRV (a zero-stock item needs none)
    without = [str(c.item_id) for c in result.closing if c.nrv_per_unit is None and c.closing_qty > 0]
    return {"policy": ctx.policy_out(), "as_on": on.isoformat(), "rows": rows, "totals": totals,
            "items_without_nrv": without, "errors": errors, "warnings": warnings, "engine_version": ENGINE_VERSION}
