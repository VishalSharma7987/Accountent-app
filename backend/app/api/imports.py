"""Excel voucher import endpoints (docs/API_CONTRACT.md, "Excel import").

Needs app/api/deps.py (get_conn, get_actor), which is written in step 1.7: the router is included in app/main.py
after both steps are merged.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn
from app.importers.voucher_template import build_template
from app.services import voucher_import


def _allocations(items) -> list[dict]:
    return [
        {
            "line_no": a.line_no, "row": a.row, "kind": a.kind, "bill_ref": a.bill_ref, "amount": a.amount,
            "due_date": a.due_date.isoformat() if a.due_date else None, "auto": a.auto,
        }
        for a in items
    ]


router = APIRouter(prefix="/clients/{client_id}/imports/vouchers", tags=["imports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Conn = Annotated[Connection, Depends(get_conn)]
Actor = Annotated[str, Depends(get_actor)]
Upload = Annotated[UploadFile, File()]


@router.get("/template")
def download_template(client_id: str) -> Response:
    return Response(
        content=build_template(),
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="voucher_import_template.xlsx"'},
    )


@router.post("/dry-run")
def dry_run(client_id: str, file: Upload, conn: Conn) -> dict:
    result = voucher_import.dry_run(conn, client_id, file.file.read())
    return {
        "vouchers": [
            {
                "ref_id": v.ref_id,
                "first_row": v.first_row,
                "status": v.status,
                "errors": [
                    {"rule_id": e.rule_id, "message": e.message, "line_no": e.line_no, "row": e.row} for e in v.errors
                ],
                "allocations": _allocations(v.allocations),
            }
            for v in result.vouchers
        ],
        "ok_count": result.ok_count,
        "error_count": result.error_count,
    }


@router.post("/commit")
def commit(client_id: str, file: Upload, conn: Conn, actor: Actor, ref_ids: Annotated[str, Form()] = "") -> dict:
    chosen = [r.strip() for r in ref_ids.split(",") if r.strip()]
    result = voucher_import.commit(conn, client_id, file.file.read(), chosen, actor=actor)
    return {
        "created": [
            {"ref_id": c.ref_id, "voucher_id": str(c.voucher_id), "allocations": _allocations(c.allocations)}
            for c in result.created
        ],
        "skipped": [{"ref_id": s.ref_id, "reason": s.reason} for s in result.skipped],
    }
