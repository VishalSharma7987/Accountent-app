"""Audit runs (Phase 8, package A): choose checks, load facts (read only), run the pure checks, store the run and its findings, audit-log it.

The audit never changes the books: loaders SELECT, checks are pure, only audit_runs / audit_findings / audit_log are written. A failing check is
shown in the run summary and does not stop the run; a run is `failed` only when the common facts cannot be loaded at all. Services never commit.

Package loaders (B, C, D): a module `app.services.audit_load_<books|compliance|analytic>` may define
`load_extra(conn, client_id, fy_start, fy_end, params, facts) -> dict[str, Any]`; the dict becomes `facts.extra` for that package's checks
(keys are the package's own). A package without extra facts defines no loader.
"""

import importlib
import uuid
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_audit as repo
from app.engine import audit_registry as reg
from app.engine.audit_types import AUDIT_ENGINE_VERSION
from app.services import audit_hooks, audit_load_common
from app.services import audit_report as report
from app.services.errors import ServiceError, require_actor

_LOADER_MODULES = {"books": "app.services.audit_load_books", "compliance": "app.services.audit_load_compliance",
                   "analytic": "app.services.audit_load_analytic"}


def list_checks(conn: Connection) -> list[dict[str, Any]]:
    return repo.catalogue(conn)


def list_rules(conn: Connection) -> list[dict[str, Any]]:
    return repo.rule_rows(conn)


def _select_checks(conn: Connection, requested: list[str] | None) -> list[str]:
    active = [c["check_id"] for c in repo.catalogue(conn) if c["active"]]
    if requested is None:
        return sorted(active)
    unknown = sorted({c for c in requested if c not in active})
    if unknown:
        raise ServiceError("unknown_check", "Unknown or inactive audit check: " + ", ".join(unknown), {"check_ids": unknown})
    if not requested:
        raise ServiceError("unknown_check", "Choose at least one audit check.")
    return sorted(set(requested))


def _period(conn: Connection, client_id: object, fy_id: object, from_date: date | None, to_date: date | None) -> tuple[date, date, date, date]:
    fy = repo.financial_year(conn, client_id, fy_id)
    if fy is None:
        raise ServiceError("no_period", "The financial year does not exist for this client.")
    start, end = from_date or fy[0], to_date or fy[1]
    if start > end or start < fy[0] or end > fy[1]:
        raise ServiceError("no_period", f"The audit period {start:%d-%m-%Y} to {end:%d-%m-%Y} must lie inside the financial year "
                                        f"{fy[0]:%d-%m-%Y} to {fy[1]:%d-%m-%Y}.")
    return start, end, fy[0], fy[1]


def _load_extras(conn: Connection, client_id: object, fy: tuple[date, date], params, facts, check_ids: list[str]) -> tuple[Any, dict[str, str]]:
    """Run the loader of every package that has a selected check. A loader that fails (or is missing) only fails that package's checks."""
    extra: dict[str, Any] = {}
    failed: dict[str, str] = {}
    for module in sorted({m for c in check_ids if (m := reg.module_of(c))}):
        try:
            mod = importlib.import_module(_LOADER_MODULES[module])
        except ModuleNotFoundError as exc:
            if exc.name != _LOADER_MODULES[module]:
                raise
            continue  # a package without a loader needs no extra facts
        loader = getattr(mod, "load_extra", None)
        if loader is None:
            continue
        try:
            with conn.begin_nested():
                extra.update(loader(conn, client_id, fy[0], fy[1], params, facts))
        except Exception as exc:  # noqa: BLE001 - isolate: the savepoint is rolled back, the run continues without these checks
            for c in check_ids:
                if reg.module_of(c) == module:
                    failed[c] = f"check {c} failed: loading its facts failed: {type(exc).__name__}: {exc}"
    return replace(facts, extra={**facts.extra, **extra}), failed


