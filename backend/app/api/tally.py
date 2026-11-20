"""Tally XML import and export (docs/PHASE7_API_CONTRACT.md, package B).

Upload the XML first with POST /documents (doc_type tally_xml). Reading and storing files goes through the documents package
(`services.documents.read_bytes` / `register`, private store); it is imported when a request arrives, so this module loads on
its own. Nothing here approves or posts a voucher.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_tally import ExportIn, ImportIn, MasterDecisionIn, QueueVouchersIn
from app.services import tally_export, tally_import

router = APIRouter(prefix="/clients/{client_id}/tally", tags=["tally"])

Conn = Annotated[Connection, Depends(get_conn)]
Actor = Annotated[str, Depends(get_actor)]


def get_store() -> Any:
    from app.api.documents import get_store as documents_store

    return documents_store()


Store = Annotated[Any, Depends(get_store)]


def _opt(value: str | None, what: str):
    return None if value is None else parse_id(value, what)


def _xml(conn: Connection, store: Any, client_id: Any, document_id: Any) -> bytes:
    from app.services import documents

    return documents.read_bytes(conn, store, client_id, document_id)


def _import_row(conn: Connection, client_id: Any, import_id: str) -> dict:
    return tally_import.get_import(conn, client_id, parse_id(import_id, "Tally import"))


@router.post("/imports", status_code=201)
def create_import(client_id: str, body: ImportIn, conn: Conn, actor: Actor, store: Store) -> dict:
    cid, did = parse_id(client_id, "Client"), parse_id(body.document_id, "Document")
    result = tally_import.import_xml(conn, cid, did, _xml(conn, store, cid, did), actor=actor)
    return {"import_id": result.import_id, "company_name": result.company_name, "report": result.report}


@router.get("/imports")
def list_imports(client_id: str, conn: Conn) -> list[dict]:
    return tally_import.list_imports(conn, parse_id(client_id, "Client"))


@router.get("/imports/{import_id}")
def get_import(client_id: str, import_id: str, conn: Conn) -> dict:
    row = tally_import.get_import(conn, parse_id(client_id, "Client"), parse_id(import_id, "Tally import"))
    return {"import_id": row["id"], "status": row["status"], "company_name": row["company_name"], "document_id": row["document_id"],
            "created_by": row["created_by"], "created_at": row["created_at"], "counts": row["counts"], "report": row["mapping_report"]}


@router.get("/masters")
def list_masters(client_id: str, conn: Conn, kind: str | None = None, decision: str | None = None) -> list[dict]:
    rows = tally_import.list_masters(conn, parse_id(client_id, "Client"), kind, decision)
    return [{"id": r["id"], "kind": r["kind"], "source_name": r["source_name"], "source_parent": r["source_parent"], "decision": r["decision"],
             "reason": r["reason"], "target_group_id": r["target_group_id"], "target_ledger_id": r["target_ledger_id"],
             "target_item_id": r["target_item_id"]} for r in rows]


@router.put("/masters/{master_id}")
def decide_master(client_id: str, master_id: str, body: MasterDecisionIn, conn: Conn, actor: Actor) -> dict:
    tally_import.set_master_decision(
        conn, parse_id(client_id, "Client"), parse_id(master_id, "Tally master"), decision=body.decision,
        target_group_id=_opt(body.target_group_id, "Group"), target_ledger_id=_opt(body.target_ledger_id, "Ledger"),
        target_item_id=_opt(body.target_item_id, "Item"), accept_nature_change=body.accept_nature_change, actor=actor)
    return {"ok": True}


@router.post("/imports/{import_id}/confirm-exact-matches")
def confirm_exact_matches(client_id: str, import_id: str, conn: Conn, actor: Actor) -> dict:
    return {"confirmed": tally_import.confirm_exact_matches(conn, parse_id(client_id, "Client"), parse_id(import_id, "Tally import"), actor=actor)}


@router.post("/imports/{import_id}/apply-masters")
def apply_masters(client_id: str, import_id: str, conn: Conn, actor: Actor, store: Store) -> dict:
    cid = parse_id(client_id, "Client")
    row = _import_row(conn, cid, import_id)
    return tally_import.apply_masters(conn, cid, row["id"], _xml(conn, store, cid, row["document_id"]), actor=actor)


@router.post("/imports/{import_id}/queue-vouchers")
def queue_vouchers(client_id: str, import_id: str, body: QueueVouchersIn, conn: Conn, actor: Actor, store: Store) -> dict:
    cid = parse_id(client_id, "Client")
    row = _import_row(conn, cid, import_id)
    result = tally_import.queue_vouchers(conn, cid, row["id"], _xml(conn, store, cid, row["document_id"]),
                                         financial_year_id=_opt(body.financial_year_id, "Financial year"), actor=actor)
    return {"queued": result.queued, "drafted": result.drafted, "needs_review": result.needs_review, "skipped": result.skipped}


def _store_document(store: Any):
    def store_document(conn: Connection, client_id: Any, doc_type: str, filename: str, data: bytes, actor: str) -> Any:
        from app.services import documents

        return documents.register(conn, store, client_id, data=data, filename=filename, doc_type=doc_type, actor=actor)["id"]

    return store_document


@router.post("/export", status_code=201)
def create_export(client_id: str, body: ExportIn, conn: Conn, actor: Actor, store: Store) -> dict:
    out = tally_export.export(
        conn, parse_id(client_id, "Client"), kind=body.kind, from_date=body.from_date, to_date=body.to_date,
        financial_year_id=_opt(body.financial_year_id, "Financial year"), posted_only=body.posted_only,
        store_document=_store_document(store), actor=actor)
    return {"export_id": out.export_id, "document_id": out.document_id, "master_count": out.master_count, "voucher_count": out.voucher_count,
            "warnings": out.warnings}


@router.get("/exports")
def list_exports(client_id: str, conn: Conn) -> list[dict]:
    return tally_export.list_exports(conn, parse_id(client_id, "Client"))
