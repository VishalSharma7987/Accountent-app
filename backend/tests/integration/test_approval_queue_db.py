"""Phase 7 package F on the test schema: the approval queue (edit with checks re-run, accept, reject, Tally items), the guard hooks of the
voucher service, and the end-to-end acceptance property with the FAKE language model (no network, no key):

  a deliberately wrong extraction can never be accepted / approved / posted unless the accountant edits it until the engine has no
  blocking finding; a correct one posts only after accept + approve + post.

Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_approval_queue_db.py`.
Hand-calculated figures (seeded EXAMPLE rules: HSN 8415 = 18 % from 22-09-2025, HSN 1701 = 5 %; supplier and client both in Maharashtra):
  line 1: 2 x 1000.00                 -> taxable 2000.00, CGST 180.00, SGST 180.00
  line 2: 1 x 500.00 - 50.00 discount -> taxable  450.00, CGST  11.25, SGST  11.25
  total payable to the supplier 2832.50 (taxable 2450.00 + CGST 191.25 + SGST 191.25)
"""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.fake import FakeLlmClient
from app.api import narration as narration_api
from app.api.deps import get_conn
from app.db import connection, migrate
from app.engine.doc_types import DocFinding, QueueKind, Severity
from app.main import app
from app.services import (
    ai_hooks,
    approval_queue,
    client_setup,
    doc_drafts,
    doc_mappings,
    extractions,
    llm_gateway,
    narration,
    parties,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError
from app.services.llm_extraction_gateway import ExtractionCall

pytestmark = pytest.mark.integration

CLIENT_GSTIN = "27AAAPL1234C1ZE"
SUPPLIER = "27CCCPM4321E1ZZ"
ROLE_LEDGERS = {
    "output_cgst": "Output CGST", "output_sgst": "Output SGST", "output_igst": "Output IGST",
    "input_cgst": "Input CGST", "input_sgst": "Input SGST", "input_igst": "Input IGST",
    "rcm_cgst": "RCM CGST Payable", "rcm_sgst": "RCM SGST Payable", "rcm_igst": "RCM IGST Payable",
}
H = {"X-User": "tester"}


@dataclass
class World:
    client_id: object
    ids: dict
    lines: dict


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("Queue Traders", "proprietorship", "trading", "regular"), fy_start=date(2026, 4, 1), actor="setup",
            proprietor_name="Ramesh Kumar")
        cid = created.client_id
        ids = dict(created.ledger_ids)
        for name, group in (("Shree Traders", "sundry_creditors"), ("Tea Expense", "indirect_expenses"),
                            ("Staff Welfare", "indirect_expenses"), ("HDFC Bank", "bank_accounts")):
            ids[name] = client_setup.add_ledger(conn, cid, name, group, actor="setup")
        for name in ROLE_LEDGERS.values():
            ids[name] = client_setup.add_ledger(conn, cid, name, "duties_taxes", actor="setup")
        reg_id = uuid.uuid4()
        conn.execute(text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                          "VALUES (:r, :c, :g, '27', 'regular', '2026-04-01')"), {"r": reg_id, "c": cid, "g": CLIENT_GSTIN})
        for role, name in ROLE_LEDGERS.items():
            conn.execute(text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                         {"r": reg_id, "c": cid, "role": role, "l": ids[name]})
        parties.set_party(conn, cid, ids["Shree Traders"], gstin=SUPPLIER, state_code="27", bill_wise=False, actor="setup")
        conn.execute(text("INSERT INTO client_ai_settings (client_id, llm_enabled, enabled_by, enabled_at, note, updated_by) "
                          "VALUES (:c, true, 'owner', now(), 'synthetic data only', 'owner')"), {"c": cid})
        stmt = conn.execute(
            text("INSERT INTO bank_statements (client_id, bank_ledger_id, file_name, file_sha256, period_from, period_to, opening_balance, "
                 "closing_balance, imported_by) VALUES (:c, :b, 'stmt.csv', :h, '2026-06-01', '2026-06-30', 0, 0, 'setup') RETURNING id"),
            {"c": cid, "b": ids["HDFC Bank"], "h": "a" * 64}).scalar_one()
        lines = {}
        for no, (key, desc, debit, credit) in enumerate((
            ("tea1", "UPI/DR/111111111111/Ramesh Tea Stall/SBIN", "150.00", "0"),
            ("tea2", "UPI/DR/222222222222/RAMESH TEA STALL/SBIN 03/06/2026", "200.00", "0"),
            ("amb", "Cheque No 004512 to Gupta", "900.00", "0"),
            ("llm1", "Payment to Verma Stationers 12/06/2026", "450.00", "0"),
            ("llm2", "Payment to Mehta Hardware ABCDE1234F", "380.00", "0"),
            ("llm3", "Payment to Joshi Sweets", "120.00", "0"),
        ), start=1):
            lines[key] = conn.execute(
                text("INSERT INTO bank_statement_lines (client_id, statement_id, line_no, txn_date, description, debit, credit) "
                     "VALUES (:c, :s, :n, '2026-06-05', :d, :db, :cr) RETURNING id"),
                {"c": cid, "s": stmt, "n": no, "d": desc, "db": debit, "cr": credit}).scalar_one()
        w = World(cid, ids, lines)
    yield w
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


