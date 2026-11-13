"""Package D integration: GSTR-2B import, reconciliation, links through the API with the rolled-back connection.

Dependencies: needs migrations 0009-0011 (applied). Package B's voucher_gst / voucher_item_lines are written here with raw SQL
(the books side reads them); package C's `apply_2b_result` is not required (apply returns the effects, applied = false).
Run only this file: C:/temp/Account/scripts/dbrun.sh pytest -m integration tests/integration/test_gst_recon.py
"""

import uuid
from pathlib import Path

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app

pytestmark = pytest.mark.integration

GSTIN = "27AAPFU0939F1ZV"
SUPPLIER = "29AAACB1234C1Z5"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gstr2b" / "gstr2b_sample_042026.json"
H = {"X-User": "tester"}


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[deps.get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def purchase(f: Factory, client_id, fy_id, registration_id, ref: str, on: str, taxable: str, igst: str):
    """A posted Purchase with a voucher_gst header and one item line (18 percent IGST)."""
    a = f.ledger(client_id, f"Purchases {uuid.uuid4().hex[:6]}", "purchase_accounts")
    b = f.ledger(client_id, f"Supplier {uuid.uuid4().hex[:6]}", "sundry_creditors")
    vid = f.draft(client_id, fy_id, [(a, taxable, "0.00"), (b, "0.00", taxable)], vtype="purchase", on=on)
    f.conn.execute("UPDATE vouchers SET reference_no = %s WHERE id = %s", (ref, vid))
    f.conn.execute(
        "INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, counterparty_gstin, "
        "place_of_supply, invoice_date, invoice_value, engine_version) VALUES (%s, %s, %s, 'tax_invoice', 'b2b', %s, '27', %s, 1, 't')",
        (vid, client_id, registration_id, SUPPLIER, on),
    )
    f.conn.execute(
        "INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, description, hsn_sac, quantity, unit_rate, gross_amount, "
        "taxable_value, ledger_id, treatment, gst_rate, igst) VALUES (%s, %s, 1, 'Goods', '3004', 1, %s, %s, %s, %s, 'taxable', 18, %s)",
        (client_id, vid, taxable, taxable, taxable, a, igst),
    )
    f.approve(vid)
    f.post(vid, f"PUR/2026-27/{uuid.uuid4().int % 10000:04d}")
    check_deferred(f.conn)
    return vid


@pytest.fixture
def world(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    client_id, fy_id = f.setup()
    reg = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
        "VALUES (%s, %s, %s, '27', 'regular', '2026-04-01')", (reg, client_id, GSTIN))
    inv1 = purchase(f, client_id, fy_id, reg, "inv/001", "2026-04-10", "1000.00", "180.00")  # in the 2B: INV-001
    bill9 = purchase(f, client_id, fy_id, reg, "BILL-9", "2026-04-15", "500.00", "90.00")  # only in books
    return f, client_id, reg, inv1, bill9


def upload(api, client_id, reg, content: bytes, name="gstr2b.json", period="2026-04", kind="gstr2b"):
    return api.post(f"/clients/{client_id}/gst/2b/import", headers=H, data={"registration_id": str(reg), "period": period, "kind": kind},
                    files={"file": (name, content, "application/json")})


def test_G40_G41_G42_import_reconcile_and_duplicate_refused(api, world):
    _, client_id, reg, inv1, bill9 = world
    response = upload(api, client_id, reg, FIXTURE.read_bytes())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["documents"] == 3 and body["period"] == "2026-04"
    assert body["totals"] == {"taxable_value": "3100.00", "igst": "558.00", "cgst": "0.00", "sgst": "0.00", "cess": "0.00"}

    again = upload(api, client_id, reg, FIXTURE.read_bytes())
    assert again.status_code == 409 and again.json()["code"] == "import_duplicate"

    listing = api.get(f"/clients/{client_id}/gst/2b/imports", params={"registration_id": str(reg)}).json()
    assert [(r["kind"], r["period"], r["document_count"]) for r in listing] == [("gstr2b", "2026-04", 3)]
    docs = api.get(f"/clients/{client_id}/gst/2b/imports/{body['import_id']}/documents").json()
    assert [d["doc_no"] for d in docs] == ["INV-001", "INV-002", "CN-01"]

    recon = api.get(f"/clients/{client_id}/gst/2b/reconciliation", params={"registration_id": str(reg), "period": "2026-04"}).json()
    assert recon["summary"] == {"matched": 1, "value_mismatch": 0, "gstin_mismatch": 0, "period_mismatch": 0,
                                "only_in_books": 1, "only_in_2b": 2, "ambiguous": 0}
    by_class = {}
    for row in recon["rows"]:
        by_class.setdefault(row["class"], []).append(row)
    assert by_class["matched"][0]["books"]["voucher_id"] == str(inv1)
    assert by_class["only_in_books"][0]["books"]["voucher_id"] == str(bill9)
    assert by_class["matched"][0]["doc_2b"]["itc_available"] == "yes"
    # books 1000 + 500 taxable; 2B 1000 + 2000 - 100 (credit note subtracted)
    assert recon["totals"]["books"]["taxable_value"] == "1500.00"
    assert recon["totals"]["doc_2b"]["taxable_value"] == "2900.00"

    applied = api.post(f"/clients/{client_id}/gst/2b/apply", headers=H, params={"registration_id": str(reg), "period": "2026-04"}).json()
    assert [(e["voucher_id"], e["supplier_tax_paid"], e["pending_reason"]) for e in applied["effects"]] == [
        (str(inv1), "in_2b", None), (str(bill9), "not_in_2b", "not_in_2b")]


def test_G40_wrong_recipient_wrong_period_and_ims_rejected(api, world):
    _, client_id, reg, _, _ = world
    other = FIXTURE.read_text(encoding="utf-8").replace(GSTIN, "29AAACB1234C1Z5")
    response = upload(api, client_id, reg, other.encode())
    assert response.status_code == 422 and response.json()["code"] == "import_invalid"
    assert "is for GSTIN 29AAACB1234C1Z5" in response.json()["message"]
    response = upload(api, client_id, reg, FIXTURE.read_bytes(), period="2026-05")
    assert response.status_code == 422 and "2026-04" in response.json()["message"]
    response = upload(api, client_id, reg, FIXTURE.read_bytes(), kind="ims")
    assert response.status_code == 422 and "IMS" in response.json()["message"]
    assert api.get(f"/clients/{client_id}/gst/2b/imports").json() == []


def test_G43_manual_link_one_to_one_accepted_difference_and_delete(api, world):
    _, client_id, reg, inv1, bill9 = world
    imp = upload(api, client_id, reg, FIXTURE.read_bytes()).json()["import_id"]
    docs = {d["doc_no"]: d["id"] for d in api.get(f"/clients/{client_id}/gst/2b/imports/{imp}/documents").json()}
    link = api.post(f"/clients/{client_id}/gst/2b/links", headers=H,
                    json={"document_id": docs["INV-002"], "voucher_id": str(bill9), "link_kind": "accepted_difference", "note": "same bill"})
    assert link.status_code == 201, link.text
    clash = api.post(f"/clients/{client_id}/gst/2b/links", headers=H,
                     json={"document_id": docs["INV-002"], "voucher_id": str(inv1), "link_kind": "manual", "note": "x"})
    assert clash.status_code == 409 and clash.json()["code"] == "link_exists"
    blank = api.post(f"/clients/{client_id}/gst/2b/links", headers=H,
                     json={"document_id": docs["CN-01"], "voucher_id": str(inv1), "link_kind": "manual", "note": " "})
    assert blank.status_code == 422
    recon = api.get(f"/clients/{client_id}/gst/2b/reconciliation", params={"registration_id": str(reg), "period": "2026-04"}).json()
    linked = [r for r in recon["rows"] if r["link_id"] == link.json()["link_id"]]
    assert linked[0]["class"] == "matched" and len(linked[0]["differences"]) == 2  # taxable 2000 vs 500, igst 360 vs 90
    assert api.delete(f"/clients/{client_id}/gst/2b/links/{link.json()['link_id']}", headers=H).status_code == 204
    assert api.delete(f"/clients/{client_id}/gst/2b/links/{link.json()['link_id']}", headers=H).status_code == 404
