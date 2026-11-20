"""Package D against the database: the extraction service and API with SCRIPTED model answers (ai/fake.py; no network, no key).

Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_extractions_service.py`.
Every test runs in a rolled-back transaction. The gateway here is a TEST DOUBLE of package C's gateway: it checks the client's switch (D-51),
writes an `llm_calls` row and calls the fake client. Expected values are hand-calculated:

  clean purchase, Maharashtra to Maharashtra, 10-05-2026 (seeded example rules: HSN 8415 = 18 % from 22-09-2025, HSN 1701 = 5 %):
    line 1: 8415, 2 x 1000.00           -> taxable 2000.00, CGST 180.00, SGST 180.00
    line 2: 1701, 1 x 500.00 - 50.00    -> taxable  450.00, CGST  11.25, SGST  11.25
    totals: taxable 2450.00, CGST 191.25, SGST 191.25, grand total 2832.50
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date

import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai.fake import FakeLlmClient
from app.ai.llm import LlmError, LlmRequest
from app.api import extractions as extractions_api
from app.api.deps import get_conn
from app.engine.doc_types import DocFinding, QueueKind, Severity
from app.main import app
from app.services import ai_hooks, extractions, gst_registrations
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

CLIENT_GSTIN = "27AAAPL1234C1ZE"
SUPPLIER = "27CCCPM4321E1ZZ"
H = {"X-User": "clerk"}


def fv(value, conf=0.95):
    return {"value": value, "page": 1, "bbox": None, "confidence": conf}


def invoice_answer(**over):
    ans = {
        "document_kind": fv("Tax Invoice"), "supplier_name": fv("Shree Traders"), "supplier_gstin": fv(SUPPLIER),
        "buyer_name": fv("Client Pvt Ltd"), "buyer_gstin": fv(CLIENT_GSTIN), "invoice_no": fv("INV-77"),
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


@dataclass
class GatewayResult:
    status: str
    llm_call_id: object
    text: str | None
    message: str


class TestGateway:
    """Stands in for package C's gateway: switch check, one llm_calls row per call, then the fake client."""

    __test__ = False

    def __init__(self, fake: FakeLlmClient):
        self.fake = fake

    def call(self, conn, *, client_id, document_id, request: LlmRequest, prompt_version, actor):
        if not ai_hooks.llm_enabled(conn, client_id):
            call_id = conn.execute(text(
                "INSERT INTO llm_calls (client_id, document_id, purpose, provider, prompt_version, status, created_by) "
                "VALUES (:c, :d, :p, 'test', :v, 'blocked', :by) RETURNING id"),
                {"c": client_id, "d": document_id, "p": request.purpose, "v": prompt_version, "by": actor}).scalar_one()
            return GatewayResult("blocked", call_id, None, "AI reading is switched off for this client.")
        try:
            answer = self.fake.complete(request)
        except LlmError as error:
            call_id = conn.execute(text(
                "INSERT INTO llm_calls (client_id, document_id, purpose, provider, model, prompt_version, prompt_masked, masking_applied, "
                "status, error_message, created_by) VALUES (:c, :d, :p, 'test', 'fake/model', :v, :u, true, 'error', :e, :by) RETURNING id"),
                {"c": client_id, "d": document_id, "p": request.purpose, "v": prompt_version, "u": request.user, "e": str(error),
                 "by": actor}).scalar_one()
            return GatewayResult("error", call_id, None, str(error))
        call_id = conn.execute(text(
            "INSERT INTO llm_calls (client_id, document_id, purpose, provider, model, prompt_version, prompt_masked, masking_applied, "
            "response_raw, status, created_by) VALUES (:c, :d, :p, 'test', 'fake/model', :v, :u, true, :r, 'ok', :by) RETURNING id"),
            {"c": client_id, "d": document_id, "p": request.purpose, "v": prompt_version, "u": request.user, "r": answer.text,
             "by": actor}).scalar_one()
        return GatewayResult("ok", call_id, answer.text, "")