# ---- the fake model, wired through package C's real gateway -------------------------------------------------------
class FakeGateway:
    """Package D's gateway protocol on top of package C's gateway (`llm_gateway.call`) with a scripted fake client."""

    def __init__(self, fake: FakeLlmClient):
        self.fake = fake

    def call(self, conn, *, client_id, document_id, request, prompt_version, actor):
        r = llm_gateway.call(conn, client_id=client_id, purpose=request.purpose, system=request.system, user=request.user,
                             prompt_version=prompt_version, actor=actor, document_id=document_id, llm_client=self.fake,
                             model="fake/model", max_tokens=request.max_tokens)
        if r.status == "ok" and r.data is not None:
            return ExtractionCall("ok", r.call_id, json.dumps(r.data, default=str), r.message)
        return ExtractionCall("blocked" if r.status == "blocked" else "error", r.call_id, None, r.message)


def fv(value, conf=0.95):
    return {"value": value, "page": 1, "bbox": None, "confidence": conf}


def answer(**over):
    ans = {
        "document_kind": fv("Tax Invoice"), "supplier_name": fv("Shree Traders"), "supplier_gstin": fv(SUPPLIER),
        "buyer_name": fv("Queue Traders"), "buyer_gstin": fv(CLIENT_GSTIN), "invoice_no": fv("INV-77"),
        "invoice_date": fv("10-05-2026"), "place_of_supply": fv("27-Maharashtra"),
        "lines": [
            {"description": fv("Air conditioner"), "hsn_sac": fv("8415"), "quantity": fv("2"), "unit": fv("NOS"),
             "unit_rate": fv("1000.00"), "taxable_value": fv("2000.00"), "gst_rate": fv("18"), "cgst": fv("180.00"), "sgst": fv("180.00")},
            {"description": fv("Sugar"), "hsn_sac": fv("1701"), "quantity": fv("1"), "unit": fv("NOS"), "unit_rate": fv("500.00"),
             "discount": fv("50.00"), "taxable_value": fv("450.00"), "gst_rate": fv("5"), "cgst": fv("11.25"), "sgst": fv("11.25")},
        ],
        "totals": {"taxable_total": fv("2450.00"), "cgst_total": fv("191.25"), "sgst_total": fv("191.25"), "round_off": fv("0.00"),
                   "grand_total": fv("2832.50")},
        "currency": "INR", "notes": [],
    }
    ans.update(over)
    return ans


def wrong_cgst_answer():
    a = answer()
    a["lines"][0]["cgst"] = fv("200.00")  # printed CGST of line 1 is wrong (the table gives 180.00)
    return a


def new_doc(conn, w, doc_type="purchase_invoice"):
    n = uuid.uuid4().int
    doc = conn.execute(text(
        "INSERT INTO documents (client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by, page_count) "
        "VALUES (:c, :t, 'bill.pdf', 'application/pdf', 100, :h, :k, 'clerk', 1) RETURNING id"),
        {"c": w.client_id, "t": doc_type, "h": f"{n % (16 ** 63):064x}", "k": f"{str(w.client_id)[:8]}/{n % (16 ** 63):064x}.pdf"}).scalar_one()
    conn.execute(text("INSERT INTO document_texts (client_id, document_id, page_no, method, engine_version, text) "
                      "VALUES (:c, :d, 1, 'pdf_text', 'test', 'Invoice text page 1')"), {"c": w.client_id, "d": doc})
    return doc


def save_mappings(conn, w):
    doc_mappings.put_party_mapping(conn, w.client_id, match_kind="gstin", match_key=SUPPLIER, party_ledger_id=w.ids["Shree Traders"],
                                   actor="acc")
    for hsn in ("8415", "1701"):
        doc_mappings.put_line_mapping(conn, w.client_id, match_kind="hsn_sac", match_key=hsn, ledger_id=w.ids["Purchases"], actor="acc")


def queue_from_llm(conn, w, ans):
    """The model (fake) reads the document; the extraction is checked and a queue item (with a draft only when nothing blocks) is made."""
    doc = new_doc(conn, w)
    out = extractions.run_llm_extraction(conn, client_id=w.client_id, document_id=doc, actor="clerk",
                                         gateway=FakeGateway(FakeLlmClient([json.dumps(ans)])))
    assert out.status == "ok", out.message
    built = doc_drafts.build_for_document(conn, w.client_id, doc, out.extraction_id, actor="clerk")
    return doc, out.extraction_id, built


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def item_row(conn, item_id):
    return conn.execute(text("SELECT status, blocking_count, warning_count, draft_voucher_id, reviewer FROM approval_queue_items WHERE id = :i"),
                        {"i": item_id}).one()


