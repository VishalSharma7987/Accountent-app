"""Phase 4 package D against the database: return working, versions, finalise (locks challans), filed figures, certificates.

Rows are written with raw SQL (not package B's / C's services) so these tests need only the 0012-0014 schema and seeds.
Everything runs in one rolled-back transaction. Expected values typed literally (hand-calculated).

World: contractor payments in Q1 FY 2026-27 (Act 2025 forms): Alpha (valid PAN) 1,00,000.00 -> tax 1,000.00 on 10-05-2026;
Beta (PAN missing) 50,000.00 -> tax 10,000.00 on 20-05-2026. Challan C1 tax 7,000.00 allocated 1,000.00 to Alpha and 6,000.00
to Beta; challan C2 tax 500.00 not allocated. A draft item (5,000.00 / tax 50.00) is not in the working.
"""

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api.deps import get_conn
from app.main import app
from app.services import tds_export, tds_returns
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}


def _item(raw, client, fy, voucher, item_no, ledger, paid, rate, tds, event, line_no):
    item_id = uuid.uuid4()
    raw.execute(
        "INSERT INTO tds_voucher_items (id, client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
        "rate_rule_id, financial_year_id, event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, "
        "rate_applied, rate_reason, tds_amount, tds_line_no, engine_version) "
        "VALUES (%s, %s, %s, %s, 'tds', %s, 'contractor', 'it_act_2025', '393(1)', "
        "(SELECT id FROM tds_rates WHERE nature_key = 'contractor' AND act = 'it_act_2025' AND deductee_group = 'individual_huf'), "
        "%s, %s, %s, %s, 0, %s, %s, %s, 'normal', %s, %s, 'tds-1')",
        (item_id, client, voucher, item_no, ledger, fy, event, event, paid, paid, paid, rate, tds, line_no))
    return item_id


def _payment(f, client, fy, party, bank, tds_ledger, paid, tds, on):
    net = f"{Decimal(paid) - Decimal(tds):.2f}"
    return f.draft(client, fy, [(party, paid, "0.00"), (bank, "0.00", net), (tds_ledger, "0.00", tds)], vtype="payment", on=on)


@pytest.fixture
def world(svc_conn):
    raw = svc_conn.connection.driver_connection
    f = Factory(raw)
    client, fy = f.setup()
    raw.execute("UPDATE clients SET tan = 'DELA12345B', pan = 'AAACA1234A', legal_name = 'Acme Traders Pvt Ltd' WHERE id = %s", (client,))
    alpha = f.ledger(client, "Alpha Contractors", "sundry_creditors")
    beta = f.ledger(client, "Beta Works", "sundry_creditors")
    bank = f.ledger(client, "HDFC Bank", "bank_accounts")
    tds_payable = f.ledger(client, "TDS Payable", "duties_taxes")
    raw.execute("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (%s, %s, 'AAAPA1111A', 'valid', 'individual')",
                (alpha, client))
    raw.execute("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (%s, %s, NULL, 'missing', 'company')",
                (beta, client))
    v1 = _payment(f, client, fy, alpha, bank, tds_payable, "100000.00", "1000.00", "2026-05-10")
    i1 = _item(raw, client, fy, v1, 1, alpha, "100000.00", "1", "1000.00", "2026-05-10", 3)
    v2 = _payment(f, client, fy, beta, bank, tds_payable, "50000.00", "10000.00", "2026-05-20")
    i2 = _item(raw, client, fy, v2, 1, beta, "50000.00", "20", "10000.00", "2026-05-20", 3)
    v3 = _payment(f, client, fy, alpha, bank, tds_payable, "5000.00", "50.00", "2026-05-25")  # stays draft
    _item(raw, client, fy, v3, 1, alpha, "5000.00", "1", "50.00", "2026-05-25", 3)
    for v in (v1, v2):
        f.approve(v)
        f.post(v)
    check_deferred(raw)
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    for cid, tax, serial in ((c1, "7000.00", "00041"), (c2, "500.00", "00042")):
        raw.execute(
            "INSERT INTO tds_challans (id, client_id, kind, financial_year_id, quarter, bsr_code, deposit_date, challan_serial_no, "
            "tax_amount, total_amount, created_by) VALUES (%s, %s, 'tds', %s, 1, '0510308', '2026-06-07', %s, %s, %s, 'tester')",
            (cid, client, fy, serial, tax, tax))
    for item, amount in ((i1, "1000.00"), (i2, "6000.00")):
        raw.execute("INSERT INTO tds_challan_allocations (client_id, challan_id, item_id, amount, created_by) VALUES (%s, %s, %s, %s, 'tester')",
                    (client, c1, item, amount))
    return {"raw": raw, "client": client, "fy": fy, "alpha": alpha, "beta": beta, "c1": c1, "c2": c2}


