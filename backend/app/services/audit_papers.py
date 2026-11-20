"""Audit working papers (Phase 8, package E; rules W-01 .. W-08): create from run + check, sample, decide exceptions, notes, review, sign-off.

READ-ONLY on the books: this service reads audit_runs / audit_findings and writes only audit_working_papers, audit_paper_items and
audit_paper_notes. Every action is audit-logged (audit_hooks.log_action) with old and new values. Services never commit. The conclusion on a
paper is only ever the reviewer's own text; no model is called here.

Dependency on package A: the run's per-check summary (audit_runs.summary.by_check[check_id]) may carry `population_ids`,
`population_amounts` (id -> amount) and `population_amount`. When it does not (A stores only the count), the check's findings are the
population and the sample records `population_source = "findings"`.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.db import repositories_audit_papers as repo
from app.engine import audit_papers as rules
from app.engine import audit_sampling as sampling
from app.engine.audit_types import CHECKS, PaperStatus, SampleMethod
from app.engine.money import MoneyError, parse_amount
from app.services import audit_hooks, queries
from app.services.errors import ServiceError, require_actor

METHODS = (SampleMethod.RANDOM.value, SampleMethod.SYSTEMATIC.value, SampleMethod.VALUE.value)


def _raise(e: rules.PaperError) -> ServiceError:
    return ServiceError(e.code, e.message, {"rule_id": e.rule_id})


def _snapshot(p: dict) -> dict:
    return {"status": p["status"], "sample_method": p["sample_method"], "sample_seed": p["sample_seed"], "conclusion": p["conclusion"]}


def _summary_entry(run: dict, check_id: str) -> dict | None:
    by_check = (run.get("summary") or {}).get("by_check") or {}
    entry = by_check.get(check_id)
    return entry if isinstance(entry, dict) else None


def _population(conn: Connection, run: dict, check_id: str) -> tuple[rules.Population, list[dict]]:
    findings = repo.findings_of_check(conn, run["id"], check_id)
    return rules.resolve_population(_summary_entry(run, check_id), [(f["id"], f["amount"]) for f in findings]), findings


def _require_paper(conn: Connection, client_id: Any, paper_id: Any, *, lock: bool = False) -> dict:
    queries.require_client(conn, client_id)
    paper = repo.get_paper(conn, client_id, paper_id, lock=lock)
    if paper is None:
        raise ServiceError("not_found", "Working paper not found.")
    return paper


# ------------------------------------------------------------------------------------------------------------------------- create / read


def create_paper(conn: Connection, client_id: Any, run_id: Any, check_id: str, actor: str) -> dict:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    run = repo.get_run(conn, client_id, run_id)
    if run is None:
        raise ServiceError("not_found", "Audit run not found.")
    if check_id not in CHECKS or check_id not in run["check_ids"]:
        raise ServiceError("unknown_check", f"Check {check_id} is not part of this audit run.")
    if repo.paper_for_run_check(conn, run["id"], check_id) is not None:
        raise ServiceError("paper_exists", f"A working paper for {check_id} already exists for this run (one paper per run and check).")
    pop, findings = _population(conn, run, check_id)
    paper_id = repo.insert_paper(conn, client_id=client_id, financial_year_id=run["financial_year_id"], run_id=run["id"], check_id=check_id,
                                 population_count=pop.count, population_digest=pop.digest, population_amount=pop.amount, created_by=actor)
    repo.insert_items(conn, client_id, paper_id, [f["id"] for f in findings])
    audit_hooks.log_action(conn, client_id, actor, "create", "audit_working_paper", paper_id, None,
                           {"run_id": run["id"], "check_id": check_id, "status": "open", "population_count": pop.count,
                            "population_digest": pop.digest, "population_source": pop.source, "items": len(findings)})
    return {"id": paper_id, "status": "open", "population_count": pop.count, "population_digest": pop.digest, "items": len(findings)}


def list_papers(conn: Connection, client_id: Any, *, run_id: Any = None, check_id: str | None = None, status: str | None = None) -> list[dict]:
    queries.require_client(conn, client_id)
    if status is not None and status not in {s.value for s in PaperStatus}:
        raise ServiceError("invalid_status", "Status must be open, in_review or signed_off.")
    return repo.list_papers(conn, client_id, run_id=run_id, check_id=check_id, status=status)


def get_paper(conn: Connection, client_id: Any, paper_id: Any) -> dict:
    paper = _require_paper(conn, client_id, paper_id)
    out = dict(paper)
    out["sample"] = {"method": paper["sample_method"], "seed": paper["sample_seed"], "params": paper["sample_params"], "ids": paper["sample_ids"]}
    out["items"] = repo.list_items(conn, paper_id)
    out["notes"] = repo.list_notes(conn, paper_id)
    return out


# --------------------------------------------------------------------------------------------------------------------------- exceptions


def decide_item(conn: Connection, client_id: Any, paper_id: Any, item_id: Any, status: str, reviewer_note: str | None, actor: str) -> None:
    """W-03: clear or confirm one exception with a reason; who and when are recorded."""
    actor = require_actor(actor)
    paper = _require_paper(conn, client_id, paper_id, lock=True)
    try:
        rules.check_editable(paper["status"])
        rules.check_decision(status, reviewer_note)
    except rules.PaperError as e:
        raise _raise(e) from None
    item = repo.get_item(conn, paper["id"], item_id)
    if item is None:
        raise ServiceError("not_found", "Working paper item not found.")
    note = reviewer_note.strip()  # type: ignore[union-attr]  # check_decision proved it is not blank
    repo.decide_item(conn, item["id"], status, note, actor)
    audit_hooks.log_action(conn, client_id, actor, "decide", "audit_paper_item", item["id"],
                           {"status": item["status"], "reviewer_note": item["reviewer_note"], "decided_by": item["decided_by"]},
                           {"status": status, "reviewer_note": note, "paper_id": paper["id"]})


def add_note(conn: Connection, client_id: Any, paper_id: Any, note: str | None, actor: str) -> Any:
    """W-06: notes are insert only; refused after sign-off."""
    actor = require_actor(actor)
    paper = _require_paper(conn, client_id, paper_id, lock=True)
    try:
        rules.check_editable(paper["status"])
    except rules.PaperError as e:
        raise _raise(e) from None
    text_ = (note or "").strip()
    if not text_:
        raise ServiceError("invalid_note", "The note is empty.")
    note_id = repo.insert_note(conn, client_id, paper["id"], text_, actor)
    audit_hooks.log_action(conn, client_id, actor, "note", "audit_paper_note", note_id, None, {"paper_id": paper["id"], "note": text_})
    return note_id


# ------------------------------------------------------------------------------------------------------------------- review / sign-off


def _move(conn: Connection, client_id: Any, paper_id: Any, new: PaperStatus, action: str, actor: str) -> None:
    actor = require_actor(actor)
    paper = _require_paper(conn, client_id, paper_id, lock=True)
    try:
        rules.check_move(paper["status"], new.value)
    except rules.PaperError as e:
        raise _raise(e) from None
    repo.set_status(conn, paper["id"], new.value)
    audit_hooks.log_action(conn, client_id, actor, action, "audit_working_paper", paper["id"], {"status": paper["status"]}, {"status": new.value})


def send_to_review(conn: Connection, client_id: Any, paper_id: Any, actor: str) -> None:
    _move(conn, client_id, paper_id, PaperStatus.IN_REVIEW, "review", actor)


def reopen(conn: Connection, client_id: Any, paper_id: Any, actor: str) -> None:
    _move(conn, client_id, paper_id, PaperStatus.OPEN, "reopen", actor)


def sign_off(conn: Connection, client_id: Any, paper_id: Any, conclusion: str | None, actor: str) -> dict:
    """W-05: needs in_review, every exception decided, and the reviewer's own conclusion; terminal."""
    actor = require_actor(actor)
    paper = _require_paper(conn, client_id, paper_id, lock=True)
    try:
        rules.check_sign_off(paper["status"], repo.item_statuses(conn, paper["id"]), conclusion)
    except rules.PaperError as e:
        raise _raise(e) from None
    text_ = conclusion.strip()  # type: ignore[union-attr]
    signed_at = repo.sign_off(conn, paper["id"], text_, actor)
    audit_hooks.log_action(conn, client_id, actor, "sign_off", "audit_working_paper", paper["id"], _snapshot(paper),
                           {"status": "signed_off", "conclusion": text_, "signed_off_by": actor, "signed_off_at": signed_at})
    return {"ok": True, "signed_off_at": signed_at}