def sums(conn, voucher_id):
    rows = conn.execute(text("SELECT l.name, sum(vl.debit), sum(vl.credit) FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                             "WHERE vl.voucher_id = :v GROUP BY l.name"), {"v": voucher_id})
    return {r[0]: (r[1], r[2]) for r in rows}


# ================================================================================================ the acceptance property


def test_D60_D61_D62_wrong_extraction_can_never_be_accepted_approved_or_posted_until_the_accountant_fixes_it(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext, built = queue_from_llm(svc_conn, w, wrong_cgst_answer())
    item_id = built.queue_item_id
    # 1. the engine caught the wrong tax: error D-11 on the line, nothing was drafted
    assert any(f.rule_id == "D-11" and f.severity == Severity.ERROR for f in built.findings)
    assert built.draft_voucher_id is None
    assert scalar(svc_conn, "SELECT count(*) FROM document_vouchers WHERE document_id = :d", d=doc) == 0
    # 2. accept is refused by the SERVICE (stored counts are not trusted: the checks are re-run), the item stays pending
    with pytest.raises(ServiceError) as e:
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert e.value.code == "queue_blocked"
    assert any(f["rule_id"] == "D-11" for f in e.value.details["findings"])
    assert item_row(svc_conn, item_id).status == "pending"
    # 3. the accountant corrects the printed value from the document (180.00); the checks re-run and the draft appears
    res = approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("lines[0].cgst", "180.00")], actor="acc")
    assert [f for f in res.findings if f.severity in (Severity.ERROR, Severity.REVIEW)] == []
    assert res.draft_voucher_id is not None
    vid = res.draft_voucher_id
    assert sums(svc_conn, vid) == {"Purchases": (D("2450.00"), D("0.00")), "Input CGST": (D("191.25"), D("0.00")),
                                   "Input SGST": (D("191.25"), D("0.00")), "Shree Traders": (D("0.00"), D("2832.50"))}
    # the AI's answer is evidence and never changed; the edit lives in edited_payload; both are in the audit log
    assert scalar(svc_conn, "SELECT payload->'lines'->0->'cgst'->>'value' FROM extractions WHERE id = :e", e=ext) == "200.00"
    assert scalar(svc_conn, "SELECT edited_payload->'lines'->0->'cgst'->>'value' FROM approval_queue_items WHERE id = :i", i=item_id) == "180.00"
    assert scalar(svc_conn, "SELECT old_data->'edits'->>'lines[0].cgst' FROM audit_log WHERE entity_id = :i AND action = 'queue_item_edited'",
                  i=item_id) == "200.00"
    # 4. the draft exists but cannot be approved before accept: friendly refusal from the service, DB trigger as backstop
    with pytest.raises(ServiceError) as e:
        vouchers.approve(svc_conn, vid, actor="partner")
    assert e.value.code == "queue_not_accepted"
    with pytest.raises(DBAPIError), svc_conn.begin_nested():
        svc_conn.execute(text("UPDATE vouchers SET status = 'approved', approved_by = 'x', approved_at = now() WHERE id = :v"), {"v": vid})
    # and the draft cannot be deleted behind the queue's back
    with pytest.raises(ServiceError) as e:
        vouchers.delete_draft(svc_conn, vid, actor="partner")
    assert e.value.code == "queue_item_exists"
    # 5. accept (never posts) -> then the normal approve and post
    out = approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert out.draft_voucher_id == vid
    assert scalar(svc_conn, "SELECT status FROM vouchers WHERE id = :v", v=vid) == "draft"
    assert item_row(svc_conn, item_id).status == "accepted"
    assert scalar(svc_conn, "SELECT count(*) FROM document_vouchers WHERE document_id = :d AND voucher_id = :v AND link_kind = 'source'",
                  d=doc, v=vid) == 1
    vouchers.approve(svc_conn, vid, actor="partner")
    number = vouchers.post(svc_conn, vid, actor="partner")
    assert number.startswith("PUR/2026-27/")
    assert scalar(svc_conn, "SELECT status FROM vouchers WHERE id = :v", v=vid) == "posted"
    # an accepted item is final
    with pytest.raises(ServiceError) as e:
        approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("invoice_no", "X")], actor="acc")
    assert e.value.code == "queue_state"