@pytest.fixture
def f(svc_conn) -> Factory:
    return Factory(svc_conn.connection.driver_connection)


@pytest.fixture
def world(svc_conn, f):
    """A client with FY 2026-27, a GST registration (GSTIN of the client above) and the AI switch on."""
    client_id, _ = f.setup()
    gst_registrations.create_registration(svc_conn, client_id, gstin=CLIENT_GSTIN, registration_type="regular",
                                          effective_from=date(2026, 4, 1), actor="clerk")
    svc_conn.execute(text("INSERT INTO client_ai_settings (client_id, llm_enabled, enabled_by, enabled_at, note, updated_by) "
                          "VALUES (:c, true, 'owner', now(), 'synthetic data only', 'owner')"), {"c": client_id})
    return client_id


def new_doc(conn, client_id, doc_type="purchase_invoice", *, text_pages=("Invoice text page 1",), n=None):
    n = n or uuid.uuid4().int
    doc_id = conn.execute(text(
        "INSERT INTO documents (client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by, page_count) "
        "VALUES (:c, :t, 'bill.pdf', 'application/pdf', 100, :h, :k, 'clerk', 1) RETURNING id"),
        {"c": client_id, "t": doc_type, "h": f"{n % (16 ** 63):064x}", "k": f"{str(client_id)[:8]}/{n % (16 ** 63):064x}.pdf"}).scalar_one()
    for no, page in enumerate(text_pages, start=1):
        conn.execute(text("INSERT INTO document_texts (client_id, document_id, page_no, method, engine_version, text) "
                          "VALUES (:c, :d, :n, 'pdf_text', 'test', :t)"), {"c": client_id, "d": doc_id, "n": no, "t": page})
    return doc_id


def run(conn, client_id, doc_id, *answers):
    fake = FakeLlmClient([a if isinstance(a, (str, Exception)) else json.dumps(a) for a in answers])
    out = extractions.run_llm_extraction(conn, client_id=client_id, document_id=doc_id, actor="clerk", gateway=TestGateway(fake))
    return out, fake


def ids(out):
    return sorted((x.rule_id, x.severity.value, x.field_path) for x in out.findings)


def test_D05_to_D13_clean_answer_is_stored_and_recomputed_with_no_finding(svc_conn, world):
    doc = new_doc(svc_conn, world)
    out, fake = run(svc_conn, world, doc, invoice_answer())
    assert out.status == "ok" and out.findings == () and out.version == 1
    row = extractions.get_extraction(svc_conn, world, out.extraction_id)
    assert (row.status, row.source, row.schema_version, row.llm_call_id) == ("valid", "llm", "invoice-extract-1", out.llm_call_id)
    assert row.payload["invoice_no"]["value"] == "INV-77" and row.payload["lines"][1]["discount"]["value"] == "50.00"
    chk = extractions.check_extraction(svc_conn, world, out.extraction_id)
    assert chk.direction == "purchase" and chk.place_of_supply == "27"
    assert chk.recomputed["totals"] == {"taxable_total": "2450.00", "cgst_total": "191.25", "sgst_total": "191.25", "igst_total": "0.00",
                                        "cess_total": "0.00", "round_off": "0.00", "grand_total": "2832.50"}
    assert chk.recomputed["lines"][1] == {"taxable_value": "450.00", "rate": "5.0000", "cgst": "11.25", "sgst": "11.25",
                                          "igst": "0.00", "cess": "0.00"}
    # what the model was sent: fixed system text, the page text as data (the real gateway masks it, package C)
    assert "Invoice text page 1" in fake.requests[0].user and "Invoice text page 1" not in fake.requests[0].system
    audit_rows = svc_conn.execute(text("SELECT action FROM audit_log WHERE entity = 'extraction'")).scalars().all()
    assert audit_rows == ["extraction_created"]


