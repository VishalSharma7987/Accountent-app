"""Excel and PDF export of every statement with ledger drill-down references (docs/PHASE6_API_CONTRACT.md, package E)."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.services import final_export

router = APIRouter(tags=["final-accounts"])


def _file(result: tuple[bytes, str, str]) -> Response:
    content, media, name = result
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/clients/{client_id}/final/export")
def export_statements(client_id: str, financial_year_id: str, format: str = "xlsx", statements: str | None = None,
                      layout: str | None = None, conn: Connection = Depends(get_conn)):
    return _file(final_export.export_statements(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"),
                                                format, statements, layout))


@router.get("/clients/{client_id}/final/export/{kind}")
def export_working(client_id: str, kind: str, financial_year_id: str, format: str = "xlsx", conn: Connection = Depends(get_conn)):
    """kind = register | depreciation | it-working | adjustments."""
    return _file(final_export.export_working(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), kind, format))