def test_D60_correct_extraction_posts_only_after_accept_approve_post_and_learns_from_final_values(svc_conn, world):
    w = world
    doc, ext, built = queue_from_llm(svc_conn, w, answer())
    item_id = built.queue_item_id
    # unmapped supplier and lines: review findings, no draft (never auto-created)
    assert {"D-20", "D-21"} <= {f.rule_id for f in built.findings}
    assert built.draft_voucher_id is None
    with pytest.raises(ServiceError) as e:
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert e.value.code == "queue_blocked"
    # the accountant saves the mappings in the mapping screen; the next re-run of the checks builds the draft
    save_mappings(svc_conn, w)
    res = approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("invoice_no", "INV-77")], actor="acc")
    assert res.draft_voucher_id is not None
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE id = :v AND status = 'draft'", v=res.draft_voucher_id) == 1
    out = approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    # D-26: from the final values; what already resolves is not duplicated: GSTIN mapping exists, the name key is new,
    # the HSN keys already exist, the two descriptions are new (scoped to this supplier)
    assert out.learned == {"party": ["unchanged", "created"], "lines": ["created", "unchanged", "created", "unchanged"]}
    assert scalar(svc_conn, "SELECT count(*) FROM party_mappings WHERE client_id = :c AND match_kind = 'name' AND match_key = 'shree traders'",
                  c=w.client_id) == 1
    assert scalar(svc_conn, "SELECT count(*) FROM line_mappings WHERE client_id = :c AND match_kind = 'description' AND party_ledger_id = :p",
                  c=w.client_id, p=w.ids["Shree Traders"]) == 2
    vouchers.approve(svc_conn, out.draft_voucher_id, actor="partner")
    vouchers.post(svc_conn, out.draft_voucher_id, actor="partner")
    assert scalar(svc_conn, "SELECT status FROM vouchers WHERE id = :v", v=out.draft_voucher_id) == "posted"


def test_D60_a_warning_is_accepted_only_after_it_is_acknowledged_by_rule_and_field(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    a = answer()
    a["invoice_no"] = fv("INV-77", 0.50)  # below the minimum confidence: D-05 warning
    doc, ext, built = queue_from_llm(svc_conn, w, a)
    warn = [f for f in built.findings if f.severity == Severity.WARNING]
    assert built.draft_voucher_id is not None and [f.rule_id for f in warn] == ["D-05"]
    item_id = built.queue_item_id
    with pytest.raises(ServiceError) as e:
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert e.value.code == "queue_blocked" and "acknowledged" in e.value.message
    with pytest.raises(ServiceError):  # the wrong field does not acknowledge it
        approval_queue.accept(svc_conn, w.client_id, item_id, acknowledge=[{"rule_id": "D-05", "field_path": "buyer_name"}], actor="acc")
    approval_queue.accept(svc_conn, w.client_id, item_id,
                          acknowledge=[{"rule_id": warn[0].rule_id, "field_path": warn[0].field_path}], actor="acc")
    row = item_row(svc_conn, item_id)
    assert (row.status, row.warning_count, row.blocking_count) == ("accepted", 1, 0)
    assert scalar(svc_conn, "SELECT acknowledged->0->>'rule_id' FROM approval_queue_items WHERE id = :i", i=item_id) == "D-05"


def test_D63_reject_needs_a_reason_and_removes_the_draft_in_the_safe_order(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext, built = queue_from_llm(svc_conn, w, answer())
    item_id, vid = built.queue_item_id, built.draft_voucher_id
    assert vid is not None
    approval_queue.claim(svc_conn, w.client_id, item_id, actor="acc")
    with pytest.raises(ServiceError) as e:  # someone else cannot act on a claimed item
        approval_queue.reject(svc_conn, w.client_id, item_id, reason="x", actor="other")
    assert e.value.code == "queue_state"
    for blank in ("", "   "):
        with pytest.raises(ServiceError) as e:
            approval_queue.reject(svc_conn, w.client_id, item_id, reason=blank, actor="acc")
        assert e.value.code == "reason_required"
    approval_queue.reject(svc_conn, w.client_id, item_id, reason="Duplicate of a bill already booked", actor="acc")
    row = item_row(svc_conn, item_id)
    assert (row.status, row.draft_voucher_id) == ("rejected", None)
    assert scalar(svc_conn, "SELECT reject_reason FROM approval_queue_items WHERE id = :i", i=item_id) == "Duplicate of a bill already booked"
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE id = :v", v=vid) == 0
    assert scalar(svc_conn, "SELECT count(*) FROM document_vouchers WHERE document_id = :d", d=doc) == 0
    assert scalar(svc_conn, "SELECT count(*) FROM extractions WHERE id = :e", e=ext) == 1  # the record stays
    assert scalar(svc_conn, "SELECT status FROM documents WHERE id = :d", d=doc) == "extracted"
    assert scalar(svc_conn, "SELECT count(*) FROM audit_log WHERE entity_id = :i AND action = 'queue_item_rejected'", i=item_id) == 1
    with pytest.raises(ServiceError) as e:
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert e.value.code == "queue_state"
    # a rejected extraction can be read again
    again = extractions.run_llm_extraction(svc_conn, client_id=w.client_id, document_id=doc, actor="clerk",
                                           gateway=FakeGateway(FakeLlmClient([json.dumps(answer())])))
    assert again.status == "ok"


def test_D61_edit_errors_and_whole_payload_replacement(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext, built = queue_from_llm(svc_conn, w, answer())
    item_id = built.queue_item_id
    with pytest.raises(ServiceError) as e:
        approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("lines[9].hsn_sac", "1")], actor="acc")
    assert e.value.code == "invalid_field_path"
    # an invalid GSTIN typed by the accountant is an engine finding (D-07) and the draft is removed (D-27)
    res = approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("supplier_gstin", "27CCCPM4321E1ZX")], actor="acc")
    assert res.draft_voucher_id is None
    assert any(f.rule_id == "D-07" for f in res.findings)
    assert item_row(svc_conn, item_id).draft_voucher_id is None
    # whole replacement with the right value brings the draft back
    original = svc_conn.execute(text("SELECT payload FROM extractions WHERE id = :e"), {"e": ext}).scalar_one()
    back = approval_queue.edit_fields(svc_conn, w.client_id, item_id, payload=original, actor="acc")
    assert back.draft_voucher_id is not None
    # a payload that does not fit the schema is one D-04 error, no draft, nothing crashes
    bad = approval_queue.edit_fields(svc_conn, w.client_id, item_id, payload={"unknown_key": 1}, actor="acc")
    assert [f.rule_id for f in bad.findings] == ["D-04"] and bad.draft_voucher_id is None
    with pytest.raises(ServiceError) as e:
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert e.value.code == "queue_blocked"


