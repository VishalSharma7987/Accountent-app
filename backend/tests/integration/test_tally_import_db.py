"""Package B: Tally import, queue and export against the database (D-30..D-39).
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_tally_import_db.py`.

Synthetic XML only (tests/fixtures/tally/sample_company.xml). Every test runs in a transaction that is rolled back.
"""

import hashlib
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

pytest.importorskip("defusedxml")

from app.engine.models import VoucherDraft, VoucherLine
from app.importers.tally_xml import parse_tally_xml
from app.services import client_setup, tally_export, tally_import, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

XML = (Path(__file__).resolve().parents[1] / "fixtures" / "tally" / "sample_company.xml").read_bytes()
ACTOR = "tester"


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def world(conn):
    created = client_setup.create_client(
        conn, ClientProfile("Tally Test Co", "proprietorship", "trading", "regular"), fy_start=date(2026, 4, 1), actor="setup",
        proprietor_name="Owner")
    ids = dict(created.ledger_ids)
    have = {n.lower() for n in ids}
    for name, group in (("Rahul Enterprises", "sundry_debtors"), ("Sales - Goods", "sales_accounts"), ("Output IGST", "duties_taxes"),
                        ("Office Rent", "indirect_expenses")):
        if name.lower() not in have:
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, group, actor="setup")
    return created.client_id, ids


def document(conn, client_id, data=XML, doc_type="tally_xml"):
    doc_id, sha = uuid.uuid4(), hashlib.sha256(data).hexdigest()
    conn.execute(
        text("INSERT INTO documents (id, client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by) "
             "VALUES (:i, :c, :t, 'tally.xml', 'application/xml', :n, :h, :k, 'tester')"),
        {"i": doc_id, "c": client_id, "t": doc_type, "n": len(data), "h": sha, "k": f"{client_id}/{sha}.xml"})
    return doc_id


def by_name(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_D31_D32_D33_import_writes_report_and_suggestions_but_creates_nothing(svc_conn):
    client_id, ids = world(svc_conn)
    ledgers_before = scalar(svc_conn, "SELECT count(*) FROM ledgers WHERE client_id = :c", c=client_id)
    doc_id = document(svc_conn, client_id)

    result = tally_import.import_xml(svc_conn, client_id, doc_id, XML, actor=ACTOR)
    report = result.report

    assert result.company_name == "Synthetic Traders (Test)"
    assert report["counts"] == {"groups": 2, "ledgers": 8, "stock_items": 2, "vouchers": 7}
    assert report["opening_balances_not_applied"] is True
    rahul = by_name(report["ledgers"], "Rahul Enterprises")
    assert (rahul["suggested_group_code"], rahul["existing_ledger_id"], rahul["opening_balance_reported"]) == (
        "sundry_debtors", str(ids["Rahul Enterprises"]), "-12000.00")  # custom group "Retail Debtors" resolved through its parent
    assert by_name(report["ledgers"], "Cash")["opening_balance_reported"] == "-5000.00"
    mystery = by_name(report["ledgers"], "Mystery Ledger")
    assert (mystery["suggested_group_code"], mystery["decision"]) == (None, "suggested")
    assert "choose a group" in mystery["reason"]
    sharma = by_name(report["ledgers"], "Sharma Suppliers")
    assert (sharma["suggested_group_code"], sharma["existing_ledger_id"]) == ("sundry_creditors", None)
    assert by_name(report["groups"], "Orphan Group")["suggested_group_code"] is None
    assert by_name(report["stock_items"], "Widget")["hsn"] == "8471"
    assert "No HSN" in by_name(report["stock_items"], "Gadget")["reason"]
    assert report["vouchers"]["by_type"] == {"Sales": 2, "Payment": 1, "Purchase": 1, "Journal": 1, "Stock Journal": 1, "Receipt": 1}
    assert report["vouchers"]["drafted_later"] == 4
    assert sorted((s["number"], s["reason_rule"]) for s in report["vouchers"]["skipped"]) == [("2", "D-36"), ("R-1", "D-36"), ("SJ-1", "D-34")]
    assert report["bill_allocations_not_imported"] == 1

    # nothing was created or posted; every master is only a suggestion
    assert scalar(svc_conn, "SELECT count(*) FROM ledgers WHERE client_id = :c", c=client_id) == ledgers_before
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=client_id) == 0
    assert scalar(svc_conn, "SELECT count(*) FROM tally_master_map WHERE client_id = :c AND decision <> 'suggested'", c=client_id) == 0
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE client_id = :c AND action = 'tally_import'", c=client_id) == 1

    with pytest.raises(ServiceError) as again:
        tally_import.import_xml(svc_conn, client_id, doc_id, XML, actor=ACTOR)
    assert again.value.code == "import_exists"
    with pytest.raises(ServiceError) as wrong:
        tally_import.import_xml(svc_conn, client_id, document(svc_conn, client_id, b"<x/>", "other"), b"<x/>", actor=ACTOR)
    assert wrong.value.code == "invalid_document_type"
    bad = b"<ENVELOPE><BODY/></ENVELOPE>"
    with pytest.raises(ServiceError) as broken:
        tally_import.import_xml(svc_conn, client_id, document(svc_conn, client_id, bad), bad, actor=ACTOR)
    assert broken.value.code == "invalid_tally_file" and broken.value.details == {"rule_id": "D-30"}


