from datetime import date

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut, money
from app.api.schemas_recon import (
    AutoMatchIn,
    AutoMatchOut,
    BankOnlySuggestionOut,
    BrsOut,
    DraftCreated,
    DraftsIn,
    DraftsOut,
    MatchCreated,
    MatchesOut,
    MatchIn,
    OpeningItemOut,
    OpeningItemsIn,
    OpeningItemsOut,
    UnmatchedOut,
    bank_out,
    book_out,
    brs_out,
    match_out,
    suggestion_out,
)
from app.services import reconciliation as svc

router = APIRouter(tags=["reconciliation"])
BASE = "/clients/{client_id}/reconciliation"


@router.get(BASE + "/{bank_ledger_id}/unmatched", response_model=UnmatchedOut)
def unmatched(client_id: str, bank_ledger_id: str, as_on: date, conn: Connection = Depends(get_conn)):
    u = svc.unmatched(conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"), as_on)
    return UnmatchedOut(bank=[bank_out(x) for x in u.bank], book=[book_out(x) for x in u.book],
                        suggestions=[suggestion_out(x) for x in u.suggestions])


@router.post(BASE + "/{bank_ledger_id}/auto-match", response_model=AutoMatchOut)
def auto_match(client_id: str, bank_ledger_id: str, body: AutoMatchIn, conn: Connection = Depends(get_conn),
               actor: str = Depends(get_actor)):
    s = svc.auto_match(
        conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"), body.as_on, actor=actor,
        date_window_days=svc.RECON_DATE_WINDOW_DAYS if body.date_window_days is None else body.date_window_days,
    )
    return AutoMatchOut(matched_groups=s.matched_groups, matched_bank_lines=s.matched_bank_lines,
                        matched_book_items=s.matched_book_items, suggestions_left=s.suggestions_left)


@router.post(BASE + "/{bank_ledger_id}/matches", response_model=MatchCreated, status_code=201)
def create_match(client_id: str, bank_ledger_id: str, body: MatchIn, conn: Connection = Depends(get_conn),
                 actor: str = Depends(get_actor)):
    match_id = svc.manual_match(
        conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"), body.bank_line_ids,
        body.voucher_line_ids, body.opening_item_ids, body.note, actor=actor,
    )
    return MatchCreated(match_id=match_id)


@router.get(BASE + "/{bank_ledger_id}/matches", response_model=MatchesOut)
def list_matches(client_id: str, bank_ledger_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    groups = svc.list_matches(conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"), as_on)
    return MatchesOut(matches=[match_out(g) for g in groups])


@router.delete(BASE + "/matches/{match_id}", status_code=204)
def delete_match(client_id: str, match_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.unmatch(conn, parse_id(client_id, "Client"), parse_id(match_id, "Match"), actor=actor)
    return Response(status_code=204)


@router.get(BASE + "/{bank_ledger_id}/brs", response_model=BrsOut)
def brs(client_id: str, bank_ledger_id: str, as_on: date, conn: Connection = Depends(get_conn)):
    return brs_out(svc.brs(conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"), as_on))


@router.get("/clients/{client_id}/financial-years/{fy_id}/bank-opening-items/{bank_ledger_id}",
            response_model=OpeningItemsOut)
def get_opening_items(client_id: str, fy_id: str, bank_ledger_id: str, conn: Connection = Depends(get_conn)):
    rows = svc.get_bank_opening_items(conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"),
                                      parse_id(bank_ledger_id, "Ledger"))
    return OpeningItemsOut(items=[
        OpeningItemOut(id=r["id"], kind=r["kind"], reference=r["reference"], item_date=r["item_date"],
                       amount=money(r["amount"])) for r in rows
    ])


@router.put("/clients/{client_id}/financial-years/{fy_id}/bank-opening-items/{bank_ledger_id}", response_model=OkOut)
def put_opening_items(client_id: str, fy_id: str, bank_ledger_id: str, body: OpeningItemsIn,
                      conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    svc.set_bank_opening_items(
        conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"), parse_id(bank_ledger_id, "Ledger"),
        [x.model_dump() for x in body.items], actor=actor,
    )
    return OkOut()


@router.get(BASE + "/{bank_ledger_id}/bank-only-suggestions", response_model=list[BankOnlySuggestionOut])
def bank_only_suggestions(client_id: str, bank_ledger_id: str, as_on: date, conn: Connection = Depends(get_conn)):
    rows = svc.bank_only_suggestions(conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"), as_on)
    return [BankOnlySuggestionOut(
        bank_line_id=x.bank_line_id, txn_date=x.txn_date, description=x.description, amount=money(x.amount),
        direction=x.direction, counter_ledger_id=x.counter_ledger_id, counter_ledger_name=x.counter_ledger_name,
        reason=x.reason) for x in rows]


@router.post(BASE + "/{bank_ledger_id}/bank-only-drafts", response_model=DraftsOut, status_code=201)
def bank_only_drafts(client_id: str, bank_ledger_id: str, body: DraftsIn, conn: Connection = Depends(get_conn),
                     actor: str = Depends(get_actor)):
    result = svc.draft_vouchers_for_bank_only(
        conn, parse_id(client_id, "Client"), parse_id(bank_ledger_id, "Ledger"),
        [(x.bank_line_id, x.counter_ledger_id) for x in body.items], actor=actor,
    )
    if result.errors:
        return JSONResponse(status_code=422, content={"errors": [
            {"rule_id": e.rule_id, "message": e.message, "line_no": e.line_no, "bank_line_id": str(bank_line_id)}
            for bank_line_id, errs in result.errors for e in errs
        ]})
    return DraftsOut(created=[DraftCreated(bank_line_id=b, voucher_id=v) for b, v in result.created])