# ================================================================================================ Tally items


def tally_item(conn, w, *, party="", with_second_ledger=True, ref="T-1"):
    """What package B queues (plain lines, a journal): the second line has no ledger yet when `with_second_ledger` is False."""
    doc = conn.execute(text(
        "INSERT INTO documents (client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by) "
        "VALUES (:c, 'tally_xml', 'x.xml', 'application/xml', 10, :h, :k, 'clerk') RETURNING id"),
        {"c": w.client_id, "h": f"{uuid.uuid4().int % (16 ** 63):064x}", "k": f"t/{uuid.uuid4()}.xml"}).scalar_one()
    imp = conn.execute(text("INSERT INTO tally_imports (client_id, document_id, created_by) VALUES (:c, :d, 'clerk') RETURNING id"),
                       {"c": w.client_id, "d": doc}).scalar_one()
    payload = {
        "source": "tally", "tally_voucher_type": "Journal", "voucher_type": "journal", "voucher_date": "2026-06-05", "number": "1",
        "guid": ref, "fallback_ref": "tvh:x", "narration": "Tea for office", "reference_no": "1", "party_ledger_name": party,
        "total": "500.00", "total_display": "500.00",
        "lines": [{"tally_ledger_name": "Tea Expense", "ledger_id": str(w.ids["Tea Expense"]), "debit": "500.00", "credit": "0.00"},
                  {"tally_ledger_name": "Shree Traders", "ledger_id": str(w.ids["Shree Traders"]) if with_second_ledger else "",
                   "debit": "0.00", "credit": "500.00"}],
    }
    findings = [DocFinding("D-31", Severity.REVIEW, "Ledger 'Shree Traders' was skipped in the mapping; map it to a ledger to continue.")] \
        if not with_second_ledger else []
    item_id = ai_hooks.add_queue_item(conn, client_id=w.client_id, kind=QueueKind.TALLY_VOUCHER, document_id=doc, findings=findings,
                                      created_by="clerk", tally_import_id=imp, source_ref=ref, edited_payload=payload)
    return item_id, doc


def test_D60_D61_tally_item_is_fixed_by_editing_then_accepted_and_posted(svc_conn, world):
    w = world
    item_id, doc = tally_item(svc_conn, w, with_second_ledger=False)
    with pytest.raises(ServiceError) as e:
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert e.value.code == "queue_blocked"
    detail = approval_queue.get_detail(svc_conn, w.client_id, item_id)
    assert detail["draft_voucher"] is None and detail["summary"]["total"] == "500.00"
    res = approval_queue.edit_fields(svc_conn, w.client_id, item_id,
                                     edits=[("lines[1].ledger_id", str(w.ids["Shree Traders"]))], actor="acc")
    assert [f for f in res.findings if f.severity in (Severity.ERROR, Severity.REVIEW)] == [] and res.draft_voucher_id
    with pytest.raises(ServiceError) as e:
        vouchers.approve(svc_conn, res.draft_voucher_id, actor="partner")
    assert e.value.code == "queue_not_accepted"
    out = approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    assert out.learned == {}
    vouchers.approve(svc_conn, out.draft_voucher_id, actor="partner")
    vouchers.post(svc_conn, out.draft_voucher_id, actor="partner")
    detail = approval_queue.get_detail(svc_conn, w.client_id, item_id)
    assert detail["status"] == "accepted"
    # the original proposal is kept in the audit row of the first edit
    assert detail["original"]["lines"][1]["ledger_id"] == "" and detail["current"]["lines"][1]["ledger_id"] == str(w.ids["Shree Traders"])


def test_D61_tally_unbalanced_edit_is_a_voucher_rule_finding_V04_and_no_draft(svc_conn, world):
    w = world
    item_id, _ = tally_item(svc_conn, w)
    approval_queue.claim(svc_conn, w.client_id, item_id, actor="acc")
    res = approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("lines[1].credit", "400.00")], actor="acc")
    assert res.draft_voucher_id is None and any(f.rule_id == "V-04" for f in res.findings)
    bad = approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("lines[1].credit", "400.005")], actor="acc")
    assert any(f.rule_id == "D-06" and f.severity == Severity.ERROR for f in bad.findings)  # more than 2 decimals: rejected, not rounded
    with pytest.raises(ServiceError):
        approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    fixed = approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("lines[1].credit", "500.00")], actor="acc")
    assert fixed.draft_voucher_id is not None


