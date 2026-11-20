"""Plain-language AI summary of exceptions (docs/PHASE8_API_CONTRACT.md, package F). A suggestion only: nothing here concludes anything."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.services import audit_summary

router = APIRouter(tags=["audit_summary"])


class SummaryIn(BaseModel):
    paper_id: str | None = None
    check_id: str | None = None


def get_llm_client():
    """The model client for audit summaries. None = the gateway builds the real one (key from config). Tests replace this."""
    return


@router.post("/clients/{client_id}/audit/runs/{run_id}/summary")
def create_summary(client_id: str, run_id: str, body: SummaryIn | None = None, conn: Connection = Depends(get_conn),
                   actor: str = Depends(get_actor), llm_client=Depends(get_llm_client)):
    body = body or SummaryIn()
    res = audit_summary.summarise(
        conn, parse_id(client_id, "Client"), parse_id(run_id, "Audit run"), actor=actor,
        paper_id=parse_id(body.paper_id, "Working paper") if body.paper_id else None, check_id=body.check_id, llm_client=llm_client)
    out: dict = {"status": res.status, "message": res.message, "is_suggestion": True,
                 "llm_call_id": None if res.llm_call_id is None else str(res.llm_call_id)}
    if res.status == "ok":
        out.update(id=str(res.id), summary_text=res.summary_text)
    else:
        out.update(reason=res.reason)
        if res.problems:
            out["problems"] = res.problems
    return out


@router.get("/clients/{client_id}/audit/runs/{run_id}/summaries")
def list_summaries(client_id: str, run_id: str, conn: Connection = Depends(get_conn)):
    return [{"id": str(r["id"]), "run_id": str(r["run_id"]), "paper_id": None if r["paper_id"] is None else str(r["paper_id"]),
             "llm_call_id": str(r["llm_call_id"]), "summary_text": r["summary_text"], "is_suggestion": r["is_suggestion"],
             "created_by": r["created_by"], "created_at": r["created_at"].isoformat()}
            for r in audit_summary.list_summaries(conn, parse_id(client_id, "Client"), parse_id(run_id, "Audit run"))]
