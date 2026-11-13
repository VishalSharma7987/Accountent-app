"""Invoice-mode endpoints (Phase 3, package B): the preview of the lines the engine builds. Draft create / update / read
use the ordinary voucher endpoints (api/vouchers.py) with the optional `gst` block."""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.schemas import VoucherIn
from app.api.schemas_gst_invoices import GstPreviewOut
from app.api.vouchers import draft_from_body
from app.engine.models import ValidationError
from app.services import gst_invoices

router = APIRouter(tags=["gst"])


@router.post("/clients/{client_id}/vouchers/gst-preview", response_model=GstPreviewOut)
def gst_preview(client_id: str, body: VoucherIn, conn: Connection = Depends(get_conn)):
    """The ledger lines and tax the engine would build; nothing is saved. Rule errors are listed (status 200)."""
    if body.gst is None:
        return _out([], None, [ValidationError("G-14", "The preview needs the invoice block (gst).")])
    draft, bad = draft_from_body(parse_id(client_id, "Client"), body)
    if bad:
        return _out([], None, bad)
    out = gst_invoices.preview(conn, draft)
    return _out(out["lines"], out["gst"], out["errors"])


def _out(lines: list, gst: dict | None, errors: list[ValidationError]) -> GstPreviewOut:
    return GstPreviewOut(
        lines=lines, gst=gst,
        errors=[{"rule_id": e.rule_id, "message": e.message, "line_no": e.line_no} for e in errors],
    )
