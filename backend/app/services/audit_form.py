"""Tax audit form data: Form 3CD (FY ending up to 31-03-2026) / Form 26 (FY ending from 01-04-2026) (Phase 8, package F).

The form is chosen by the financial year's end date from the seeded definitions (`audit_form_defs`, pending / secondary status shown).
A set holds entries per clause: `derived` (from the findings of one audit run, by `engine/audit_form.derive`, the entry names the run) or
`manual` (typed by the accountant). A clause the books cannot give, or whose source check is missing from the run, is reported and left for
manual entry, never guessed. A finalised set is immutable (database guard + a friendly `form_finalised` here). Read-only on the books: only
audit_form_sets / audit_form_entries are written. Services take a Connection and never commit.
"""

import io
import json
from typing import Any

from sqlalchemy import Connection, text

from app.engine import audit_form as engine
from app.services import audit_hooks, queries
from app.services.errors import ServiceError, require_actor

FORM_NOT_VERIFIED = "not verified against the official form"


def _year(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    row = conn.execute(text("SELECT id, start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"),
                       {"f": fy_id, "c": client_id}).mappings().first()
    if row is None:
        raise ServiceError("no_financial_year", "The financial year was not found for this client.")
    return dict(row)


def _defs(conn: Connection) -> list[engine.FormDef]:
    rows = conn.execute(text("SELECT form_key, title, law, section_ref, effective_from, effective_to, verification_status "
                             "FROM audit_form_defs")).all()
    return [engine.FormDef(*r) for r in rows]


def _clauses(conn: Connection, form_key: str) -> list[engine.ClauseDef]:
    rows = conn.execute(text("SELECT form_key, clause_no, title, derivability, data_source, verification_status FROM audit_form_clauses "
                             "WHERE form_key = :k ORDER BY sort_order, clause_no"), {"k": form_key}).all()
    return [engine.ClauseDef(*r) for r in rows]


def _form_for(conn: Connection, client_id: Any, fy_id: Any) -> tuple[engine.FormDef, dict]:
    queries.require_client(conn, client_id)
    year = _year(conn, client_id, fy_id)
    form = engine.select_form(_defs(conn), year["end_date"])
    if form is None:
        raise ServiceError("no_rule", "No tax audit form is defined for the financial year ending "
                                      f"{year['end_date'].strftime('%d-%m-%Y')}.")
    return form, year


def form_for_year(conn: Connection, client_id: Any, fy_id: Any) -> dict:
    form, _ = _form_for(conn, client_id, fy_id)
    clauses = _clauses(conn, form.form_key)
    note = None
    if form.form_key == "form_26" and not clauses:
        note = ("The clause list of Form 26 has not been read from the official form and is not seeded: enter every clause by hand "
                "(clause number, field, value). " + FORM_NOT_VERIFIED + ".")
    return {"form_key": form.form_key, "title": form.title, "law": form.law, "section_ref": form.section_ref,
            "verification_status": form.verification_status, "note": note,
            "clauses": [{"clause_no": c.clause_no, "title": c.title, "derivability": c.derivability, "data_source": c.data_source,
                         "verification_status": c.verification_status, "derivable_here": engine.derivable_here(c)} for c in clauses]}


def _set(conn: Connection, client_id: Any, set_id: Any) -> dict:
    row = conn.execute(text("SELECT id, financial_year_id, form_key, status, created_by, created_at, finalised_by, finalised_at "
                            "FROM audit_form_sets WHERE id = :s AND client_id = :c"), {"s": set_id, "c": client_id}).mappings().first()
    if row is None:
        raise ServiceError("not_found", "Form set not found.")
    return dict(row)


def _require_draft(form_set: dict) -> None:
    if form_set["status"] == "finalised":
        raise ServiceError("form_finalised", "This form set is finalised and cannot be changed.")


def create_set(conn: Connection, client_id: Any, fy_id: Any, *, actor: str) -> dict:
    actor = require_actor(actor)
    form, _ = _form_for(conn, client_id, fy_id)
    exists = conn.execute(text("SELECT id FROM audit_form_sets WHERE client_id = :c AND financial_year_id = :f AND form_key = :k"),
                          {"c": client_id, "f": fy_id, "k": form.form_key}).first()
    if exists:
        raise ServiceError("duplicate_form_set", f"A {form.title.split(' - ')[0]} set already exists for this financial year.",
                           {"id": str(exists[0])})
    new_id = conn.execute(text("INSERT INTO audit_form_sets (client_id, financial_year_id, form_key, created_by) "
                               "VALUES (:c, :f, :k, :by) RETURNING id"),
                          {"c": client_id, "f": fy_id, "k": form.form_key, "by": actor}).scalar_one()
    audit_hooks.log_action(conn, client_id, actor, "create", "audit_form_set", new_id, None,
                           {"financial_year_id": str(fy_id), "form_key": form.form_key, "status": "draft"})
    return {"id": new_id, "form_key": form.form_key, "status": "draft"}


def _entries(conn: Connection, set_id: Any) -> list[dict]:
    rows = conn.execute(text("SELECT clause_no, field_key, value, origin, run_id, entered_by, entered_at FROM audit_form_entries "
                             "WHERE form_set_id = :s ORDER BY clause_no, field_key"), {"s": set_id}).mappings().all()
    return [dict(r) for r in rows]


def get_set(conn: Connection, client_id: Any, set_id: Any) -> dict:
    queries.require_client(conn, client_id)
    s = _set(conn, client_id, set_id)
    info = conn.execute(text("SELECT title, law, section_ref, verification_status FROM audit_form_defs WHERE form_key = :k"),
                        {"k": s["form_key"]}).mappings().one()
    clauses = _clauses(conn, s["form_key"])
    return {**s, "form": dict(info),
            "clauses": [{"clause_no": c.clause_no, "title": c.title, "derivability": c.derivability,
                         "verification_status": c.verification_status} for c in clauses],
            "entries": _entries(conn, set_id)}


def derive(conn: Connection, client_id: Any, set_id: Any, run_id: Any, *, actor: str, clause_nos: list[str] | None = None) -> dict:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    s = _set(conn, client_id, set_id)
    _require_draft(s)
    run = conn.execute(text("SELECT id, financial_year_id, check_ids, summary FROM audit_runs WHERE id = :r AND client_id = :c"),
                       {"r": run_id, "c": client_id}).mappings().first()
    if run is None:
        raise ServiceError("not_found", "Audit run not found.")
    if run["financial_year_id"] != s["financial_year_id"]:
        raise ServiceError("invalid_run", "The audit run belongs to a different financial year than this form set.")
    by_check = (run["summary"] or {}).get("by_check", {}) or {}
    failed = [c for c, v in by_check.items() if isinstance(v, dict) and v.get("error")]
    rows = conn.execute(text("SELECT id, check_id, amount, disallowance_amount, evidence FROM audit_findings WHERE run_id = :r AND client_id = :c"),
                        {"r": run_id, "c": client_id}).mappings().all()
    findings = [engine.FindingRow(str(r["id"]), r["check_id"], r["amount"], r["disallowance_amount"],
                                  ((r["evidence"] or {}).get("rule") or {}).get("verification_status")) for r in rows]
    result = engine.derive(_clauses(conn, s["form_key"]), findings, list(run["check_ids"]), failed, clause_nos)

    existing = {(e["clause_no"], e["field_key"]): e for e in _entries(conn, set_id)}
    written, kept_manual = [], []
    for e in result.entries:
        old = existing.get((e.clause_no, e.field_key))
        if old is not None and old["origin"] == "manual":
            kept_manual.append({"clause_no": e.clause_no, "field_key": e.field_key})
            continue
        conn.execute(
            text("INSERT INTO audit_form_entries (client_id, form_set_id, clause_no, field_key, value, origin, run_id, entered_by) "
                 "VALUES (:c, :s, :n, :k, CAST(:v AS jsonb), 'derived', :r, :by) "
                 "ON CONFLICT (form_set_id, clause_no, field_key) DO UPDATE SET value = EXCLUDED.value, run_id = EXCLUDED.run_id, "
                 "entered_by = EXCLUDED.entered_by, entered_at = now()"),
            {"c": client_id, "s": set_id, "n": e.clause_no, "k": e.field_key, "v": json.dumps(e.value), "r": run_id, "by": actor})
        written.append({"clause_no": e.clause_no, "field_key": e.field_key, "value": e.value, "origin": "derived", "run_id": str(run_id)})
    audit_hooks.log_action(conn, client_id, actor, "derive", "audit_form_set", set_id, None,
                           {"run_id": str(run_id), "entries": len(written), "kept_manual": kept_manual,
                            "skipped": [x.clause_no for x in result.skipped]})
    return {"entries": written, "skipped": [{"clause_no": x.clause_no, "reason": x.reason} for x in result.skipped],
            "kept_manual": kept_manual}


def enter_manual(conn: Connection, client_id: Any, set_id: Any, clause_no: str, field_key: str, value: Any, *, actor: str) -> dict:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    s = _set(conn, client_id, set_id)
    _require_draft(s)
    clause_no, field_key = (clause_no or "").strip(), (field_key or "").strip()
    if not clause_no or not field_key:
        raise ServiceError("invalid_entry", "Clause number and field are required.")
    if value is None or isinstance(value, (float, bool)) or (isinstance(value, str) and not value.strip()):
        raise ServiceError("invalid_entry", "Give a value as text (amounts as text, for example \"1250.00\"); an empty value or a number "
                                            "with a fraction is not accepted.")
    old = conn.execute(text("SELECT value, origin FROM audit_form_entries WHERE form_set_id = :s AND clause_no = :n AND field_key = :k"),
                       {"s": set_id, "n": clause_no, "k": field_key}).first()
    conn.execute(
        text("INSERT INTO audit_form_entries (client_id, form_set_id, clause_no, field_key, value, origin, run_id, entered_by) "
             "VALUES (:c, :s, :n, :k, CAST(:v AS jsonb), 'manual', NULL, :by) "
             "ON CONFLICT (form_set_id, clause_no, field_key) DO UPDATE SET value = EXCLUDED.value, origin = 'manual', run_id = NULL, "
             "entered_by = EXCLUDED.entered_by, entered_at = now()"),
        {"c": client_id, "s": set_id, "n": clause_no, "k": field_key, "v": json.dumps(value), "by": actor})
    audit_hooks.log_action(conn, client_id, actor, "enter" if old is None else "change", "audit_form_entry", set_id,
                           None if old is None else {"clause_no": clause_no, "field_key": field_key, "value": old[0], "origin": old[1]},
                           {"clause_no": clause_no, "field_key": field_key, "value": value, "origin": "manual"})
    return {"clause_no": clause_no, "field_key": field_key, "value": value, "origin": "manual"}


def finalise(conn: Connection, client_id: Any, set_id: Any, *, actor: str) -> None:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    s = _set(conn, client_id, set_id)
    _require_draft(s)
    conn.execute(text("UPDATE audit_form_sets SET status = 'finalised', finalised_by = :by, finalised_at = now() WHERE id = :s"),
                 {"by": actor, "s": set_id})
    audit_hooks.log_action(conn, client_id, actor, "finalise", "audit_form_set", set_id, {"status": "draft"}, {"status": "finalised"})


def export_xlsx(conn: Connection, client_id: Any, set_id: Any) -> tuple[bytes, str, str]:
    """Workbook of the set: every clause of the form (entered or not), with its verification status; a pending clause says it is not verified."""
    import openpyxl

    queries.require_client(conn, client_id)
    s = _set(conn, client_id, set_id)
    info = conn.execute(text("SELECT title, verification_status FROM audit_form_defs WHERE form_key = :k"), {"k": s["form_key"]}).one()
    clauses = {c.clause_no: c for c in _clauses(conn, s["form_key"])}
    entries = _entries(conn, set_id)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = s["form_key"]
    ws.append([info[0]])
    ws.append([f"Form status: {info[1]}" + (f" ({FORM_NOT_VERIFIED})" if info[1] != "verified" else ""), f"Set status: {s['status']}"])
    ws.append([])
    ws.append(["Clause", "Title", "Field", "Value", "Origin", "Audit run", "Clause status"])
    seen: set[str] = set()
    for e in entries:
        c = clauses.get(e["clause_no"])
        seen.add(e["clause_no"])
        status = c.verification_status if c else "pending"
        value = e["value"] if isinstance(e["value"], str) else json.dumps(e["value"])
        ws.append([e["clause_no"], c.title if c else "", e["field_key"], value, e["origin"], str(e["run_id"] or ""),
                   status if status == "verified" else f"{status}: {FORM_NOT_VERIFIED}"])
    for no, c in clauses.items():
        if no not in seen:
            ws.append([no, c.title, "", "", "not entered", "",
                       c.verification_status if c.verification_status == "verified" else f"{c.verification_status}: {FORM_NOT_VERIFIED}"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"tax_audit_{s['form_key']}.xlsx"
