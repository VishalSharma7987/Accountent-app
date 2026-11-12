"""Step 2.7: reconciliation service and API on the mini case (committed once per module by the `books` fixture).

Bank ledger = HDFC Bank. Book side (hand-listed from books.py): opening 3,00,000.00 Dr;
  10-04 Dr 30,000.00 (receipt from Rahul), 12-04 Cr 15,000.00 (paid Sharma), 15-04 Dr 10,000.00 (cash deposited).
  Books balance on 30-04 = 3,00,000 + 30,000 - 15,000 + 10,000 = 3,25,000.00 Dr.
Statement (April): opening 3,00,000.00; credit 30,000.00 on 11-04; debit 15,000.00 on 18-04; credit 10,000.00 on
  15-04; debit 118.00 'SMS CHARGES' on 25-04. Closing = 3,00,000 + 30,000 - 15,000 + 10,000 - 118 = 3,24,882.00.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from recon_helpers import add_statement
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app
from app.services import reconciliation as svc
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}
AS_ON = date(2026, 4, 30)
STATEMENT = [
    (date(2026, 4, 11), "NEFT RAHUL ENTERPRISES", "UTR1", "0.00", "30000.00"),
    (date(2026, 4, 18), "CHQ PAID SHARMA", "000321", "15000.00", "0.00"),
    (date(2026, 4, 15), "CASH DEPOSIT", None, "0.00", "10000.00"),
    (date(2026, 4, 25), "SMS CHARGES Q1", None, "118.00", "0.00"),
]


@pytest.fixture
def b(books):
    return books[0]


@pytest.fixture
def world(svc_conn, b):
    sid, ids = add_statement(svc_conn, b.client_id, b.ids["HDFC Bank"], "300000.00", "324882.00", STATEMENT)
    return b.client_id, b.ids["HDFC Bank"], ids


def audit_actions(conn, client_id, entity):
    return [r[0] for r in conn.execute(
        text("SELECT action FROM audit_log WHERE client_id = :c AND entity = :e ORDER BY id"), {"c": client_id, "e": entity})]


def test_R03_auto_match_then_BRS_ties_with_the_bank_charge_only_in_the_bank(svc_conn, world):
    client, bank, lines = world
    summary = svc.auto_match(svc_conn, client, bank, AS_ON, actor="tester")
    assert (summary.matched_groups, summary.matched_bank_lines, summary.matched_book_items, summary.suggestions_left) == (3, 3, 3, 0)
    left = svc.unmatched(svc_conn, client, bank, AS_ON)
    assert [x.id for x in left.bank] == [lines[3]] and left.book == []
    r = svc.brs(svc_conn, client, bank, AS_ON)
    assert r.balance_per_books == Decimal("325000.00")
    assert r.balance_per_bank == Decimal("324882.00")
    assert [(i.description, i.amount) for i in r.bank_only_debits] == [("SMS CHARGES Q1", Decimal("118.00"))]
    assert r.issued_not_presented == [] and r.deposited_not_cleared == [] and r.bank_only_credits == []
    assert r.computed_bank_balance == Decimal("324882.00") and r.difference == Decimal("0.00") and r.ties is True
    # a second run finds nothing new
    again = svc.auto_match(svc_conn, client, bank, AS_ON, actor="tester")
    assert again.matched_groups == 0
    assert audit_actions(svc_conn, client, "recon_match") == ["match", "match", "match"]
    assert svc_conn.execute(text("SELECT count(*) FROM recon_matches WHERE method = 'auto'")).scalar_one() == 3


def test_R04_manual_match_refused_when_not_tied_and_R03_when_not_this_ledgers_line(svc_conn, world, books):
    client, bank, lines = world
    found = svc.unmatched(svc_conn, client, bank, AS_ON)
    k4 = next(x.id for x in found.book if x.amount == Decimal("30000.00"))
    k5 = next(x.id for x in found.book if x.amount == Decimal("15000.00"))
    with pytest.raises(ServiceError) as info:  # bank 10,000.00 deposit vs books 30,000.00 deposit
        svc.manual_match(svc_conn, client, bank, [lines[2]], [k4], [], actor="tester")
    assert info.value.code == "match_not_tied"
    assert info.value.message == (
        "R-04: The match does not tie: books 30,000.00 deposit and bank 10,000.00 deposit are not equal (difference 20,000.00)."
    )
    with pytest.raises(ServiceError) as info:  # opposite directions: Cr 15,000 book vs credit 30,000 bank
        svc.manual_match(svc_conn, client, bank, [lines[0]], [k5], [], actor="tester")
    assert info.value.code == "match_not_tied"
    # a line of another client's bank ledger is not acceptable
    other = books[1]
    _, other_lines = add_statement(svc_conn, other.client_id, other.ids["HDFC Bank"], "300000.00", "330000.00",
                                   [(date(2026, 4, 11), "x", None, "0.00", "30000.00")])
    with pytest.raises(ServiceError) as info:
        svc.manual_match(svc_conn, client, bank, [other_lines[0]], [k4], [], actor="tester")
    assert info.value.code == "match_invalid" and info.value.message.startswith("R-03")
    assert svc_conn.execute(text("SELECT count(*) FROM recon_matches WHERE client_id = :c"), {"c": client}).scalar_one() == 0

    match_id = svc.manual_match(svc_conn, client, bank, [lines[0]], [k4], [], " by hand ", actor="tester")
    with pytest.raises(ServiceError) as info:  # already matched
        svc.manual_match(svc_conn, client, bank, [lines[0]], [k4], [], actor="tester")
    assert info.value.code == "match_invalid" and "already matched" in info.value.message

    svc.unmatch(svc_conn, client, match_id, actor="checker")
    assert any(x.id == lines[0] for x in svc.unmatched(svc_conn, client, bank, AS_ON).bank)
    entries = svc_conn.execute(
        text("SELECT action, actor, old_data FROM audit_log WHERE client_id = :c AND entity = 'recon_match' ORDER BY id"),
        {"c": client}).all()
    assert [e[0] for e in entries] == ["match", "unmatch"]
    assert entries[1][1] == "checker" and entries[1][2]["bank_line_ids"] == [str(lines[0])] and entries[1][2]["note"] == "by hand"
    with pytest.raises(ServiceError) as info:
        svc.unmatch(svc_conn, client, match_id, actor="checker")
    assert info.value.code == "not_found"


def test_R05_no_statement_covering_the_date_and_opening_item_that_does_not_tie(svc_conn, b, world):
    client, bank, lines = world
    with pytest.raises(ServiceError) as info:
        svc.brs(svc_conn, client, bank, date(2026, 6, 30))
    assert info.value.code == "no_statement"
    assert info.value.message == "No bank statement of this bank ledger covers 30-06-2026. Import the statement first."

    # opening items: dated before the year; a cheque of 4,000.00 issued 28-03 and still not presented
    with pytest.raises(ServiceError) as info:
        svc.set_bank_opening_items(svc_conn, client, b.fy_id, bank, [
            {"kind": "issued_not_presented", "reference": "000900", "item_date": date(2026, 4, 2), "amount": "4000.00"}], actor="tester")
    assert info.value.code == "invalid_item"
    svc.set_bank_opening_items(svc_conn, client, b.fy_id, bank, [
        {"kind": "issued_not_presented", "reference": "000900", "item_date": date(2026, 3, 28), "amount": "4000.00"}], actor="tester")
    assert [(x["kind"], x["reference"], x["amount"]) for x in svc.get_bank_opening_items(svc_conn, client, b.fy_id, bank)] == [
        ("issued_not_presented", "000900", Decimal("4000.00"))]
    svc.auto_match(svc_conn, client, bank, AS_ON, actor="tester")
    r = svc.brs(svc_conn, client, bank, AS_ON)
    # the books' opening balance in this test data does not include that cheque, so: 3,25,000 + 4,000 - 118 = 3,28,882
    # against a bank balance of 3,24,882: difference -4,000.00
    assert [i.amount for i in r.issued_not_presented] == [Decimal("4000.00")]
    assert r.computed_bank_balance == Decimal("328882.00")
    assert r.difference == Decimal("-4000.00") and r.ties is False


def test_R03_bank_only_drafts_are_drafts_only_and_only_once(svc_conn, b, world):
    client, bank, lines = world
    charges = b.ids["Bank Charges"]
    cash = b.ids["Cash"]
    suggestions = svc.bank_only_suggestions(svc_conn, client, bank, AS_ON)
    assert [(s.bank_line_id, s.counter_ledger_id, s.counter_ledger_name) for s in suggestions] == [(lines[3], charges, "Bank Charges")]

    # a counter ledger that is cash breaks the Payment rule: rule error returned, nothing created
    bad = svc.draft_vouchers_for_bank_only(svc_conn, client, bank, [(lines[3], cash)], actor="tester")
    assert bad.created == [] and [e.rule_id for _, errs in bad.errors for e in errs] == ["V-08"]
    assert svc_conn.execute(text("SELECT count(*) FROM bank_line_drafts")).scalar_one() == 0

    done = svc.draft_vouchers_for_bank_only(svc_conn, client, bank, [(lines[3], charges)], actor="tester")
    assert done.errors == [] and len(done.created) == 1
    voucher_id = done.created[0][1]
    row = svc_conn.execute(text(
        "SELECT voucher_type, status, voucher_date, narration, reference_no, voucher_number FROM vouchers WHERE id = :v"),
        {"v": voucher_id}).one()
    assert tuple(row) == ("payment", "draft", date(2026, 4, 25), "SMS CHARGES Q1", None, None)
    vl = svc_conn.execute(text("SELECT ledger_id, debit, credit FROM voucher_lines WHERE voucher_id = :v ORDER BY line_no"),
                          {"v": voucher_id}).all()
    assert [(x[0], x[1], x[2]) for x in vl] == [(charges, Decimal("118.0000"), Decimal("0.0000")), (bank, Decimal("0.0000"), Decimal("118.0000"))]
    # the draft is not in the books, so the BRS still shows the charge as bank-only (nothing is matched yet here,
    # so the 18-04 withdrawal of 15,000.00 is bank-only too)
    assert [i.amount for i in svc.brs(svc_conn, client, bank, AS_ON).bank_only_debits] == [Decimal("15000.00"), Decimal("118.00")]
    with pytest.raises(ServiceError) as info:
        svc.draft_vouchers_for_bank_only(svc_conn, client, bank, [(lines[3], charges)], actor="tester")
    assert info.value.code == "already_drafted"
    assert svc.bank_only_suggestions(svc_conn, client, bank, AS_ON) == []
    # a deposit becomes a Receipt: Dr bank / Cr counter, with the bank reference as reference no
    receipt = svc.draft_vouchers_for_bank_only(svc_conn, client, bank, [(lines[0], charges)], actor="tester")
    rv = svc_conn.execute(text("SELECT voucher_type, reference_no FROM vouchers WHERE id = :v"), {"v": receipt.created[0][1]}).one()
    assert tuple(rv) == ("receipt", "UTR1")
    with pytest.raises(ServiceError) as info:  # a matched line cannot be drafted
        svc.auto_match(svc_conn, client, bank, AS_ON, actor="tester")
        svc.draft_vouchers_for_bank_only(svc_conn, client, bank, [(lines[1], charges)], actor="tester")
    assert info.value.code == "match_invalid"


# ======================================================================================================== API


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_API_reconciliation_flow(api, svc_conn, b, world):
    client, bank, lines = world
    base = f"/clients/{client}/reconciliation"
    r = api.get(f"{base}/{bank}/unmatched", params={"as_on": "2026-04-30"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["bank"]) == 4 and len(body["book"]) == 3
    thirty = next(x for x in body["bank"] if x["credit"] == "30000.00")
    assert thirty["debit"] == "0.00"
    k4 = next(x for x in body["book"] if x["debit"] == "30000.00")
    assert k4["opening_item_id"] is None and k4["voucher_number"] == "REC/2026-27/0001"

    r = api.post(f"{base}/{bank}/matches", json={"bank_line_ids": [str(lines[2])], "voucher_line_ids": [k4["voucher_line_id"]]}, headers=H)
    assert r.status_code == 409 and r.json()["code"] == "match_not_tied"
    r = api.post(f"{base}/{bank}/matches", json={"bank_line_ids": [thirty["line_id"]], "voucher_line_ids": [k4["voucher_line_id"]]}, headers=H)
    assert r.status_code == 201
    match_id = r.json()["match_id"]
    assert api.post(f"{base}/{bank}/auto-match", json={"as_on": "2026-04-30"}, headers=H).json() == {
        "matched_groups": 2, "matched_bank_lines": 2, "matched_book_items": 2, "suggestions_left": 0}
    assert api.post(f"{base}/{bank}/auto-match", json={"as_on": "2026-04-30"}).status_code == 400  # X-User required

    r = api.get(f"{base}/{bank}/brs", params={"as_on": "2026-04-30"})
    assert r.status_code == 200
    out = r.json()
    assert out["balance_per_books"] == {"amount": "325000.00", "side": "Dr"}
    assert out["balance_per_bank"] == {"amount": "324882.00", "side": "Dr"}
    assert out["bank_only_debits"] == [{"date": "2026-04-25", "reference": None, "description": "SMS CHARGES Q1", "amount": "118.00"}]
    assert out["difference"] == {"amount": "0.00", "side": None} and out["ties"] is True
    assert api.get(f"{base}/{bank}/brs", params={"as_on": "2026-07-01"}).json()["code"] == "no_statement"

    assert api.delete(f"{base}/matches/{match_id}", headers=H).status_code == 204
    assert api.delete(f"{base}/matches/{match_id}", headers=H).status_code == 404

    charges = b.ids["Bank Charges"]
    sug = api.get(f"{base}/{bank}/bank-only-suggestions", params={"as_on": "2026-04-30"}).json()
    assert [(s["bank_line_id"], s["counter_ledger_name"], s["amount"]) for s in sug] == [(str(lines[3]), "Bank Charges", "118.00")]
    r = api.post(f"{base}/{bank}/bank-only-drafts", json={"items": [{"bank_line_id": str(lines[3]), "counter_ledger_id": str(b.ids["Cash"])}]}, headers=H)
    assert r.status_code == 422 and r.json()["errors"][0]["rule_id"] == "V-08" and r.json()["errors"][0]["bank_line_id"] == str(lines[3])
    r = api.post(f"{base}/{bank}/bank-only-drafts", json={"items": [{"bank_line_id": str(lines[3]), "counter_ledger_id": str(charges)}]}, headers=H)
    assert r.status_code == 201 and r.json()["created"][0]["bank_line_id"] == str(lines[3])
    r = api.post(f"{base}/{bank}/bank-only-drafts", json={"items": [{"bank_line_id": str(lines[3]), "counter_ledger_id": str(charges)}]}, headers=H)
    assert r.status_code == 409 and r.json()["code"] == "already_drafted"

    url = f"/clients/{client}/financial-years/{b.fy_id}/bank-opening-items/{bank}"
    assert api.put(url, json={"items": [{"kind": "deposited_not_cleared", "item_date": "2026-03-30", "amount": "500.00"}]}, headers=H).json() == {"ok": True}
    got = api.get(url).json()["items"]
    assert [(x["kind"], x["reference"], x["item_date"], x["amount"]) for x in got] == [("deposited_not_cleared", None, "2026-03-30", "500.00")]