def test_T31_T32_T30_working_shows_form_140_rows_totals_errors_and_rule_status(world, svc_conn):
    w = world
    r = tds_returns.return_working(svc_conn, w["client"], w["fy"], 1, "non_salary_resident")
    assert (r["form_no"], r["form_status"], r["tan"], r["quarter"], r["financial_year"]) == ("Form 140", "secondary_verified", "DELA12345B", 1, "2026-27")
    assert (r["period_start"], r["period_end"]) == ("2026-04-01", "2026-06-30")
    assert [(x["deductee_name"], x["amount_paid"], x["tax_deducted"], x["tax_deposited"]) for x in r["deductee_rows"]] == [
        ("Alpha Contractors", "100000.00", "1000.00", "1000.00"), ("Beta Works", "50000.00", "10000.00", "6000.00")]
    assert r["deductee_rows"][1]["error_row"] is True and r["deductee_rows"][0]["pan"] == "AAAPA1111A"
    assert r["totals"]["amount_paid"] == "150000.00" and r["totals"]["tax_deducted"] == "11000.00"
    assert r["totals"]["tax_deposited"] == "7000.00" and r["totals"]["short_deposit"] == "4000.00"
    assert r["totals"]["challan_tax"] == "7500.00" and r["totals"]["challan_count"] == 2
    assert [e["rule_id"] for e in r["errors"]] == ["T-30"] and r["errors"][0]["blocking"] is False
    assert sorted(x["rule_id"] for x in r["warnings"]) == ["T-32", "T-32", "T-50"]
    assert r["rule_status"]["tables"]["form"] == "secondary_verified"
    assert r["rule_status"]["worst"] == "pending" and r["rule_status"]["tables"]["payment_code"] == "pending"
    # the draft voucher's item is not in the figures
    assert r["totals"]["row_count"] == 2


def test_T31_quarter_two_has_no_rows_and_other_kinds_are_empty(world, svc_conn):
    w = world
    r = tds_returns.return_working(svc_conn, w["client"], w["fy"], 2, "non_salary_resident")
    assert r["deductee_rows"] == [] and r["totals"]["tax_deducted"] == "0.00" and r["challan_rows"] == []
    assert tds_returns.return_working(svc_conn, w["client"], w["fy"], 1, "salary")["deductee_rows"] == []
    with pytest.raises(ServiceError) as e:
        tds_returns.return_working(svc_conn, w["client"], w["fy"], 5, "salary")
    assert e.value.code == "period_invalid"


def test_T33_versions_finalise_locks_challans_stale_and_final_are_refused_and_filed_figures_compare(world, svc_conn):
    w = world
    v1 = tds_returns.save_working(svc_conn, w["client"], w["fy"], 1, "non_salary_resident", "tester")
    v2 = tds_returns.save_working(svc_conn, w["client"], w["fy"], 1, "non_salary_resident", "tester")
    assert (v1["version"], v2["version"]) == (1, 2)
    out = tds_returns.finalise_working(svc_conn, uuid.UUID(v2["working_id"]), "tester")
    assert out["status"] == "final" and out["locked_challans"] == 2
    statuses = {r[0]: r[1] for r in svc_conn.connection.driver_connection.execute(
        "SELECT id, status FROM tds_challans WHERE client_id = %s", (w["client"],)).fetchall()}
    assert statuses == {w["c1"]: "locked", w["c2"]: "locked"}
    with pytest.raises(ServiceError) as e:
        tds_returns.finalise_working(svc_conn, uuid.UUID(v2["working_id"]), "tester")
    assert e.value.code == "working_final"
    with pytest.raises(ServiceError) as e2:
        tds_returns.finalise_working(svc_conn, uuid.UUID(v1["working_id"]), "tester")
    assert e2.value.code == "working_stale"
    saved = tds_returns.get_working(svc_conn, uuid.UUID(v2["working_id"]))
    assert saved["status"] == "final" and saved["totals"]["tax_deducted"] == "11000.00"
    # filed figures: typed 10,900.00 against a working of 11,000.00
    tds_returns.put_filed(svc_conn, w["client"], w["fy"], 1, "non_salary_resident", "RCPT1", None, {"tax_deducted": "10900.00"}, "tester")
    got = tds_returns.get_filed(svc_conn, w["client"], w["fy"], 1, "non_salary_resident")
    assert got["receipt_no"] == "RCPT1" and got["differences"] == {"tax_deducted": "-100.00"} and got["working"]["version"] == 2
    with pytest.raises(ServiceError) as e3:
        tds_returns.put_filed(svc_conn, w["client"], w["fy"], 1, "non_salary_resident", None, None, {"tax_deducted": 10900.5}, "tester")
    assert e3.value.code == "invalid_data"
    with pytest.raises(ServiceError) as e4:
        tds_returns.put_filed(svc_conn, w["client"], w["fy"], 1, "non_salary_resident", None, None, {"tax_deducted": "10.005"}, "tester")
    assert e4.value.code == "invalid_data"
    audit = svc_conn.connection.driver_connection.execute(
        "SELECT action, entity FROM audit_log WHERE client_id = %s ORDER BY id", (w["client"],)).fetchall()
    assert [("create", "tds_return_working"), ("create", "tds_return_working"), ("finalise", "tds_return_working"),
            ("create", "tds_filed_return")] == [tuple(a) for a in audit]


