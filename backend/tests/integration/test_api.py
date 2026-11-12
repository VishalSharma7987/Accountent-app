"""Step 1.7: the HTTP API (docs/API_CONTRACT.md) on the Step 1.3 mini case.

TestClient + the rolled-back `svc_conn` instead of the real per-request transaction (that one is tested in
test_api_transaction.py). Expected numbers are the hand-calculated ones of test_periods_reports.py.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}
MAY_DRAFT_NARRATION = "May draft"


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def b(books):
    return books[0]


@pytest.fixture
def other(books):
    return books[1]


def voucher_body(b, vtype, on, lines, narration="API voucher", reference_no=None, party=None, override=None):
    """lines = [(ledger name, debit, credit)]"""
    return {
        "voucher_type": vtype, "voucher_date": on, "narration": narration, "reference_no": reference_no,
        "party_ledger_id": str(b.ids[party]) if party else None, "duplicate_override_reason": override,
        "lines": [{"ledger_id": str(b.ids[n]), "debit": dr, "credit": cr} for n, dr, cr in lines],
    }


def payment(b, amount="1250.50", on="2026-05-03", narration="API voucher"):
    return voucher_body(b, "payment", on, [("Rent", amount, None), ("Cash", None, amount)], narration)


def new_draft(api, b, **kw):
    r = api.post(f"/clients/{b.client_id}/vouchers", json=payment(b, **kw), headers=H)
    assert r.status_code == 201, r.text
    return r.json()["voucher_id"]


def numbers(response):
    return [x["voucher_number"] for x in response.json()["items"]]


# ============================================================================================ actor header


def test_X_USER_header_is_required_on_writes_and_not_on_reads(api, b):
    for blank in ({}, {"X-User": "   "}):
        r = api.post(f"/clients/{b.client_id}/ledgers", json={"name": "HDFC Current", "group_code": "bank_accounts"}, headers=blank)
        assert r.status_code == 400
        assert r.json() == {"code": "invalid_actor", "message": "The actor (who is making this change) is required.", "details": None}
    assert api.get("/clients").status_code == 200
    assert api.get(f"/clients/{b.client_id}/ledgers").status_code == 200


def test_health_still_answers(api):
    assert api.get("/health").json()["status"] == "ok"


# ================================================================================================== clients


def test_create_client_returns_ids_and_the_client_can_be_read_back(api):
    body = {"name": "Sita Services", "entity_type": "proprietorship", "business_type": "service", "gst_type": "unregistered",
            "fy_start": "2026-04-01", "proprietor_name": "Sita Devi", "pan": "ABCDE1234F"}
    r = api.post("/clients", json=body, headers=H)
    assert r.status_code == 201
    created = r.json()
    assert "Sita Devi Capital A/c" in created["ledger_ids"] and "Service Income" in created["ledger_ids"]

    detail = api.get(f"/clients/{created['client_id']}").json()
    assert detail["name"] == "Sita Services" and detail["entity_type"] == "proprietorship" and detail["pan"] == "ABCDE1234F"
    assert detail["financial_years"] == [{"id": created["financial_year_id"], "start_date": "2026-04-01", "end_date": "2027-03-31"}]
    assert "Sita Services" in [c["name"] for c in api.get("/clients").json()]


def test_create_client_refusals(api):
    base = {"name": "X", "entity_type": "proprietorship", "business_type": "trading", "gst_type": "regular",
            "fy_start": "2026-04-01", "proprietor_name": "Owner"}
    r = api.post("/clients", json={**base, "entity_type": "trust"}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "invalid_profile" and "Unknown entity type 'trust'" in r.json()["message"]
    r = api.post("/clients", json={**base, "fy_start": "2026-05-01"}, headers=H)
    assert r.status_code == 422 and r.json()["message"] == "A financial year must start on 1 April (got 01-05-2026)."
    r = api.post("/clients", json={k: v for k, v in base.items() if k != "fy_start"}, headers=H)
    assert r.status_code == 422 and "detail" in r.json()  # standard request validation


def test_unknown_and_malformed_client_ids_are_404(api):
    for client_id in ("00000000-0000-0000-0000-000000000000", "not-a-uuid"):
        r = api.get(f"/clients/{client_id}")
        assert (r.status_code, r.json()) == (404, {"code": "not_found", "message": "Client not found.", "details": None})
    assert api.get("/clients/not-a-uuid/groups").status_code == 404


# =================================================================================================== groups


def test_groups_tree_nests_children_under_the_primary_groups_in_display_order(api, b):
    tree = api.get(f"/clients/{b.client_id}/groups").json()
    assert [g["name"] for g in tree] == [
        "Capital Account", "Loans (Liability)", "Current Liabilities", "Fixed Assets", "Investments", "Current Assets",
        "Sales Accounts", "Direct Incomes", "Indirect Incomes", "Purchase Accounts", "Direct Expenses",
        "Indirect Expenses", "Suspense A/c",
    ]
    by_name = {g["name"]: g for g in tree}
    assert [c["name"] for c in by_name["Capital Account"]["children"]] == ["Reserves & Surplus"]
    assert [c["name"] for c in by_name["Current Assets"]["children"]] == [
        "Bank Accounts", "Cash-in-hand", "Deposits (Asset)", "Loans & Advances (Asset)", "Stock-in-hand", "Sundry Debtors"]
    assert by_name["Sales Accounts"] == {"code": "sales_accounts", "name": "Sales Accounts", "nature": "income",
                                         "report": "trading", "is_system": True, "children": []}


# ================================================================================================== ledgers

NIL = {"amount": "0.00", "side": None}


def test_ledgers_list_has_group_path_and_closing_balance_as_on_a_date(api, b):
    rows = api.get(f"/clients/{b.client_id}/ledgers", params={"as_on": "2026-04-30"}).json()
    by_name = {x["name"]: x for x in rows}
    assert len(rows) == 21
    assert {n: (x["group_name"], x["balance"]) for n, x in by_name.items() if x["balance"]["side"]} == {
        "Cash": ("Cash-in-hand", {"amount": "15000.00", "side": "Dr"}),
        "HDFC Bank": ("Bank Accounts", {"amount": "325000.00", "side": "Dr"}),
        "Opening Stock": ("Stock-in-hand", {"amount": "100000.00", "side": "Dr"}),
        "Rahul Enterprises": ("Sundry Debtors", {"amount": "50000.00", "side": "Dr"}),
        "Sharma Suppliers": ("Sundry Creditors", {"amount": "35000.00", "side": "Cr"}),
        "Owner Capital A/c": ("Capital Account", {"amount": "450000.00", "side": "Cr"}),
        "Drawings A/c": ("Capital Account", {"amount": "5000.00", "side": "Dr"}),
        "Rent": ("Indirect Expenses", {"amount": "20000.00", "side": "Dr"}),
        "Purchases": ("Purchase Accounts", {"amount": "50000.00", "side": "Dr"}),
        "Sales": ("Sales Accounts", {"amount": "80000.00", "side": "Cr"}),
    }
    assert by_name["Rahul Enterprises"]["group_path"] == ["Current Assets", "Sundry Debtors"]
    assert by_name["Telephone & Internet"]["balance"] == NIL
    assert set(by_name["Cash"]) == {"id", "name", "group_code", "group_name", "group_path", "is_active", "balance"}


def test_ledgers_list_balance_depends_on_the_as_on_date(api, b):
    cash = {x["name"]: x["balance"] for x in api.get(f"/clients/{b.client_id}/ledgers", params={"as_on": "2026-04-10"}).json()}["Cash"]
    assert cash == {"amount": "30000.00", "side": "Dr"}
    default = {x["name"]: x["balance"] for x in api.get(f"/clients/{b.client_id}/ledgers").json()}["Cash"]
    assert default == {"amount": "15000.00", "side": "Dr"}  # today is inside (or after) the year: all vouchers counted


def test_ledgers_list_for_a_date_outside_every_year_is_422(api, b):
    r = api.get(f"/clients/{b.client_id}/ledgers", params={"as_on": "2030-01-01"})
    assert r.status_code == 422 and r.json()["code"] == "no_financial_year"


def test_create_ledger_then_it_appears_with_a_nil_balance(api, b):
    r = api.post(f"/clients/{b.client_id}/ledgers", json={"name": "HDFC Current", "group_code": "bank_accounts"}, headers=H)
    assert r.status_code == 201
    listed = {x["name"]: x for x in api.get(f"/clients/{b.client_id}/ledgers", params={"as_on": "2026-04-30"}).json()}
    assert listed["HDFC Current"]["id"] == r.json()["ledger_id"] and listed["HDFC Current"]["balance"] == NIL


def test_create_ledger_refusals(api, b):
    r = api.post(f"/clients/{b.client_id}/ledgers", json={"name": "cash", "group_code": "cash_in_hand"}, headers=H)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (409, "duplicate_ledger", "A ledger named 'cash' already exists for this client.")
    r = api.post(f"/clients/{b.client_id}/ledgers", json={"name": "X", "group_code": "no_such_group"}, headers=H)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")
    r = api.post(f"/clients/{b.client_id}/ledgers", json={"name": " ", "group_code": "bank_accounts"}, headers=H)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_ledger")


def test_reactivate_ledger_endpoint(api, b, other):
    api.post(f"/clients/{b.client_id}/ledgers/{b.ids['Bank Charges']}/deactivate", headers=H)
    r = api.post(f"/clients/{b.client_id}/ledgers/{b.ids['Bank Charges']}/reactivate", headers=H)
    assert (r.status_code, r.json()) == (200, {"ok": True})
    again = api.post(f"/clients/{b.client_id}/ledgers/{b.ids['Bank Charges']}/reactivate", headers=H)
    assert (again.status_code, again.json()["code"]) == (409, "ledger_active")


def test_deactivate_ledger_blocked_by_a_balance_and_allowed_when_nil(api, b, other):
    r = api.post(f"/clients/{b.client_id}/ledgers/{b.ids['Cash']}/deactivate", headers=H)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (
        409, "ledger_in_use", "Ledger 'Cash' cannot be deactivated: it has a closing balance of 15,000.00 Dr.")
    r = api.post(f"/clients/{b.client_id}/ledgers/{b.ids['Bank Charges']}/deactivate", headers=H)
    assert (r.status_code, r.json()) == (200, {"ok": True})
    listed = {x["name"]: x["is_active"] for x in api.get(f"/clients/{b.client_id}/ledgers", params={"as_on": "2026-04-30"}).json()}
    assert listed["Bank Charges"] is False
    again = api.post(f"/clients/{b.client_id}/ledgers/{b.ids['Bank Charges']}/deactivate", headers=H)
    assert (again.status_code, again.json()["code"]) == (409, "ledger_inactive")
    foreign = api.post(f"/clients/{b.client_id}/ledgers/{other.ids['Rent']}/deactivate", headers=H)
    assert (foreign.status_code, foreign.json()["code"]) == (404, "not_found")


def test_opening_balances_report_of_the_mini_case(api, b):
    r = api.get(f"/clients/{b.client_id}/financial-years/{b.fy_id}/opening-balances")
    assert r.json() == {
        "rows": [
            {"ledger_id": str(b.ids["Cash"]), "ledger_name": "Cash", "debit": "50000.00", "credit": "0.00"},
            {"ledger_id": str(b.ids["HDFC Bank"]), "ledger_name": "HDFC Bank", "debit": "300000.00", "credit": "0.00"},
            {"ledger_id": str(b.ids["Opening Stock"]), "ledger_name": "Opening Stock", "debit": "100000.00", "credit": "0.00"},
            {"ledger_id": str(b.ids["Owner Capital A/c"]), "ledger_name": "Owner Capital A/c", "debit": "0.00", "credit": "450000.00"},
        ],
        "total_debit": "450000.00", "total_credit": "450000.00", "difference": NIL, "is_balanced": True,
    }


def test_set_opening_balance_on_a_fresh_client_and_its_difference(api):
    created = api.post("/clients", json={"name": "Fresh", "entity_type": "proprietorship", "business_type": "trading",
                                         "gst_type": "regular", "fy_start": "2026-04-01", "proprietor_name": "Owner"}, headers=H).json()
    cid, fy, ids = created["client_id"], created["financial_year_id"], created["ledger_ids"]
    base = f"/clients/{cid}/financial-years/{fy}/opening-balances"
    assert api.put(f"{base}/{ids['Cash']}", json={"debit": "100"}, headers=H).json() == {"ok": True}
    report = api.get(base).json()
    assert (report["total_debit"], report["total_credit"], report["is_balanced"]) == ("100.00", "0.00", False)
    assert report["difference"] == {"amount": "100.00", "side": "Dr"}
    assert api.put(f"{base}/{ids['Owner Capital A/c']}", json={"credit": "100.00"}, headers=H).status_code == 200
    assert api.get(base).json()["is_balanced"] is True
    assert api.put(f"{base}/{ids['Cash']}", json={}, headers=H).status_code == 200  # both empty removes the row
    assert [r["ledger_name"] for r in api.get(base).json()["rows"]] == ["Owner Capital A/c"]


def test_set_opening_balance_refusals(api, b):
    base = f"/clients/{b.client_id}/financial-years/{b.fy_id}/opening-balances"
    r = api.put(f"{base}/{b.ids['Cash']}", json={"debit": "1"}, headers=H)
    assert (r.status_code, r.json()["code"]) == (409, "opening_locked")
    fresh = api.post("/clients", json={"name": "Fresh", "entity_type": "company", "business_type": "service",
                                       "gst_type": "regular", "fy_start": "2026-04-01"}, headers=H).json()
    fbase = f"/clients/{fresh['client_id']}/financial-years/{fresh['financial_year_id']}/opening-balances"
    cash = fresh["ledger_ids"]["Cash"]
    both = api.put(f"{fbase}/{cash}", json={"debit": "10", "credit": "5"}, headers=H)
    assert (both.status_code, both.json()["message"]) == (422, "Enter either a Debit or a Credit opening balance, not both.")
    three = api.put(f"{fbase}/{cash}", json={"debit": "10.005"}, headers=H)
    assert (three.status_code, three.json()["code"]) == (422, "invalid_amount")
    as_number = api.put(f"{fbase}/{cash}", json={"debit": 100.5}, headers=H)  # a JSON number is never accepted
    assert as_number.status_code == 422 and "detail" in as_number.json()
    unknown = api.put(f"{fbase}/00000000-0000-0000-0000-000000000000", json={"debit": "1"}, headers=H)
    assert (unknown.status_code, unknown.json()["message"]) == (404, "Ledger not found for this client.")


# ================================================================================================== vouchers


def test_create_get_update_approve_post_a_voucher_through_the_api(api, b):
    vid = new_draft(api, b)
    voucher = api.get(f"/vouchers/{vid}").json()
    assert (voucher["status"], voucher["voucher_number"], voucher["created_by"], voucher["voucher_type"]) == ("draft", None, "tester", "payment")
    assert voucher["lines"] == [
        {"line_no": 1, "ledger_id": str(b.ids["Rent"]), "ledger_name": "Rent", "debit": "1250.50", "credit": "0.00"},
        {"line_no": 2, "ledger_id": str(b.ids["Cash"]), "ledger_name": "Cash", "debit": "0.00", "credit": "1250.50"},
    ]

    r = api.put(f"/vouchers/{vid}", json=payment(b, amount="999.99", narration="Edited"), headers=H)
    assert (r.status_code, r.json()) == (200, {"voucher_id": vid})
    edited = api.get(f"/vouchers/{vid}").json()
    assert edited["narration"] == "Edited" and edited["lines"][0]["debit"] == "999.99"

    assert api.post(f"/vouchers/{vid}/approve", headers={"X-User": "partner"}).json() == {"ok": True}
    assert api.get(f"/vouchers/{vid}").json()["approved_by"] == "partner"
    posted = api.post(f"/vouchers/{vid}/post", headers={"X-User": "partner"})
    assert (posted.status_code, posted.json()) == (200, {"voucher_number": "PAY/2026-27/0004"})
    assert api.get(f"/vouchers/{vid}").json()["status"] == "posted"


def test_create_voucher_with_rule_errors_is_422_with_the_error_list(api, b):
    bad = voucher_body(b, "payment", "2026-05-03", [("Rent", "10000", None), ("Cash", None, "9000")])
    r = api.post(f"/clients/{b.client_id}/vouchers", json=bad, headers=H)
    assert r.status_code == 422
    assert r.json() == {"errors": [{
        "rule_id": "V-04", "line_no": None,
        "message": "Debit 10,000.00 and Credit 9,000.00 are not equal (difference 1,000.00)"}]}


def test_rule_errors_carry_line_numbers_and_all_errors_are_returned(api, b):
    bad = voucher_body(b, "journal", "2027-04-01", [("Rent", "10.005", None), ("HDFC Bank", None, "5")], narration="")
    errors = api.post(f"/clients/{b.client_id}/vouchers", json=bad, headers=H).json()["errors"]
    assert [(e["rule_id"], e["line_no"]) for e in errors] == [("V-03", 1), ("V-06", None), ("V-09", None)]
    assert errors[0]["message"] == "Line 1: amount 10.005 has more than 2 decimal places."


def test_an_amount_sent_as_a_json_number_is_refused_not_rounded(api, b):
    body = payment(b)
    body["lines"][0]["debit"] = 1250.5
    r = api.post(f"/clients/{b.client_id}/vouchers", json=body, headers=H)
    assert r.status_code == 422 and "detail" in r.json() and "errors" not in r.json()


def test_an_unknown_voucher_type_is_refused(api, b):
    body = payment(b)
    body["voucher_type"] = "expense"
    assert api.post(f"/clients/{b.client_id}/vouchers", json=body, headers=H).status_code == 422


def test_V10_duplicate_is_422_until_an_override_reason_is_given(api, b):
    dup = voucher_body(b, "purchase", "2026-05-03", [("Purchases", "50000", None), ("Sharma Suppliers", None, "50000")],
                       reference_no="SUP/889", party="Sharma Suppliers")
    r = api.post(f"/clients/{b.client_id}/vouchers", json=dup, headers=H)
    assert r.status_code == 422
    assert r.json()["errors"] == [{"rule_id": "V-10", "line_no": None, "message": (
        "A Purchase voucher with Reference No 'SUP/889' and amount 50,000.00 for this party already exists: "
        "PUR/2026-27/0001 dated 03-04-2026. Save it anyway only with a reason.")}]
    dup["duplicate_override_reason"] = "Supplier billed twice"
    r = api.post(f"/clients/{b.client_id}/vouchers", json=dup, headers=H)
    assert r.status_code == 201
    assert api.get(f"/vouchers/{r.json()['voucher_id']}").json()["duplicate_override_reason"] == "Supplier billed twice"


def test_update_with_rule_errors_is_422_and_changes_nothing(api, b):
    vid = new_draft(api, b)
    bad = voucher_body(b, "payment", "2026-05-03", [("Rent", "5", None), ("Cash", None, "4")])
    r = api.put(f"/vouchers/{vid}", json=bad, headers=H)
    assert r.status_code == 422 and r.json()["errors"][0]["rule_id"] == "V-04"
    assert api.get(f"/vouchers/{vid}").json()["lines"][0]["debit"] == "1250.50"


def test_a_posted_voucher_cannot_be_edited_or_deleted(api, b):
    posted = str(b.voucher_ids["v1"])
    r = api.put(f"/vouchers/{posted}", json=payment(b), headers=H)
    assert (r.status_code, r.json()["code"]) == (409, "not_draft")
    assert r.json()["message"].startswith("Only a draft voucher can be edited; this voucher is posted.")
    r = api.delete(f"/vouchers/{posted}", headers=H)
    assert (r.status_code, r.json()["message"]) == (409, "Only a draft voucher can be deleted; this voucher is posted.")


def test_delete_a_draft_returns_204_and_it_is_gone(api, b):
    vid = new_draft(api, b)
    assert api.delete(f"/vouchers/{vid}", headers=H).status_code == 204
    assert api.get(f"/vouchers/{vid}").status_code == 404
    assert api.delete(f"/vouchers/{vid}", headers=H).status_code == 404


def test_lifecycle_state_errors_are_409(api, b):
    vid = new_draft(api, b)
    r = api.post(f"/vouchers/{vid}/post", headers=H)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (409, "not_approved", "Only an approved voucher can be posted (this one is draft).")
    api.post(f"/vouchers/{vid}/approve", headers=H)
    r = api.post(f"/vouchers/{vid}/approve", headers=H)
    assert (r.status_code, r.json()["message"]) == (409, "Only a draft voucher can be approved (this one is approved).")
    assert api.post(f"/vouchers/{vid}/return-to-draft", headers=H).json() == {"ok": True}
    assert api.get(f"/vouchers/{vid}").json()["status"] == "draft"
    r = api.post(f"/vouchers/{b.voucher_ids['v1']}/return-to-draft", headers=H)
    assert (r.status_code, r.json()["code"]) == (409, "not_approved")


def test_approve_that_fails_a_rule_recheck_is_422_with_errors(api, b, svc_conn):
    vid = new_draft(api, b)
    svc_conn.execute(text("UPDATE periods SET status = 'locked' WHERE id = :id"), {"id": b.period_ids["2026-05"]})
    r = api.post(f"/vouchers/{vid}/approve", headers=H)
    assert r.status_code == 422
    assert r.json() == {"errors": [{"rule_id": "V-07", "line_no": None, "message": "The period 01-05-2026 to 31-05-2026 is locked."}]}


def test_reverse_creates_the_mirror_voucher_and_marks_the_original_reversed(api, b):
    r = api.post(f"/vouchers/{b.voucher_ids['v1']}/reverse", json={"reversal_date": "2026-04-25", "reason": "wrong month"}, headers={"X-User": "partner"})
    assert r.status_code == 201
    reversal = api.get(f"/vouchers/{r.json()['reversal_voucher_id']}").json()
    assert (reversal["voucher_number"], reversal["narration"], reversal["status"]) == (
        "PAY/2026-27/0004", "Reversal of PAY/2026-27/0001: wrong month", "posted")
    assert [(x["ledger_name"], x["debit"], x["credit"]) for x in reversal["lines"]] == [
        ("Rent", "0.00", "20000.00"), ("Cash", "20000.00", "0.00")]
    original = api.get(f"/vouchers/{b.voucher_ids['v1']}").json()
    assert (original["status"], original["reversed_by_voucher_id"]) == ("reversed", reversal["id"])
    assert reversal["reverses_voucher_id"] == str(b.voucher_ids["v1"])


def test_reverse_refusals(api, b):
    once = api.post(f"/vouchers/{b.voucher_ids['v1']}/reverse", json={"reversal_date": "2026-04-25", "reason": "first"}, headers=H)
    assert once.status_code == 201
    again = api.post(f"/vouchers/{b.voucher_ids['v1']}/reverse", json={"reversal_date": "2026-04-26", "reason": "second"}, headers=H)
    assert (again.status_code, again.json()["code"], again.json()["message"]) == (
        409, "already_reversed", "Voucher PAY/2026-27/0001 has already been reversed by PAY/2026-27/0004.")
    draft = new_draft(api, b)
    r = api.post(f"/vouchers/{draft}/reverse", json={"reversal_date": "2026-05-04", "reason": "x"}, headers=H)
    assert (r.status_code, r.json()["code"]) == (409, "not_posted")
    r = api.post(f"/vouchers/{b.voucher_ids['v3']}/reverse", json={"reversal_date": "2026-05-04", "reason": " "}, headers=H)
    assert (r.status_code, r.json()["code"]) == (422, "reason_required")
    r = api.post(f"/vouchers/{b.voucher_ids['v3']}/reverse", json={"reversal_date": "2027-04-02", "reason": "next year"}, headers=H)
    assert r.status_code == 422 and [e["rule_id"] for e in r.json()["errors"]] == ["V-06"]


def test_reverse_into_a_locked_period_is_422_with_the_rule_error(api, b):
    assert api.post(f"/clients/{b.client_id}/periods/{b.period_ids['2026-05']}/lock", headers=H).status_code == 200
    r = api.post(f"/vouchers/{b.voucher_ids['v1']}/reverse", json={"reversal_date": "2026-05-10", "reason": "late"}, headers=H)
    assert r.status_code == 422
    assert r.json()["errors"][0]["message"] == "The period 01-05-2026 to 31-05-2026 is locked."


def test_get_voucher_unknown_or_malformed_is_404(api):
    for vid in ("00000000-0000-0000-0000-000000000000", "nope"):
        r = api.get(f"/vouchers/{vid}")
        assert (r.status_code, r.json()["message"]) == (404, "Voucher not found.")


# ------------------------------------------------------------------------------------------- voucher list

ALL_SEVEN = ["PAY/2026-27/0001", "PUR/2026-27/0001", "SAL/2026-27/0001", "REC/2026-27/0001",
             "PAY/2026-27/0002", "CON/2026-27/0001", "PAY/2026-27/0003"]


def test_list_vouchers_returns_the_seven_posted_vouchers_by_date(api, b):
    r = api.get(f"/clients/{b.client_id}/vouchers")
    body = r.json()
    assert body["total_count"] == 7 and numbers(r) == ALL_SEVEN
    assert body["items"][0] == {
        "id": str(b.voucher_ids["v1"]), "voucher_number": "PAY/2026-27/0001", "voucher_type": "payment",
        "voucher_date": "2026-04-02", "narration": "April rent", "reference_no": None, "status": "posted", "total": "20000.00"}
    assert [x["total"] for x in body["items"]] == ["20000.00", "50000.00", "80000.00", "30000.00", "15000.00", "10000.00", "5000.00"]
    assert body["items"][1]["reference_no"] == "SUP/889"


def test_list_vouchers_filters(api, b):
    url = f"/clients/{b.client_id}/vouchers"
    assert numbers(api.get(url, params={"type": "payment"})) == ["PAY/2026-27/0001", "PAY/2026-27/0002", "PAY/2026-27/0003"]
    assert numbers(api.get(url, params={"ledger_id": str(b.ids["Cash"])})) == ["PAY/2026-27/0001", "CON/2026-27/0001", "PAY/2026-27/0003"]
    assert numbers(api.get(url, params={"from": "2026-04-10", "to": "2026-04-15"})) == ["REC/2026-27/0001", "PAY/2026-27/0002", "CON/2026-27/0001"]
    assert api.get(url, params={"status": "posted"}).json()["total_count"] == 7
    assert api.get(url, params={"status": "draft"}).json() == {"items": [], "total_count": 0}
    both = api.get(url, params={"type": "payment", "ledger_id": str(b.ids["HDFC Bank"])})
    assert numbers(both) == ["PAY/2026-27/0002"]


def test_list_vouchers_paging_and_validation(api, b, other):
    url = f"/clients/{b.client_id}/vouchers"
    page = api.get(url, params={"limit": 2, "offset": 1})
    assert numbers(page) == ["PUR/2026-27/0001", "SAL/2026-27/0001"] and page.json()["total_count"] == 7
    assert api.get(url, params={"type": "expense"}).status_code == 422
    assert api.get(url, params={"ledger_id": "not-a-uuid"}).status_code == 404
    assert api.get(f"/clients/{other.client_id}/vouchers").json() == {"items": [], "total_count": 0}


def test_list_vouchers_shows_new_drafts_and_the_status_filter_finds_them(api, b):
    vid = new_draft(api, b, narration="Fresh draft")
    drafts = api.get(f"/clients/{b.client_id}/vouchers", params={"status": "draft"}).json()
    assert [x["id"] for x in drafts["items"]] == [vid] and drafts["items"][0]["voucher_number"] is None
    assert drafts["items"][0]["total"] == "1250.50"


# ================================================================================================== periods


def test_list_lock_and_unlock_periods(api, b):
    base = f"/clients/{b.client_id}/periods"
    periods = api.get(base, params={"fy_id": str(b.fy_id)}).json()
    assert len(periods) == 12
    assert periods[0] == {"id": str(b.period_ids["2026-04"]), "financial_year_id": str(b.fy_id), "start": "2026-04-01",
                          "end": "2026-04-30", "status": "open", "locked_at": None, "locked_by": None}
    assert api.post(f"{base}/{b.period_ids['2026-04']}/lock", headers={"X-User": "partner"}).json() == {"ok": True}
    april = api.get(base).json()[0]
    assert (april["status"], april["locked_by"]) == ("locked", "partner") and april["locked_at"] is not None
    again = api.post(f"{base}/{b.period_ids['2026-04']}/lock", headers=H)
    assert (again.status_code, again.json()["code"]) == (409, "already_locked")
    assert api.post(f"/clients/{b.client_id}/vouchers", json=payment(b, on="2026-04-28"), headers=H).status_code == 422

    blank = api.post(f"{base}/{b.period_ids['2026-04']}/unlock", json={"reason": " "}, headers=H)
    assert (blank.status_code, blank.json()["code"]) == (422, "reason_required")
    ok = api.post(f"{base}/{b.period_ids['2026-04']}/unlock", json={"reason": "Auditor request"}, headers=H)
    assert (ok.status_code, ok.json()) == (200, {"ok": True})
    assert api.get(base).json()[0]["status"] == "open"
    not_locked = api.post(f"{base}/{b.period_ids['2026-04']}/unlock", json={"reason": "again"}, headers=H)
    assert (not_locked.status_code, not_locked.json()["code"]) == (409, "not_locked")


def test_lock_period_with_open_vouchers_is_409_and_lists_them(api, b):
    vid = new_draft(api, b, on="2026-05-04", narration=MAY_DRAFT_NARRATION)
    r = api.post(f"/clients/{b.client_id}/periods/{b.period_ids['2026-05']}/lock", headers=H)
    assert (r.status_code, r.json()["code"]) == (409, "period_has_open_vouchers")
    assert r.json()["message"].startswith("The period 01-05-2026 to 31-05-2026 cannot be locked: 1 draft or approved voucher(s)")
    assert r.json()["details"] == [{"voucher_id": vid, "voucher_type": "payment", "voucher_date": "2026-05-04",
                                    "status": "draft", "narration": MAY_DRAFT_NARRATION}]


def test_periods_unknown_or_foreign_ids_are_404(api, b, other):
    assert api.post(f"/clients/{b.client_id}/periods/{other.period_ids['2026-04']}/lock", headers=H).status_code == 404
    assert api.post(f"/clients/{b.client_id}/periods/not-a-uuid/lock", headers=H).status_code == 404
    assert api.get("/clients/00000000-0000-0000-0000-000000000000/periods").status_code == 404


# ================================================================================================== reports


def test_ledger_statement_of_cash_matches_the_hand_calculation(api, b):
    r = api.get(f"/clients/{b.client_id}/reports/ledger-statement",
                params={"ledger_id": str(b.ids["Cash"]), "from": "2026-04-01", "to": "2026-04-30"})
    assert r.status_code == 200
    body = r.json()
    assert (body["ledger_name"], body["from_date"], body["to_date"]) == ("Cash", "2026-04-01", "2026-04-30")
    assert (body["opening"], body["closing"]) == ({"amount": "50000.00", "side": "Dr"}, {"amount": "15000.00", "side": "Dr"})
    assert (body["total_debit"], body["total_credit"]) == ("0.00", "35000.00")
    assert body["rows"] == [
        {"kind": "opening", "date": "2026-04-01", "voucher_number": None, "voucher_type": None, "narration": None,
         "particulars": "Opening Balance", "debit": "50000.00", "credit": "0.00", "balance": {"amount": "50000.00", "side": "Dr"}},
        {"kind": "entry", "date": "2026-04-02", "voucher_number": "PAY/2026-27/0001", "voucher_type": "payment",
         "narration": "April rent", "particulars": "By Rent", "debit": "0.00", "credit": "20000.00",
         "balance": {"amount": "30000.00", "side": "Dr"}},
        {"kind": "entry", "date": "2026-04-15", "voucher_number": "CON/2026-27/0001", "voucher_type": "contra",
         "narration": "Cash deposited", "particulars": "By HDFC Bank", "debit": "0.00", "credit": "10000.00",
         "balance": {"amount": "20000.00", "side": "Dr"}},
        {"kind": "entry", "date": "2026-04-20", "voucher_number": "PAY/2026-27/0003", "voucher_type": "payment",
         "narration": "Owner withdrew cash", "particulars": "By Drawings A/c", "debit": "0.00", "credit": "5000.00",
         "balance": {"amount": "15000.00", "side": "Dr"}},
        {"kind": "closing", "date": "2026-04-30", "voucher_number": None, "voucher_type": None, "narration": None,
         "particulars": "Closing Balance", "debit": "0.00", "credit": "0.00", "balance": {"amount": "15000.00", "side": "Dr"}},
    ]


def test_ledger_statement_refusals(api, b, other):
    url = f"/clients/{b.client_id}/reports/ledger-statement"
    cash = str(b.ids["Cash"])
    r = api.get(url, params={"ledger_id": cash, "from": "2026-04-30", "to": "2026-04-01"})
    assert (r.status_code, r.json()["code"]) == (422, "invalid_range")
    r = api.get(url, params={"ledger_id": cash, "from": "2026-04-01", "to": "2027-04-30"})
    assert r.status_code == 422 and "01-04-2026 to 31-03-2027" in r.json()["message"]
    r = api.get(url, params={"ledger_id": str(other.ids["Cash"]), "from": "2026-04-01", "to": "2026-04-30"})
    assert (r.status_code, r.json()["message"]) == (404, "Ledger not found for this client.")
    assert api.get(url, params={"ledger_id": cash}).status_code == 422  # missing dates


def test_trial_balance_of_the_mini_case_is_5_65_000_on_both_sides(api, b):
    body = api.get(f"/clients/{b.client_id}/reports/trial-balance", params={"as_on": "2026-04-30", "hide_zero": "true"}).json()
    assert (body["total_debit"], body["total_credit"], body["is_balanced"]) == ("565000.00", "565000.00", True)
    assert body["difference"] == NIL and body["as_on"] == "2026-04-30"
    assert [(s["group_name"], s["debit"], s["credit"]) for s in body["sections"]] == [
        ("Capital Account", "5000.00", "450000.00"), ("Current Liabilities", "0.00", "35000.00"),
        ("Current Assets", "490000.00", "0.00"), ("Sales Accounts", "0.00", "80000.00"),
        ("Purchase Accounts", "50000.00", "0.00"), ("Indirect Expenses", "20000.00", "0.00"),
    ]
    rows = {r["ledger_name"]: (r["debit"], r["credit"], r["group_path"]) for s in body["sections"] for r in s["rows"]}
    assert rows["Rahul Enterprises"] == ("50000.00", "0.00", ["Current Assets", "Sundry Debtors"])
    assert rows["Sharma Suppliers"] == ("0.00", "35000.00", ["Current Liabilities", "Sundry Creditors"])
    assert len(rows) == 10


def test_trial_balance_lists_nil_ledgers_unless_hidden_and_reflects_the_as_on_date(api, b):
    url = f"/clients/{b.client_id}/reports/trial-balance"
    full = api.get(url, params={"as_on": "2026-04-10"}).json()
    assert sum(len(s["rows"]) for s in full["sections"]) == 21
    assert (full["total_debit"], full["total_credit"]) == ("580000.00", "580000.00")


def test_trial_balance_refusals(api, b):
    url = f"/clients/{b.client_id}/reports/trial-balance"
    r = api.get(url, params={"as_on": "2027-04-01"})
    assert (r.status_code, r.json()["message"]) == (422, "No financial year of this client contains 01-04-2027.")
    assert api.get(url).status_code == 422  # as_on is required
    assert api.get("/clients/00000000-0000-0000-0000-000000000000/reports/trial-balance", params={"as_on": "2026-04-30"}).status_code == 404


# =============================================================================================== audit log


def test_audit_log_of_a_voucher_is_listed_newest_first(api, b):
    r = api.get(f"/clients/{b.client_id}/audit-log", params={"entity": "voucher", "entity_id": str(b.voucher_ids["v1"])})
    rows = r.json()
    assert [(x["action"], x["actor"]) for x in rows] == [("post", "partner"), ("approve", "partner"), ("create", "clerk")]
    assert rows[0]["entity"] == "voucher" and rows[0]["entity_id"] == str(b.voucher_ids["v1"])
    assert rows[0]["old_data"] == {"status": "approved"}
    assert rows[0]["new_data"] == {"status": "posted", "voucher_number": "PAY/2026-27/0001"}
    assert rows[2]["old_data"] is None and rows[2]["new_data"]["voucher_type"] == "payment"
    assert set(rows[0]) == {"id", "actor", "action", "entity", "entity_id", "old_data", "new_data", "created_at"}


def test_audit_log_filters_limit_and_new_entries_from_the_api(api, b):
    api.post(f"/clients/{b.client_id}/periods/{b.period_ids['2026-04']}/lock", headers={"X-User": "partner"})
    periods = api.get(f"/clients/{b.client_id}/audit-log", params={"entity": "period"}).json()
    assert [(x["action"], x["actor"]) for x in periods if x["action"] == "lock"] == [("lock", "partner")]
    assert len(api.get(f"/clients/{b.client_id}/audit-log", params={"limit": 1}).json()) == 1
    everything = api.get(f"/clients/{b.client_id}/audit-log", params={"limit": 500}).json()
    assert {x["entity"] for x in everything} >= {"client", "financial_year", "period", "ledger", "voucher", "opening_balance"}
    assert [x["id"] for x in everything] == sorted((x["id"] for x in everything), reverse=True)
    assert api.get("/clients/00000000-0000-0000-0000-000000000000/audit-log").status_code == 404
