"""Schedule III use-cases (docs/PHASE6_API_CONTRACT.md, package D): ledger classification (CRUD with group defaults), the company
Balance Sheet and Statement of Profit and Loss with notes and previous-year comparatives. No service computes an amount: it loads
data, calls `engine/final_sch3.py` and shapes the answer. Reads only, except the classification which is audit-logged."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_final_sch3 as repo
from app.engine import final_sch3 as engine
from app.engine.final_types import ClosingStockIn, Finding, Statement
from app.services.audit import AuditEntry, log_many
from app.services.errors import ServiceError

CF_CLASSES = ("operating", "investing", "financing", "cash_equivalent", "non_cash", "equity_profit")
STOCK_REQUIRED_BUSINESS = ("trading", "manufacturing")


@dataclass(frozen=True)
class ClassificationRow:
    ledger_id: Any
    line_code: str | None
    cf_class: str | None
    note: str | None = None


@dataclass
class _Context:
    client_id: Any
    fy_id: Any
    fy_start: date
    fy_end: date
    entity_type: str
    business_type: str
    line_rows: list[dict]
    group_rows: list[dict]


def _client_year(conn: Connection, client_id: Any, fy_id: Any) -> _Context:
    info = repo.client_info(conn, client_id)
    if info is None:
        raise ServiceError("not_found", "Client not found.")
    year = repo.financial_year(conn, client_id, fy_id)
    if year is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return _Context(client_id, fy_id, year[1], year[2], info["entity_type"], info["business_type"],
                    repo.fs_line_rows(conn, year[2]), repo.group_map_rows(conn, year[2]))


def _require_company(ctx: _Context) -> None:
    if ctx.entity_type != "company":
        raise ServiceError(
            "not_company",
            "Schedule III statements are for companies. Use /final/trading, /final/profit-loss and /final/balance-sheet for this client.")


# ======================================================================================================== classification


def _classified(conn: Connection, ctx: _Context, fy_id: Any, as_on: date, line_rows: list[dict], group_rows: list[dict]):
    positions = repo.ledger_positions(conn, ctx.client_id, fy_id, as_on)
    return engine.classify(tuple(positions), repo.overrides(conn, ctx.client_id), repo.to_defaults(group_rows), repo.to_rules(line_rows))


def get_classification(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    ctx = _client_year(conn, client_id, fy_id)
    classified = _classified(conn, ctx, fy_id, ctx.fy_end, ctx.line_rows, ctx.group_rows)
    unclassified, defaults, ledgers = [], [], []
    for item in classified:
        ledger = item.ledger
        active = engine.has_activity(ledger) and ledger.group_code != engine.STOCK_GROUP
        if active and item.source == "none":
            unclassified.append(str(ledger.ledger_id))
        if active and item.source == "group_default":
            defaults.append(str(ledger.ledger_id))
        ledgers.append({"ledger_id": str(ledger.ledger_id), "name": ledger.name, "group_code": ledger.group_code,
                        "nature": ledger.nature, "line_code": ledger.line_code, "source": item.source, "cf_class": ledger.cf_class,
                        "has_activity": engine.has_activity(ledger)})
    lines = [{"format_key": r["format_key"], "line_code": r["line_code"], "label": r["label"], "section": r["section"],
              "cf_class": r["cf_class"], "verification_status": r["verification_status"]} for r in ctx.line_rows]
    return {"lines": lines, "ledgers": ledgers, "unclassified": unclassified, "defaults": defaults, "rule_status": _status_all(ctx)}


def put_classification(conn: Connection, client_id: Any, rows: list[ClassificationRow], *, actor: str) -> None:
    """Upsert the ledger overrides. A row with neither a line nor a cash-flow class removes the override (back to the group
    default). Everything is validated before the first write."""
    if repo.client_info(conn, client_id) is None:
        raise ServiceError("not_found", "Client not found.")
    formats = repo.known_line_formats(conn)
    seen: set[Any] = set()
    checked = []
    for row in rows:
        if row.ledger_id in seen:
            raise ServiceError("invalid_classification", "A ledger appears twice in the request.")
        seen.add(row.ledger_id)
        info = repo.ledger_info(conn, client_id, row.ledger_id)
        if info is None:
            raise ServiceError("not_found", "Ledger not found for this client.")
        if row.line_code is not None:
            fmt = formats.get(row.line_code)
            if fmt is None:
                raise ServiceError("invalid_line", f"'{row.line_code}' is not a Schedule III line.")
            if fmt != engine.format_for_nature(info["nature"]):
                where = "Profit and Loss" if fmt == engine.PL else "Balance Sheet"
                raise ServiceError("invalid_line", f"Ledger '{info['name']}' cannot go to '{row.line_code}': that is a {where} line "
                                                   "and the ledger's group belongs to the other statement.")
        if row.cf_class is not None and row.cf_class not in CF_CLASSES:
            raise ServiceError("invalid_cf_class", f"'{row.cf_class}' is not a cash-flow class.")
        checked.append((row, info))
    entries = []
    for row, info in checked:
        old = repo.override_row(conn, client_id, row.ledger_id)
        if row.line_code is None and row.cf_class is None:
            if old is None:
                continue
            repo.delete_override(conn, client_id, row.ledger_id)
            entries.append(AuditEntry(client_id, actor, "unclassify", "client_ledger_fs_map", row.ledger_id, old=old,
                                      new={"ledger": info["name"]}))
            continue
        repo.upsert_override(conn, client_id, row.ledger_id, row.line_code, row.cf_class, row.note, actor)
        entries.append(AuditEntry(client_id, actor, "classify", "client_ledger_fs_map", row.ledger_id, old=old,
                                  new={"ledger": info["name"], "line_code": row.line_code, "cf_class": row.cf_class, "note": row.note}))
    log_many(conn, entries)


# ======================================================================================================== statements


def _stock_input(conn: Connection, ctx: _Context, fy_id: Any, as_on: date, *, exact_date: bool) -> tuple[ClosingStockIn | None, str | None]:
    found = repo.approved_closing_stock(conn, ctx.client_id, fy_id)
    if found is None:
        return None, None
    stock, method = found
    if exact_date and stock.as_on_date != as_on:
        return None, None   # approved for another date: a provisional statement needs its own approval (F-41)
    return stock, method


def _previous_amounts(conn: Connection, ctx: _Context) -> dict:
    """F-45: signed-off snapshot of the previous year, else a recomputation (previous year has data and, for stock-holding
    businesses, an approved closing stock), else nothing. Returns {key: (amounts|None, source)}."""
    out: dict[str, tuple[dict | None, str]] = {"balance_sheet": (None, "none"), "profit_loss": (None, "none")}
    prev = repo.previous_financial_year(conn, ctx.client_id, ctx.fy_start)
    if prev is None:
        return out
    prev_id, prev_start, prev_end = prev
    for key in ("balance_sheet", "profit_loss"):
        payload = repo.snapshot_payload(conn, ctx.client_id, prev_id, key)
        if payload is not None:
            out[key] = (engine.amounts_from_payload(payload), "snapshot")
    if all(v[1] == "snapshot" for v in out.values()) or not repo.year_has_data(conn, ctx.client_id, prev_id):
        return out
    stock, _ = _stock_input(conn, ctx, prev_id, prev_end, exact_date=False)
    if stock is None and ctx.business_type in STOCK_REQUIRED_BUSINESS:
        return out
    line_rows = repo.fs_line_rows(conn, prev_end)
    group_rows = repo.group_map_rows(conn, prev_end)
    classified = tuple(c.ledger for c in _classified(conn, ctx, prev_id, prev_end, line_rows, group_rows))
    result = engine.build_sch3(engine.Sch3Input(prev_start, prev_end, classified, stock, False, repo.to_rules(line_rows)))
    if any(f.severity == "error" for f in (*result.balance_sheet.findings, *result.profit_loss.findings)):
        return out  # a previous year that does not stand on its own is not used as a comparative
    if out["balance_sheet"][1] != "snapshot":
        out["balance_sheet"] = (engine.amounts_of(result.balance_sheet), "recomputed")
    if out["profit_loss"][1] != "snapshot":
        out["profit_loss"] = (engine.amounts_of(result.profit_loss), "recomputed")
    return out


@dataclass(frozen=True)
class Built:
    result: engine.Sch3Result
    ctx: _Context
    previous_source: dict[str, str]
    rule_status: list[dict]
    basis: dict
    as_on: date
    classified: tuple[engine.ClassifiedLedger, ...]


def _build(conn: Connection, client_id: Any, fy_id: Any, as_on: date | None) -> Built:
    ctx = _client_year(conn, client_id, fy_id)
    _require_company(ctx)
    as_on = as_on or ctx.fy_end
    if not (ctx.fy_start <= as_on <= ctx.fy_end):
        raise ServiceError("invalid_range", "The date must be inside the financial year.")
    classified = _classified(conn, ctx, fy_id, as_on, ctx.line_rows, ctx.group_rows)
    stock, method = _stock_input(conn, ctx, fy_id, as_on, exact_date=True)
    previous = _previous_amounts(conn, ctx)
    ppe = None
    assets, events, dep = repo.register_inputs(conn, client_id)
    if assets:
        ppe = engine.build_ppe_rows(assets, events, dep, ctx.fy_start, ctx.fy_end) or None
    result = engine.build_sch3(engine.Sch3Input(
        ctx.fy_start, as_on, tuple(c.ledger for c in classified), stock, ctx.business_type in STOCK_REQUIRED_BUSINESS,
        repo.to_rules(ctx.line_rows), previous["balance_sheet"][0], previous["profit_loss"][0], ppe))
    basis = {"closing_stock_method": method, "closing_stock_source": stock.source if stock else None,
             "entity_type": ctx.entity_type, "format": "sch3"}
    return Built(result, ctx, {k: v[1] for k, v in previous.items()}, _rule_status(ctx, result, classified), basis, as_on, classified)


def _rule_status(ctx: _Context, result: engine.Sch3Result, classified: tuple[engine.ClassifiedLedger, ...]) -> list[dict]:
    """Rule rows behind the figures with their verification status (printed on exports; all 'pending' until verified)."""
    used = {ln.code for st in (result.balance_sheet, result.profit_loss) for ln in st.left}
    status = [{"table": "fs_lines", "format_key": r["format_key"], "line_code": r["line_code"],
               "verification_status": r["verification_status"], "source_reference": r["source_reference"]}
              for r in ctx.line_rows if r["line_code"] in used]
    group_map = {(r["group_code"], r["format_key"]): r for r in ctx.group_rows}
    seen: set[tuple[str, str]] = set()
    for item in classified:
        ledger = item.ledger
        if item.source not in ("group_firm", "group_default") or not engine.has_activity(ledger):
            continue
        fmt = engine.format_for_nature(ledger.nature)
        key = (ledger.group_code, fmt) if (ledger.group_code, fmt) in group_map else (ledger.parent_group_code, fmt)
        if key in seen or key not in group_map:
            continue
        seen.add(key)
        r = group_map[key]
        status.append({"table": "fs_group_map", "group_code": r["group_code"], "format_key": r["format_key"],
                       "line_code": r["line_code"], "is_firm": r["is_firm"], "verification_status": r["verification_status"],
                       "source_reference": r["source_reference"]})
    return status


def _status_all(ctx: _Context) -> list[dict]:
    return [{"table": "fs_lines", "format_key": r["format_key"], "line_code": r["line_code"],
             "verification_status": r["verification_status"], "source_reference": r["source_reference"]} for r in ctx.line_rows]


def _money(value: Any) -> str:
    return f"{value:.2f}"


def _line_dict(line) -> dict:
    return {"code": line.code, "label": line.label, "amount": _money(line.amount),
            "previous_amount": None if line.previous_amount is None else _money(line.previous_amount),
            "note_no": line.note_no, "level": line.level, "is_total": line.is_total,
            "drill": [{"ledger_id": None if d.ledger_id is None else str(d.ledger_id), "ledger_name": d.ledger_name,
                       "amount": _money(d.amount)} for d in line.drill]}


def _finding_dict(f: Finding) -> dict:
    return {"rule_id": f.rule_id, "message": f.message, "severity": f.severity,
            "ledger_id": None if f.ledger_id is None else str(f.ledger_id)}


def statement_dict(statement: Statement, built: Built, previous_key: str) -> dict:
    statuses = {r["verification_status"] for r in built.rule_status}
    return {
        "key": statement.key, "format": statement.format.value, "title": statement.title,
        "from_date": statement.from_date.isoformat(), "to_date": statement.to_date.isoformat(),
        "left": [_line_dict(ln) for ln in statement.left], "right": [],
        "totals": {k: _money(v) for k, v in statement.totals.items()},
        "notes": [{"note_no": no, "title": title, "lines": [_line_dict(ln) for ln in lines]} for no, title, lines in statement.notes],
        "findings": [_finding_dict(f) for f in statement.findings],
        "engine_version": statement.engine_version, "rule_status": built.rule_status,
        "rule_status_summary": "verified" if statuses == {"verified"} else ("pending" if "pending" in statuses else "partly_verified"),
        "basis": built.basis, "previous_source": built.previous_source[previous_key],
    }


def _guard_unclassified(built: Built, statement: Statement, body: dict) -> None:
    errors = [f for f in statement.findings if f.rule_id == "F-44" and f.severity == "error"]
    if errors:
        raise UnclassifiedError(
            ServiceError("unclassified", f"{len(errors)} ledger(s) are not classified to a Schedule III line. Classify them first.",
                         {"unclassified": [str(x) for x in built.result.unclassified], "findings": body["findings"]}), body)


class UnclassifiedError(Exception):
    """F-44: carries the ServiceError (code, message, details) and the statement the caller may still show."""

    def __init__(self, error: ServiceError, statement: dict):
        super().__init__(error.message)
        self.error = error
        self.statement = statement


def balance_sheet(conn: Connection, client_id: Any, fy_id: Any, as_on: date | None = None) -> dict:
    built = _build(conn, client_id, fy_id, as_on)
    body = statement_dict(built.result.balance_sheet, built, "balance_sheet")
    _guard_unclassified(built, built.result.balance_sheet, body)
    return body


def profit_loss(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    built = _build(conn, client_id, fy_id, None)
    body = statement_dict(built.result.profit_loss, built, "profit_loss")
    _guard_unclassified(built, built.result.profit_loss, body)
    return body


def notes(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    built = _build(conn, client_id, fy_id, None)
    body = statement_dict(built.result.balance_sheet, built, "balance_sheet")
    out = {"notes": body["notes"], "findings": body["findings"], "engine_version": body["engine_version"],
           "rule_status": body["rule_status"], "rule_status_summary": body["rule_status_summary"], "basis": body["basis"]}
    _guard_unclassified(built, built.result.balance_sheet, out)
    return out