def test_injected_wrong_extractions_are_each_flagged_with_the_expected_rule(svc_conn, world):
    doc = new_doc(svc_conn, world)
    bad_total = invoice_answer(totals={**invoice_answer()["totals"], "grand_total": fv("2932.50")})
    out, _ = run(svc_conn, world, doc, bad_total)
    assert out.status == "ok" and ids(out) == [("D-13", "error", "totals.grand_total")]

    wrong_tax = invoice_answer()
    wrong_tax["lines"][0]["cgst"] = fv("170.00")
    out, _ = run(svc_conn, world, doc, wrong_tax)
    assert ids(out) == [("D-11", "error", "lines[0].cgst")] and out.version == 2

    bad_gstin = invoice_answer(supplier_gstin=fv("27CCCPM4321E1ZA"))
    out, _ = run(svc_conn, world, doc, bad_gstin)
    assert ids(out) == [("D-07", "error", "supplier_gstin")]

    missing = invoice_answer(invoice_no={"value": None, "page": None})
    out, _ = run(svc_conn, world, doc, missing)
    assert ids(out) == [("D-05", "error", "invoice_no")]

    low = invoice_answer(invoice_date=fv("10-05-2026", 0.6))
    out, _ = run(svc_conn, world, doc, low)
    assert ids(out) == [("D-05", "warning", "invoice_date")]

    # each run superseded the one before; the earlier rows are still there
    versions = extractions.list_versions(svc_conn, world, doc)
    assert [(v.version, v.superseded_at is not None) for v in versions] == [(1, True), (2, True), (3, True), (4, True), (5, False)]


def test_D04_answer_that_is_not_json_or_has_extra_keys_is_stored_invalid_and_nothing_is_drafted(svc_conn, world):
    doc = new_doc(svc_conn, world)
    out, _ = run(svc_conn, world, doc, "Sorry, I cannot read this invoice.")
    assert out.status == "invalid" and out.extraction_id is not None and out.llm_call_id is not None
    row = extractions.get_extraction(svc_conn, world, out.extraction_id)
    assert (row.status, row.payload, row.invalid_reason) == ("invalid", {}, "The answer is not valid JSON.")
    assert [x.rule_id for x in out.findings] == ["D-04"]
    with pytest.raises(ServiceError) as e:
        extractions.check_extraction(svc_conn, world, out.extraction_id)
    assert e.value.code == "extraction_invalid"

    out, _ = run(svc_conn, world, doc, invoice_answer(approve_and_post_voucher=True))
    assert out.status == "invalid" and "approve_and_post_voucher" in out.message and out.version == 2
    assert svc_conn.execute(text("SELECT count(*) FROM approval_queue_items")).scalar_one() == 0


def test_D51_switch_off_blocks_the_call_and_stores_no_extraction(svc_conn, world):
    svc_conn.execute(text("UPDATE client_ai_settings SET llm_enabled = false, enabled_by = NULL, enabled_at = NULL, note = NULL"))
    doc = new_doc(svc_conn, world)
    out, fake = run(svc_conn, world, doc)
    assert out.status == "blocked" and out.extraction_id is None and fake.requests == []
    assert svc_conn.execute(text("SELECT status FROM llm_calls WHERE id = :i"), {"i": out.llm_call_id}).scalar_one() == "blocked"
    assert extractions.list_versions(svc_conn, world, doc) == []


def test_provider_error_is_a_result_not_an_exception_and_the_call_is_logged(svc_conn, world):
    doc = new_doc(svc_conn, world)
    out, _ = run(svc_conn, world, doc, LlmError("The model service did not answer (timeout)."))
    assert out.status == "error" and out.extraction_id is None and "timeout" in out.message
    assert svc_conn.execute(text("SELECT status FROM llm_calls WHERE id = :i"), {"i": out.llm_call_id}).scalar_one() == "error"


