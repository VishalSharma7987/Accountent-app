"""Phase 3 package E against the database: GSTR-1 / tie-out / saved versions from posted invoice-mode vouchers.

Rows are written with raw SQL (not package B's voucher service) so these tests need only the 0009-0011 schema.
Everything runs in one rolled-back transaction. Expected values typed literally.
"""

import uuid
from datetime import date

import pytest
from dbfactory import Factory, check_deferred

from app.services import gst_returns
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

GSTIN = "27AAPFU0939F1ZV"
BUYER = "27AAAAA0000A1Z5"
ROLES = {
    "output_cgst": "Output CGST", "output_sgst": "Output SGST", "output_igst": "Output IGST", "output_cess": "Output Cess",
    "input_cgst": "Input CGST", "input_sgst": "Input SGST", "input_igst": "Input IGST", "input_cess": "Input Cess",
}
APRIL = date(2026, 4, 1)


@pytest.fixture
def world(svc_conn):
    raw = svc_conn.connection.driver_connection
    f = Factory(raw)
    client_id, fy_id = f.setup()
    reg_id = uuid.uuid4()
    raw.execute(
        "INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
        "VALUES (%s, %s, %s, '27', 'regular', '2026-04-01')", (reg_id, client_id, GSTIN))
    ledgers = {role: f.ledger(client_id, name, "duties_taxes") for role, name in ROLES.items()}
    for role, ledger_id in ledgers.items():
        raw.execute("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (%s, %s, %s, %s)",
                    (reg_id, client_id, role, ledger_id))
    debtor = f.ledger(client_id, "Buyer Ltd", "sundry_debtors")
    sales = f.ledger(client_id, "Sales", "sales_accounts")
    expense = f.ledger(client_id, "Misc expense", "indirect_expenses")
    return {"raw": raw, "f": f, "client": client_id, "fy": fy_id, "reg": reg_id, "ledgers": ledgers,
            "debtor": debtor, "sales": sales, "expense": expense}


def _invoice_header(w, vid, value, number_day=5):
    w["raw"].execute(
        "INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, counterparty_gstin, "
        "counterparty_state_code, place_of_supply, invoice_date, invoice_value, engine_version) "
        "VALUES (%s, %s, %s, 'tax_invoice', 'b2b', %s, '27', '27', %s, %s, 'gst-1')",
        (vid, w["client"], w["reg"], BUYER, date(2026, 4, number_day), value))


def _posted_sale(w):
    """Dr Buyer 1,180.00 / Cr Sales 1,000.00 / Cr Output CGST 90.00 / Cr Output SGST 90.00, posted as SAL/2026-27/0001."""
    f, raw, lg = w["f"], w["raw"], w["ledgers"]
    vid = f.draft(w["client"], w["fy"], [(w["debtor"], "1180.00", "0.00"), (w["sales"], "0.00", "1000.00"),
                                         (lg["output_cgst"], "0.00", "90.00"), (lg["output_sgst"], "0.00", "90.00")],
                  vtype="sales")
    _invoice_header(w, vid, "1180.00")
    raw.execute(
        "INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, description, hsn_sac, uqc, quantity, unit_rate, "
        "gross_amount, discount, taxable_value, ledger_id, treatment, gst_rate, cgst, sgst) "
        "VALUES (%s, %s, 1, 'Goods', '1001', 'NOS', 1, 1000, 1000, 0, 1000, %s, 'taxable', 18, 90, 90)",
        (w["client"], vid, w["sales"]))
    f.approve(vid)
    f.post(vid, "SAL/2026-27/0001")
    check_deferred(raw)
    return vid


