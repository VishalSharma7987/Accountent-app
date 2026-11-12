"""Bank statement endpoints (docs/PHASE2_API_CONTRACT.md, "Bank statements")."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import money
from app.api.schemas_bank import (
    BankFormatIn,
    BankFormatOut,
    FormatCreated,
    PreviewOut,
    PreviewRow,
    Problem,
    StatementCreated,
    StatementLineOut,
    StatementOut,
)
from app.services import bank
from app.services.errors import ServiceError

router = APIRouter(tags=["bank"])

Conn = Annotated[Connection, Depends(get_conn)]
Actor = Annotated[str, Depends(get_actor)]
Upload = Annotated[UploadFile, File()]
PREVIEW_ROWS = 20


def _opt(value: object) -> str | None:
    return None if value is None else money(value)


@router.get("/clients/{client_id}/bank-formats", response_model=list[BankFormatOut])
def list_formats(client_id: str, conn: Conn):
    return [BankFormatOut(id=f.id, name=f.name, mapping=f.mapping)
            for f in bank.list_formats(conn, parse_id(client_id, "Client"))]


@router.post("/clients/{client_id}/bank-formats", status_code=201, response_model=FormatCreated)
def create_format(client_id: str, body: BankFormatIn, conn: Conn, actor: Actor):
    format_id = bank.save_format(conn, parse_id(client_id, "Client"), body.name, body.mapping, actor=actor)
    return FormatCreated(format_id=format_id)


@router.post("/clients/{client_id}/bank-statements/preview", response_model=PreviewOut)
def preview(
    client_id: str, file: Upload, conn: Conn, format_id: Annotated[str | None, Form()] = None,
    mapping: Annotated[str | None, Form()] = None, opening_balance: Annotated[str | None, Form()] = None,
    closing_balance: Annotated[str | None, Form()] = None,
):
    parsed_mapping = None
    if mapping:
        try:
            parsed_mapping = json.loads(mapping)
        except ValueError:
            raise ServiceError("invalid_mapping", "The mapping is not valid JSON.") from None
    parsed = bank.preview_statement(
        conn, parse_id(client_id, "Client"), file.file.read(),
        format_id=parse_id(format_id, "Bank format") if format_id else None, mapping=parsed_mapping,
        opening_balance=opening_balance, closing_balance=closing_balance,
    )
    return PreviewOut(
        rows=[PreviewRow(row=x.row, txn_date=x.txn_date, description=x.description, reference=x.reference,
                         debit=money(x.debit), credit=money(x.credit), balance=_opt(x.balance))
              for x in parsed.lines[:PREVIEW_ROWS]],
        count=len(parsed.lines), opening_balance=_opt(parsed.opening_balance),
        closing_balance=_opt(parsed.closing_balance),
        problems=[Problem(row=p.row, message=p.message) for p in parsed.problems],
    )


@router.post("/clients/{client_id}/bank-statements", status_code=201, response_model=StatementCreated)
def import_statement(
    client_id: str, file: Upload, bank_ledger_id: Annotated[str, Form()], format_id: Annotated[str, Form()],
    conn: Conn, actor: Actor, opening_balance: Annotated[str | None, Form()] = None,
    closing_balance: Annotated[str | None, Form()] = None,
):
    result = bank.import_statement(
        conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Bank ledger"),
        parse_id(format_id, "Bank format"), file.filename or "statement", file.file.read(),
        opening_balance, closing_balance, actor=actor,
    )
    return StatementCreated(statement_id=result.statement_id, lines=result.lines,
                            opening_balance=money(result.opening_balance), closing_balance=money(result.closing_balance))


@router.get("/clients/{client_id}/bank-statements", response_model=list[StatementOut])
def list_statements(client_id: str, conn: Conn, bank_ledger_id: str | None = None):
    rows = bank.list_statements(
        conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Bank ledger") if bank_ledger_id else None
    )
    return [StatementOut(id=r.id, bank_ledger_id=r.bank_ledger_id, file_name=r.file_name, period_from=r.period_from,
                         period_to=r.period_to, opening_balance=money(r.opening_balance),
                         closing_balance=money(r.closing_balance), line_count=r.line_count,
                         matched_count=r.matched_count) for r in rows]


@router.get("/bank-statements/{statement_id}/lines", response_model=list[StatementLineOut])
def statement_lines(statement_id: str, conn: Conn):
    rows = bank.statement_lines(conn, parse_id(statement_id, "Bank statement"))
    return [StatementLineOut(id=r.id, line_no=r.line_no, txn_date=r.txn_date, description=r.description,
                             reference=r.reference, debit=money(r.debit), credit=money(r.credit),
                             balance=_opt(r.balance), match_id=r.match_id) for r in rows]


@router.delete("/bank-statements/{statement_id}", status_code=204)
def delete_statement(statement_id: str, conn: Conn, actor: Actor) -> Response:
    bank.delete_statement(conn, parse_id(statement_id, "Bank statement"), actor=actor)
    return Response(status_code=204)