def test_bad_requests_raise_service_errors_and_write_nothing(svc_conn, world, f):
    no_text = new_doc(svc_conn, world, text_pages=())
    with pytest.raises(ServiceError) as e:
        run(svc_conn, world, no_text)
    assert e.value.code == "no_text"
    tally = new_doc(svc_conn, world, "tally_xml")
    with pytest.raises(ServiceError) as e:
        run(svc_conn, world, tally)
    assert e.value.code == "invalid_document_type"
    other_client = f.client()
    doc = new_doc(svc_conn, world)
    with pytest.raises(ServiceError) as e:
        run(svc_conn, other_client, doc)
    assert e.value.code == "not_found"
    assert svc_conn.execute(text("SELECT count(*) FROM llm_calls")).scalar_one() == 0


def _queue_item(conn, client_id, doc_id, extraction_id):
    return ai_hooks.add_queue_item(conn, client_id=client_id, kind=QueueKind.INVOICE, document_id=doc_id, extraction_id=extraction_id,
                                   findings=[DocFinding("D-20", Severity.REVIEW, "party not mapped")], created_by="clerk")


def test_queue_state_a_live_queue_item_blocks_a_new_extraction_until_it_is_rejected(svc_conn, world):
    doc = new_doc(svc_conn, world)
    out, _ = run(svc_conn, world, doc, invoice_answer())
    item = _queue_item(svc_conn, world, doc, out.extraction_id)
    with pytest.raises(ServiceError) as e:
        run(svc_conn, world, doc, invoice_answer())
    assert e.value.code == "queue_state"
    svc_conn.execute(text("UPDATE approval_queue_items SET status = 'rejected', rejected_by = 'owner', rejected_at = now(), "
                          "reject_reason = 'wrong document' WHERE id = :i"), {"i": item})
    again, _ = run(svc_conn, world, doc, invoice_answer())
    assert again.status == "ok" and again.version == 2
    assert extractions.get_extraction(svc_conn, world, out.extraction_id).superseded_at is not None


def test_manual_extraction_needs_no_switch_model_page_or_confidence(svc_conn, world):
    svc_conn.execute(text("UPDATE client_ai_settings SET llm_enabled = false, enabled_by = NULL, enabled_at = NULL, note = NULL"))
    doc = new_doc(svc_conn, world, text_pages=())
    typed = {k: {"value": v} for k, v in {"supplier_name": "Shree Traders", "supplier_gstin": SUPPLIER, "buyer_name": "Client Pvt Ltd",
                                          "buyer_gstin": CLIENT_GSTIN, "invoice_no": "INV-77", "invoice_date": "2026-05-10",
                                          "place_of_supply": "27"}.items()}
    typed["lines"] = [{"description": {"value": "Sugar"}, "hsn_sac": {"value": "1701"}, "quantity": {"value": "10"},
                       "unit_rate": {"value": "100.00"}, "taxable_value": {"value": "1000.00"}, "cgst": {"value": "25.00"},
                       "sgst": {"value": "25.00"}}]
    typed["totals"] = {"grand_total": {"value": "1050.00"}}
    out = extractions.enter_manual(svc_conn, client_id=world, document_id=doc, actor="clerk", payload=typed)
    assert out.status == "ok" and out.findings == () and out.llm_call_id is None
    assert extractions.get_extraction(svc_conn, world, out.extraction_id).source == "manual"
    wrong = json.loads(json.dumps(typed))
    wrong["totals"]["grand_total"] = {"value": "1060.00"}
    svc_conn.execute(text("UPDATE extractions SET superseded_at = now() WHERE id = :i"), {"i": out.extraction_id})
    out = extractions.enter_manual(svc_conn, client_id=world, document_id=doc, actor="clerk", payload=wrong)
    assert ids(out) == [("D-13", "error", "totals.grand_total")]
    bad_schema = extractions.enter_manual(svc_conn, client_id=world, document_id=doc, actor="clerk", payload={"surprise": 1})
    assert bad_schema.status == "invalid"


