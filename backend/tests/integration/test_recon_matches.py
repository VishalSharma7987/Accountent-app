"""Phase 2.1: GET .../reconciliation/{bank}/matches (service + API) on the mini case of test_reconciliation.py.

Statement lines (HDFC Bank): 11-04 credit 30,000.00 UTR1; 18-04 debit 15,000.00 chq 000321; 15-04 credit 10,000.00 cash
deposit; 25-04 debit 118.00 SMS charges. Books: 10-04 Dr 30,000.00 (receipt REC/2026-27/0001), 12-04 Cr 15,000.00,
15-04 Dr 10,000.00. Auto-match pairs the first three.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from recon_helpers import add_statement

from app.api.deps import get_conn
from app.main import app
from app.services import reconciliation as svc
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

D = Decimal
H = {"X-User": "tester"}
AS_ON = date(2026, 4, 30)
STATEMENT = [
    (date(2026, 4, 11), "NEFT RAHUL ENTERPRISES", "UTR1", "0.00", "30000.00"),
    (date(2026, 4, 18), "CHQ PAID SHARMA", "000321", "15000.00", "0.00"),
    (date(2026, 4, 15), "CASH DEPOSIT", None, "0.00", "10000.00"),
    (date(2026, 4, 25), "SMS CHARGES Q1", None, "118.00", "0.00"),
]


@pytest.fixture
def world(svc_conn, books):
    b = books[0]
    _, ids = add_statement(svc_conn, b.client_id, b.ids["HDFC Bank"], "300000.00", "324882.00", STATEMENT)
    return b, ids


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def by_total(groups):
    return sorted(groups, key=lambda g: g.total_bank)


def test_R03_no_matches_yet_gives_an_empty_list(svc_conn, world):
    b, _ = world
    assert svc.list_matches(svc_conn, b.client_id, b.ids["HDFC Bank"]) == []


def test_R03_matches_listed_with_bank_and_book_items_and_totals(svc_conn, world):
    b, lines = world
    bank = b.ids["HDFC Bank"]
    svc.auto_match(svc_conn, b.client_id, bank, AS_ON, actor="tester")
    got = by_total(svc.list_matches(svc_conn, b.client_id, bank))
    assert [(g.total_bank, g.total_book, g.method, g.created_by) for g in got] == [
        (D("-15000.00"), D("-15000.00"), "auto", "tester"),
        (D("10000.00"), D("10000.00"), "auto", "tester"),
        (D("30000.00"), D("30000.00"), "auto", "tester"),
    ]
    assert all(g.note.startswith("auto rule") for g in got)
    thirty = got[2]
    assert [(x.id, x.date, x.amount, x.direction, x.reference) for x in thirty.bank_items] == [
        (lines[0], date(2026, 4, 11), D("30000.00"), "deposit", "UTR1")]
    assert [(x.date, x.amount, x.direction, x.voucher_number, x.kind) for x in thirty.book_items] == [
        (date(2026, 4, 10), D("30000.00"), "deposit", "REC/2026-27/0001", "voucher_line")]
    # the SMS charge is unmatched: it appears in no match
    assert lines[3] not in [x.id for g in got for x in g.bank_items]


def test_R03_as_on_keeps_only_matches_with_an_item_dated_on_or_before_it(svc_conn, world):
    b, _ = world
    bank = b.ids["HDFC Bank"]
    svc.auto_match(svc_conn, b.client_id, bank, AS_ON, actor="tester")
    # 12-04: the 30,000 (book 10-04, bank 11-04) and the 15,000 payment (book 12-04) qualify; the 10,000 (15-04) not
    got = by_total(svc.list_matches(svc_conn, b.client_id, bank, date(2026, 4, 12)))
    assert [g.total_bank for g in got] == [D("-15000.00"), D("30000.00")]
    assert svc.list_matches(svc_conn, b.client_id, bank, date(2026, 4, 9)) == []


def test_R03_manual_match_with_note_and_opening_item_and_other_ledger_or_client_errors(svc_conn, world):
    b, _ = world
    bank = b.ids["HDFC Bank"]
    _, extra = add_statement(svc_conn, b.client_id, bank, "0.00", "500.00",
                             [(date(2026, 4, 2), "CHQ CLEARED", "CH77", "0.00", "500.00")], period=(date(2026, 4, 2), date(2026, 4, 2)))
    svc.set_bank_opening_items(svc_conn, b.client_id, b.fy_id, bank, [
        {"kind": "deposited_not_cleared", "reference": "CH77", "item_date": date(2026, 3, 30), "amount": "500.00"}], actor="tester")
    opening = svc.get_bank_opening_items(svc_conn, b.client_id, b.fy_id, bank)[0]["id"]
    match_id = svc.manual_match(svc_conn, b.client_id, bank, [extra[0]], [], [opening], " opening cheque ", actor="tester")
    (g,) = svc.list_matches(svc_conn, b.client_id, bank)
    assert (g.match_id, g.method, g.note) == (match_id, "manual", "opening cheque")
    assert [(x.id, x.date, x.amount, x.direction, x.reference_no, x.kind, x.voucher_number) for x in g.book_items] == [
        (opening, date(2026, 3, 30), D("500.00"), "deposit", "CH77", "opening_item", None)]
    assert (g.total_bank, g.total_book) == (D("500.00"), D("500.00"))
    with pytest.raises(ServiceError) as info:  # a ledger that is not this client's
        svc.list_matches(svc_conn, b.client_id, uuid.uuid4())
    assert info.value.code == "not_found"


def test_API_matches_endpoint_shape(api, svc_conn, world):
    b, lines = world
    bank, base = b.ids["HDFC Bank"], f"/clients/{b.client_id}/reconciliation"
    assert api.get(f"{base}/{bank}/matches").json() == {"matches": []}
    rows = api.get(f"{base}/{bank}/unmatched", params={"as_on": "2026-04-30"}).json()
    thirty = next(x for x in rows["bank"] if x["credit"] == "30000.00")
    k4 = next(x for x in rows["book"] if x["debit"] == "30000.00")
    created = api.post(f"{base}/{bank}/matches", json={"bank_line_ids": [thirty["line_id"]], "voucher_line_ids": [k4["voucher_line_id"]], "note": "ok"}, headers=H)
    assert created.status_code == 201
    r = api.get(f"{base}/{bank}/matches", params={"as_on": "2026-04-30"})
    assert r.status_code == 200
    (m,) = r.json()["matches"]
    assert m["match_id"] == created.json()["match_id"] and (m["method"], m["note"], m["created_by"]) == ("manual", "ok", "tester")
    assert m["created_at"]
    assert m["bank_items"] == [{"line_id": str(lines[0]), "txn_date": "2026-04-11", "description": "NEFT RAHUL ENTERPRISES",
                                "reference": "UTR1", "debit": "0.00", "credit": "30000.00"}]
    (book,) = m["book_items"]
    assert (book["voucher_line_id"], book["opening_item_id"], book["date"], book["voucher_number"], book["debit"], book["credit"]) == (
        k4["voucher_line_id"], None, "2026-04-10", "REC/2026-27/0001", "30000.00", "0.00")
    assert (m["total_bank"], m["total_book"]) == ("30000.00", "30000.00")
    assert api.get(f"{base}/{bank}/matches", params={"as_on": "2026-04-01"}).json() == {"matches": []}
    assert api.get(f"{base}/{bank}/matches", params={"as_on": "not-a-date"}).status_code == 422
    assert api.get(f"{base}/not-a-uuid/matches").status_code == 404
