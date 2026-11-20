"""Approval queue (docs/PHASE7_API_CONTRACT.md "Approval queue", package F). Accepting never approves or posts a voucher (D-62)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import money
from app.api.schemas_queue import AcceptCleanIn, AcceptIn, EditFieldsIn, RejectIn
from app.services import approval_queue
from app.services.errors import ServiceError

router = APIRouter(tags=["approval-queue"])


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _sid(value) -> str | None:
    return None if value is None else str(value)


def _row(i: dict) -> dict:
    return {
        "id": str(i["id"]), "kind": i["kind"], "status": i["status"], "document_id": str(i["document_id"]),
        "document_name": i["original_filename"], "summary": i["summary"], "blocking_count": i["blocking_count"],
        "warning_count": i["warning_count"], "draft_voucher_id": _sid(i["draft_voucher_id"]), "reviewer": i["reviewer"],
        "created_at": _iso(i["created_at"]),
    }


def _draft(d: dict | None) -> dict | None:
    if d is None:
        return None
    return {"id": str(d["id"]), "status": d["status"], "voucher_type": d["voucher_type"], "voucher_date": _iso(d["voucher_date"]),
            "voucher_number": d["voucher_number"], "reference_no": d["reference_no"], "narration": d["narration"],
            "lines": [{"line_no": x["line_no"], "ledger_id": str(x["ledger_id"]), "ledger_name": x["name"],
                       "debit": money(x["debit"]), "credit": money(x["credit"])} for x in d["lines"]]}


def _history(h: dict) -> dict:
    return {"id": h["id"], "actor": h["actor"], "action": h["action"], "old": h["old_data"], "new": h["new_data"],
            "at": _iso(h["created_at"])}


def _detail(d: dict) -> dict:
    cid = str(d["client_id"])
    return {
        **_row(d),
        "document": {"id": str(d["document_id"]), "content_type": d["content_type"], "page_count": d["page_count"],
                     "download_url": f"/clients/{cid}/documents/{d['document_id']}/download"},
        "original": d["original"], "current": d["current"], "findings": d["findings"], "draft_voucher": _draft(d["draft_voucher"]),
        "acknowledged": d["acknowledged"] or [], "history": [_history(h) for h in d["history"]],
        "accepted_by": d["accepted_by"], "accepted_at": _iso(d["accepted_at"]), "rejected_by": d["rejected_by"],
        "rejected_at": _iso(d["rejected_at"]), "reject_reason": d["reject_reason"],
    }


@router.get("/clients/{client_id}/queue")
def list_queue(client_id: str, status: str | None = Query(default=None), kind: str | None = Query(default=None),
               has_blocking: bool | None = Query(default=None), conn: Connection = Depends(get_conn)):
    return [_row(i) for i in approval_queue.list_items(conn, parse_id(client_id, "Client"), status=status, kind=kind,
                                                       has_blocking=has_blocking)]


@router.post("/clients/{client_id}/queue/accept-clean")
def accept_clean(client_id: str, body: AcceptCleanIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return approval_queue.accept_clean(conn, parse_id(client_id, "Client"), [parse_id(i, "Queue item") for i in body.ids], actor=actor)


@router.get("/clients/{client_id}/queue/{item_id}")
def get_queue_item(client_id: str, item_id: str, conn: Connection = Depends(get_conn)):
    return _detail(approval_queue.get_detail(conn, parse_id(client_id, "Client"), parse_id(item_id, "Queue item")))


@router.post("/clients/{client_id}/queue/{item_id}/claim")
def claim(client_id: str, item_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    approval_queue.claim(conn, parse_id(client_id, "Client"), parse_id(item_id, "Queue item"), actor=actor)
    return {"ok": True}


@router.post("/clients/{client_id}/queue/{item_id}/release")
def release(client_id: str, item_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    approval_queue.release(conn, parse_id(client_id, "Client"), parse_id(item_id, "Queue item"), actor=actor)
    return {"ok": True}


@router.put("/clients/{client_id}/queue/{item_id}/fields")
def edit_fields(client_id: str, item_id: str, body: EditFieldsIn, conn: Connection = Depends(get_conn),
                actor: str = Depends(get_actor)):
    if (body.edits is None) == (body.payload is None):
        raise ServiceError("invalid_request", "Send either `edits` or a whole `payload`.")
    out = approval_queue.edit_fields(
        conn, parse_id(client_id, "Client"), parse_id(item_id, "Queue item"),
        edits=None if body.edits is None else [(e.field_path, e.value) for e in body.edits], payload=body.payload, actor=actor)
    return {"findings": [f.as_dict() for f in out.findings], "draft_voucher_id": _sid(out.draft_voucher_id), "status": out.status}


@router.post("/clients/{client_id}/queue/{item_id}/accept")
def accept(client_id: str, item_id: str, body: AcceptIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    out = approval_queue.accept(conn, parse_id(client_id, "Client"), parse_id(item_id, "Queue item"),
                                acknowledge=[a.model_dump() for a in body.acknowledge], learn=body.learn, actor=actor)
    return {"ok": True, "draft_voucher_id": str(out.draft_voucher_id), "learned": out.learned}


@router.post("/clients/{client_id}/queue/{item_id}/reject")
def reject(client_id: str, item_id: str, body: RejectIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    approval_queue.reject(conn, parse_id(client_id, "Client"), parse_id(item_id, "Queue item"), reason=body.reason, actor=actor)
    return {"ok": True}
