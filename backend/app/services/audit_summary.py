"""Plain-language AI summary of audit exceptions (Phase 8, package F; W-08).

A SUGGESTION only. The findings of a run (optionally one check, or the check of one working paper) are turned into a fixed, masked prompt and
sent through `llm_gateway` (purpose `audit_summary`; the client's AI switch is required; the call is stored by the gateway whatever happens).
The model may only restate; Python then checks the text (`prompts_audit.check_summary`): every number and identifier it quotes must exist in the
findings that were sent and it must not state a conclusion or opinion. A summary that fails is NOT stored (status `rejected`, the problems are
listed); a valid one is inserted into `audit_ai_summaries` (insert only, `is_suggestion` true). Nothing here writes to a paper's conclusion, a
paper item or a finding, and nothing writes to the books.

The exact findings summarised are recorded twice: the gateway stores the masked prompt (which lists them) on the linked `llm_calls` row, and the
audit_log entry of the summary lists the finding ids and the check filter. Expected failures are RESULTS, not exceptions, so the stored
gateway row commits (Phase 7 convention); a bad request (unknown run, nothing to summarise) raises ServiceError.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from app.ai import prompts_audit as prompts
from app.ai.llm import LlmClient
from app.services import audit_hooks, llm_gateway, queries
from app.services.errors import ServiceError, require_actor

_SEVERITY_RANK = "CASE severity WHEN 'error' THEN 0 WHEN 'review' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END"


@dataclass
class SummaryResult:
    status: str                       # ok | blocked | error | rejected
    message: str
    id: Any = None
    summary_text: str | None = None
    is_suggestion: bool = True
    llm_call_id: Any = None
    reason: str | None = None
    problems: list[str] = field(default_factory=list)


def _run(conn: Connection, client_id: Any, run_id: Any) -> dict:
    row = conn.execute(text("SELECT id, check_ids FROM audit_runs WHERE id = :r AND client_id = :c"),
                       {"r": run_id, "c": client_id}).mappings().first()
    if row is None:
        raise ServiceError("not_found", "Audit run not found.")
    return dict(row)


def _date(value: Any) -> str | None:
    return None if value is None else value.strftime("%d-%m-%Y")


def summarise(conn: Connection, client_id: Any, run_id: Any, *, actor: str, paper_id: Any = None, check_id: str | None = None,
              llm_client: LlmClient | None = None) -> SummaryResult:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    _run(conn, client_id, run_id)
    if paper_id is not None:
        paper = conn.execute(text("SELECT run_id, check_id FROM audit_working_papers WHERE id = :p AND client_id = :c"),
                             {"p": paper_id, "c": client_id}).mappings().first()
        if paper is None or paper["run_id"] != run_id:
            raise ServiceError("not_found", "Working paper not found for this run.")
        if check_id is not None and check_id != paper["check_id"]:
            raise ServiceError("invalid_selection", "The check does not match the check of the working paper.")
        check_id = paper["check_id"]
    where = "run_id = :r AND client_id = :c" + (" AND check_id = :k" if check_id else "")
    params = {"r": run_id, "c": client_id, **({"k": check_id} if check_id else {})}
    total = conn.execute(text(f"SELECT count(*) FROM audit_findings WHERE {where}"), params).scalar_one()
    if total == 0:
        raise ServiceError("invalid_selection", "There are no findings to summarise for this selection.")
    rows = conn.execute(
        text(f"SELECT id, check_id, severity, message, finding_date, amount, subject_ref FROM audit_findings WHERE {where} "
             f"ORDER BY {_SEVERITY_RANK}, check_id, finding_date NULLS LAST, finding_key LIMIT :n"),
        {**params, "n": prompts.MAX_FINDINGS}).mappings().all()
    findings = [prompts.SummaryFinding(str(r["id"]), r["check_id"], r["severity"], r["message"], _date(r["finding_date"]), r["amount"],
                                       r["subject_ref"]) for r in rows]
    user = prompts.build_user(findings, total)

    result = llm_gateway.call(conn, client_id=client_id, purpose="audit_summary", system=prompts.SYSTEM, user=user,
                              prompt_version=prompts.PROMPT_VERSION, actor=actor, llm_client=llm_client, max_tokens=1500)
    if result.status == "blocked":
        return SummaryResult("blocked", result.message, llm_call_id=result.call_id, reason=result.reason)
    if not result.ok:
        return SummaryResult("error", result.message, llm_call_id=result.call_id, reason=result.reason)
    summary = (result.data or {}).get("summary")
    if not isinstance(summary, str):
        return SummaryResult("rejected", "The answer has no text under the key 'summary'; nothing was stored.", llm_call_id=result.call_id,
                             reason="invalid_shape", problems=["The answer has no text under the key 'summary'."])
    summary = summary.strip()
    problems = prompts.check_summary(summary, user)
    detail = {"run_id": str(run_id), "paper_id": None if paper_id is None else str(paper_id), "check_id": check_id,
              "llm_call_id": str(result.call_id), "finding_ids": [f.id for f in findings], "findings_total": total}
    if problems:
        audit_hooks.log_action(conn, client_id, actor, "summary_rejected", "audit_ai_summary", result.call_id, None,
                               {**detail, "problems": problems})
        return SummaryResult("rejected", "The model's summary quotes something that is not in the findings or states a conclusion, so it was "
                                         "not stored. Read the findings themselves.", llm_call_id=result.call_id,
                             reason="unverified_text", problems=problems)
    new_id = conn.execute(
        text("INSERT INTO audit_ai_summaries (client_id, run_id, paper_id, llm_call_id, summary_text, is_suggestion, created_by) "
             "VALUES (:c, :r, :p, :l, :t, true, :by) RETURNING id"),
        {"c": client_id, "r": run_id, "p": paper_id, "l": result.call_id, "t": summary, "by": actor}).scalar_one()
    audit_hooks.log_action(conn, client_id, actor, "create", "audit_ai_summary", new_id, None, {**detail, "is_suggestion": True})
    return SummaryResult("ok", "Summary stored as a suggestion. It is not a conclusion; the reviewer writes the conclusion.", id=new_id,
                         summary_text=summary, llm_call_id=result.call_id)


def list_summaries(conn: Connection, client_id: Any, run_id: Any) -> list[dict]:
    queries.require_client(conn, client_id)
    _run(conn, client_id, run_id)
    rows = conn.execute(
        text("SELECT id, run_id, paper_id, llm_call_id, summary_text, is_suggestion, created_by, created_at FROM audit_ai_summaries "
             "WHERE run_id = :r AND client_id = :c ORDER BY created_at, id"), {"r": run_id, "c": client_id}).mappings().all()
    return [dict(r) for r in rows]
