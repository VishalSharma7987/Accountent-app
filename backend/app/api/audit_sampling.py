"""Sampling helpers (random / systematic / value) with recorded seeds (docs/PHASE8_API_CONTRACT.md, package E)."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_audit_papers import PreviewIn, PreviewOut, SampleIn, SampleStoredOut
from app.engine.money import MoneyError, parse_amount
from app.services import audit_papers as svc
from app.services.errors import ServiceError

router = APIRouter(tags=["audit_sampling"])


def _options(body: SampleIn) -> dict:
    return {"seed": body.seed, "size": body.size, "threshold": body.threshold, "rest_size": body.rest_size, "start": body.start}


@router.post("/clients/{client_id}/audit/papers/{paper_id}/sample", response_model=SampleStoredOut)
def sample_paper(client_id: str, paper_id: str, body: SampleIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return svc.sample(conn, parse_id(client_id, "Client"), parse_id(paper_id, "Working paper"), body.method, actor, **_options(body))


@router.post("/clients/{client_id}/audit/sampling/preview", response_model=PreviewOut)
def preview_sample(client_id: str, body: PreviewIn):
    """Pure: draws from the ids given in the body and stores nothing."""
    parse_id(client_id, "Client")
    try:
        amounts: dict[str, Decimal | None] = {k: parse_amount(v) for k, v in (body.amounts or {}).items()}
    except MoneyError as e:
        raise ServiceError("sample_invalid", f"An amount is not valid: {e}") from None
    items = [(i, amounts.get(i)) for i in body.ids]
    return {"ids": svc.preview(items, body.method, **_options(body))}
