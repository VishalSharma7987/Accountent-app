"""Fixed Asset Register, Companies Act book depreciation run and income-tax block working (Phase 6, package B; rules F-20 .. F-34).

Services load data, call the pure engines (engine/final_assets.py, engine/final_it_depreciation.py) and write; they compute no amount.
They never commit (the caller owns the transaction), check before the first write, and audit-log every change.

The book depreciation run creates ONE DRAFT Journal voucher through the voucher service (approve / post / reverse are the ordinary
voucher actions); the income-tax block working is a working only: no voucher, no ledger effect.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_final_assets as fr
from app.engine import final_assets as fa
from app.engine.final_it_depreciation import it_block_depreciation
from app.engine.final_types import (
    ENGINE_VERSION,
    AssetBookSetup,
    AssetEvent,
    EventKind,
    Finding,
    ItBlockInput,
)
from app.engine.models import ValidationError, VoucherDraft, VoucherLine
from app.engine.money import MoneyError, parse_amount
from app.services import audit, final_hooks, vouchers
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor

ZERO = Decimal("0.00")
_SETUP_FIELDS = ("asset_ledger_id", "accumulated_dep_ledger_id", "is_depreciable", "it_block_key", "sched2_class_key",
                 "useful_life_years", "life_override_reason", "residual_value", "book_method")


# ================================================================================================== small helpers


def _client(conn: Connection, client_id: object) -> None:
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")


def _fy(conn: Connection, client_id: object, fy_id: object):
    fy = repo.get_financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def _label(fy) -> str:
    return f"{fy.start_date.year}-{str(fy.end_date.year)[-2:]}"


def _money(raw: object, what: str, default: Decimal | None = None) -> Decimal:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if default is not None:
            return default
        raise ServiceError("invalid_amount", f"{what} is required.")
    try:
        return parse_amount(raw)
    except MoneyError as exc:
        raise ServiceError("invalid_amount", f"{what}: {exc}") from None


def _rule_error(findings: list[Finding]) -> VoucherRuleError:
    return VoucherRuleError([ValidationError(f.rule_id, f.message, f.line_no) for f in findings])


def _raise_errors(findings: list[Finding]) -> None:
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise _rule_error(errors)


def _jfind(findings: list[Finding]) -> list[dict[str, Any]]:
    return [{"rule_id": f.rule_id, "message": f.message, "severity": f.severity, "ledger_id": f.ledger_id} for f in findings]


def _pick(rows, on: date, what: str):
    try:
        row = fa.pick_rule(rows, on)
    except fa.AmbiguousRule:
        raise ServiceError("no_rule", f"More than one {what} row is in force on {on.strftime('%d-%m-%Y')}; the rule table needs correcting.") from None
    return row


def _no_rule(what: str, on: date) -> ServiceError:
    return ServiceError("no_rule", f"No {what} is in force on {on.strftime('%d-%m-%Y')}; nothing is guessed. Add the rule row first.")


def _year_frozen(conn: Connection, client_id: object, on: date) -> None:
    """F-21 / database guard: an input dated in a closed financial year cannot change (409 year_closed)."""
    fy = repo.financial_year_for_date(conn, client_id, on)
    if fy is not None and final_hooks.year_is_closed(conn, client_id, fy.id):
        raise ServiceError("year_closed", f"The financial year {_label(fy)} is closed; reopen it before changing this.")


def _asset_row_snapshot(a: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if a[k] is None else str(a[k])) for k in ("asset_no", "name", *_SETUP_FIELDS, "is_active")}


# ================================================================================================== rule tables (read)


def rules_in_force(conn: Connection, as_on: date) -> dict[str, Any]:
    """The depreciation rule rows in force on a date (law is data; the status of every row is shown)."""
    blocks, seen = [], set()
    for row in fr.it_rate_rows(conn):
        if row.block_key in seen:
            continue
        picked = _pick([r for r in fr.it_rate_rows(conn, row.block_key)], as_on, "income-tax block rate")
        seen.add(row.block_key)
        if picked is not None:
            blocks.append({"block_key": picked.block_key, "description": picked.description, "rate": f"{picked.rate:.4f}", "act": picked.act,
                           "verification_status": picked.verification_status, "source_reference": picked.source_reference})
    classes = []
    keys = sorted({r.class_key for r in fr.sched2_rows(conn)})
    for key in keys:
        picked = _pick(fr.sched2_rows(conn, key), as_on, "Schedule II class")
        if picked is not None:
            classes.append({"class_key": key, "description": picked.description, "useful_life_years": f"{picked.useful_life_years:.2f}",
                            "max_residual_percent": f"{picked.max_residual_percent:.4f}", "verification_status": picked.verification_status})
    scalars = {}
    for key in ("half_rate_days", "half_rate_percent"):
        rows = [r for r in fr.it_scalar_rows(conn) if r.rule_key == key]
        picked = _pick(rows, as_on, f"income-tax rule '{key}'")
        scalars[key] = None if picked is None else {"value": f"{picked.rule_value:.4f}", "act": picked.act,
                                                    "verification_status": picked.verification_status}
    return {"it_blocks": blocks, "sched2_classes": classes,
            "half_rate_days": None if scalars["half_rate_days"] is None else int(Decimal(scalars["half_rate_days"]["value"])),
            "half_rate_percent": None if scalars["half_rate_percent"] is None else scalars["half_rate_percent"]["value"],
            "half_rate_status": scalars, "engine_version": ENGINE_VERSION}


# ================================================================================================== assets


def _asset_values(conn: Connection, client_id: object, body: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
    """Validate an asset body (F-20, F-24) and return the row values. The class life is copied when `useful_life_years` is omitted."""
    asset_no = (body.get("asset_no") or "").strip()
    name = (body.get("name") or "").strip()
    if not asset_no or not name:
        raise ServiceError("invalid_asset", "The asset number and the name are required.")
    ledger = repo.get_ledger(conn, client_id, body.get("asset_ledger_id"))
    if ledger is None or ledger.group_code != "fixed_assets":
        raise _rule_error([Finding("F-20", "The asset ledger must be a ledger of the Fixed Assets group of this client.", "error")])
    accum_id = body.get("accumulated_dep_ledger_id")
    if accum_id is not None:
        accum = repo.get_ledger(conn, client_id, accum_id)
        if accum is None or accum.group_code != "fixed_assets":
            raise _rule_error([Finding("F-20", "The accumulated depreciation ledger must be a ledger of the Fixed Assets group of this client.", "error")])
    depreciable = bool(body.get("is_depreciable", True))
    method = body.get("book_method")
    block = (body.get("it_block_key") or None)
    class_key = (body.get("sched2_class_key") or None)
    reason = (body.get("life_override_reason") or "").strip() or None
    residual = _money(body.get("residual_value"), "The residual value", ZERO)
    life_raw = body.get("useful_life_years")
    class_rule = None
    if depreciable and class_key:
        rows = fr.sched2_rows(conn, class_key)
        if not rows:
            raise ServiceError("invalid_asset", f"Schedule II class '{class_key}' does not exist.")
        class_rule = _pick(rows, date.today(), "Schedule II class")
        if class_rule is None:
            raise _no_rule(f"Schedule II class '{class_key}'", date.today())
    if depreciable and block and not fr.it_rate_rows(conn, block):
        raise ServiceError("invalid_asset", f"Income-tax block '{block}' does not exist in the rate table.")
    if life_raw is None or (isinstance(life_raw, str) and not life_raw.strip()):
        life = class_rule.useful_life_years if class_rule is not None else None
    else:
        try:
            life = Decimal(str(life_raw))
        except ArithmeticError:
            raise ServiceError("invalid_asset", "The useful life is not a number.") from None
        if life != life.quantize(Decimal("0.01")):
            raise ServiceError("invalid_asset", "The useful life can have at most 2 decimals.")
    if not depreciable:
        block = block or None
    findings = fa.validate_asset_setup(is_depreciable=depreciable, it_block_key=block, method=method, life=life, residual=residual,
                                       class_rule=class_rule, override_reason=reason)
    _raise_errors(findings)
    if asset_no and fr.asset_no_exists(conn, client_id, asset_no, None if current is None else current["id"]):
        raise ServiceError("asset_exists", f"Asset number '{asset_no}' already exists for this client.")
    return {"asset_no": asset_no, "name": name, "asset_ledger_id": body["asset_ledger_id"], "accumulated_dep_ledger_id": accum_id,
            "is_depreciable": depreciable, "it_block_key": block if depreciable else None,
            "sched2_class_key": class_key if depreciable else None, "useful_life_years": life if depreciable else None,
            "life_override_reason": reason if depreciable else None, "residual_value": residual,
            "book_method": method if depreciable else None, "is_active": True if current is None else current["is_active"]}


def create_asset(conn: Connection, client_id: object, body: dict[str, Any], *, actor: str) -> object:
    actor = require_actor(actor)
    _client(conn, client_id)
    values = _asset_values(conn, client_id, body, None)
    asset_id = fr.insert_asset(conn, client_id, values, actor)
    audit.log(conn, AuditEntry(client_id, actor, "create", "fixed_asset", asset_id, new=_asset_row_snapshot(values)))
    return asset_id


def update_asset(conn: Connection, client_id: object, asset_id: object, body: dict[str, Any], *, actor: str) -> None:
    actor = require_actor(actor)
    _client(conn, client_id)
    current = fr.get_asset(conn, client_id, asset_id, lock=True)
    if current is None:
        raise ServiceError("not_found", "Fixed asset not found for this client.")
    values = _asset_values(conn, client_id, body, current)
    if "is_active" in body and body["is_active"] is not None:
        values["is_active"] = bool(body["is_active"])
    changed_setup = any(str(current[k] if current[k] is not None else "") != str(values[k] if values[k] is not None else "")
                        for k in _SETUP_FIELDS)
    if changed_setup and fr.asset_has_posted_depreciation(conn, client_id, asset_id):
        raise ServiceError("asset_in_use", "Depreciation of this asset is already approved or posted: its setup cannot change. "
                                           "Reverse the depreciation voucher first (name and active flag can still be edited).")
    fr.update_asset(conn, client_id, asset_id, values)
    audit.log(conn, AuditEntry(client_id, actor, "update", "fixed_asset", asset_id, old=_asset_row_snapshot(current), new=_asset_row_snapshot(values)))


def list_assets(conn: Connection, client_id: object, q: str | None = None, active: bool | None = None) -> list[dict[str, Any]]:
    _client(conn, client_id)
    events = fr.events_of_client(conn, client_id)
    out = []
    for a in fr.list_assets(conn, client_id, q, active):
        ev = events.get(a["id"], [])
        out.append({**a, "useful_life_years": None if a["useful_life_years"] is None else f"{a['useful_life_years']:.2f}",
                    "cost": sum((e["amount"] for e in ev if e["kind"] != "disposal"), ZERO),
                    "additions": sum((e["amount"] for e in ev if e["kind"] == "addition"), ZERO),
                    "disposed": any(e["kind"] == "disposal" for e in ev)})
    return out


# ================================================================================================== events


def list_events(conn: Connection, client_id: object, asset_id: object) -> list[dict[str, Any]]:
    _client(conn, client_id)
    if fr.get_asset(conn, client_id, asset_id) is None:
        raise ServiceError("not_found", "Fixed asset not found for this client.")
    return fr.events_of_asset(conn, client_id, asset_id)


def _frozen_by_run(conn: Connection, client_id: object, on: date) -> None:
    for start, end in fr.active_run_dates(conn, client_id):
        if end >= on:
            raise ServiceError("asset_in_use", f"A depreciation run for the year ending {end.strftime('%d-%m-%Y')} is draft, approved or posted: "
                                               "it would no longer match the register. Delete the draft run or reverse its voucher first.")


def _event_error(findings: list[Finding]) -> ServiceError:
    errors = [f for f in findings if f.severity == "error"]
    return ServiceError("event_order", "; ".join(f.message for f in errors),
                        {"errors": [{"rule_id": f.rule_id, "message": f.message} for f in errors]})


def add_event(conn: Connection, client_id: object, asset_id: object, body: dict[str, Any], *, actor: str) -> object:
    actor = require_actor(actor)
    _client(conn, client_id)
    asset = fr.get_asset(conn, client_id, asset_id, lock=True)
    if asset is None:
        raise ServiceError("not_found", "Fixed asset not found for this client.")
    try:
        kind = EventKind(body.get("kind"))
    except ValueError:
        raise ServiceError("invalid_event", "The event kind must be opening, purchase, addition or disposal.") from None
    event_date = body.get("event_date")
    if not isinstance(event_date, date):
        raise ServiceError("invalid_event", "The event date is required.")
    amount = _money(body.get("amount"), "The amount" if kind != EventKind.DISPOSAL else "The sale proceeds", ZERO if kind == EventKind.DISPOSAL else None)
    accumulated = _money(body.get("accumulated_dep_bf"), "The accumulated depreciation brought forward", ZERO)
    if kind != EventKind.OPENING and accumulated != 0:
        raise _event_error([Finding("F-21", "Accumulated depreciation brought forward belongs only to an opening event.", "error")])
    ptu = body.get("put_to_use_date")
    if kind == EventKind.DISPOSAL and ptu is not None:
        raise _event_error([Finding("F-21", "A disposal has no put-to-use date.", "error")])
    voucher_id = body.get("voucher_id")
    if voucher_id is not None and not fr.voucher_in_client(conn, client_id, voucher_id):
        raise ServiceError("not_found", "Voucher not found for this client.")
    if repo.financial_year_for_date(conn, client_id, event_date) is None:
        raise ServiceError("no_financial_year", f"{event_date.strftime('%d-%m-%Y')} is not inside a financial year of this client (F-22).")
    _year_frozen(conn, client_id, event_date)
    _frozen_by_run(conn, client_id, event_date)
    existing = [fr.to_engine_event(e) for e in fr.events_of_asset(conn, client_id, asset_id)]
    new = AssetEvent(kind, event_date, amount, ptu, accumulated)
    findings = fa.validate_event(existing, new)
    if any(f.severity == "error" for f in findings):
        raise _event_error(findings)
    event_id = fr.insert_event(conn, client_id, asset_id, {"kind": kind.value, "event_date": event_date, "put_to_use_date": ptu, "amount": amount,
                                                          "accumulated_dep_bf": accumulated, "voucher_id": voucher_id, "note": body.get("note")}, actor)
    audit.log(conn, AuditEntry(client_id, actor, "create", "fixed_asset_event", event_id,
                               new={"asset_id": str(asset_id), "asset_no": asset["asset_no"], "kind": kind.value, "event_date": event_date.isoformat(),
                                    "put_to_use_date": None if ptu is None else ptu.isoformat(), "amount": f"{amount:.2f}",
                                    "accumulated_dep_bf": f"{accumulated:.2f}"}))
    return event_id


def delete_event(conn: Connection, client_id: object, asset_id: object, event_id: object, *, actor: str) -> None:
    actor = require_actor(actor)
    _client(conn, client_id)
    asset = fr.get_asset(conn, client_id, asset_id, lock=True)
    event = fr.get_event(conn, client_id, asset_id, event_id) if asset is not None else None
    if event is None:
        raise ServiceError("not_found", "Asset event not found for this client.")
    _year_frozen(conn, client_id, event["event_date"])
    _frozen_by_run(conn, client_id, event["event_date"])
    others = [e for e in fr.events_of_asset(conn, client_id, asset_id) if e["id"] != event["id"]]
    if event["kind"] in ("opening", "purchase") and others:
        raise _event_error([Finding("F-21", "The opening or purchase event cannot be removed while later events (additions, disposal) exist: "
                                            "remove those first.", "error")])
    fr.delete_event(conn, client_id, event["id"])
    audit.log(conn, AuditEntry(client_id, actor, "delete", "fixed_asset_event", event["id"],
                               old={"asset_id": str(asset_id), "asset_no": asset["asset_no"], "kind": event["kind"],
                                    "event_date": event["event_date"].isoformat(), "amount": f"{event['amount']:.2f}"}))


# ================================================================================================== book depreciation (Companies Act)


def _setups(conn: Connection, client_id: object) -> list[tuple[dict[str, Any], AssetBookSetup]]:
    events = fr.events_of_client(conn, client_id)
    out = []
    for a in fr.list_assets(conn, client_id):
        evs = tuple(fr.to_engine_event(e) for e in events.get(a["id"], []))
        out.append((a, AssetBookSetup(a["id"], a["asset_no"], a["name"], a["is_depreciable"], a["book_method"], a["useful_life_years"],
                                      a["residual_value"], a["it_block_key"], evs)))
    return out


def _book_compute(conn: Connection, client_id: object, fy) -> dict[str, Any]:
    findings: list[Finding] = []
    lines, statuses, snapshot, accum_by_asset, disposals = [], {}, {}, {}, []
    for a, setup in _setups(conn, client_id):
        if not a["is_depreciable"]:
            continue
        class_rule = None
        if a["sched2_class_key"]:
            class_rule = _pick(fr.sched2_rows(conn, a["sched2_class_key"]), fy.end_date, "Schedule II class")
            if class_rule is None:
                raise _no_rule(f"Schedule II class '{a['sched2_class_key']}' (asset {a['asset_no']})", fy.end_date)
        setup_findings = fa.validate_asset_setup(is_depreciable=True, it_block_key=a["it_block_key"], method=a["book_method"],
                                                 life=a["useful_life_years"], residual=a["residual_value"], class_rule=class_rule,
                                                 override_reason=a["life_override_reason"])
        starts = [e for e in setup.events if e.kind in (EventKind.OPENING, EventKind.PURCHASE)]
        if starts:
            setup_findings += fa.residual_findings(starts[0].amount, a["residual_value"], class_rule)
        findings += [replace(f, message=f"Asset {a['asset_no']}: {f.message}", ledger_id=a["asset_ledger_id"]) for f in setup_findings]
        if any(f.severity == "error" for f in setup_findings):
            continue
        for line in fa.book_depreciation(setup, fy.start_date, fy.end_date):
            lines.append(line)
            accum_by_asset[a["id"]] = a["accumulated_dep_ledger_id"] or a["asset_ledger_id"]
            status = ({"class_key": class_rule.class_key, "verification_status": class_rule.verification_status,
                       "source_reference": class_rule.source_reference} if class_rule is not None
                      else {"class_key": None, "verification_status": "override", "life_override_reason": a["life_override_reason"]})
            statuses[a["id"]] = status
            snapshot[str(a["id"])] = {"asset_no": a["asset_no"], **status, "life_years": f"{a['useful_life_years']:.2f}"}
            disposal = next((e for e in setup.events if e.kind == EventKind.DISPOSAL and fy.start_date <= e.event_date <= fy.end_date), None)
            if disposal is not None:
                w = fa.disposal_working(line.cost, line.closing_accumulated, disposal.amount)
                disposals.append({"asset_id": a["id"], "asset_no": a["asset_no"], "disposal_date": disposal.event_date, "proceeds": w.proceeds,
                                  "book_value": w.book_value, "profit_or_loss": w.profit_or_loss})
    total = sum((x.depreciation for x in lines), ZERO)
    return {"lines": lines, "findings": findings, "statuses": statuses, "snapshot": snapshot, "accum_by_asset": accum_by_asset,
            "disposals": disposals, "total": total}


def _expense_role(conn: Connection, client_id: object) -> object | None:
    return fr.ledger_role(conn, client_id, "depreciation_expense")


def preview_book(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any]:
    _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    c = _book_compute(conn, client_id, fy)
    findings = list(c["findings"])
    expense = _expense_role(conn, client_id)
    if expense is None:
        findings.append(Finding("F-02", "The ledger role 'depreciation_expense' is not set: set it before the depreciation journal can be created.", "error"))
    if fr.active_run(conn, client_id, fy.id) is not None:
        findings.append(Finding("F-26", "This financial year already has a depreciation run that is not reversed.", "warning"))
    asset_by_id = {a["id"]: a for a, _ in _setups(conn, client_id)}
    out_lines = []
    for line in c["lines"]:
        a = asset_by_id[line.asset_id]
        out_lines.append({"asset_id": line.asset_id, "asset_no": a["asset_no"], "name": a["name"], "method": line.method, "cost": line.cost,
                          "opening_accumulated": line.opening_accumulated,
                          "wdv_rate_percent": None if line.wdv_rate_percent is None else f"{line.wdv_rate_percent:.2f}",
                          "days_used": line.days_used, "days_in_year": line.days_in_year, "depreciation": line.depreciation,
                          "closing_accumulated": line.closing_accumulated, "rule_status": c["statuses"][line.asset_id], "details": line.details})
    journal = []
    if expense is not None:
        for jl in fa.depreciation_journal_lines(c["lines"], expense, c["accum_by_asset"]):
            ledger = repo.get_ledger(conn, client_id, jl.ledger_id)
            journal.append({"ledger_id": jl.ledger_id, "ledger_name": ledger.name if ledger else None, "debit": jl.debit, "credit": jl.credit})
    return {"financial_year_id": fy.id, "lines": out_lines, "total": c["total"], "journal_lines": journal, "disposal_workings": c["disposals"],
            "findings": _jfind(findings), "rule_status": list(c["statuses"].values()), "engine_version": ENGINE_VERSION}


def run_book(conn: Connection, client_id: object, fy_id: object, *, actor: str) -> dict[str, Any]:
    actor = require_actor(actor)
    _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    if final_hooks.year_is_closed(conn, client_id, fy.id):
        raise ServiceError("year_closed", f"The financial year {_label(fy)} is closed.")
    if fr.active_run(conn, client_id, fy.id) is not None:
        raise ServiceError("run_exists", f"A depreciation run for {_label(fy)} already exists and is not reversed (F-26). "
                                         "Delete the draft run or reverse its voucher before running again.")
    expense = _expense_role(conn, client_id)
    if expense is None:
        raise ServiceError("ledger_role_missing", "Set the ledger role 'depreciation_expense' first (F-02).", {"roles": ["depreciation_expense"]})
    c = _book_compute(conn, client_id, fy)
    _raise_errors(c["findings"])
    journal = fa.depreciation_journal_lines(c["lines"], expense, c["accum_by_asset"])
    if not journal:
        raise ServiceError("invalid_no_depreciation", f"There is no depreciation to post for {_label(fy)}.")
    n = len(fr.runs_of_year(conn, client_id, fy.id)) + 1
    draft = VoucherDraft(
        client_id, "journal", fy.end_date,
        f"Depreciation for the year {_label(fy)} under Schedule II of the Companies Act 2013 (F-26)", f"DEP/{_label(fy)}/{n}", None,
        tuple(VoucherLine(j.ledger_id, j.debit if j.debit > 0 else None, j.credit if j.credit > 0 else None) for j in journal))
    result = vouchers.create_draft(conn, draft, actor=actor)
    if result.errors:
        raise VoucherRuleError(result.errors)
    run_id = fr.insert_run(conn, client_id, fy.id, fy.end_date, c["total"], result.voucher_id,
                           {"assets": c["snapshot"], "half_rate": "n/a (book run)"}, ENGINE_VERSION, actor)
    for line in c["lines"]:
        fr.insert_run_line(conn, client_id, run_id, result.voucher_id, {
            "asset_id": line.asset_id, "method": line.method, "cost": line.cost, "opening_accumulated": line.opening_accumulated,
            "wdv_rate_percent": line.wdv_rate_percent, "days_used": line.days_used, "days_in_year": line.days_in_year,
            "depreciation": line.depreciation, "closing_accumulated": line.closing_accumulated,
            "details": {**line.details, "rule_status": c["statuses"][line.asset_id]}})
    audit.log(conn, AuditEntry(client_id, actor, "create", "depreciation_run", run_id,
                               new={"financial_year_id": str(fy.id), "voucher_id": str(result.voucher_id), "total": f"{c['total']:.2f}",
                                    "assets": len(c["lines"]), "engine_version": ENGINE_VERSION}))
    return {"run_id": run_id, "voucher_id": result.voucher_id, "total": c["total"]}


def list_runs(conn: Connection, client_id: object, fy_id: object) -> list[dict[str, Any]]:
    _client(conn, client_id)
    _fy(conn, client_id, fy_id)
    return fr.runs_of_year(conn, client_id, fy_id)


def delete_run(conn: Connection, client_id: object, run_id: object, *, actor: str) -> None:
    actor = require_actor(actor)
    _client(conn, client_id)
    run = fr.get_run(conn, client_id, run_id)
    if run is None:
        raise ServiceError("not_found", "Depreciation run not found for this client.")
    if run["voucher_status"] != "draft":
        raise ServiceError("run_state", f"The voucher of this run is {run['voucher_status']}: only a draft run can be deleted. "
                                        "Undo a posted run by reversing its voucher.")
    fr.delete_run(conn, client_id, run["run_id"])
    vouchers.delete_draft(conn, run["voucher_id"], actor=actor)
    audit.log(conn, AuditEntry(client_id, actor, "delete", "depreciation_run", run["run_id"],
                               old={"voucher_id": str(run["voucher_id"]), "total": f"{run['total']:.2f}"}))


def register(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any]:
    """The book view of every asset for the year, computed by the engine from the events (equal to the saved run while the inputs are unchanged)."""
    _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    rows, totals = [], {k: ZERO for k in ("opening_cost", "additions", "disposals", "closing_cost", "opening_accumulated",
                                          "depreciation_for_year", "disposal_accumulated", "closing_accumulated", "net_block")}
    for a, setup in _setups(conn, client_id):
        if setup.is_depreciable and not (setup.method and setup.useful_life_years):
            continue
        r = fa.register_row(setup, fy.start_date, fy.end_date)
        if r is None:
            continue
        ledger = repo.get_ledger(conn, client_id, a["asset_ledger_id"])
        row = {"asset_id": a["id"], "asset_no": a["asset_no"], "name": a["name"], "ledger": ledger.name if ledger else None,
               "opening_cost": r.opening_cost, "additions": r.additions, "disposals": r.disposals_cost, "closing_cost": r.closing_cost,
               "opening_accumulated": r.opening_accumulated, "depreciation_for_year": r.depreciation,
               "disposal_accumulated": r.disposal_accumulated, "closing_accumulated": r.closing_accumulated, "net_block": r.net_block,
               "put_to_use_dates": list(r.put_to_use_dates)}
        rows.append(row)
        for k in totals:
            totals[k] += row[k]
    return {"financial_year_id": fy.id, "rows": rows, "totals": totals, "engine_version": ENGINE_VERSION}


# ================================================================================================== income-tax block working (F-30 .. F-34)


def set_it_openings(conn: Connection, client_id: object, fy_id: object, rows: list[dict[str, Any]], *, actor: str) -> None:
    actor = require_actor(actor)
    _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    if final_hooks.year_is_closed(conn, client_id, fy.id):
        raise ServiceError("year_closed", f"The financial year {_label(fy)} is closed.")
    parsed: dict[str, Decimal] = {}
    for row in rows:
        key = (row.get("block_key") or "").strip()
        if not key or key in parsed:
            raise ServiceError("invalid_opening", "Each row needs a block key, and a block can appear once.")
        if _pick(fr.it_rate_rows(conn, key), fy.end_date, "income-tax block rate") is None:
            raise _no_rule(f"income-tax rate for block '{key}'", fy.end_date)
        parsed[key] = _money(row.get("opening_wdv"), f"The opening WDV of '{key}'")
    old = fr.it_openings(conn, client_id, fy.id)
    for key, wdv in parsed.items():
        fr.upsert_it_opening(conn, client_id, fy.id, key, wdv, actor)
    audit.log(conn, AuditEntry(client_id, actor, "update", "it_block_openings", fy.id,
                               old={k: f"{v['opening_wdv']:.2f}" for k, v in old.items()}, new={k: f"{v:.2f}" for k, v in parsed.items()}))


def _it_compute(conn: Connection, client_id: object, fy) -> dict[str, Any]:
    scalars = {}
    for key in ("half_rate_days", "half_rate_percent"):
        picked = _pick([r for r in fr.it_scalar_rows(conn) if r.rule_key == key], fy.end_date, f"income-tax rule '{key}'")
        if picked is None:
            raise _no_rule(f"income-tax rule '{key}'", fy.end_date)
        scalars[key] = picked
    openings = fr.it_openings(conn, client_id, fy.id)
    by_block: dict[str, list[tuple[dict[str, Any], AssetBookSetup]]] = {}
    for a, setup in _setups(conn, client_id):
        if not a["is_depreciable"] or not a["it_block_key"]:
            continue
        cost_events = [e for e in setup.events if e.kind != EventKind.DISPOSAL]
        if not cost_events:
            continue
        by_block.setdefault(a["it_block_key"], []).append((a, setup))
    keys = sorted(set(openings) | set(by_block))
    blocks, findings = [], []
    for key in keys:
        rate_row = _pick(fr.it_rate_rows(conn, key), fy.end_date, "income-tax block rate")
        if rate_row is None:
            raise _no_rule(f"income-tax rate for block '{key}'", fy.end_date)
        members = by_block.get(key, [])
        additions, disposals, assets_info, remaining = [], [], [], 0
        for a, setup in members:
            disposal = next((e for e in setup.events if e.kind == EventKind.DISPOSAL), None)
            if disposal is not None and disposal.event_date < fy.start_date:
                continue    # gone before the year: its value left the block in an earlier year
            first_cost = min(e.event_date for e in setup.events if e.kind != EventKind.DISPOSAL)
            if first_cost <= fy.end_date and (disposal is None or disposal.event_date > fy.end_date):
                remaining += 1
            for e in setup.events:
                if e.kind in (EventKind.PURCHASE, EventKind.ADDITION) and fy.start_date <= e.put_to_use_date <= fy.end_date:
                    additions.append((a["id"], e.amount, e.put_to_use_date))
                    days = (fy.end_date - e.put_to_use_date).days + 1
                    assets_info.append({"asset_id": a["id"], "asset_no": a["asset_no"], "cost": e.amount, "put_to_use_date": e.put_to_use_date,
                                        "days": days, "half": days < int(scalars["half_rate_days"].rule_value)})
                if e.kind == EventKind.DISPOSAL and fy.start_date <= e.event_date <= fy.end_date:
                    disposals.append((a["id"], e.amount))
        if key not in openings:
            findings.append(Finding("F-30", f"Block '{key}': the opening written down value for {_label(fy)} is not entered "
                                            "(enter 0.00 if the block is new). The block is not computed.", "error"))
            continue
        inp = ItBlockInput(key, rate_row.rate, rate_row.verification_status, int(scalars["half_rate_days"].rule_value),
                           scalars["half_rate_percent"].rule_value, openings[key]["opening_wdv"], tuple(additions), tuple(disposals), fy.end_date)
        res = it_block_depreciation(inp, assets_remaining=remaining if members else None)
        for flag in res.flags:
            findings.append(Finding("F-33" if flag != "negative_block" else "F-32",
                                    f"Block '{key}': {_FLAG_TEXT[flag]}", "warning"))
        blocks.append({"block_key": key, "description": rate_row.description, "rate": f"{rate_row.rate:.4f}", "rate_act": rate_row.act,
                       "rate_verification": rate_row.verification_status, "opening_wdv": res.opening_wdv, "opening_source": openings[key]["source"],
                       "additions_full": res.additions_full, "additions_half": res.additions_half, "disposals": res.disposals,
                       "depreciation": res.depreciation, "closing_wdv": res.closing_wdv, "flags": list(res.flags), "assets": assets_info,
                       "details": res.details})
    rule_status = [{"rule": "it_block_rate", "block_key": b["block_key"], "act": b["rate_act"], "verification_status": b["rate_verification"]}
                   for b in blocks]
    rule_status += [{"rule": k, "act": r.act, "verification_status": r.verification_status} for k, r in scalars.items()]
    return {"blocks": blocks, "findings": findings, "rule_status": rule_status}


_FLAG_TEXT = {
    "negative_block": "the disposals are more than the block (opening, additions): no depreciation is computed and the excess may be a "
                      "short-term capital gain. For the CA to decide.",
    "terminal_depreciation_review": "no registered asset is left in the block but the written down value is above zero: terminal "
                                    "depreciation or a loss may apply. Flagged only, nothing is computed. For the CA to decide.",
}


def it_working(conn: Connection, client_id: object, fy_id: object) -> dict[str, Any]:
    _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    final = fr.final_workings(conn, client_id, fy.id)
    if final:
        blocks = []
        for w in final:
            d = w["details"] or {}
            blocks.append({"block_key": w["block_key"], "description": d.get("description"), "rate": f"{w['rate']:.4f}", "rate_act": w["act"],
                           "rate_verification": w["rate_verification"], "opening_wdv": w["opening_wdv"], "additions_full": w["additions_full"],
                           "additions_half": w["additions_half"], "disposals": w["disposals"], "depreciation": w["depreciation"],
                           "closing_wdv": w["closing_wdv"], "flags": d.get("flags", []), "assets": d.get("assets", []), "details": d})
        return {"financial_year_id": fy.id, "blocks": blocks, "total_depreciation": sum((b["depreciation"] for b in blocks), ZERO),
                "status": "final", "findings": [], "rule_status": d.get("rule_status", []), "engine_version": ENGINE_VERSION}
    c = _it_compute(conn, client_id, fy)
    return {"financial_year_id": fy.id, "blocks": c["blocks"], "total_depreciation": sum((b["depreciation"] for b in c["blocks"]), ZERO),
            "status": "draft", "findings": _jfind(c["findings"]), "rule_status": c["rule_status"], "engine_version": ENGINE_VERSION}


def finalize_it(conn: Connection, client_id: object, fy_id: object, acknowledged_flags: list[str] | None, *, actor: str) -> None:
    actor = require_actor(actor)
    _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    if final_hooks.year_is_closed(conn, client_id, fy.id):
        raise ServiceError("year_closed", f"The financial year {_label(fy)} is closed.")
    if fr.final_workings(conn, client_id, fy.id):
        raise ServiceError("working_final", f"The income-tax working for {_label(fy)} is already final. It is superseded only when the financial "
                                            "year is reopened.")
    c = _it_compute(conn, client_id, fy)
    errors = [f for f in c["findings"] if f.severity == "error"]
    if errors or not c["blocks"]:
        msg = "; ".join(f.message for f in errors) or "There is no block to finalise."
        raise ServiceError("invalid_it_working", msg, {"errors": _jfind(errors)})
    ack = set(acknowledged_flags or [])
    pending = sorted(b["block_key"] for b in c["blocks"] if b["flags"] and b["block_key"] not in ack)
    if pending:
        raise ServiceError("invalid_flags_unacknowledged",
                           f"These blocks carry a flag that needs the CA's acknowledgement before finalising: {', '.join(pending)}.",
                           {"blocks": pending})
    for b in c["blocks"]:
        w = dict(b)
        w["act"] = b["rate_act"]
        w["rate"] = Decimal(b["rate"])
        w["rate_verification"] = b["rate_verification"]
        w["details"] = {**b["details"], "description": b["description"], "flags": b["flags"], "rule_status": c["rule_status"],
                        "acknowledged": b["block_key"] in ack,
                        "assets": [{**x, "asset_id": str(x["asset_id"]), "cost": f"{x['cost']:.2f}", "put_to_use_date": x["put_to_use_date"].isoformat()}
                                   for x in b["assets"]]}
        fr.insert_final_working(conn, client_id, fy.id, w, ENGINE_VERSION, actor)
    audit.log(conn, AuditEntry(client_id, actor, "finalize", "it_depreciation_working", fy.id,
                               new={"blocks": {b["block_key"]: {"depreciation": f"{b['depreciation']:.2f}", "closing_wdv": f"{b['closing_wdv']:.2f}",
                                                                "flags": b["flags"]} for b in c["blocks"]},
                                    "acknowledged_flags": sorted(ack), "engine_version": ENGINE_VERSION}))