def test_D31_D34_D35_D36_D37_masters_decided_then_vouchers_queued_as_drafts_only(svc_conn):
    client_id, ids = world(svc_conn)
    doc_id = document(svc_conn, client_id)
    imp = tally_import.import_xml(svc_conn, client_id, doc_id, XML, actor=ACTOR).import_id

    with pytest.raises(ServiceError) as early:  # no decisions yet: refused, nothing queued
        tally_import.queue_vouchers(svc_conn, client_id, imp, XML, actor=ACTOR)
    assert early.value.code == "masters_not_ready"
    assert "Mystery Ledger" in early.value.details["ledgers"] and "Sharma Suppliers" in early.value.details["ledgers"]
    assert scalar(svc_conn, "SELECT count(*) FROM approval_queue_items WHERE client_id = :c", c=client_id) == 0

    assert tally_import.confirm_exact_matches(svc_conn, client_id, imp, actor=ACTOR) == 6  # Cash, Purchases, Rahul, Sales - Goods, Output IGST, Office Rent; not Sharma (new) and not Mystery
    masters = {m["source_name"]: m for m in tally_import.list_masters(svc_conn, client_id, kind="ledger")}
    assert masters["Rahul Enterprises"]["decision"] == "confirmed"
    assert masters["Rahul Enterprises"]["target_ledger_id"] == ids["Rahul Enterprises"]
    tally_import.set_master_decision(svc_conn, client_id, masters["Sharma Suppliers"]["id"], decision="create", actor=ACTOR)
    tally_import.set_master_decision(svc_conn, client_id, masters["Mystery Ledger"]["id"], decision="skip", actor=ACTOR)
    with pytest.raises(ServiceError) as nature:  # a ledger mapped into a group of another nature needs an explicit yes
        tally_import.set_master_decision(svc_conn, client_id, masters["Office Rent"]["id"], decision="confirmed",
                                         target_ledger_id=ids["Rahul Enterprises"], actor=ACTOR)
    assert nature.value.code == "mapping_nature"

    applied = tally_import.apply_masters(svc_conn, client_id, imp, XML, actor=ACTOR)
    assert applied["created"] == {"groups": 0, "ledgers": 1, "stock_items": 0} and applied["skipped"] == []
    assert scalar(svc_conn, "SELECT count(*) FROM ledgers WHERE client_id = :c AND name = 'Sharma Suppliers'", c=client_id) == 1
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE client_id = :c AND action = 'tally_apply_masters'", c=client_id) == 1

    queued = tally_import.queue_vouchers(svc_conn, client_id, imp, XML, actor=ACTOR)
    assert (queued.queued, queued.drafted, queued.needs_review) == (4, 2, 2)
    assert sorted((s["number"], s["reason_rule"]) for s in queued.skipped) == [("2", "D-36"), ("R-1", "D-36"), ("SJ-1", "D-34")]

    # nothing was approved or posted; the two good vouchers are drafts, the two with findings have no draft
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c AND status <> 'draft'", c=client_id) == 0
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=client_id) == 2
    items = {r["number"]: r for r in svc_conn.execute(
        text("SELECT edited_payload ->> 'number' AS number, status, blocking_count, warning_count, draft_voucher_id, findings, source_ref "
             "FROM approval_queue_items WHERE client_id = :c AND kind = 'tally_voucher'"), {"c": client_id}).mappings()}
    assert set(items) == {"1", "P-1", "7", "J-1"} and all(i["status"] == "pending" for i in items.values())
    assert items["1"]["draft_voucher_id"] is not None and items["P-1"]["draft_voucher_id"] is not None
    assert (items["P-1"]["blocking_count"], items["P-1"]["warning_count"]) == (0, 0)
    # the GST sales voucher: plain lines, so two warnings (bill allocation not imported, tax ledger in plain lines), no blocking
    assert (items["1"]["blocking_count"], items["1"]["warning_count"]) == (0, 2)
    assert any("not an invoice for GST" in f["message"] for f in items["1"]["findings"])
    assert items["1"]["source_ref"] == "guid-sales-1"
    # purchase without the supplier's bill number: the voucher service refuses it (V-14), no draft
    assert items["7"]["draft_voucher_id"] is None
    assert [f["rule_id"] for f in items["7"]["findings"]] == ["V-14"]
    # journal uses a skipped ledger: review finding, no draft
    assert items["J-1"]["draft_voucher_id"] is None
    assert [(f["rule_id"], f["severity"]) for f in items["J-1"]["findings"]] == [("D-31", "review")]
    # the sales draft carries the right debit / credit lines (Tally sign convention converted)
    lines = svc_conn.execute(
        text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id WHERE vl.voucher_id = :v ORDER BY vl.line_no"),
        {"v": items["1"]["draft_voucher_id"]}).all()
    assert [(n, f"{d:.2f}", f"{c:.2f}") for n, d, c in lines] == [
        ("Rahul Enterprises", "11800.00", "0.00"), ("Sales - Goods", "0.00", "10000.00"), ("Output IGST", "0.00", "1800.00")]

    # a second run queues nothing (D-37)
    again = tally_import.queue_vouchers(svc_conn, client_id, imp, XML, actor=ACTOR)
    assert (again.queued, again.drafted) == (0, 0)
    assert sorted(s["reason_rule"] for s in again.skipped) == ["D-34", "D-36", "D-36", "D-37", "D-37", "D-37", "D-37"]