def test_D03_same_supplier_and_invoice_number_on_another_document_is_a_warning(svc_conn, world):
    first = new_doc(svc_conn, world)
    out, _ = run(svc_conn, world, first, invoice_answer())
    assert out.findings == ()
    second = new_doc(svc_conn, world)
    out, _ = run(svc_conn, world, second, invoice_answer())
    assert ids(out) == [("D-03", "warning", "invoice_no")]
    assert "another document" in out.findings[0].message
    # the first document's own re-check does not flag itself, only the other document counts
    again = extractions.check_extraction(svc_conn, world, extractions.list_versions(svc_conn, world, first)[0].id)
    assert [x.rule_id for x in again.findings] == ["D-03"]


def test_D18_bank_statement_extraction_flags_a_wrong_running_balance(svc_conn, world):
    doc = new_doc(svc_conn, world, "bank_statement")
    fvb = fv
    answer = {"bank_name": fvb("Test Bank"), "account_ref": fvb("<ACCOUNT_1>"), "opening_balance": fvb("1000.00"),
              "closing_balance": fvb("1300.00"),
              "lines": [{"date": fvb("01-04-2026"), "narration": fvb("UPI/ABC"), "credit": fvb("500.00"), "balance": fvb("1500.00")},
                        {"date": fvb("02-04-2026"), "narration": fvb("ATM"), "debit": fvb("200.00"), "balance": fvb("1200.00")}]}
    out, fake = run(svc_conn, world, doc, answer)
    assert out.status == "ok" and ids(out) == [("D-18", "error", "lines[1].balance")]
    assert "bank statement" in fake.requests[0].system
    assert extractions.get_extraction(svc_conn, world, out.extraction_id).schema_version == "bank-extract-1"


@pytest.fixture
def api(svc_conn, monkeypatch):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_extract_check_and_read_back_with_a_scripted_model(svc_conn, world, api, monkeypatch):
    doc = new_doc(svc_conn, world)
    wrong = invoice_answer(totals={**invoice_answer()["totals"], "grand_total": fv("2932.50")})
    fake = FakeLlmClient([json.dumps(wrong), "not json"])
    monkeypatch.setattr(extractions_api, "get_gateway", lambda: TestGateway(fake))
    base = f"/clients/{world}"
    r = api.post(f"{base}/documents/{doc}/extract", json={"mode": "llm"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and [(x["rule_id"], x["severity"], x["printed"], x["computed"]) for x in body["findings"]] == [
        ("D-13", "error", "2932.50", "2832.50")]
    ext = body["extraction_id"]
    got = api.get(f"{base}/extractions/{ext}").json()
    assert got["status"] == "valid" and got["payload"]["totals"]["grand_total"]["value"] == "2932.50"
    chk = api.post(f"{base}/extractions/{ext}/check").json()
    assert chk["recomputed"]["totals"]["grand_total"] == "2832.50" and chk["direction"] == "purchase"
    assert [v["version"] for v in api.get(f"{base}/documents/{doc}/extractions").json()] == [1]
    # a second, invalid answer is a normal 200 answer with status invalid (the audit rows commit), and its check is a 422
    r = api.post(f"{base}/documents/{doc}/extract", json={"mode": "llm"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "invalid"
    bad = api.post(f"{base}/extractions/{r.json()['extraction_id']}/check")
    assert bad.status_code == 422 and bad.json()["code"] == "extraction_invalid"
    assert api.post(f"{base}/documents/{doc}/extract", json={"mode": "manual"}, headers=H).status_code == 422
    assert api.post(f"{base}/documents/{doc}/extract", json={"mode": "llm"}).status_code == 400    # X-User is required
    assert api.get(f"{base}/extractions/{uuid.uuid4()}").status_code == 404
