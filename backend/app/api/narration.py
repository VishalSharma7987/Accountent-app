"""Bank narration -> ledger suggestions (docs/PHASE7_API_CONTRACT.md, package F). A suggestion never books anything (D-44)."""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_queue import RuleActiveIn
from app.services import narration

router = APIRouter(tags=["narration"])


def get_llm_client():
    """The model client for narration suggestions. None = the gateway builds the real one (key from config). Tests replace this."""
    return


def _out(res: narration.SuggestionResult) -> dict:
    s = res.suggestion
    return {
        "line_id": str(res.line_id), "status": res.status, "message": res.message,
        "suggestion": None if s is None else {
            "id": str(s.id), "source": s.source, "ledger_id": str(s.ledger_id), "ledger_name": s.ledger_name, "reason": s.reason,
            "confidence": None if s.confidence is None else f"{s.confidence:.4f}"},
        "ambiguous": [{"ledger_id": str(c["ledger_id"]), "ledger_name": c["ledger_name"], "count": c["count"]} for c in res.ambiguous],
    }


@router.get("/clients/{client_id}/bank/lines/{line_id}/suggestion")
def get_suggestion(client_id: str, line_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor),
                   llm_client=Depends(get_llm_client)):
    return _out(narration.suggest(conn, parse_id(client_id, "Client"), parse_id(line_id, "Bank statement line"), actor=actor,
                                  llm_client=llm_client))


@router.post("/clients/{client_id}/bank/suggestions/{suggestion_id}/accept")
def accept_suggestion(client_id: str, suggestion_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    out = narration.accept_suggestion(conn, parse_id(client_id, "Client"), parse_id(suggestion_id, "Suggestion"), actor=actor)
    return {"ok": True, "learned": out.learned}


@router.post("/clients/{client_id}/bank/suggestions/{suggestion_id}/reject")
def reject_suggestion(client_id: str, suggestion_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    narration.reject_suggestion(conn, parse_id(client_id, "Client"), parse_id(suggestion_id, "Suggestion"), actor=actor)
    return {"ok": True}


@router.get("/clients/{client_id}/ai/narration-rules")
def list_rules(client_id: str, conn: Connection = Depends(get_conn)):
    return [{"id": str(r["id"]), "direction": r["direction"], "narration_key": r["narration_key"], "ledger_id": str(r["ledger_id"]),
             "ledger_name": r["ledger_name"], "approved_count": r["approved_count"], "is_active": r["is_active"]}
            for r in narration.list_rules(conn, parse_id(client_id, "Client"))]


@router.put("/clients/{client_id}/ai/narration-rules/{rule_id}")
def set_rule(client_id: str, rule_id: str, body: RuleActiveIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    narration.set_rule_active(conn, parse_id(client_id, "Client"), parse_id(rule_id, "Narration rule"), body.is_active, actor=actor)
    return {"ok": True}