# ----------------------------------------------------------------------------------------------------------------------------- sampling


def draw(method: str, items: list[tuple[str, Decimal | None]], *, seed: Any, size: Any = None, threshold: Any = None, rest_size: Any = None,
         start: Any = None) -> tuple[list[str], dict]:
    """Pure dispatch used by the stored sample and the preview. Returns (ids, params). Raises ServiceError sample_invalid."""
    try:
        sampling.check_seed(seed)
        ids = [i for i, _ in items]
        if method == SampleMethod.RANDOM.value:
            return sampling.random_sample(ids, _need(size, "size"), seed), {"size": size}
        if method == SampleMethod.SYSTEMATIC.value:
            n = _need(size, "size")
            chosen = sampling.systematic_sample(ids, n, seed, start)
            return chosen, {"size": n, "interval": len(ids) // n, "start": sorted(str(i) for i in ids).index(chosen[0])}
        if method == SampleMethod.VALUE.value:
            if threshold is None:
                raise sampling.SamplingError("A value sample needs a threshold amount.")
            limit = parse_amount(threshold)
            rest = 0 if rest_size is None else rest_size
            return sampling.value_sample(items, limit, rest, seed), {"threshold": str(limit), "rest_size": rest}
    except MoneyError as e:
        raise ServiceError("sample_invalid", f"The threshold is not a valid amount: {e}") from None
    except sampling.SamplingError as e:
        raise ServiceError("sample_invalid", e.message) from None
    raise ServiceError("sample_invalid", "The sampling method must be random, systematic or value.")


def _need(value: Any, name: str) -> int:
    if value is None:
        raise sampling.SamplingError(f"A {name} is needed for this sampling method.")
    return value


def preview(items: list[tuple[str, Decimal | None]], method: str, **kw: Any) -> list[str]:
    return draw(method, items, **kw)[0]


def sample(conn: Connection, client_id: Any, paper_id: Any, method: str, actor: str, **kw: Any) -> dict:
    """W-02: draw and store a sample (method, seed, parameters, ids). A new sample replaces the old one until sign-off (logged old and new)."""
    actor = require_actor(actor)
    paper = _require_paper(conn, client_id, paper_id, lock=True)
    try:
        rules.check_sample_allowed(paper["status"])
    except rules.PaperError as e:
        raise _raise(e) from None
    run = repo.get_run(conn, client_id, paper["run_id"])
    pop, _ = _population(conn, run, paper["check_id"])  # type: ignore[arg-type]
    if method == SampleMethod.VALUE.value:
        items = [(i, pop.amounts.get(i)) for i in pop.ids]
    else:
        items = [(i, None) for i in pop.ids]
    ids, params = draw(method, items, **kw)
    params["population_source"] = pop.source
    repo.set_sample(conn, paper["id"], method=method, seed=kw["seed"], params=params, ids=ids)
    audit_hooks.log_action(conn, client_id, actor, "sample", "audit_working_paper", paper["id"], _snapshot(paper),
                           {"sample_method": method, "sample_seed": kw["seed"], "sample_params": params, "sample_ids": ids})
    return {"method": method, "seed": kw["seed"], "params": params, "ids": ids, "population_count": pop.count,
            "population_digest": pop.digest}