def test_D38_D39_export_posted_vouchers_only_and_reads_back(svc_conn):
    client_id, ids = world(svc_conn)

    def draft(number_ref, amount):
        made = vouchers.create_draft(svc_conn, VoucherDraft(
            client_id, "sales", date(2026, 4, 15), "Goods sold", number_ref, ids["Rahul Enterprises"],
            (VoucherLine(ids["Rahul Enterprises"], debit=amount), VoucherLine(ids["Sales - Goods"], credit=amount))), actor=ACTOR)
        assert made.errors == []
        return made.voucher_id

    posted_id = draft("INV-1", "500.00")
    vouchers.approve(svc_conn, posted_id, actor=ACTOR)
    number = vouchers.post(svc_conn, posted_id, actor=ACTOR)
    assert number == "SAL/2026-27/0001"
    draft("INV-2", "700.00")  # stays a draft

    stored: list = []

    def store(conn, cid, doc_type, filename, data, actor):
        stored.append((doc_type, filename, data))
        return document(conn, cid, data, doc_type if doc_type == "tally_export" else "other")

    with pytest.raises(ServiceError) as refused:
        tally_export.export(svc_conn, client_id, kind="vouchers", store_document=store, actor=ACTOR)
    assert refused.value.code == "unposted_vouchers" and refused.value.details == {"unposted": 1}
    assert stored == []

    out = tally_export.export(svc_conn, client_id, kind="vouchers", posted_only=True, store_document=store, actor=ACTOR)
    assert out.voucher_count == 1 and out.master_count == 2  # the two ledgers the voucher uses
    assert any("1 unposted voucher" in w for w in out.warnings)
    doc_type, filename, data = stored[0]
    assert doc_type == "tally_export" and filename.endswith(".xml")
    back = parse_tally_xml(data)
    assert [(v.number, v.reference, v.party_ledger, v.voucher_type) for v in back.vouchers] == [("SAL/2026-27/0001", "INV-1", "Rahul Enterprises", "Sales")]
    assert [(e.ledger_name, f"{e.amount:.2f}", e.deemed_positive) for e in back.vouchers[0].entries] == [
        ("Rahul Enterprises", "-500.00", True), ("Sales - Goods", "500.00", False)]
    assert sorted(x.name for x in back.ledgers) == ["Rahul Enterprises", "Sales - Goods"]
    assert scalar(svc_conn, "SELECT voucher_count FROM tally_exports WHERE client_id = :c", c=client_id) == 1
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE client_id = :c AND action = 'tally_export'", c=client_id) == 1