def test_T30_finalise_is_refused_without_tan(world, svc_conn):
    w = world
    svc_conn.connection.driver_connection.execute("UPDATE clients SET tan = NULL WHERE id = %s", (w["client"],))
    saved = tds_returns.save_working(svc_conn, w["client"], w["fy"], 1, "non_salary_resident", "tester")
    with pytest.raises(VoucherRuleError) as e:
        tds_returns.finalise_working(svc_conn, uuid.UUID(saved["working_id"]), "tester")
    assert [x.rule_id for x in e.value.errors] == ["T-30"]


def test_T34_certificate_only_for_fully_deposited_items_versions_and_number_update(world, svc_conn):
    w = world
    p = tds_returns.certificate_preview(svc_conn, w["client"], w["alpha"], w["fy"], 1, "non_salary")
    assert (p["form_no"], p["total_deducted"], p["total_deposited"], p["total_amount_paid"]) == ("Form 131", "1000.00", "1000.00", "100000.00")
    assert p["deductor"] == {"name": "Acme Traders Pvt Ltd", "tan": "DELA12345B", "pan": "AAACA1234A"}
    assert p["challans"] == [{"bsr_code": "0510308", "deposit_date": "2026-06-07", "serial_no": "00041", "tax_deposited": "1000.00"}]
    with pytest.raises(VoucherRuleError) as e:
        tds_returns.certificate_preview(svc_conn, w["client"], w["beta"], w["fy"], 1, "non_salary")
    assert [x.rule_id for x in e.value.errors] == ["T-34"] and "4,000.00" in e.value.errors[0].message
    c1 = tds_returns.create_certificate(svc_conn, w["client"], w["alpha"], w["fy"], 1, "non_salary", "tester")
    c2 = tds_returns.create_certificate(svc_conn, w["client"], w["alpha"], w["fy"], 1, "non_salary", "tester")
    assert (c1["version"], c2["version"]) == (1, 2)
    tds_returns.update_certificate(svc_conn, w["client"], uuid.UUID(c2["id"]), "CERT-9", date(2026, 7, 20), "tester")
    got = tds_returns.get_certificate(svc_conn, w["client"], uuid.UUID(c2["id"]))
    assert (got["certificate_no"], got["issued_on"], got["total_deducted"], got["form_no"]) == ("CERT-9", "2026-07-20", "1000.00", "Form 131")
    listed = tds_returns.list_certificates(svc_conn, w["client"], w["fy"], 1, None, None)
    assert [(x["version"], x["certificate_no"]) for x in listed] == [(2, "CERT-9"), (1, None)]
    wb = load_workbook(io.BytesIO(tds_export.certificate_to_xlsx(got)))
    assert ["Certificate no", "CERT-9"] in [list(r) for r in wb["Summary"].iter_rows(values_only=True)]
    raw = svc_conn.connection.driver_connection
    with pytest.raises(Exception, match="only the certificate number"):
        raw.execute("UPDATE tds_certificates SET data = '{}'::jsonb WHERE id = %s", (c1["id"],))


def test_T31_T50_http_working_export_and_certificate_paths(world, svc_conn):
    w = world
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        base = f"/clients/{w['client']}/tds"
        r = api.get(f"{base}/return-working", params={"financial_year_id": str(w["fy"]), "quarter": 1, "return_kind": "non_salary_resident"})
        assert r.status_code == 200 and r.json()["form_no"] == "Form 140"
        saved = api.post(f"{base}/return-workings", json={"financial_year_id": str(w["fy"]), "quarter": 1, "return_kind": "non_salary_resident"},
                         headers=H)
        assert saved.status_code == 201 and saved.json()["version"] == 1
        wid = saved.json()["working_id"]
        x = api.get(f"/tds/return-workings/{wid}/export.xlsx")
        assert x.status_code == 200 and x.headers["X-Rule-Status"] == "pending"
        j = api.get(f"/tds/return-workings/{wid}/export.json")
        assert j.headers["X-Format-Status"] == "unverified-own-structure" and j.json()["totals"]["tax_deducted"] == "11000.00"
        bad = api.get(f"{base}/certificates/preview", params={"deductee_ledger_id": str(w["beta"]), "financial_year_id": str(w["fy"]),
                                                              "quarter": 1, "certificate_kind": "non_salary"})
        assert bad.status_code == 422 and bad.json()["errors"][0]["rule_id"] == "T-34"
        no_actor = api.post(f"/tds/return-workings/{wid}/finalise")
        assert no_actor.status_code == 400
        done = api.post(f"/tds/return-workings/{wid}/finalise", headers=H)
        assert done.status_code == 200 and done.json()["locked_challans"] == 2
        again = api.post(f"/tds/return-workings/{wid}/finalise", headers=H)
        assert again.status_code == 409 and again.json()["code"] == "working_final"
    finally:
        app.dependency_overrides.clear()
