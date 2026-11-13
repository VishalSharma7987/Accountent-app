"""Phase 4 package C: challan entry, allocation rules, matching proposal, interest, due calendar, reversal block (T-20 .. T-28).

Deduction items are written with plain SQL (package B's voucher integration is merged later): a posted voucher + one tds_voucher_items row.
Every test runs in a rolled-back transaction. Expected values are hand-calculated literals.

Hand numbers (FY 2026-27, Q1): item I1 deducted 10-05-2026, tax 1,000.00; item I2 deducted 20-05-2026, tax 500.00; due date 07-06-2026.
Challan C1 deposited 20-07-2026 pays I1: 10-05 -> 20-07 is 3 months x 1.5% x 1,000.00 = 45.00. I2 is open on 31-08-2026:
20-05 -> 31-08 is 4 months x 1.5% x 500.00 = 30.00. Days late: I1 20-07 - 07-06 = 43; I2 31-08 - 07-06 = 85.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import tds_challans
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

D = Decimal

ITEM_SQL = (
    "INSERT INTO tds_voucher_items (id, client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
    "financial_year_id, event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, rate_applied, "
    "rate_reason, tds_amount, tds_line_no, engine_version) "
    "VALUES (%s, %s, %s, 1, 'tds', %s, 'contractor', 'it_act_2025', '393(1) Sl.6(i)', %s, %s, %s, 100000.00, 0, 100000.00, 100000.00, 1, "
    "'normal', %s, 1, 't')"
)


class World:
    def __init__(self, conn):
        self.f = Factory(conn.connection.driver_connection)
        self.conn = conn
        self.client_id, self.fy_id = self.f.setup()
        self.party = self.f.ledger(self.client_id, "Raj Contractors", "sundry_creditors")
        self.f.conn.execute(
            "INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (%s, %s, 'ABCDE1234F', 'valid', 'individual')",
            (self.party, self.client_id))

    def item(self, event: date, tax: str, *, voucher_date: date | None = None, post: bool = True) -> uuid.UUID:
        """A voucher (posted unless post=False) carrying one deduction item of `tax` rupees."""
        f = self.f
        vdate = (voucher_date or event).isoformat()
        vid = f.draft(self.client_id, self.fy_id, f.balanced_lines(self.client_id), on=vdate)
        item_id = uuid.uuid4()
        f.conn.execute(ITEM_SQL, (item_id, self.client_id, vid, self.party, self.fy_id, event, event, tax))
        if post:
            f.approve(vid)
            f.post(vid)
            check_deferred(f.conn)
        return item_id

    def challan(self, conn, *, deposit="2026-07-20", serial="11", tax="1000.00", allocations=None, **extra):
        data = {
            "kind": "tds", "financial_year_id": self.fy_id, "quarter": 1, "bsr_code": "0510308", "deposit_date": date.fromisoformat(deposit),
            "challan_serial_no": serial, "tax_amount": tax, "allocations": allocations, **extra,
        }
        return tds_challans.create_challan(conn, self.client_id, data, actor="clerk")


@pytest.fixture
def w(svc_conn) -> World:
    return World(svc_conn)


def alloc(item_id, amount):
    return {"item_id": item_id, "amount": amount}


def rule_ids(exc: VoucherRuleError) -> list[str]:
    return [e.rule_id for e in exc.errors]


def test_T20_T23_create_challan_with_allocations_lists_totals_and_logs(svc_conn, w):
    i1 = w.item(date(2026, 5, 10), "1000.00")
    i2 = w.item(date(2026, 5, 20), "500.00")
    cid = w.challan(svc_conn, tax="1500.00", interest_amount="45.00", allocations=[alloc(i1, "1000.00"), alloc(i2, "500.00")])
    c = tds_challans.get_challan(svc_conn, w.client_id, cid)
    assert (c["total_amount"], c["allocated"], c["unallocated"], c["status"]) == (D("1545.00"), D("1500.00"), D("0.00"), "entered")
    assert [(a["deductee_name"], a["amount"]) for a in c["allocations"]] == [("Raj Contractors", D("1000.00")), ("Raj Contractors", D("500.00"))]
    listing = tds_challans.list_challans(svc_conn, w.client_id, w.fy_id, 1, "tds")
    assert [(r["challan_serial_no"], r["tax_amount"], r["unallocated"]) for r in listing] == [("11", D("1500.00"), D("0.00"))]
    n = w.f.conn.execute("SELECT count(*) FROM audit_log WHERE entity = 'tds_challan' AND action = 'create' AND entity_id = %s", (cid,)).fetchone()[0]
    assert n == 1


def test_T20_duplicate_cin_unposted_item_and_bad_fields_are_refused(svc_conn, w):
    posted = w.item(date(2026, 5, 10), "1000.00")
    draft = w.item(date(2026, 5, 12), "300.00", post=False)
    w.challan(svc_conn, allocations=[alloc(posted, "400.00")])
    with pytest.raises(ServiceError) as e:
        w.challan(svc_conn)
    assert e.value.code == "challan_exists"
    with pytest.raises(VoucherRuleError) as e2:
        w.challan(svc_conn, serial="12", allocations=[alloc(draft, "100.00")])
    assert rule_ids(e2.value) == ["T-21"]
    assert e2.value.errors[0].line_no == 1
    with pytest.raises(VoucherRuleError) as e3:
        w.challan(svc_conn, serial="13", bsr_code="12", tax="10.005")
    assert rule_ids(e3.value) == ["T-20", "T-20"]
    with pytest.raises(VoucherRuleError) as e4:
        w.challan(svc_conn, serial="14", allocations=[alloc(uuid.uuid4(), "1.00")])
    assert rule_ids(e4.value) == ["T-21"]


def test_T22_T23_T24_allocation_limits_across_challans(svc_conn, w):
    i1 = w.item(date(2026, 5, 10), "1000.00")
    q2 = w.item(date(2026, 7, 10), "100.00")
    c1 = w.challan(svc_conn, allocations=[alloc(i1, "700.00")])
    with pytest.raises(VoucherRuleError) as e:  # 700 + 400 > 1,000 of the item
        w.challan(svc_conn, serial="12", allocations=[alloc(i1, "400.00")])
    assert rule_ids(e.value) == ["T-24"]
    assert "more than its balance 300.00 (tax 1,000.00)" in e.value.errors[0].message
    with pytest.raises(VoucherRuleError) as e2:  # challan tax 200 < 300 allocated
        w.challan(svc_conn, serial="13", tax="200.00", allocations=[alloc(i1, "300.00")])
    assert rule_ids(e2.value) == ["T-23"]
    with pytest.raises(VoucherRuleError) as e3:  # quarter 2 item on a quarter 1 challan
        w.challan(svc_conn, serial="14", allocations=[alloc(q2, "100.00")])
    assert "T-22" in rule_ids(e3.value)
    # replacing the allocations of c1 may use its own old share again
    done = tds_challans.replace_allocations(svc_conn, w.client_id, c1, [alloc(i1, "1000.00")], actor="clerk")
    assert (done["allocated"], done["unallocated"]) == (D("1000.00"), D("0.00"))
    done = tds_challans.replace_allocations(svc_conn, w.client_id, c1, [], actor="clerk")
    assert done["allocated"] == D("0.00")


def test_T25_locked_challan_refuses_changes_and_reversal_is_blocked_by_an_allocation(svc_conn, w):
    i1 = w.item(date(2026, 5, 10), "1000.00")
    voucher_id = w.f.conn.execute("SELECT voucher_id FROM tds_voucher_items WHERE id = %s", (i1,)).fetchone()[0]
    tds_challans.on_reverse_check(svc_conn, w.client_id, voucher_id)  # no allocation yet: allowed
    c1 = w.challan(svc_conn, allocations=[alloc(i1, "1000.00")])
    with pytest.raises(ServiceError) as e:
        tds_challans.on_reverse_check(svc_conn, w.client_id, voucher_id)
    assert e.value.code == "item_has_allocation"
    assert e.value.message.startswith("This voucher cannot be reversed: its tax is allocated to challan BSR 0510308 serial 11 dated 20-07-2026 (1,000.00)")
    tds_challans.replace_allocations(svc_conn, w.client_id, c1, [], actor="clerk")
    tds_challans.on_reverse_check(svc_conn, w.client_id, voucher_id)  # allocation removed: allowed again
    tds_challans.replace_allocations(svc_conn, w.client_id, c1, [alloc(i1, "1000.00")], actor="clerk")
    w.f.conn.execute("UPDATE tds_challans SET status = 'locked' WHERE id = %s", (c1,))
    with pytest.raises(ServiceError) as e2:
        tds_challans.replace_allocations(svc_conn, w.client_id, c1, [], actor="clerk")
    assert e2.value.code == "challan_locked"
    fields = {"financial_year_id": w.fy_id, "quarter": 1, "bsr_code": "0510308", "deposit_date": date(2026, 7, 20), "challan_serial_no": "11", "tax_amount": "1000.00"}
    with pytest.raises(ServiceError) as e3:
        tds_challans.update_challan(svc_conn, w.client_id, c1, fields, actor="clerk")
    assert e3.value.code == "challan_locked"


def test_T20_update_challan_revalidates_its_allocations(svc_conn, w):
    i1 = w.item(date(2026, 5, 10), "1000.00")
    c1 = w.challan(svc_conn, allocations=[alloc(i1, "1000.00")])
    fields = {"financial_year_id": w.fy_id, "quarter": 1, "bsr_code": "0510308", "deposit_date": date(2026, 7, 21), "challan_serial_no": "11",
              "tax_amount": "1000.00", "fee_amount": "200.00"}
    out = tds_challans.update_challan(svc_conn, w.client_id, c1, fields, actor="clerk")
    assert (out["total_amount"], out["deposit_date"]) == (D("1200.00"), date(2026, 7, 21))
    with pytest.raises(VoucherRuleError) as e:
        tds_challans.update_challan(svc_conn, w.client_id, c1, {**fields, "tax_amount": "900.00"}, actor="clerk")
    assert rule_ids(e.value) == ["T-23"]


def test_T21_T26_T27_T28_matching_proposal_interest_and_calendar(svc_conn, w):
    i1 = w.item(date(2026, 5, 10), "1000.00")
    i2 = w.item(date(2026, 5, 20), "500.00")
    c1 = w.challan(svc_conn, tax="1000.00", interest_amount="45.00")
    proposal = tds_challans.propose(svc_conn, w.client_id, w.fy_id, 1, "tds")
    assert proposal == {"proposed": [{"item_id": str(i1), "challan_id": str(c1), "amount": D("1000.00")}]}
    tds_challans.replace_allocations(svc_conn, w.client_id, c1, [alloc(i1, "1000.00")], actor="clerk")
    on = date(2026, 8, 31)
    m = tds_challans.matching(svc_conn, w.client_id, w.fy_id, 1, "tds", on)
    rows = {str(r["item_id"]): r for r in m["rows"]}
    assert (rows[str(i1)]["balance"], rows[str(i1)]["deposited_on"], rows[str(i1)]["days_late"], rows[str(i1)]["interest_late_deposit"]) == (
        D("0.00"), date(2026, 7, 20), 43, D("45.00"))
    assert (rows[str(i2)]["balance"], rows[str(i2)]["deposited_on"], rows[str(i2)]["days_late"], rows[str(i2)]["interest_late_deposit"]) == (
        D("500.00"), None, 85, D("30.00"))
    assert rows[str(i2)]["due_date"] == date(2026, 6, 7)
    assert m["totals"] == {"tds_amount": D("1500.00"), "allocated": D("1000.00"), "balance": D("500.00"), "interest_late_deposit": D("75.00")}
    assert m["unallocated_challans"] == []
    assert m["rule_status"]["worst"] == "pending"
    assert "interest" in m["rule_status"]["tables"] and "due_date" in m["rule_status"]["tables"]

    i = tds_challans.interest(svc_conn, w.client_id, w.fy_id, on)
    assert i["totals"] == {"tds_amount": D("1500.00"), "interest_late_deduction": D("0.00"), "interest_late_deposit": D("75.00"), "interest_total": D("75.00")}

    cal = tds_challans.due_calendar(svc_conn, w.client_id, w.fy_id, on)
    by = {(r["kind"], r["period"], r["event"].split(" ")[0]): r for r in cal["rows"]}
    may = by[("tds", "May 2026", "Deposit")]
    assert (may["due_date"], may["status"], may["amount_due"]) == (date(2026, 6, 7), "overdue", D("500.00"))
    assert by[("tds", "Apr 2026", "Deposit")]["status"] == "done"
    q1 = next(r for r in cal["rows"] if r["event"] == "TDS statement, quarter 1")
    assert (q1["due_date"], q1["status"]) == (date(2026, 7, 31), "overdue")


def test_T26_late_deduction_interest_from_the_voucher_date(svc_conn, w):
    # deductible 10-04-2026 (event), booked in a voucher dated 05-06-2026: 2 months x 1% x 5,000.00 = 100.00; due 07-05-2026
    w.item(date(2026, 4, 10), "5000.00", voucher_date=date(2026, 6, 5))
    i = tds_challans.interest(svc_conn, w.client_id, w.fy_id, date(2026, 6, 5))
    row = i["rows"][0]
    assert (row["deductible_on"], row["deducted_on"], row["months_late_deduction"], row["interest_late_deduction"]) == (
        date(2026, 4, 10), date(2026, 6, 5), 2, D("100.00"))
    assert (row["due_date"], row["interest_late_deposit"]) == (date(2026, 5, 7), D("0.00"))  # open on the booking day: 0 months of late deposit


def test_api_challan_round_trip(svc_conn, w):
    i1 = w.item(date(2026, 5, 10), "1000.00")
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        h = {"X-User": "clerk"}
        base = f"/clients/{w.client_id}/tds"
        body = {"kind": "tds", "financial_year_id": str(w.fy_id), "quarter": 1, "bsr_code": "0510308", "deposit_date": "2026-07-20",
                "challan_serial_no": "11", "tax_amount": "1000.00", "allocations": [{"item_id": str(i1), "amount": "1000.00"}]}
        r = api.post(f"{base}/challans", json=body, headers=h)
        assert r.status_code == 201
        cid = r.json()["id"]
        assert api.post(f"{base}/challans", json=body, headers=h).json()["code"] == "challan_exists"
        bad = api.post(f"{base}/challans", json={**body, "challan_serial_no": "12", "allocations": [{"item_id": str(i1), "amount": "1.00"}]}, headers=h)
        assert bad.status_code == 422 and bad.json()["errors"][0]["rule_id"] == "T-24"
        g = api.get(f"{base}/challans/{cid}")
        assert g.json()["total_amount"] == "1000.00" and g.json()["allocations"][0]["amount"] == "1000.00"
        m = api.get(f"{base}/challan-matching", params={"financial_year_id": str(w.fy_id), "quarter": 1, "as_on": "2026-08-31"})
        assert m.status_code == 200 and m.json()["rows"][0]["days_late"] == 43
        auto = api.post(f"{base}/challan-matching/auto", json={"financial_year_id": str(w.fy_id), "quarter": 1, "kind": "tds"})
        assert auto.json() == {"proposed": []}
        assert api.get(f"{base}/due-calendar", params={"financial_year_id": str(w.fy_id)}).status_code == 200
        assert api.get(f"{base}/interest", params={"financial_year_id": str(w.fy_id), "as_on": "2026-08-31"}).status_code == 200
        assert api.put(f"{base}/challans/{cid}/allocations", json={"allocations": []}, headers=h).json()["allocated"] == "0.00"
        assert api.get(f"{base}/challans/not-an-id").status_code == 404
    finally:
        app.dependency_overrides.clear()