def test_D63_tally_item_reject_and_accept_clean_bulk(svc_conn, world):
    w = world
    good, _ = tally_item(svc_conn, w, ref="G-1")
    bad, _ = tally_item(svc_conn, w, with_second_ledger=False, ref="G-2")
    rejected_item, _ = tally_item(svc_conn, w, ref="G-3")
    # a clean item is accepted by the bulk action (the service re-runs the checks and builds the draft); one with findings is refused
    out = approval_queue.accept_clean(svc_conn, w.client_id, [good, bad], actor="acc")
    assert out["accepted"] == [str(good)] and [r["id"] for r in out["refused"]] == [str(bad)]
    assert item_row(svc_conn, bad).status == "pending"
    # reject a drafted Tally item: the draft goes, the source reference can be queued again (unique index ignores rejected)
    res = approval_queue.edit_fields(svc_conn, w.client_id, rejected_item, edits=[("reference_no", "9")], actor="acc")
    approval_queue.reject(svc_conn, w.client_id, rejected_item, reason="Not our voucher", actor="acc")
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE id = :v", v=res.draft_voucher_id) == 0
    assert item_row(svc_conn, rejected_item).status == "rejected"
    # accepted draft cannot be deleted either
    accepted_voucher = scalar(svc_conn, "SELECT draft_voucher_id FROM approval_queue_items WHERE id = :i", i=good)
    with pytest.raises(ServiceError) as e:
        vouchers.delete_draft(svc_conn, accepted_voucher, actor="x")
    assert e.value.code == "queue_item_exists"


