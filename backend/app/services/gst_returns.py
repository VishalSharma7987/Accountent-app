"""GSTR-1 / GSTR-3B workings, tie-out, composition working, saved versions and filed figures (Phase 3, package E).

All figures come from POSTED vouchers only (G-56); the engine modules do the arithmetic, this module reads the books,
collects rule statuses (G-55), saves versions (draft -> final, immutable once final) and writes the audit log.
Services take a Connection and never commit. Needs package A (GST registrations, parties), B (invoice-mode vouchers:
voucher_gst / voucher_item_lines rows) and C (itc_entries rows); without invoice-mode data the workings are empty.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_gst_returns as repo
from app.engine import composition as comp_engine
from app.engine import gst_tieout, gstr1, gstr3b
from app.engine.money import MoneyError, parse_amount
from app.services import audit
from app.services.errors import ServiceError

RETURN_TYPES = ("gstr1", "gstr3b", "cmp08", "gstr4")
HEAD_KEYS = ("taxable_value", "igst", "cgst", "sgst", "cess", "invoice_value", "total_value")
TAX_HEADS = ("igst", "cgst", "sgst", "cess")
RANK = {"pending": 0, "secondary_verified": 1, "verified": 2}
PORTAL_NUMBERING_SOURCE = (
    "GSTR-1 / GSTR-3B table numbering and the 3B utilisation order: engine constants, not yet confirmed against the portal "
    "(PHASE3_LEGAL_VALUES.md section 5)"
)


# ---- helpers -------------------------------------------------------------------------------------------------------


def jsonable(value: Any, key: str = "") -> Any:
    """Decimals become strings (2 places; rates up to 4; quantities 3), dates ISO, dataclasses dicts."""
    if isinstance(value, Decimal):
        if key in ("rate", "gst_rate", "cess_rate"):
            return format(value.normalize(), "f")
        if key == "quantity":
            return f"{value:.3f}"
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, key) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {k: jsonable(getattr(value, k), k) for k in value.__dataclass_fields__}
    return value


def data_hash(tables: dict) -> str:
    return hashlib.sha256(json.dumps(tables, sort_keys=True, default=str).encode()).hexdigest()


def _registration(conn: Connection, client_id: object, registration_id: object) -> dict:
    reg = repo.registration(conn, client_id, registration_id)
    if reg is None:
        raise ServiceError("not_found", "GST registration not found.")
    return reg


def _period(reg: dict, period_kind: str, period_start: date, *, composition: bool) -> date:
    try:
        end = gstr1.period_end(period_kind, period_start)
    except ValueError as exc:
        raise ServiceError("period_invalid", str(exc)) from None
    if composition:
        if period_kind != "quarter":
            raise ServiceError("period_invalid", "A composition working is made for a quarter.")
    elif reg["return_frequency"] == "monthly" and period_kind != "month":
        raise ServiceError("period_invalid", "This registration files monthly: use a month (QRMP registrations may use a quarter).")
    return end


def _regular(reg: dict) -> None:
    if reg["registration_type"] != "regular":
        raise ServiceError("not_gst_client", "A composition registration does not file GSTR-1 or GSTR-3B; use the composition working.")


def _rule_status(entries: list[tuple[str, str, str]]) -> dict:
    """entries: (rule table, status, source). Worst status first (G-55)."""
    tables: dict[str, str] = {}
    pending: list[str] = []
    for table, status, source in entries:
        if table not in tables or RANK[status] < RANK[tables[table]]:
            tables[table] = status
        if status == "pending" and source not in pending:
            pending.append(source)
    worst = min(tables.values(), key=lambda s: RANK[s]) if tables else "verified"
    return {"worst": worst, "tables": tables, "pending_sources": pending}


def _statuses(conn: Connection, client_id: object, registration_id: object, start: date, end: date, extra=()) -> dict:
    entries = [("portal_numbering", "pending", PORTAL_NUMBERING_SOURCE)]
    entries += [("rate", s, src) for s, src in repo.rate_rule_statuses(conn, client_id, registration_id, start, end)]
    entries += list(extra)
    return _rule_status(entries)


def _envelope(reg: dict, period_kind: str, start: date, end: date, tables: dict, warnings: list[str], rule_status: dict,
              source_count: int, drafts: list[dict]) -> dict:
    return {
        "registration_id": str(reg["id"]), "gstin": reg["gstin"], "period_kind": period_kind, "period_start": start,
        "period_end": end, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "rule_status": rule_status,
        "warnings": warnings, "tables": tables, "source_voucher_count": source_count,
        "unposted_drafts_in_period": drafts,
    }


def _draft_warnings(drafts: list[dict]) -> list[str]:
    if not drafts:
        return []
    return [(f"{len(drafts)} unposted draft or approved voucher(s) dated in this period are NOT in these figures; "
            "post or discard them (G-56).")]


# ---- GSTR-1 --------------------------------------------------------------------------------------------------------


def _gstr1(conn: Connection, client_id: object, reg: dict, start: date, end: date):
    limit = repo.threshold(conn, "b2cl_invoice_value", end)
    if limit is None:
        raise ServiceError("no_rate_rule", f"No B2C-large limit is in force on {end.strftime('%d-%m-%Y')}.")
    docs = repo.documents(conn, client_id, reg["id"], start, end, ("sales", "credit_note"), by_voucher_date=False)
    numbers = repo.numbers_issued(conn, client_id, reg["id"], start, end)
    result = gstr1.build_gstr1(docs, numbers, reg["state_code"], Decimal(limit["value"]).quantize(Decimal("0.01")))
    extra = [("thresholds", limit["status"], limit["source"])]
    return result, docs, extra


def gstr1_working(conn: Connection, client_id: object, registration_id: object, period_kind: str, period_start: date) -> dict:
    reg = _registration(conn, client_id, registration_id)
    _regular(reg)
    end = _period(reg, period_kind, period_start, composition=False)
    result, docs, extra = _gstr1(conn, client_id, reg, period_start, end)
    drafts = repo.unposted_drafts(conn, client_id, reg["id"], period_start, end)
    status = _statuses(conn, client_id, reg["id"], period_start, end, extra)
    warnings = list(result.warnings) + _draft_warnings(drafts)
    return _envelope(reg, period_kind, period_start, end, result.tables, warnings, status, len(docs), drafts)


# ---- GSTR-3B -------------------------------------------------------------------------------------------------------


def _gstr3b(conn: Connection, client_id: object, reg: dict, start: date, end: date):
    out_docs = repo.documents(conn, client_id, reg["id"], start, end, ("sales", "credit_note"), by_voucher_date=False)
    in_docs = repo.documents(conn, client_id, reg["id"], start, end, ("purchase", "debit_note"), by_voucher_date=True)
    itc = repo.itc_rows(conn, client_id, reg["id"], start, end)
    reversals = repo.itc_reversals(conn, client_id, reg["id"], start, end)
    result = gstr3b.build_gstr3b(out_docs, in_docs, itc, reversals, reg["state_code"], start, end)
    return result, out_docs, in_docs, itc, reversals


def gstr3b_working(conn: Connection, client_id: object, registration_id: object, period_kind: str, period_start: date) -> dict:
    reg = _registration(conn, client_id, registration_id)
    _regular(reg)
    end = _period(reg, period_kind, period_start, composition=False)
    result, out_docs, in_docs, itc, _ = _gstr3b(conn, client_id, reg, period_start, end)
    drafts = repo.unposted_drafts(conn, client_id, reg["id"], period_start, end)
    warnings = list(result.warnings) + _draft_warnings(drafts)
    unclaimed = sum(1 for r in itc if r.status == "pending")
    if unclaimed:
        warnings.append(f"{unclaimed} ITC line(s) are pending (evidence or 2B) and are not claimed in 4(A); see 4(D).")
    status = _statuses(conn, client_id, reg["id"], period_start, end)
    return _envelope(reg, period_kind, period_start, end, result.tables, warnings, status,
                     len(out_docs) + len(in_docs), drafts)


# ---- tie-out -------------------------------------------------------------------------------------------------------


def _heads_from(movement: dict, roles: dict, prefix: str, sign: int, warnings: list[str]) -> dict[str, Decimal]:
    out = {}
    for h in TAX_HEADS:
        ledger = roles.get(f"{prefix}_{h}")
        if ledger is None:
            warnings.append(f"Ledger role {prefix}_{h} is not mapped for this registration: the books figure for {h.upper()} is shown as 0.00.")
            out[h] = Decimal("0.00")
        else:
            out[h] = sign * movement.get(ledger, Decimal("0.00"))
    return out


def tie_out(conn: Connection, client_id: object, registration_id: object, period_kind: str, period_start: date) -> dict:
    reg = _registration(conn, client_id, registration_id)
    _regular(reg)
    end = _period(reg, period_kind, period_start, composition=False)
    r1, docs1, extra = _gstr1(conn, client_id, reg, period_start, end)
    r3, out_docs, in_docs, itc, reversals = _gstr3b(conn, client_id, reg, period_start, end)
    roles = repo.ledger_roles(conn, reg["id"])
    warnings: list[str] = list(r1.warnings) + list(r3.warnings)
    ledger_ids = [roles[k] for k in roles if k.startswith(("output_", "input_", "round_off"))]
    movement = repo.ledger_movement(conn, client_id, ledger_ids, period_start, end)

    books_out = _heads_from(movement, roles, "output", 1, warnings)
    books_out = {"taxable_value": repo.sales_ledger_movement(conn, client_id, period_start, end), **books_out}
    books_in = _heads_from(movement, roles, "input", -1, warnings)
    if repo.active_registration_count(conn, client_id) > 1:
        warnings.append("The client has more than one GST registration: the books taxable value covers all Sales Accounts ledgers of the client.")

    t4 = r3.tables["t4"]
    zero = Decimal("0.00")
    pending = {h: sum((getattr(r, h) * (-1 if r.doc_type != "invoice" else 1)
                       for r in itc if r.status == "pending"), zero) for h in TAX_HEADS}
    reg_net = {h: t4["a"]["total"][h] - t4["b"]["others"][h] for h in TAX_HEADS}
    filed1 = repo.filed_return(conn, reg["id"], "gstr1", period_start)
    filed3 = repo.filed_return(conn, reg["id"], "gstr3b", period_start)
    try:
        f1 = gst_tieout.filed_gstr1_totals(filed1["data"] if filed1 else None)
        f3 = gst_tieout.filed_gstr3b_totals(filed3["data"] if filed3 else None)
    except ArithmeticError:
        raise ServiceError("filed_invalid", "A filed figure is not a valid amount; enter the filed return again.") from None

    causes = _causes(conn, client_id, reg, roles, period_start, end, pending)
    res = gst_tieout.build_tieout(
        books_out, r1.tables["totals"], r3.tables["outward_total"], f1, f3, books_in, reg_net, t4["c_net"], pending, causes)
    drafts = repo.unposted_drafts(conn, client_id, reg["id"], period_start, end)
    warnings += _draft_warnings(drafts)
    tables = {"rows": res.rows, "itc": res.itc, "causes": res.causes, "ties": res.ties,
              "itc_note": "gstr3b_4a is 4(A) less the 4(B) reversals; itc_register_eligible is the same net from the ITC register."}
    status = _statuses(conn, client_id, reg["id"], period_start, end, extra)
    env = _envelope(reg, period_kind, period_start, end, tables, warnings, status, len(docs1) + len(in_docs), drafts)
    return env


def _causes(conn, client_id, reg, roles, start, end, pending) -> list[gst_tieout.Cause]:
    causes: list[gst_tieout.Cause] = []
    for d in repo.unposted_drafts(conn, client_id, reg["id"], start, end):
        causes.append(gst_tieout.Cause("draft_voucher", d["reference_no"] or d["voucher_id"], d["invoice_value"]))
    role_of = {v: k for k, v in roles.items() if k.startswith(("output_", "input_"))}
    for j in repo.manual_tax_journals(conn, client_id, list(role_of), start, end):
        if j["net"]:
            causes.append(gst_tieout.Cause("manual_journal_on_tax_ledger", j["number"] or j["voucher_id"], j["net"],
                                           role_of[j["ledger_id"]]))
    for o in repo.other_period_documents(conn, client_id, reg["id"], start, end):
        causes.append(gst_tieout.Cause("other_period_document", o["number"], o["invoice_value"]))
    total_pending = sum(pending.values(), Decimal("0.00"))
    if total_pending:
        causes.append(gst_tieout.Cause("pending_itc", "ITC register: pending lines", total_pending))
    if "round_off" in roles:
        ro = repo.ledger_movement(conn, client_id, [roles["round_off"]], start, end).get(roles["round_off"], Decimal("0.00"))
        if ro:
            causes.append(gst_tieout.Cause("rounding", "Round-off ledger movement", ro))
    return causes


# ---- composition ---------------------------------------------------------------------------------------------------


def fy_start(on: date) -> date:
    return date(on.year if on.month >= 4 else on.year - 1, 4, 1)


def composition_working(conn: Connection, client_id: object, registration_id: object, period_start: date) -> dict:
    reg = _registration(conn, client_id, registration_id)
    if reg["registration_type"] != "composition":
        raise ServiceError("not_gst_client", "The composition working is for composition registrations only.")
    end = _period(reg, "quarter", period_start, composition=True)
    rule = repo.composition_rule(conn, reg["composition_category"], end)
    if rule is None:
        raise ServiceError("no_rate_rule", f"No composition rule for '{reg['composition_category']}' is in force on {end.strftime('%d-%m-%Y')}.")
    fy = fy_start(period_start)
    docs = repo.documents(conn, client_id, reg["id"], fy, end, ("sales", "credit_note"), by_voucher_date=False)
    engine_rule = comp_engine.CompositionRule(rule["category"], rule["rate"], rule["turnover_limit"].quantize(Decimal("0.01")),
                                              rule["turnover_basis"], rule["verification_status"])
    res = comp_engine.build_composition(engine_rule, docs, period_start, end, fy)
    drafts = repo.unposted_drafts(conn, client_id, reg["id"], period_start, end)
    status = _statuses(conn, client_id, reg["id"], period_start, end,
                       [("composition", rule["verification_status"], rule["source_reference"])])
    w = res.working
    return {**_envelope(reg, "quarter", period_start, end, {"cmp08": w}, list(res.warnings) + _draft_warnings(drafts), status,
                        len([d for d in docs if period_start <= d.invoice_date <= end]), drafts), **w}


# ---- saved versions ------------------------------------------------------------------------------------------------


def _compute(conn: Connection, client_id: object, registration_id: object, return_type: str, period_kind: str, period_start: date) -> dict:
    if return_type == "gstr1":
        return gstr1_working(conn, client_id, registration_id, period_kind, period_start)
    if return_type == "gstr3b":
        return gstr3b_working(conn, client_id, registration_id, period_kind, period_start)
    if return_type == "cmp08":
        return composition_working(conn, client_id, registration_id, period_start)
    raise ServiceError("working_unsupported", f"A working for {return_type.upper()} is not built in this phase.", None)


def save_working(conn: Connection, client_id: object, registration_id: object, return_type: str, period_kind: str,
                 period_start: date, actor: str) -> tuple[object, int]:
    env = jsonable(_compute(conn, client_id, registration_id, return_type, period_kind, period_start))
    version = repo.next_version(conn, registration_id, return_type, period_start)
    end = date.fromisoformat(env["period_end"])
    working_id = repo.insert_working(conn, client_id, registration_id, return_type, period_kind, period_start, end, version,
                                     env, data_hash(env["tables"]), env["rule_status"], actor)
    audit.log(conn, audit.AuditEntry(client_id, actor, "gst_working_saved", "gst_return_working", working_id, None,
                                     {"return_type": return_type, "period_start": period_start, "version": version,
                                      "data_hash": data_hash(env["tables"])}))
    return working_id, version


def _own_working(conn: Connection, working_id: object, client_id: object | None = None) -> dict:
    w = repo.working(conn, working_id)
    if w is None or (client_id is not None and w["client_id"] != client_id):
        raise ServiceError("not_found", "Working not found.")
    return w


def get_working(conn: Connection, working_id: object) -> dict:
    return _own_working(conn, working_id)


def finalise_working(conn: Connection, working_id: object, actor: str) -> None:
    w = _own_working(conn, working_id)
    if w["status"] == "final":
        raise ServiceError("working_final", "This working is already final and cannot be changed.")
    repo.finalise_working(conn, working_id)
    audit.log(conn, audit.AuditEntry(w["client_id"], actor, "gst_working_finalised", "gst_return_working", working_id,
                                     {"status": "draft"}, {"status": "final", "data_hash": w["data_hash"]}))


def list_workings(conn: Connection, client_id: object, registration_id: object | None, return_type: str | None) -> list[dict]:
    return repo.list_workings(conn, client_id, registration_id, return_type)


# ---- filed figures -------------------------------------------------------------------------------------------------


def _check_amounts(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in HEAD_KEYS and v not in (None, ""):
                try:
                    parse_amount(v)
                except MoneyError as exc:
                    raise ServiceError("filed_invalid", f"Filed figure {path}{k}: {exc}") from None
            else:
                _check_amounts(v, f"{path}{k}.")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_amounts(v, f"{path}{i}.")


def put_filed_return(conn: Connection, client_id: object, registration_id: object, return_type: str, period_start: date,
                     arn: str | None, filed_on: date | None, data: dict, actor: str) -> None:
    _registration(conn, client_id, registration_id)
    if return_type not in RETURN_TYPES:
        raise ServiceError("period_invalid", f"Return type must be one of {', '.join(RETURN_TYPES)}.")
    if period_start.day != 1:
        raise ServiceError("period_invalid", "Period must start on the 1st of a month.")
    _check_amounts(data)
    old = repo.filed_return(conn, registration_id, return_type, period_start)
    new_id = repo.upsert_filed_return(conn, client_id, registration_id, return_type, period_start, arn, filed_on, data, actor)
    audit.log(conn, audit.AuditEntry(client_id, actor, "gst_filed_return_saved", "gst_filed_return", new_id,
                                     None if old is None else {"arn": old["arn"], "filed_on": old["filed_on"], "data": old["data"]},
                                     {"arn": arn, "filed_on": filed_on, "data": data}))


def get_filed_return(conn: Connection, client_id: object, registration_id: object, return_type: str, period_start: date) -> dict | None:
    _registration(conn, client_id, registration_id)
    return repo.filed_return(conn, registration_id, return_type, period_start)