def create_run(conn: Connection, client_id: object, actor: str, financial_year_id: object, from_date: date | None = None,
               to_date: date | None = None, check_ids: list[str] | None = None, params: dict | None = None) -> dict[str, Any]:
    actor = require_actor(actor)
    selected = _select_checks(conn, check_ids)
    start, end, fy_start, fy_end = _period(conn, client_id, financial_year_id, from_date, to_date)
    try:
        audit_params = reg.params_from_input(start, end, params)
    except ValueError as exc:
        raise ServiceError("invalid_params", str(exc)) from None
    rules = audit_load_common.load_rules(conn)
    wanted_keys = {c["rule_key"] for c in repo.catalogue(conn) if c["check_id"] in selected and c["rule_key"]}
    rules_used = [reg.rule_to_dict(r) for r in rules
                  if any(r.rule_key.startswith(k) for k in wanted_keys) and r.effective_from <= end and (r.effective_to is None or r.effective_to >= start)]
    params_json = reg.params_to_dict(audit_params)
    try:
        with conn.begin_nested():
            facts = audit_load_common.load_common(conn, client_id, financial_year_id)
    except Exception as exc:  # noqa: BLE001 - nothing could be loaded: store a failed run so the attempt is on record
        run_id = repo.insert_run(conn, client_id, financial_year_id, start, end, selected, params_json, rules_used, AUDIT_ENGINE_VERSION,
                                 "failed", 0, {}, f"{type(exc).__name__}: {exc}", actor)
        _log(conn, client_id, actor, run_id, selected, start, end, "failed", 0)
        return {"id": run_id, "status": "failed", "finding_count": 0, "summary": {}, "error": f"{type(exc).__name__}: {exc}"}
    facts, loader_errors = _load_extras(conn, client_id, (fy_start, fy_end), audit_params, facts, selected)
    runnable = [c for c in selected if c not in loader_errors]
    outcomes = reg.execute(runnable, facts, audit_params, rules)
    outcomes += [reg.CheckOutcome(c, None, msg) for c, msg in loader_errors.items()]
    outcomes.sort(key=lambda o: o.check_id)
    summary = reg.build_summary(outcomes)
    total = reg.finding_total(outcomes)
    run_id = repo.insert_run(conn, client_id, financial_year_id, start, end, selected, params_json, rules_used, AUDIT_ENGINE_VERSION,
                             "completed", total, summary, None, actor)
    for o in outcomes:
        for f in (o.result.findings if o.result else ()):
            repo.insert_finding(conn, client_id, run_id, report.finding_row(f))
    _log(conn, client_id, actor, run_id, selected, start, end, "completed", total)
    return {"id": run_id, "status": "completed", "finding_count": total, "summary": summary}


def _log(conn: Connection, client_id: object, actor: str, run_id: object, check_ids: list[str], start: date, end: date, status: str,
         findings: int) -> None:
    audit_hooks.log_action(conn, client_id, actor, "run", "audit_run", run_id, None,
                           {"check_ids": check_ids, "from_date": start.isoformat(), "to_date": end.isoformat(), "status": status,
                            "finding_count": findings})


def list_runs(conn: Connection, client_id: object) -> list[dict[str, Any]]:
    return repo.list_runs(conn, client_id)


def get_run(conn: Connection, client_id: object, run_id: object) -> dict[str, Any]:
    run = repo.get_run(conn, client_id, run_id)
    if run is None:
        raise ServiceError("not_found", "Audit run not found.")
    return run


def list_findings(conn: Connection, client_id: object, run_id: object, check_id: str | None = None, severity: str | None = None,
                  subject_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    get_run(conn, client_id, run_id)
    return repo.list_findings(conn, client_id, run_id, check_id, severity, subject_id)


def build_report(conn: Connection, client_id: object, run_id: object) -> dict[str, Any]:
    run = get_run(conn, client_id, run_id)
    run = {**run, **{k: report.json_safe(run[k]) for k in ("id", "financial_year_id", "from_date", "to_date", "created_at")}}
    findings = [{**f, **{k: report.json_safe(f[k]) for k in ("id", "run_id", "subject_id", "finding_date", "amount", "disallowance_amount")
                         if f[k] is not None}} for f in repo.list_findings(conn, client_id, run_id)]
    catalogue = {c["check_id"]: c for c in repo.catalogue(conn)}
    return report.assemble_report(run, findings, catalogue)