def test_D64_every_queue_action_is_audited_with_old_and_new(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext, built = queue_from_llm(svc_conn, w, answer())
    item_id = built.queue_item_id
    approval_queue.claim(svc_conn, w.client_id, item_id, actor="acc")
    approval_queue.release(svc_conn, w.client_id, item_id, actor="acc")
    approval_queue.edit_fields(svc_conn, w.client_id, item_id, edits=[("buyer_name", "Queue Traders Ltd")], actor="acc")
    approval_queue.accept(svc_conn, w.client_id, item_id, actor="acc")
    actions = [r[0] for r in svc_conn.execute(text("SELECT action FROM audit_log WHERE entity = 'approval_queue_item' AND entity_id = :i ORDER BY id"),
                                              {"i": item_id})]
    assert actions[0] == "queue_item_created"
    assert [a for a in actions if a in ("queue_item_claimed", "queue_item_released", "queue_item_edited", "queue_item_accepted")] == [
        "queue_item_claimed", "queue_item_released", "queue_item_edited", "queue_item_accepted"]
    detail = approval_queue.get_detail(svc_conn, w.client_id, item_id)
    assert {h["actor"] for h in detail["history"]} == {"clerk", "acc"} and detail["findings"] == []


# ================================================================================================ narration suggestions


def line_of(w, key):
    return w.lines[key]


class Boom(FakeLlmClient):
    """A model that must never be called."""

    def __init__(self):
        super().__init__([])

    def complete(self, request):
        raise AssertionError("the model must not be called when a rule exists or the switch is off")


def pick(name):
    """A scripted model: answers with the code of the ledger called `name` in the list it was given."""

    def respond(request):
        code = re.search(rf"^(L\d+): {re.escape(name)}$", request.user, re.MULTILINE).group(1)
        return json.dumps({"choice": code, "confidence": 0.8})

    return respond


def test_D41_D44_rule_learned_from_accepted_suggestions_comes_first_and_the_model_is_not_called(svc_conn, world, monkeypatch):
    w = world
    monkeypatch.setenv("LLM_MODEL", "fake/model")
    # first line: no rule yet -> the model is the fallback (D-43)
    fake = FakeLlmClient(pick("Tea Expense"))
    first = narration.suggest(svc_conn, w.client_id, line_of(w, "tea1"), actor="acc", llm_client=fake)
    assert first.status == "suggested" and first.suggestion.source == "llm"
    assert first.suggestion.ledger_name == "Tea Expense" and first.suggestion.confidence == D("0.8000")
    assert "check it" in first.suggestion.reason
    # what reached the model: the narration without numbers / dates, the direction, ledger names; no ledger id, no amount
    sent = fake.requests[0].user
    assert "Ramesh Tea Stall" in sent and "150.00" not in sent and str(w.ids["Tea Expense"]) not in sent
    assert scalar(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c AND narration ILIKE '%tea stall%'", c=w.client_id) == 0
    # not applied by itself: no rule exists until the accountant accepts
    assert scalar(svc_conn, "SELECT count(*) FROM narration_rules WHERE client_id = :c", c=w.client_id) == 0
    assert narration.accept_suggestion(svc_conn, w.client_id, first.suggestion.id, actor="acc").learned is True
    assert scalar(svc_conn, "SELECT approved_count FROM narration_rules WHERE client_id = :c AND narration_key = 'upi dr ramesh tea stall sbin'",
                  c=w.client_id) == 1
    with pytest.raises(ServiceError) as e:  # a decision is final
        narration.reject_suggestion(svc_conn, w.client_id, first.suggestion.id, actor="acc")
    assert e.value.code == "suggestion_decided"
    # second line, same payee, other reference numbers: the RULE answers, the model is never called
    second = narration.suggest(svc_conn, w.client_id, line_of(w, "tea2"), actor="acc", llm_client=Boom())
    assert (second.status, second.suggestion.source, second.suggestion.ledger_name) == ("suggested", "rule", "Tea Expense")
    assert second.suggestion.reason == "Learned from 1 earlier entry with the same narration."
    narration.accept_suggestion(svc_conn, w.client_id, second.suggestion.id, actor="acc")
    assert scalar(svc_conn, "SELECT approved_count FROM narration_rules WHERE client_id = :c", c=w.client_id) == 2
    again = narration.suggest(svc_conn, w.client_id, line_of(w, "tea2"), actor="acc", llm_client=Boom())
    assert again.suggestion.id == second.suggestion.id  # no churn of rows


def test_D42_ambiguous_rules_select_nothing_and_list_the_candidates(svc_conn, world):
    w = world
    key = "cheque no to gupta"
    svc_conn.execute(text("INSERT INTO narration_rules (client_id, direction, narration_key, ledger_id, approved_count, created_by) VALUES "
                          "(:c, 'debit', :k, :a, 3, 'acc'), (:c, 'debit', :k, :b, 1, 'acc')"),
                     {"c": w.client_id, "k": key, "a": w.ids["Tea Expense"], "b": w.ids["Staff Welfare"]})
    res = narration.suggest(svc_conn, w.client_id, line_of(w, "amb"), actor="acc", llm_client=Boom())
    assert res.status == "ambiguous" and res.suggestion is None
    assert [(c["ledger_name"], c["count"]) for c in res.ambiguous] == [("Tea Expense", 3), ("Staff Welfare", 1)]
    assert scalar(svc_conn, "SELECT count(*) FROM narration_suggestions WHERE client_id = :c", c=w.client_id) == 0
    # the accountant can switch a rule off: the narration then points to one ledger again (D-41)
    rule_id = scalar(svc_conn, "SELECT id FROM narration_rules WHERE client_id = :c AND ledger_id = :l", c=w.client_id, l=w.ids["Staff Welfare"])
    narration.set_rule_active(svc_conn, w.client_id, rule_id, False, actor="acc")
    one = narration.suggest(svc_conn, w.client_id, line_of(w, "amb"), actor="acc", llm_client=Boom())
    assert one.status == "suggested" and one.suggestion.reason == "Learned from 3 earlier entries with the same narration."


def test_D43_switch_off_means_no_model_call_and_a_clear_status(svc_conn, world):
    w = world
    svc_conn.execute(text("UPDATE client_ai_settings SET llm_enabled = false, enabled_by = NULL, enabled_at = NULL WHERE client_id = :c"),
                     {"c": w.client_id})
    res = narration.suggest(svc_conn, w.client_id, line_of(w, "llm1"), actor="acc", llm_client=Boom())
    assert res.status == "llm_blocked" and "switched off" in res.message
    assert scalar(svc_conn, "SELECT count(*) FROM llm_calls WHERE client_id = :c AND purpose = 'narration_suggestion'", c=w.client_id) == 0


def test_D43_D53_model_answers_that_do_not_fit_are_dropped_and_pii_is_masked(svc_conn, world, monkeypatch):
    w = world
    monkeypatch.setenv("LLM_MODEL", "fake/model")
    # a ledger that is not in the list given
    fake = FakeLlmClient([json.dumps({"choice": "L999", "confidence": 0.9})])
    res = narration.suggest(svc_conn, w.client_id, line_of(w, "llm1"), actor="acc", llm_client=fake)
    assert res.status == "none" and res.suggestion is None and "not in the client's list" in res.message
    assert scalar(svc_conn, "SELECT count(*) FROM narration_suggestions WHERE client_id = :c", c=w.client_id) == 0
    assert scalar(svc_conn, "SELECT count(*) FROM llm_calls WHERE client_id = :c AND purpose = 'narration_suggestion' AND status = 'ok'",
                  c=w.client_id) == 1
    # a PAN in the narration never reaches the model (masked by the gateway, D-50)
    fake2 = FakeLlmClient(pick("Staff Welfare"))
    res2 = narration.suggest(svc_conn, w.client_id, line_of(w, "llm2"), actor="acc", llm_client=fake2)
    assert res2.status == "suggested" and "ABCDE1234F" not in fake2.requests[0].user
    assert res2.suggestion.source == "llm"
    # a rejected model suggestion teaches nothing and the model is not asked again for the same line
    narration.reject_suggestion(svc_conn, w.client_id, res2.suggestion.id, actor="acc")
    assert scalar(svc_conn, "SELECT count(*) FROM narration_rules WHERE client_id = :c", c=w.client_id) == 0
    after = narration.suggest(svc_conn, w.client_id, line_of(w, "llm2"), actor="acc", llm_client=Boom())
    assert after.status == "none"


# ================================================================================================ API


@pytest.fixture
def client(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_queue_flow_and_error_codes(client, svc_conn, world):
    w = world
    cid = str(w.client_id)
    save_mappings(svc_conn, w)
    doc, ext, built = queue_from_llm(svc_conn, w, wrong_cgst_answer())
    iid = str(built.queue_item_id)
    lst = client.get(f"/clients/{cid}/queue", params={"status": "pending", "has_blocking": "true"}).json()
    assert [r["id"] for r in lst] == [iid]
    assert lst[0]["summary"] == {"party": "Shree Traders", "reference_no": "INV-77", "date": "10-05-2026", "total": "2832.50"}
    d = client.get(f"/clients/{cid}/queue/{iid}").json()
    assert d["document"]["download_url"] == f"/clients/{cid}/documents/{doc}/download"
    assert d["original"] == d["current"] and any(f["rule_id"] == "D-11" for f in d["findings"]) and d["draft_voucher"] is None
    r = client.post(f"/clients/{cid}/queue/{iid}/accept", json={}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "queue_blocked"
    assert client.post(f"/clients/{cid}/queue/{iid}/accept", json={}).status_code == 400  # no X-User
    r = client.put(f"/clients/{cid}/queue/{iid}/fields", json={"edits": [{"field_path": "lines[0].cgst", "value": "180.00"}]}, headers=H)
    assert r.status_code == 200 and r.json()["draft_voucher_id"] is not None and r.json()["status"] == "pending"
    assert client.put(f"/clients/{cid}/queue/{iid}/fields", json={"edits": [{"field_path": "nope.x", "value": "1"}]}, headers=H).status_code == 422
    assert client.put(f"/clients/{cid}/queue/{iid}/fields", json={}, headers=H).status_code == 422
    vid = r.json()["draft_voucher_id"]
    assert client.post(f"/vouchers/{vid}/approve", headers=H).status_code == 409  # queue_not_accepted
    r = client.post(f"/clients/{cid}/queue/{iid}/accept", json={"acknowledge": [], "learn": False}, headers=H)
    assert r.status_code == 200 and r.json()["draft_voucher_id"] == vid
    d = client.get(f"/clients/{cid}/queue/{iid}").json()
    assert d["status"] == "accepted" and d["draft_voucher"]["status"] == "draft"
    assert all(re.fullmatch(r"\d+\.\d{2}", x["debit"]) and re.fullmatch(r"\d+\.\d{2}", x["credit"]) for x in d["draft_voucher"]["lines"])
    assert d["original"]["lines"][0]["cgst"]["value"] == "200.00" and d["current"]["lines"][0]["cgst"]["value"] == "180.00"
    assert client.post(f"/clients/{cid}/queue/{iid}/reject", json={"reason": "late"}, headers=H).status_code == 409
    assert client.get(f"/clients/{cid}/queue/{uuid.uuid4()}").status_code == 404


def test_api_narration_suggestion_accept_and_rules(client, svc_conn, world, monkeypatch):
    w = world
    cid = str(w.client_id)
    monkeypatch.setenv("LLM_MODEL", "fake/model")
    fake = FakeLlmClient(pick("Staff Welfare"))
    app.dependency_overrides[narration_api.get_llm_client] = lambda: fake
    line = str(w.lines["llm3"])
    assert client.get(f"/clients/{cid}/bank/lines/{line}/suggestion").status_code == 400  # needs X-User (it records a row)
    r = client.get(f"/clients/{cid}/bank/lines/{line}/suggestion", headers=H).json()
    assert r["status"] == "suggested" and r["suggestion"]["source"] == "llm" and r["suggestion"]["confidence"] == "0.8000"
    assert r["suggestion"]["ledger_name"] == "Staff Welfare" and r["ambiguous"] == []
    sid = r["suggestion"]["id"]
    assert client.post(f"/clients/{cid}/bank/suggestions/{sid}/accept", headers=H).json() == {"ok": True, "learned": True}
    rules = client.get(f"/clients/{cid}/ai/narration-rules").json()
    assert [(x["direction"], x["narration_key"], x["ledger_name"], x["approved_count"], x["is_active"]) for x in rules] == [
        ("debit", "payment to joshi sweets", "Staff Welfare", 1, True)]
    assert client.put(f"/clients/{cid}/ai/narration-rules/{rules[0]['id']}", json={"is_active": False}, headers=H).json() == {"ok": True}
    assert client.get(f"/clients/{cid}/ai/narration-rules").json()[0]["is_active"] is False
    assert client.post(f"/clients/{cid}/bank/suggestions/{uuid.uuid4()}/reject", headers=H).status_code == 404
