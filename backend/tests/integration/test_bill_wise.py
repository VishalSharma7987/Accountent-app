"""Phase 2, steps 2.1-2.3: party master, bill-wise allocation, opening bills, outstanding and ageing.

One committed world per module (ABC Traders: openings Cash 50,000 / HDFC 3,00,000 / Stock 1,00,000 Dr and
Owner Capital 4,50,000 Cr, no vouchers); every test runs in a rolled-back transaction on top of it.
Hand-calculated numbers are in the comments.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from books import build_books
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_conn
from app.db import connection, migrate
from app.engine.bills import OpeningBillIn
from app.engine.models import Allocation, VoucherDraft, VoucherLine
from app.main import app
from app.services import bills, client_setup, msme, parties, vouchers
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

D = Decimal
H = {"X-User": "tester"}


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        b = build_books(conn)
    yield b
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def A(kind, amount, ref=None, due=None):
    return Allocation(kind, amount, ref, due)


def vd(w, vtype, on, lines, *, ref=None, party=None, narration="Test voucher"):
    """lines = [(ledger name, debit, credit) or (ledger name, debit, credit, [allocations])]"""
    built = tuple(
        VoucherLine(w.ids[x[0]], x[1], x[2], tuple(x[3]) if len(x) > 3 else ()) for x in lines
    )
    return VoucherDraft(w.client_id, vtype, on, narration, ref, w.ids[party] if party else None, built)


def post(conn, draft):
    result = vouchers.create_draft(conn, draft, actor="clerk")
    assert result.errors == [], result.errors
    vouchers.approve(conn, result.voucher_id, actor="partner")
    vouchers.post(conn, result.voucher_id, actor="partner")
    return result.voucher_id


def make_parties(conn, w):
    parties.set_party(conn, w.client_id, w.ids["Rahul Enterprises"], credit_days=30, actor="setup")
    parties.set_party(conn, w.client_id, w.ids["Sharma Suppliers"], credit_days=45, actor="setup")


def open_view(conn, w, as_on, ledger="Rahul Enterprises"):
    return [(b.bill_ref, b.kind, b.outstanding) for b in bills.open_bills(conn, w.client_id, as_on, w.ids[ledger])]


def rule_ids(excinfo):
    return [(e.rule_id, e.line_no) for e in excinfo.value.errors]


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


# =============================================================================================== party master


def test_party_set_get_list_update_and_audit(svc_conn, world):
    c, w = svc_conn, world
    parties.set_party(
        c, w.client_id, w.ids["Rahul Enterprises"], gstin=" 27aabcu9603r1zn ", pan="AABCU9603R", state_code="27",
        credit_days="30", msme_category="small", udyam_no="UDYAM-MH-18-0012345", actor="clerk",
        msme_activity="services", udyam_registration_date=date(2021, 3, 1), msme_written_agreement=True,
        msme_agreed_days=40,
    )
    p = parties.get_party(c, w.client_id, w.ids["Rahul Enterprises"])
    assert (p.nature, p.gstin, p.credit_days, p.msme_category, p.bill_wise) == ("debtor", "27AABCU9603R1ZN", 30, "small", True)
    assert (p.msme_activity, p.udyam_registration_date, p.msme_agreed_days) == ("services", date(2021, 3, 1), 40)

    parties.set_party(c, w.client_id, w.ids["Sharma Suppliers"], actor="clerk")
    assert [x.ledger_name for x in parties.list_parties(c, w.client_id)] == ["Rahul Enterprises", "Sharma Suppliers"]
    assert [x.ledger_name for x in parties.list_parties(c, w.client_id, "creditor")] == ["Sharma Suppliers"]

    parties.set_party(c, w.client_id, w.ids["Rahul Enterprises"], credit_days=45, actor="partner")
    assert parties.get_party(c, w.client_id, w.ids["Rahul Enterprises"]).credit_days == 45
    assert parties.get_party(c, w.client_id, w.ids["Rahul Enterprises"]).gstin is None  # PUT replaces the details
    actions = [r[0] for r in c.execute(
        text("SELECT action FROM audit_log WHERE entity = 'party' AND entity_id = :l ORDER BY id"),
        {"l": w.ids["Rahul Enterprises"]})]
    assert actions == ["create", "update"]


def test_G02_party_gstin_with_wrong_check_character_is_refused_and_P04_state_mismatch_blocks_the_save(svc_conn, world):
    c, w = svc_conn, world
    rahul = w.ids["Rahul Enterprises"]
    with pytest.raises(VoucherRuleError) as bad:
        parties.set_party(c, w.client_id, rahul, gstin="27AABCU9603R1ZM", state_code="27", actor="clerk")
    assert rule_ids(bad) == [("G-02", None)]
    with pytest.raises(VoucherRuleError) as state:
        parties.set_party(c, w.client_id, rahul, gstin="27AABCU9603R1ZN", state_code="29", actor="clerk")
    assert rule_ids(state) == [("P-04", None)]
    assert scalar(c, "SELECT count(*) FROM parties WHERE gstin IS NOT NULL") == 0


def test_P01_P07_party_rules_raise_all_errors_and_write_nothing(svc_conn, world):
    c, w = svc_conn, world
    with pytest.raises(VoucherRuleError) as bad:
        parties.set_party(c, w.client_id, w.ids["Rahul Enterprises"], gstin="BAD", credit_days=-1, actor="clerk")
    assert rule_ids(bad) == [("P-01", None), ("P-06", None)]
    with pytest.raises(VoucherRuleError) as rent:
        parties.set_party(c, w.client_id, w.ids["Rent"], actor="clerk")
    assert rule_ids(rent) == [("P-07", None)]
    assert scalar(c, "SELECT count(*) FROM parties") == 0
    with pytest.raises(ServiceError) as missing:
        parties.get_party(c, w.client_id, w.ids["Rahul Enterprises"])
    assert missing.value.code == "not_found"


# ======================================================================== P-08, opening bills, B-07 (posting)


def test_P08_and_opening_bills_flow(svc_conn, world):
    c, w = svc_conn, world
    rahul, fy = w.ids["Rahul Enterprises"], w.fy_id
    client_setup.set_opening_balance(c, w.client_id, fy, rahul, "50000", None, actor="setup")
    client_setup.set_opening_balance(c, w.client_id, fy, w.ids["Owner Capital A/c"], None, "500000", actor="setup")

    # the opening balance is not covered by opening bills yet: bill-wise cannot be switched on
    with pytest.raises(VoucherRuleError) as e:
        parties.set_party(c, w.client_id, rahul, credit_days=30, actor="clerk")
    assert rule_ids(e) == [("P-08", None)]
    assert "50,000.00" in e.value.errors[0].message
    parties.set_party(c, w.client_id, rahul, credit_days=30, bill_wise=False, actor="clerk")

    # opening bills: wrong first (B-03 duplicate reference, B-05 amount), then right
    day = date(2026, 2, 1)
    with pytest.raises(VoucherRuleError) as e:
        bills.set_opening_bills(c, w.client_id, fy, rahul, [
            OpeningBillIn("OB1", day, "30000", "Dr"), OpeningBillIn(" ob1 ", day, "10.001", "Dr")], actor="clerk")
    assert rule_ids(e) == [("B-03", 2), ("B-05", 2)]
    bills.set_opening_bills(c, w.client_id, fy, rahul, [OpeningBillIn("OB1", day, "30000", "Dr")], actor="clerk")
    view = bills.get_opening_bills(c, w.client_id, fy, rahul)
    assert (view.check.total.amount, view.check.difference.amount, view.check.difference.side, view.check.is_balanced) == (
        D("30000.00"), D("20000.00"), "Dr", False)
    assert [(b.bill_ref, b.due_date) for b in view.bills] == [("OB1", date(2026, 3, 3))]  # 1 Feb + 30 days

    with pytest.raises(VoucherRuleError):  # 30,000 of 50,000 is still not covered
        parties.set_party(c, w.client_id, rahul, credit_days=30, actor="clerk")
    bills.set_opening_bills(c, w.client_id, fy, rahul, [
        OpeningBillIn("OB1", day, "30000", "Dr"), OpeningBillIn("OB2", day, "20000", "Dr", date(2026, 3, 10))], actor="clerk")
    assert bills.get_opening_bills(c, w.client_id, fy, rahul).check.is_balanced
    parties.set_party(c, w.client_id, rahul, credit_days=30, actor="clerk")  # now allowed

    assert [(b.bill_ref, b.outstanding) for b in bills.open_bills(c, w.client_id, date(2026, 4, 30))] == [
        ("OB1", D("30000.00")), ("OB2", D("20000.00"))]
    actions = [r[0] for r in c.execute(
        text("SELECT action FROM audit_log WHERE entity = 'opening_bills' ORDER BY id"))]
    assert actions == ["set_opening_bills", "set_opening_bills"]


def test_B07_posting_blocked_while_opening_bills_do_not_cover_the_opening_balance(svc_conn, world):
    c, w = svc_conn, world
    parties.set_party(c, w.client_id, w.ids["Rahul Enterprises"], credit_days=30, actor="setup")  # no opening yet
    client_setup.set_opening_balance(c, w.client_id, w.fy_id, w.ids["Rahul Enterprises"], "50000", None, actor="setup")
    client_setup.set_opening_balance(c, w.client_id, w.fy_id, w.ids["Owner Capital A/c"], None, "500000", actor="setup")
    draft = vd(w, "sales", date(2026, 4, 5), [
        ("Rahul Enterprises", "1000", None, [A("new_ref", "1000", "INV1")]), ("Sales", None, "1000")])
    created = vouchers.create_draft(c, draft, actor="clerk")
    assert created.errors == []
    vouchers.approve(c, created.voucher_id, actor="partner")
    with pytest.raises(VoucherRuleError) as e:
        vouchers.post(c, created.voucher_id, actor="partner")
    assert rule_ids(e) == [("B-07", None)]
    assert "50,000.00 Dr" in e.value.errors[0].message
    assert vouchers.get_voucher(c, created.voucher_id).status == "approved"


def test_P08_bill_wise_refused_for_a_ledger_with_posted_lines_without_allocation(svc_conn, world):
    c, w = svc_conn, world
    post(c, vd(w, "sales", date(2026, 4, 5), [("Rahul Enterprises", "1000", None), ("Sales", None, "1000")]))  # Phase 1 style
    with pytest.raises(VoucherRuleError) as e:
        parties.set_party(c, w.client_id, w.ids["Rahul Enterprises"], actor="clerk")
    assert rule_ids(e) == [("P-08", None)]
    parties.set_party(c, w.client_id, w.ids["Rahul Enterprises"], bill_wise=False, actor="clerk")
    with pytest.raises(ServiceError) as locked:
        bills.set_opening_bills(c, w.client_id, w.fy_id, w.ids["Rahul Enterprises"], [], actor="clerk")
    assert locked.value.code == "opening_locked"


# ======================================================================================== the voucher flow


def test_bill_wise_voucher_flow_open_bills_advance_adjustment_and_reports(svc_conn, world):
    c, w = svc_conn, world
    make_parties(c, w)
    rahul, sharma = "Rahul Enterprises", "Sharma Suppliers"

    # B-01 at entry: a party line with no allocation is refused and nothing is saved
    no_alloc = vd(w, "sales", date(2026, 4, 5), [(rahul, "100000", None), ("Sales", None, "100000")])
    r = vouchers.create_draft(c, no_alloc, actor="clerk")
    assert [(e.rule_id, e.line_no) for e in r.errors] == [("B-01", 1)] and r.voucher_id is None

    # sale of 1,00,000 on 05-04-2026, 30 credit days -> due 05-05-2026 (resolved and stored on the draft)
    sale = vd(w, "sales", date(2026, 4, 5), [
        (rahul, "100000", None, [A("new_ref", "100000", "INV1")]), ("Sales", None, "100000")], party=rahul)
    created = vouchers.create_draft(c, sale, actor="clerk")
    assert created.errors == []
    stored = vouchers.get_voucher(c, created.voucher_id).lines[0].allocations
    assert stored == (A("new_ref", D("100000.00"), "INV1", date(2026, 5, 5)),)
    assert open_view(c, w, date(2026, 4, 30)) == []  # drafts are not bills
    vouchers.approve(c, created.voucher_id, actor="partner")
    vouchers.post(c, created.voucher_id, actor="partner")
    assert open_view(c, w, date(2026, 4, 30)) == [("INV1", "bill", D("100000.00"))]

    # 30,000 received against INV1 (partial) -> 70,000; a further receipt of 1,00,000 would over-settle (B-04)
    def receipt(amount, ref):
        return vd(w, "receipt", date(2026, 4, 10), [
            ("HDFC Bank", amount, None), (rahul, None, amount, [A("against_ref", amount, ref)])], party=rahul)

    post(c, receipt("30000", "INV1"))
    over = vouchers.create_draft(c, receipt("100000", "INV1"), actor="clerk")
    assert [(e.rule_id, e.line_no) for e in over.errors] == [("B-04", 2)]
    assert open_view(c, w, date(2026, 4, 30)) == [("INV1", "bill", D("70000.00"))]
    assert open_view(c, w, date(2026, 4, 9)) == [("INV1", "bill", D("100000.00"))]  # as on an earlier date

    # credit note 2,000 against INV1 -> 68,000; advance of 5,000 received on 20-04-2026
    post(c, vd(w, "credit_note", date(2026, 4, 15), [
        ("Sales", "2000", None), (rahul, None, "2000", [A("against_ref", "2000", "INV1")])], party=rahul))
    post(c, vd(w, "receipt", date(2026, 4, 20), [
        ("HDFC Bank", "5000", None), (rahul, None, "5000", [A("advance", "5000", "ADV1")])], party=rahul))
    assert open_view(c, w, date(2026, 4, 30)) == [("INV1", "bill", D("68000.00")), ("ADV1", "advance", D("-5000.00"))]

    # purchase of 50,000 (45 credit days -> due 18-05-2026), 15,000 paid against it
    post(c, vd(w, "purchase", date(2026, 4, 3), [
        ("Purchases", "50000", None), (sharma, None, "50000", [A("new_ref", "50000", "SUP/889")])],
        ref="SUP/889", party=sharma))
    post(c, vd(w, "payment", date(2026, 4, 12), [
        (sharma, "15000", None, [A("against_ref", "15000", "SUP/889")]), ("HDFC Bank", None, "15000")]))

    # receivable as on 30-06-2026: INV1 68,000 due 05-05 is 56 days late (31-60); ADV1 -5,000 from 20-04 is 71 (61-90)
    rep = bills.ageing_report(c, w.client_id, "receivable", date(2026, 6, 30))
    assert [p.party_name for p in rep.parties] == ["Rahul Enterprises"]
    assert (rep.buckets["31-60"], rep.buckets["61-90"], rep.total) == (D("68000.00"), D("-5000.00"), D("63000.00"))
    assert rep.parties[0].ledger_balance == D("63000.00") and rep.parties[0].ties and rep.ties  # 100000-30000-2000-5000
    # payable: SUP/889 35,000 due 18-05 is 43 days late; ledger 50,000 - 15,000
    pay = bills.outstanding_report(c, w.client_id, "payable", date(2026, 6, 30))
    assert (pay.buckets["31-60"], pay.total, pay.ties) == (D("35000.00"), D("35000.00"), True)

    # the advance is adjusted by a new sale of 25,000: 5,000 from ADV1 + 20,000 new bill INV2 (one line, two allocations)
    post(c, vd(w, "sales", date(2026, 5, 2), [
        (rahul, "25000", None, [A("against_ref", "5000", "ADV1"), A("new_ref", "20000", "INV2")]),
        ("Sales", None, "25000")], party=rahul))
    assert open_view(c, w, date(2026, 5, 31)) == [("INV1", "bill", D("68000.00")), ("INV2", "bill", D("20000.00"))]
    assert bills.ageing_report(c, w.client_id, "receivable", date(2026, 5, 31)).ties


def test_B04_reversals_follow_the_bills_and_write_mirrored_allocations(svc_conn, world):
    c, w = svc_conn, world
    make_parties(c, w)
    rahul = "Rahul Enterprises"
    sale = post(c, vd(w, "sales", date(2026, 4, 5), [
        (rahul, "100000", None, [A("new_ref", "100000", "INV1")]), ("Sales", None, "100000")], party=rahul))
    rec = post(c, vd(w, "receipt", date(2026, 4, 10), [
        ("HDFC Bank", "30000", None), (rahul, None, "30000", [A("against_ref", "30000", "INV1")])], party=rahul))

    # with 30,000 received the sale cannot be reversed first: the bill would go 30,000 past zero
    with pytest.raises(VoucherRuleError) as e:
        vouchers.reverse(c, sale, date(2026, 4, 20), "wrong customer", actor="partner")
    assert rule_ids(e) == [("B-04", 1)]
    assert "30,000.00" in e.value.errors[0].message
    assert vouchers.get_voucher(c, sale).status == "posted"

    # reverse the receipt (Dr against INV1: exempt from the 'opposite side' rule), then the sale
    back = vouchers.reverse(c, rec, date(2026, 4, 20), "cheque bounced", actor="partner")
    assert vouchers.get_voucher(c, back).lines[1].allocations == (A("against_ref", D("30000.00"), "INV1"),)
    assert open_view(c, w, date(2026, 4, 30)) == [("INV1", "bill", D("100000.00"))]
    reversal = vouchers.reverse(c, sale, date(2026, 4, 21), "wrong customer", actor="partner")
    assert vouchers.get_voucher(c, reversal).lines[0].allocations == (A("against_ref", D("100000.00"), "INV1"),)
    assert open_view(c, w, date(2026, 4, 30)) == []  # the reversed bill is gone
    assert bills.ageing_report(c, w.client_id, "receivable", date(2026, 4, 30)).ties
    again = vouchers.create_draft(c, vd(w, "sales", date(2026, 4, 22), [  # the reference stays used (B-03)
        (rahul, "10", None, [A("new_ref", "10", "inv1")]), ("Sales", None, "10")]), actor="clerk")
    assert [(e.rule_id, e.line_no) for e in again.errors] == [("B-03", 1)]


def test_database_refuses_a_posted_party_line_that_is_not_fully_allocated(svc_conn, world):
    c, w = svc_conn, world
    make_parties(c, w)
    created = vouchers.create_draft(c, vd(w, "sales", date(2026, 4, 5), [
        ("Rahul Enterprises", "1000", None, [A("new_ref", "1000", "INV1")]), ("Sales", None, "1000")]), actor="clerk")
    assert created.errors == []
    c.execute(text("DELETE FROM bill_allocations WHERE voucher_id = :v"), {"v": created.voucher_id})  # allowed on a draft
    c.execute(text("UPDATE vouchers SET status = 'approved', approved_by = 'tester', approved_at = now() WHERE id = :v"),
              {"v": created.voucher_id})
    savepoint = c.begin_nested()
    with pytest.raises(DBAPIError) as e:
        c.execute(text("UPDATE vouchers SET status = 'posted', voucher_number = 'SAL/2026-27/9999', posted_by = 'tester', "
                  "posted_at = now() WHERE id = :v"),
                  {"v": created.voucher_id})
        c.execute(text("SET CONSTRAINTS vouchers_allocation_check IMMEDIATE"))
    savepoint.rollback()
    assert "allocated 0 of 1000" in str(e.value)


# ========================================================================================================= API


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_parties_opening_bills_vouchers_open_bills_and_reports(api, svc_conn, world):
    w, rahul = world, world.ids["Rahul Enterprises"]
    base = f"/clients/{w.client_id}"
    client_setup.set_opening_balance(svc_conn, w.client_id, w.fy_id, rahul, "50000", None, actor="setup")
    client_setup.set_opening_balance(svc_conn, w.client_id, w.fy_id, w.ids["Owner Capital A/c"], None, "500000", actor="setup")

    bad = api.put(f"{base}/parties/{rahul}", json={"gstin": "BAD"}, headers=H)
    assert bad.status_code == 422
    assert [(e["rule_id"], e["line_no"]) for e in bad.json()["errors"]] == [("P-01", None), ("P-08", None)]
    assert api.put(f"{base}/parties/{rahul}", json={"credit_days": 30, "bill_wise": False}, headers=H).json() == {"ok": True}
    assert api.put(f"{base}/parties/{rahul}", json={"credit_days": 2.5}, headers=H).status_code == 422

    obs = {"bills": [
        {"bill_ref": "OB1", "bill_date": "2026-02-01", "amount": "30000.00", "side": "Dr"},
        {"bill_ref": "OB2", "bill_date": "2026-02-01", "amount": "20000.00", "side": "Dr"}]}
    url = f"{base}/financial-years/{w.fy_id}/opening-bills/{rahul}"
    assert api.put(url, json=obs, headers=H).json() == {"ok": True}
    got = api.get(url).json()
    assert got["is_balanced"] and got["total"] == {"amount": "50000.00", "side": "Dr"}
    assert got["difference"] == {"amount": "0.00", "side": None}
    assert [(b["bill_ref"], b["due_date"]) for b in got["bills"]] == [("OB1", "2026-03-03"), ("OB2", "2026-03-03")]
    assert api.put(f"{base}/parties/{rahul}", json={"credit_days": 30}, headers=H).json() == {"ok": True}
    got_party = api.get(f"{base}/parties/{rahul}").json()
    assert (got_party["ledger_name"], got_party["nature"], got_party["bill_wise"]) == ("Rahul Enterprises", "debtor", True)
    assert [p["ledger_name"] for p in api.get(f"{base}/parties?nature=debtor").json()] == ["Rahul Enterprises"]

    def body(vtype, lines, **kw):
        return {"voucher_type": vtype, "voucher_date": "2026-04-10", "narration": "API", "party_ledger_id": str(rahul),
                "lines": [{"ledger_id": str(w.ids[n]), "debit": d, "credit": cr, "allocations": al} for n, d, cr, al in lines], **kw}

    unallocated = api.post(f"{base}/vouchers", json=body("receipt", [("HDFC Bank", "30000", None, []), ("Rahul Enterprises", None, "30000", [])]), headers=H)
    assert unallocated.status_code == 422
    assert [(e["rule_id"], e["line_no"]) for e in unallocated.json()["errors"]] == [("B-01", 2)]

    receipt = body("receipt", [("HDFC Bank", "30000", None, []),
                               ("Rahul Enterprises", None, "30000", [{"kind": "against_ref", "amount": "30000", "bill_ref": "OB1"}])])
    created = api.post(f"{base}/vouchers", json=receipt, headers=H)
    assert created.status_code == 201, created.text
    vid = created.json()["voucher_id"]
    shown = api.get(f"/vouchers/{vid}").json()["lines"][1]["allocations"]
    assert shown == [{"kind": "against_ref", "amount": "30000.00", "bill_ref": "OB1", "due_date": None}]
    assert api.post(f"/vouchers/{vid}/approve", headers=H).status_code == 200
    assert api.post(f"/vouchers/{vid}/post", headers=H).json()["voucher_number"] == "REC/2026-27/0001"

    items = api.get(f"{base}/open-bills", params={"as_on": "2026-04-30", "party_ledger_id": str(rahul)}).json()
    assert [(i["bill_ref"], i["kind"], i["outstanding"]) for i in items] == [("OB2", "bill", {"amount": "20000.00", "side": "Dr"})]

    out = api.get(f"{base}/reports/outstanding", params={"kind": "receivable", "as_on": "2026-04-30"}).json()
    party = out["parties"][0]
    assert (party["party_name"], party["total"], party["ledger_balance"], party["ties"]) == (
        "Rahul Enterprises", {"amount": "20000.00", "side": "Dr"}, {"amount": "20000.00", "side": "Dr"}, True)
    assert (party["bills"][0]["bucket"], party["bills"][0]["days_past_due"]) == ("31-60", 58)  # due 03-03, 58 days late
    assert out["buckets"]["31-60"] == "20000.00" and out["total"] == {"amount": "20000.00", "side": "Dr"} and out["ties"]
    table = api.get(f"{base}/reports/ageing", params={"kind": "receivable", "as_on": "2026-04-30"}).json()
    assert table["rows"] == [{"party_ledger_id": str(rahul), "party_name": "Rahul Enterprises", "not_due": "0.00",
                              "0-30": "0.00", "31-60": "20000.00", "61-90": "0.00", "90+": "0.00", "total": "20000.00"}]
    assert api.get(f"{base}/reports/ageing", params={"kind": "other", "as_on": "2026-04-30"}).status_code == 422


# ======================================================================== Phase 2.1: MSME party fields, goods received date


def test_P09_P10_P11_party_rules_through_the_service(svc_conn, world):
    c, w = svc_conn, world
    with pytest.raises(VoucherRuleError) as bad:
        parties.set_party(
            c, w.client_id, w.ids["Sharma Suppliers"], msme_category="micro", udyam_no="UDYAM-MH-12-0000001",
            msme_written_agreement=True, actor="clerk",
        )
    assert rule_ids(bad) == [("P-09", None), ("P-10", None), ("P-11", None)]
    with pytest.raises(VoucherRuleError) as high:
        parties.set_party(c, w.client_id, w.ids["Sharma Suppliers"], msme_written_agreement=True, msme_agreed_days=46, actor="clerk")
    assert rule_ids(high) == [("P-11", None)]
    assert scalar(c, "SELECT count(*) FROM parties") == 0
    parties.set_party(
        c, w.client_id, w.ids["Sharma Suppliers"], msme_category="micro", udyam_no="UDYAM-MH-12-0000001",
        msme_activity="manufacturing", udyam_registration_date=date(2020, 1, 1), msme_written_agreement=True,
        msme_agreed_days=30, actor="clerk",
    )
    new = scalar(c, "SELECT new_data FROM audit_log WHERE entity = 'party' ORDER BY id DESC LIMIT 1")
    assert new["msme_activity"] == "manufacturing" and new["udyam_registration_date"] == "2020-01-01" and new["msme_agreed_days"] == 30


def test_V15_goods_received_date_round_trip_and_msme_report(svc_conn, world):
    c, w = svc_conn, world
    parties.set_party(
        c, w.client_id, w.ids["Sharma Suppliers"], msme_category="micro", udyam_no="UDYAM-MH-12-0000001",
        msme_activity="manufacturing", udyam_registration_date=date(2020, 1, 1), msme_written_agreement=True,
        msme_agreed_days=30, actor="clerk",
    )

    def purchase(grd, ref="SUP/1"):
        d = vd(w, "purchase", date(2026, 4, 10), [
            ("Purchases", "50000", None), ("Sharma Suppliers", None, "50000", [A("new_ref", "50000", ref)])],
            ref=ref, party="Sharma Suppliers")
        return replace(d, goods_received_date=grd)

    too_far = vouchers.create_draft(c, purchase(date(2027, 4, 11)), actor="clerk")  # 366 days after 10-04-2026
    assert [(e.rule_id, e.line_no) for e in too_far.errors] == [("V-15", None)] and too_far.voucher_id is None
    sale = replace(
        vd(w, "sales", date(2026, 4, 10), [("Cash", "100", None), ("Sales", None, "100")]),
        goods_received_date=date(2026, 4, 9))
    assert [e.rule_id for e in vouchers.create_draft(c, sale, actor="clerk").errors] == ["V-15"]

    created = vouchers.create_draft(c, purchase(date(2026, 4, 20)), actor="clerk")
    assert created.errors == []
    assert vouchers.get_voucher(c, created.voucher_id).goods_received_date == date(2026, 4, 20)
    snap = scalar(c, "SELECT new_data FROM audit_log WHERE entity = 'voucher' AND entity_id = :i", i=created.voucher_id)
    assert snap["goods_received_date"] == "2026-04-20"

    # a draft can be edited
    assert vouchers.update_draft(c, created.voucher_id, purchase(date(2026, 4, 5)), actor="clerk").errors == []
    assert vouchers.get_voucher(c, created.voucher_id).goods_received_date == date(2026, 4, 5)
    assert vouchers.update_draft(c, created.voucher_id, purchase(date(2026, 4, 20)), actor="clerk").errors == []
    vouchers.approve(c, created.voucher_id, actor="partner")
    vouchers.post(c, created.voucher_id, actor="partner")

    # 20-04-2026 + 30 = 20-05-2026; 10 days overdue on 30-05-2026 (the bill date 10-04 would have given 20 days)
    [item] = msme.msme_report(c, w.client_id, date(2026, 5, 30)).items
    assert (item.bill_ref, item.bill_date, item.acceptance_date, item.acceptance_basis) == (
        "SUP/1", date(2026, 4, 10), date(2026, 4, 20), "goods received date")
    assert (item.legal_days, item.legal_due_date, item.days_overdue, item.outstanding) == (30, date(2026, 5, 20), 10, D("50000.00"))
    assert msme.msme_report(c, w.client_id, date(2026, 5, 30)).rule_status == "secondary_verified"

    # posted: the database refuses to change it, and the service refuses to edit
    with pytest.raises(DBAPIError, match="posted voucher"), c.begin_nested():
        c.execute(text("UPDATE vouchers SET goods_received_date = '2026-04-21' WHERE id = :i"), {"i": created.voucher_id})
    with pytest.raises(ServiceError):
        vouchers.update_draft(c, created.voucher_id, purchase(date(2026, 4, 21)), actor="clerk")

    # without a goods received date the report counts from the bill date and says so
    other = vouchers.create_draft(c, purchase(None, "SUP/2"), actor="clerk").voucher_id
    vouchers.approve(c, other, actor="partner")
    vouchers.post(c, other, actor="partner")
    items = {i.bill_ref: i for i in msme.msme_report(c, w.client_id, date(2026, 5, 30)).items}
    assert (items["SUP/2"].acceptance_date, items["SUP/2"].acceptance_basis, items["SUP/2"].days_overdue) == (
        date(2026, 4, 10), "bill date", 20)


def test_api_party_msme_fields_and_voucher_goods_received_date(api, svc_conn, world):
    w, sharma = world, world.ids["Sharma Suppliers"]
    base = f"/clients/{w.client_id}"
    bad = api.put(f"{base}/parties/{sharma}", json={"msme_category": "small", "udyam_no": "UDYAM-MH-12-0000001"}, headers=H)
    assert bad.status_code == 422
    assert [e["rule_id"] for e in bad.json()["errors"]] == ["P-09", "P-10"]
    ok = api.put(f"{base}/parties/{sharma}", json={
        "msme_category": "small", "udyam_no": "UDYAM-MH-12-0000001", "msme_activity": "services",
        "udyam_registration_date": "2021-03-01", "msme_written_agreement": True, "msme_agreed_days": 45}, headers=H)
    assert ok.json() == {"ok": True}
    got = api.get(f"{base}/parties/{sharma}").json()
    assert (got["msme_activity"], got["udyam_registration_date"], got["msme_agreed_days"]) == ("services", "2021-03-01", 45)

    v = api.post(f"{base}/vouchers", json={
        "voucher_type": "purchase", "voucher_date": "2026-04-10", "narration": "Goods", "reference_no": "SUP/9",
        "party_ledger_id": str(sharma), "goods_received_date": "2026-04-12",
        "lines": [{"ledger_id": str(w.ids["Purchases"]), "debit": "1000"},
                  {"ledger_id": str(sharma), "credit": "1000", "allocations": [{"kind": "new_ref", "amount": "1000", "bill_ref": "SUP/9"}]}]},
        headers=H)
    assert v.status_code == 201, v.text
    assert api.get(f"/vouchers/{v.json()['voucher_id']}").json()["goods_received_date"] == "2026-04-12"
    r = api.get(f"{base}/reports/msme-due", params={"as_on": "2026-06-30"})
    assert r.status_code == 200 and r.json()["rule_status"] == "secondary_verified" and r.json()["items"] == []  # a draft is not a bill
