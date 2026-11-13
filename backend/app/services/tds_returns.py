"""TDS / TCS quarterly return working, filed figures and certificate data (Phase 4, package D).

All figures come from POSTED, non-reversed vouchers (deduction items written by package B) and from challans and their
allocations (package C). The engine module does the grouping and checks; this module reads the books, picks the form by the
quarter-end date from the rule table (T-31), collects rule statuses (T-50), saves versions (draft -> final, final is
immutable and locks its challans: T-33), stores certificate snapshots (T-34) and writes the audit log.
Services take a Connection and never commit. The official statement / certificate file formats are NOT produced.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_tds_returns as repo
from app.engine import tds_returns as eng
from app.engine.models import ValidationError
from app.engine.money import MoneyError, parse_amount
from app.services import audit
from app.services.errors import ServiceError, VoucherRuleError, require_actor
from app.services.tds_export import AMOUNT_KEYS

RANK = {"pending": 0, "secondary_verified": 1, "verified": 2}
CERT_KINDS = ("non_salary", "salary", "tcs")
KIND_TO_RETURN = {"non_salary": "non_salary_resident", "salary": "salary", "tcs": "tcs"}
PAYMENT_CODE_SOURCE = "Payment codes of the statement are not in the rule table for every nature (tds_section_refs.payment_code is empty): enter them from the official code list before filing"


# ---- helpers -------------------------------------------------------------------------------------------------------


def jsonable(value: Any, key: str = "") -> Any:
    """Decimals become strings (2 places; rates as given without trailing zeros), dates ISO, dataclasses dicts."""
    if isinstance(value, Decimal):
        if key == "rate":
            return format(value.normalize(), "f")
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, key) for v in value]
    return value


def data_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def rule_status(entries: list[tuple[str, str, str]]) -> dict:
    """entries: (rule table, status, source). Worst status per table and overall (T-50)."""
    tables: dict[str, str] = {}
    pending: list[str] = []
    for table, status, source in entries:
        if table not in tables or RANK[status] < RANK[tables[table]]:
            tables[table] = status
        if status == "pending" and source not in pending:
            pending.append(source)
    worst = min(tables.values(), key=lambda s: RANK[s]) if tables else "verified"
    return {"worst": worst, "tables": tables, "pending_sources": pending}


def _fy_label(start: date) -> str:
    return f"{start.year}-{str(start.year + 1)[2:]}"


def _client(conn: Connection, client_id: object) -> dict:
    c = repo.client(conn, client_id)
    if c is None:
        raise ServiceError("not_found", "Client not found.")
    return c


def _fy(conn: Connection, client_id: object, fy_id: object) -> dict:
    fy = repo.financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    return fy


def _quarter(quarter: int) -> int:
    if quarter not in (1, 2, 3, 4):
        raise ServiceError("period_invalid", "Quarter must be 1, 2, 3 or 4 (Q1 = April to June).")
    return quarter


def _form(conn: Connection, form_key: str, on: date):
    f = eng.pick_form(repo.forms(conn), form_key, on)
    if f is None:
        raise ServiceError("no_rule", f"No form is in force on {on.strftime('%d-%m-%Y')} for {form_key} in the rule table (T-31).")
    return f, ("form", f.verification_status, repo.form_source(conn, f.form_key, f.act, f.form_no))


def _kind_of_return(return_kind: str) -> str:
    return "tcs" if return_kind == "tcs" else "tds"


# ---- the working ---------------------------------------------------------------------------------------------------


def return_working(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str) -> dict:
    """The quarterly working as shown and exported (no timestamp, so the same books give the same hash)."""
    if return_kind not in eng.RETURN_KINDS:
        raise ServiceError("period_invalid", "return_kind must be salary, non_salary_resident or tcs.")
    _quarter(quarter)
    client = _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    start, end = eng.quarter_period(fy["start_date"], quarter)
    form, form_status = _form(conn, f"return_{return_kind}", end)
    items, statuses = repo.items(conn, client_id, fy_id, start, end)
    mine = [i for i in items if eng.return_kind_of(i) == return_kind]
    challans, allocs = repo.challans_and_allocations(conn, client_id, _kind_of_return(return_kind), fy_id, quarter,
                                                      [i.item_id for i in mine])
    w = eng.build_return_working(return_kind, client["tan"], items, challans, allocs)
    entries = [form_status, *statuses]
    if any(i.payment_code is None for i in mine):
        entries.append(("payment_code", "pending", PAYMENT_CODE_SOURCE))
        w.warnings.append({"rule_id": "T-50", "message": "Payment codes are missing for some rows: " + PAYMENT_CODE_SOURCE + "."})
    return jsonable({
        "return_kind": return_kind, "form_no": form.form_no, "form_status": form.verification_status, "tan": client["tan"],
        "financial_year": _fy_label(fy["start_date"]), "quarter": quarter, "period_start": start, "period_end": end,
        "deductee_rows": w.deductee_rows, "challan_rows": w.challan_rows, "totals": w.totals, "errors": w.errors,
        "warnings": w.warnings, "rule_status": rule_status(entries),
    })


def save_working(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str, actor: str) -> dict:
    actor = require_actor(actor)
    data = return_working(conn, client_id, fy_id, quarter, return_kind)
    version = repo.next_version(conn, client_id, fy_id, quarter, return_kind)
    working_id = repo.insert_working(conn, {
        "client_id": client_id, "fy": fy_id, "quarter": quarter, "return_kind": return_kind, "form_no": data["form_no"],
        "form_status": data["form_status"], "version": version, "data": data, "data_hash": data_hash(data),
        "rule_statuses": data["rule_status"], "created_by": actor})
    audit.log(conn, audit.AuditEntry(client_id, actor, "create", "tds_return_working", working_id, None,
                                     {"version": version, "return_kind": return_kind, "quarter": quarter, "form_no": data["form_no"],
                                      "data_hash": data_hash(data)}))
    return {"working_id": str(working_id), "version": version}


def _stored(row: dict) -> dict:
    """A stored working as the API returns it: the snapshot plus its identity."""
    return {**row["data"], "working_id": str(row["id"]), "version": row["version"], "status": row["status"],
            "data_hash": row["data_hash"], "created_by": row["created_by"], "created_at": row["created_at"].isoformat()}


def get_working(conn: Connection, working_id: object) -> dict:
    row = repo.working(conn, working_id)
    if row is None:
        raise ServiceError("not_found", "Return working not found.")
    return _stored(row)


def list_workings(conn: Connection, client_id: object, fy_id: object | None, quarter: int | None, return_kind: str | None) -> list[dict]:
    rows = repo.workings(conn, client_id, fy_id, quarter, return_kind)
    return [{**r, "id": str(r["id"]), "financial_year_id": str(r["financial_year_id"]), "created_at": r["created_at"].isoformat()} for r in rows]


def finalise_working(conn: Connection, working_id: object, actor: str) -> dict:
    """Freeze a saved working and lock the challans it uses (T-33). Refused when the books changed since it was saved."""
    actor = require_actor(actor)
    row = repo.working(conn, working_id, lock=True)
    if row is None:
        raise ServiceError("not_found", "Return working not found.")
    if row["status"] == "final":
        raise ServiceError("working_final", "This working is already final; make a new version instead.")
    fresh = return_working(conn, row["client_id"], row["financial_year_id"], row["quarter"], row["return_kind"])
    if data_hash(fresh) != row["data_hash"]:
        raise ServiceError("working_stale", "The books (vouchers or challans) changed after this working was saved. "
                           "Save a new version and finalise that one.")
    blocking = [e for e in fresh["errors"] if e.get("blocking")]
    if blocking:
        raise VoucherRuleError([ValidationError(e["rule_id"], e["message"], e.get("line_no")) for e in blocking])
    cins = [(c["bsr_code"], c["deposit_date"], c["serial_no"]) for c in fresh["challan_rows"]]
    challan_ids = repo.challan_ids_for_working(conn, row["client_id"], cins)
    repo.lock_challans(conn, row["client_id"], challan_ids)
    repo.mark_final(conn, working_id)
    audit.log(conn, audit.AuditEntry(row["client_id"], actor, "finalise", "tds_return_working", working_id, {"status": "draft"},
                                     {"status": "final", "version": row["version"], "locked_challans": len(challan_ids)}))
    return {"working_id": str(working_id), "status": "final", "locked_challans": len(challan_ids)}


# ---- filed returns -------------------------------------------------------------------------------------------------


def _check_filed_data(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ServiceError("invalid_data", "Filed figures must be an object such as {\"tax_deducted\": \"11000.00\"}.")
    out: dict = {}

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, float):
            raise ServiceError("invalid_data", f"{path}: amounts must be typed as text with 2 decimals, not as numbers with a fraction.")
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{path}[]") for v in node]
        return node

    for k, v in data.items():
        out[k] = walk(v, k)
        if k in AMOUNT_KEYS:
            try:
                out[k] = f"{parse_amount(v):.2f}"
            except MoneyError as exc:
                raise ServiceError("invalid_data", f"{k}: {exc}") from None
    return out


def put_filed(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str, receipt_no: str | None,
              filed_on: date | None, data: Any, actor: str) -> dict:
    actor = require_actor(actor)
    _client(conn, client_id)
    _fy(conn, client_id, fy_id)
    _quarter(quarter)
    if return_kind not in eng.RETURN_KINDS:
        raise ServiceError("period_invalid", "return_kind must be salary, non_salary_resident or tcs.")
    clean = _check_filed_data(data)
    old = repo.filed(conn, client_id, fy_id, quarter, return_kind)
    filed_id = repo.upsert_filed(conn, client_id, fy_id, quarter, return_kind, receipt_no, filed_on, clean, actor)
    audit.log(conn, audit.AuditEntry(
        client_id, actor, "update" if old else "create", "tds_filed_return", filed_id,
        None if old is None else {"receipt_no": old["receipt_no"], "filed_on": str(old["filed_on"]), "data": old["data"]},
        {"receipt_no": receipt_no, "filed_on": None if filed_on is None else filed_on.isoformat(), "data": clean}))
    return {"ok": True}


def get_filed(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str) -> dict:
    """The typed filed figures and their difference from the latest FINAL working (filed minus working), where both exist."""
    row = repo.filed(conn, client_id, fy_id, quarter, return_kind)
    if row is None:
        raise ServiceError("not_found", "No filed figures are entered for this quarter.")
    out = {"receipt_no": row["receipt_no"], "filed_on": None if row["filed_on"] is None else row["filed_on"].isoformat(),
           "data": row["data"], "entered_by": row["entered_by"], "entered_at": row["entered_at"].isoformat(),
           "working": None, "differences": {}}
    final = repo.latest_final_working(conn, client_id, fy_id, quarter, return_kind)
    if final is not None:
        totals = final["data"]["totals"]
        out["working"] = {"working_id": str(final["id"]), "version": final["version"], "totals": totals}
        for k in ("amount_paid", "tax_deducted", "tax_deposited"):
            if k in row["data"] and k in totals:
                out["differences"][k] = f"{Decimal(row['data'][k]) - Decimal(totals[k]):.2f}"
    return out


# ---- certificates --------------------------------------------------------------------------------------------------


def _certificate_data(conn: Connection, client_id: object, ledger_id: object, fy_id: object, quarter: int | None, kind: str):
    if kind not in CERT_KINDS:
        raise ServiceError("period_invalid", "certificate_kind must be non_salary, salary or tcs.")
    if quarter is None and kind != "salary":
        raise ServiceError("period_invalid", "A quarter is required (only the salary certificate is annual).")
    if quarter is not None:
        _quarter(quarter)
    client = _client(conn, client_id)
    fy = _fy(conn, client_id, fy_id)
    dd = repo.deductee(conn, client_id, ledger_id)
    if dd is None:
        raise ServiceError("not_found", "This ledger has no deductee row; enter the deductee master first.")
    if quarter is None:
        start, end = fy["start_date"], fy["end_date"]
        period = f"FY {_fy_label(fy['start_date'])}"
    else:
        start, end = eng.quarter_period(fy["start_date"], quarter)
        period = f"FY {_fy_label(fy['start_date'])} Q{quarter}"
    form, form_status = _form(conn, f"certificate_{kind}", end)
    items, statuses = repo.items(conn, client_id, fy_id, start, end, ledger_id)
    mine = [i for i in items if eng.return_kind_of(i) == KIND_TO_RETURN[kind]]
    challans, allocs = repo.challans_and_allocations(conn, client_id, _kind_of_return(KIND_TO_RETURN[kind]), fy_id, quarter,
                                                      [i.item_id for i in mine])
    deductor = {"name": client["legal_name"] or client["name"], "tan": client["tan"], "pan": client["pan"]}
    deductee = {"name": dd["name"], "pan": dd["pan"], "pan_status": dd["pan_status"]}
    data, errors = eng.build_certificate(form, deductor, deductee, mine, challans, allocs, period)
    entries = [form_status, *statuses]
    return data, errors, rule_status(entries), form, quarter


def _refuse(errors: list[dict]) -> None:
    raise VoucherRuleError([ValidationError(e["rule_id"], e["message"], e.get("line_no")) for e in errors])


def certificate_preview(conn: Connection, client_id: object, ledger_id: object, fy_id: object, quarter: int | None, kind: str) -> dict:
    data, errors, status, _, _ = _certificate_data(conn, client_id, ledger_id, fy_id, quarter, kind)
    if errors:
        _refuse(errors)
    return {**jsonable(data), "rule_status": status}


def create_certificate(conn: Connection, client_id: object, ledger_id: object, fy_id: object, quarter: int | None, kind: str,
                       actor: str) -> dict:
    actor = require_actor(actor)
    data, errors, status, form, q = _certificate_data(conn, client_id, ledger_id, fy_id, quarter, kind)
    if errors:
        _refuse(errors)
    snapshot = {**jsonable(data), "rule_status": status}
    version = repo.next_certificate_version(conn, client_id, kind, ledger_id, fy_id, q)
    cert_id = repo.insert_certificate(conn, {
        "client_id": client_id, "kind": kind, "ledger_id": ledger_id, "fy": fy_id, "quarter": q, "form_no": form.form_no,
        "form_status": form.verification_status, "version": version, "data": snapshot, "data_hash": data_hash(snapshot),
        "created_by": actor})
    audit.log(conn, audit.AuditEntry(client_id, actor, "create", "tds_certificate", cert_id, None,
                                     {"kind": kind, "deductee_ledger_id": str(ledger_id), "quarter": q, "version": version,
                                      "form_no": form.form_no, "total_deducted": snapshot["total_deducted"]}))
    return {"id": str(cert_id), "version": version}


def update_certificate(conn: Connection, client_id: object, cert_id: object, certificate_no: str | None, issued_on: date | None,
                       actor: str) -> dict:
    """Only the certificate number and the issue date can change (the snapshot is frozen by the database too)."""
    actor = require_actor(actor)
    row = repo.certificate(conn, client_id, cert_id)
    if row is None:
        raise ServiceError("not_found", "Certificate not found.")
    repo.update_certificate(conn, cert_id, certificate_no, issued_on)
    audit.log(conn, audit.AuditEntry(
        client_id, actor, "update", "tds_certificate", cert_id,
        {"certificate_no": row["certificate_no"], "issued_on": None if row["issued_on"] is None else row["issued_on"].isoformat()},
        {"certificate_no": certificate_no, "issued_on": None if issued_on is None else issued_on.isoformat()}))
    return {"ok": True}


def _cert_out(row: dict) -> dict:
    return {**row["data"], "id": str(row["id"]), "certificate_kind": row["certificate_kind"], "version": row["version"],
            "certificate_no": row["certificate_no"], "issued_on": None if row["issued_on"] is None else row["issued_on"].isoformat(),
            "quarter": row["quarter"], "financial_year_id": str(row["financial_year_id"]),
            "deductee_ledger_id": str(row["deductee_ledger_id"]), "data_hash": row["data_hash"]}


def get_certificate(conn: Connection, client_id: object, cert_id: object) -> dict:
    row = repo.certificate(conn, client_id, cert_id)
    if row is None:
        raise ServiceError("not_found", "Certificate not found.")
    return _cert_out(row)


def list_certificates(conn: Connection, client_id: object, fy_id: object | None, quarter: int | None, ledger_id: object | None,
                      kind: str | None) -> list[dict]:
    rows = repo.certificates(conn, client_id, fy_id, quarter, ledger_id, kind)
    return [{**r, "id": str(r["id"]), "deductee_ledger_id": str(r["deductee_ledger_id"]), "financial_year_id": str(r["financial_year_id"]),
             "issued_on": None if r["issued_on"] is None else r["issued_on"].isoformat(), "created_at": r["created_at"].isoformat()}
            for r in rows]
