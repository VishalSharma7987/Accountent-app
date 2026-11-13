"""Package E integration: 26AS / AIS import, reconciliation and links through the API with the rolled-back connection.

Dependencies: migrations 0012-0014 and seed 0008 (section table) applied. Package B's deduction items and package A's deductee
master are written here with raw SQL (the books side reads them); no other package's code is needed.
Run only this file: C:/temp/Account/scripts/dbrun.sh pytest -m integration tests/integration/test_tds_recon_db.py
"""

import uuid

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}
PAN_RAJ, PAN_SITA = "ABCPR1234F", "ABCPS5678G"
TAN = "MUMA12345B"
ITEM_SQL = (
    "INSERT INTO tds_voucher_items (id, client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
    "financial_year_id, event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, rate_applied, "
    "rate_reason, tds_amount, tds_line_no, engine_version) VALUES (%s, %s, %s, 1, 'tds', %s, 'contractor', 'it_act_1961', '194C', "
    "%s, %s, %s, %s, 0, %s, %s, 1, 'normal', %s, 1, 't')"
)
CUSTOMER_CR = {"1000.00": "10000.00", "5000.00": "14000.00"}  # 9,000.00 in the bank plus the tax receivable
HEADER = "Deductee PAN,Section,Transaction Date,Amount Paid/Credited,Tax Deducted,Tax Deposited"


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[deps.get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def deduction(f: Factory, client_id, fy_id, party, on: str, paid: str, tax: str) -> tuple:
    """A voucher with one deduction item (194C, 1 percent); posted."""
    vid = f.draft(client_id, fy_id, f.balanced_lines(client_id), vtype="payment", on=on)
    item_id = uuid.uuid4()
    f.conn.execute(ITEM_SQL, (item_id, client_id, vid, party, fy_id, on, on, paid, paid, paid, tax))
    f.approve(vid)
    f.post(vid, f"PAY/2026-27/{uuid.uuid4().int % 10000:04d}")
    check_deferred(f.conn)
    return item_id, vid


@pytest.fixture
def world(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    client_id, fy_id = f.setup()
    f.conn.execute("UPDATE clients SET tan = %s WHERE id = %s", (TAN, client_id))
    raj = f.ledger(client_id, "Raj Contractors", "sundry_creditors")
    sita = f.ledger(client_id, "Sita Services", "sundry_creditors")
    for ledger, pan in ((raj, PAN_RAJ), (sita, PAN_SITA)):
        f.conn.execute("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) "
                       "VALUES (%s, %s, %s, 'valid', 'individual')", (ledger, client_id, pan))
    apr, _ = deduction(f, client_id, fy_id, raj, "2026-04-20", "100000.00", "1000.00")
    may, _ = deduction(f, client_id, fy_id, raj, "2026-05-10", "50000.00", "500.00")
    jun, _ = deduction(f, client_id, fy_id, sita, "2026-06-03", "6000.00", "60.00")
    return f, client_id, fy_id, apr, may, jun


def upload(api, client_id, fy_id, text: str, side="deductor", name="26as.csv"):
    return api.post(f"/clients/{client_id}/tds/26as/import", headers=H, data={"financial_year_id": str(fy_id), "side": side, "source": "form_26as"},
                    files={"file": (name, text.encode(), "text/csv")})


STATEMENT = (
    f"{HEADER}\n"
    f"{PAN_RAJ},194C,20-04-2026,\"1,00,000.00\",1000.00,1000.00\n"  # matches the April item
    f"{PAN_RAJ},194C,10-05-2026,50000.00,400.00,400.00\n"  # books say 500.00: amount mismatch
    "CCCPC3333C,194C,12-06-2026,2000.00,40.00,40.00\n"  # PAN not in the master
    f"{PAN_SITA},194J,05-06-2026,6000.00,600.00,600.00\n"  # printed 194J maps to no single nature
)


def test_T40_T41_T42_import_reconcile_duplicate_refused(api, world):
    _, client_id, fy_id, apr, may, jun = world
    response = upload(api, client_id, fy_id, STATEMENT)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rows"] == 4 and body["totals"] == {"amount_paid": "158000.00", "tax_deducted": "2040.00", "tax_deposited": "2040.00"}

    again = upload(api, client_id, fy_id, STATEMENT)
    assert again.status_code == 409 and again.json()["code"] == "import_duplicate"

    listing = api.get(f"/clients/{client_id}/tds/26as/imports", params={"financial_year_id": str(fy_id)}).json()
    assert [(r["side"], r["source"], r["row_count"]) for r in listing] == [("deductor", "form_26as", 4)]
    rows = api.get(f"/clients/{client_id}/tds/26as/imports/{body['import_id']}/rows").json()
    assert [(r["row_no"], r["section_ref"], r["tax_deducted"]) for r in rows] == [
        (1, "194C", "1000.00"), (2, "194C", "400.00"), (3, "194C", "40.00"), (4, "194J", "600.00")]

    recon = api.get(f"/clients/{client_id}/tds/26as/reconciliation", params={"financial_year_id": str(fy_id)}).json()
    assert recon["tolerance"] == "1.00" and recon["side"] == "deductor"
    assert recon["summary"] == {"matched": 1, "amount_mismatch": 1, "only_in_books": 1, "only_in_26as": 2, "date_mismatch": 0}
    by_class: dict[str, list] = {}
    for r in recon["rows"]:
        by_class.setdefault(r["class"], []).append(r)
    assert by_class["matched"][0]["books"]["item_id"] == str(apr) and by_class["matched"][0]["difference"] == "0.00"
    mismatch = by_class["amount_mismatch"][0]
    assert (mismatch["books"]["item_id"], mismatch["difference"], mismatch["paid_difference"]) == (str(may), "-100.00", "0.00")
    assert by_class["only_in_books"][0]["books"]["item_id"] == str(jun)
    assert sorted((r["reason"], r["section_mapping_status"]) for r in by_class["only_in_26as"]) == [
        ("unknown_pan", "mapped"), ("unmapped_section", "unmapped")]
    assert recon["rule_status"]["worst"] == "pending" and recon["rule_status"]["tables"] == {"section_map": "pending"}


def test_T40_rejections_wrong_tan_outside_year_missing_pan_unknown_side(api, world):
    _, client_id, fy_id, *_ = world
    other_tan = f"Deductor TAN,{HEADER}\nDELD54321C,{PAN_RAJ},194C,20-04-2026,1,1,1\n"
    response = upload(api, client_id, fy_id, other_tan)
    assert response.status_code == 422 and response.json()["code"] == "import_invalid"
    assert "is not this client's TAN MUMA12345B" in response.json()["message"]
    outside = upload(api, client_id, fy_id, f"{HEADER}\n{PAN_RAJ},194C,20-03-2026,1,1,1\n")
    assert outside.status_code == 422 and "outside the financial year 01-04-2026 to 31-03-2027" in outside.json()["message"]
    no_pan = upload(api, client_id, fy_id, "Deductor TAN,Section,Transaction Date,Amount Paid,Tax Deducted,Tax Deposited\n"
                    f"{TAN},194C,20-04-2026,1,1,1\n")
    assert no_pan.status_code == 422 and "deductee PAN is missing" in no_pan.json()["message"]
    unknown = upload(api, client_id, fy_id, f"{HEADER}\n{PAN_RAJ},194C,20-04-2026,1,1,1\n", side="sideways")
    assert unknown.status_code == 422 and unknown.json()["code"] == "invalid_side"
    garbage = upload(api, client_id, fy_id, f"{HEADER}\n{PAN_RAJ},194C,20-04-2026,1,10.005,1\n")
    assert garbage.status_code == 422 and garbage.json()["details"][0]["row"] == 2
    assert api.get(f"/clients/{client_id}/tds/26as/imports").json() == []


def test_T43_manual_link_accepted_difference_one_to_one_and_delete(api, world):
    _, client_id, fy_id, apr, may, jun = world
    imp = upload(api, client_id, fy_id, STATEMENT).json()["import_id"]
    rows = {r["row_no"]: r["id"] for r in api.get(f"/clients/{client_id}/tds/26as/imports/{imp}/rows").json()}
    link = api.post(f"/clients/{client_id}/tds/26as/links", headers=H,
                    json={"row_id": rows[4], "item_id": str(jun), "link_kind": "accepted_difference", "note": "client booked 1 percent, deductor 10"})
    assert link.status_code == 201, link.text
    clash = api.post(f"/clients/{client_id}/tds/26as/links", headers=H,
                     json={"row_id": rows[3], "item_id": str(jun), "link_kind": "manual", "note": "x"})
    assert clash.status_code == 409 and clash.json()["code"] == "link_exists"
    blank = api.post(f"/clients/{client_id}/tds/26as/links", headers=H,
                     json={"row_id": rows[3], "item_id": str(may), "link_kind": "manual", "note": " "})
    assert blank.status_code == 422
    both = api.post(f"/clients/{client_id}/tds/26as/links", headers=H,
                    json={"row_id": rows[3], "item_id": str(may), "voucher_id": str(uuid.uuid4()), "link_kind": "manual", "note": "x"})
    assert both.status_code == 422
    recon = api.get(f"/clients/{client_id}/tds/26as/reconciliation", params={"financial_year_id": str(fy_id)}).json()
    assert recon["summary"] == {"matched": 2, "amount_mismatch": 1, "only_in_books": 0, "only_in_26as": 1, "date_mismatch": 0}
    linked = next(r for r in recon["rows"] if r["link_id"] == link.json()["link_id"])
    assert (linked["class"], linked["link_kind"], linked["difference"], linked["paid_difference"]) == ("matched", "accepted_difference", "540.00", "0.00")
    assert api.delete(f"/clients/{client_id}/tds/26as/links/{link.json()['link_id']}", headers=H).status_code == 204
    assert api.delete(f"/clients/{client_id}/tds/26as/links/{link.json()['link_id']}", headers=H).status_code == 404


def test_T42_deductee_side_matches_receivable_vouchers_on_month_and_amount(api, svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    client_id, fy_id = f.setup()
    receivable = f.ledger(client_id, "TDS Receivable", "loans_advances_asset")
    f.conn.execute("INSERT INTO tds_ledger_roles (client_id, role, ledger_id) VALUES (%s, 'tds_receivable', %s)", (client_id, receivable))
    bank = f.ledger(client_id, "Bank", "bank_accounts")
    customer = f.ledger(client_id, "Customer", "sundry_debtors")
    for on, tax in (("2026-04-25", "1000.00"), ("2026-06-02", "5000.00")):
        vid = f.draft(client_id, fy_id, [(bank, "9000.00", "0.00"), (receivable, tax, "0.00"), (customer, "0.00", CUSTOMER_CR[tax])],
                      vtype="receipt", on=on)
        f.approve(vid)
        f.post(vid, f"REC/2026-27/{uuid.uuid4().int % 10000:04d}")
    check_deferred(f.conn)
    statement = ("Deductor TAN,Section,Transaction Date,Amount Paid,Tax Deducted,Tax Deposited\n"
                 "DELD54321C,194C,20-04-2026,100000.00,1000.00,1000.00\n"
                 "DELD54321C,194C,10-05-2026,50000.00,5000.00,5000.00\n")
    assert upload(api, client_id, fy_id, statement, side="deductee").status_code == 201
    recon = api.get(f"/clients/{client_id}/tds/26as/reconciliation", params={"financial_year_id": str(fy_id)}).json()
    assert recon["side"] == "deductee"
    assert recon["summary"] == {"matched": 1, "amount_mismatch": 0, "only_in_books": 0, "only_in_26as": 0, "date_mismatch": 1}
    assert [r["section_mapping_status"] for r in recon["rows"]] == ["not_applicable", "not_applicable"]
    assert recon["rule_status"] == {"worst": "verified", "tables": {}, "pending_sources": []}