def test_G50_G56_posted_invoice_is_in_gstr1_and_an_unposted_draft_is_listed_not_counted(world, svc_conn):
    w = world
    _posted_sale(w)
    draft = w["f"].draft(w["client"], w["fy"], w["f"].balanced_lines(w["client"]), vtype="sales", on="2026-04-09")
    _invoice_header(w, draft, "100.00", 9)
    r = gst_returns.jsonable(gst_returns.gstr1_working(svc_conn, w["client"], w["reg"], "month", APRIL))
    inv = r["tables"]["b2b"][0]["invoices"][0]
    assert (r["tables"]["b2b"][0]["party_gstin"], inv["invoice_no"], inv["invoice_value"]) == (BUYER, "SAL/2026-27/0001", "1180.00")
    assert r["tables"]["totals"] == {"taxable_value": "1000.00", "igst": "0.00", "cgst": "90.00", "sgst": "90.00", "cess": "0.00"}
    assert r["source_voucher_count"] == 1
    assert [d["voucher_id"] for d in r["unposted_drafts_in_period"]] == [str(draft)]
    assert r["rule_status"]["worst"] == "pending"  # B2CL limit and portal numbering are pending
    assert r["tables"]["documents_issued"][0]["net_issued"] == 1


def test_G53_tie_out_shows_manual_journal_on_output_ledger_as_cause_and_filed_difference(world, svc_conn):
    w = world
    _posted_sale(w)
    f = w["f"]
    jv = f.draft(w["client"], w["fy"], [(w["expense"], "5.00", "0.00"), (w["ledgers"]["output_cgst"], "0.00", "5.00")],
                 on="2026-04-10")
    f.approve(jv)
    f.post(jv, "JRN/2026-27/0001")
    check_deferred(w["raw"])
    gst_returns.put_filed_return(svc_conn, w["client"], w["reg"], "gstr1", APRIL, "ARN1", date(2026, 5, 11),
                                 {"totals": {"taxable_value": "990.00"}}, "tester")
    t = gst_returns.jsonable(gst_returns.tie_out(svc_conn, w["client"], w["reg"], "month", APRIL))["tables"]
    rows = {r["head"]: r for r in t["rows"]}
    assert rows["cgst"]["books_output"] == "95.00" and rows["cgst"]["gstr1_working"] == "90.00"
    assert rows["cgst"]["d_books_gstr1"] == "5.00"
    assert rows["taxable_value"]["d_books_gstr1"] == "0.00"
    assert rows["taxable_value"]["d_books_filed"] == "10.00"
    assert t["ties"] is False
    assert {"kind": "manual_journal_on_tax_ledger", "reference": "JRN/2026-27/0001", "amount": "5.00",
            "head": "output_cgst"} in t["causes"]


def test_G56_working_versions_and_final_is_immutable(world, svc_conn):
    w = world
    _posted_sale(w)
    id1, v1 = gst_returns.save_working(svc_conn, w["client"], w["reg"], "gstr1", "month", APRIL, "tester")
    id2, v2 = gst_returns.save_working(svc_conn, w["client"], w["reg"], "gstr1", "month", APRIL, "tester")
    assert (v1, v2) == (1, 2)
    gst_returns.finalise_working(svc_conn, id1, "tester")
    with pytest.raises(ServiceError) as exc:
        gst_returns.finalise_working(svc_conn, id1, "tester")
    assert exc.value.code == "working_final"
    saved = gst_returns.get_working(svc_conn, id1)
    assert saved["status"] == "final" and saved["data"]["tables"]["totals"]["cgst"] == "90.00"
    listed = gst_returns.list_workings(svc_conn, w["client"], w["reg"], "gstr1")
    assert [(x["version"], x["status"]) for x in listed] == [(2, "draft"), (1, "final")]
    audited = svc_conn.exec_driver_sql(
        "SELECT action FROM audit_log WHERE client_id = %s AND entity = 'gst_return_working' ORDER BY created_at", (w["client"],)
    ).fetchall()
    assert [a[0] for a in audited].count("gst_working_saved") == 2


def test_G56_monthly_registration_cannot_use_a_quarter_and_bad_period_start_is_refused(world, svc_conn):
    w = world
    with pytest.raises(ServiceError) as exc:
        gst_returns.gstr1_working(svc_conn, w["client"], w["reg"], "quarter", APRIL)
    assert exc.value.code == "period_invalid"
    with pytest.raises(ServiceError) as exc2:
        gst_returns.gstr3b_working(svc_conn, w["client"], w["reg"], "month", date(2026, 4, 2))
    assert exc2.value.code == "period_invalid"
