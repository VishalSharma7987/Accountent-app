"""Phase 7 package A: documents API and service on the mini case (private store, D-01, D-02, text reading, links).

Run once through the lock script:
`C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_documents_service.py`.
Each test runs in the rolled-back `svc_conn`; the stored files live in pytest's tmp folder. No network, no LLM, no OCR program.
"""

import hashlib
import io
from datetime import date
from decimal import Decimal

import pytest
from books import draft
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai import ocr
from app.ai.storage import PrivateStore
from app.api.deps import get_conn
from app.api.documents import get_store
from app.main import app
from app.services import vouchers

reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
pytestmark = pytest.mark.integration

H = {"X-User": "tester"}


def make_pdf(pages):
    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf)
    for page_text in pages:
        if page_text:
            c.drawString(72, 750, page_text)
        c.showPage()
    c.save()
    return buf.getvalue()


INVOICE = make_pdf(["Tax Invoice B-101 Supplier Sharma Traders Total 1,180.00", "Page two terms"])
SCAN = make_pdf(["", ""])
PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 40


@pytest.fixture
def api(svc_conn, tmp_path):
    store = PrivateStore(tmp_path / "docstore")
    app.dependency_overrides[get_conn] = lambda: svc_conn
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    client.store_root = tmp_path / "docstore"
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def b(books):
    return books[0]


@pytest.fixture
def other(books):
    return books[1]


def upload(api, client_id, data=INVOICE, name="bill.pdf", doc_type="purchase_invoice", headers=H, **extra):
    return api.post(f"/clients/{client_id}/documents", files={"file": (name, data)}, data={"doc_type": doc_type, **extra}, headers=headers)


def rows(svc_conn, sql, **params):
    return svc_conn.execute(text(sql), params).all()


# ------------------------------------------------------------------------------------------------ upload, D-01, D-02


def test_D01_upload_stores_the_file_privately_under_a_generated_key_and_audits_it(api, b, svc_conn):
    r = upload(api, b.client_id, name="..\\..\\evil name.pdf", financial_year_id=str(b.fy_id))
    assert r.status_code == 201, r.text
    body = r.json()
    sha = hashlib.sha256(INVOICE).hexdigest()
    assert (body["sha256"], body["size_bytes"], body["content_type"], body["status"], body["page_count"]) == (
        sha, len(INVOICE), "application/pdf", "uploaded", 2)
    stored = api.store_root / str(b.client_id) / f"{sha}.pdf"
    assert stored.read_bytes() == INVOICE
    doc = rows(svc_conn, "SELECT original_filename, storage_key, uploaded_by FROM documents WHERE id = :i", i=body["id"])[0]
    assert tuple(doc) == ("evil name.pdf", f"{b.client_id}/{sha}.pdf", "tester")
    audit = rows(svc_conn, "SELECT actor, action, new_data->>'sha256' FROM audit_log WHERE entity = 'document' AND entity_id = :i", i=body["id"])
    assert [tuple(a) for a in audit] == [("tester", "document_uploaded", sha)]


def test_D01_file_decided_by_content_an_exe_named_pdf_is_rejected_and_nothing_is_stored(api, b, svc_conn):
    r = upload(api, b.client_id, data=b"MZ\x90\x00 not a pdf", name="invoice.pdf")
    assert r.status_code == 422 and r.json()["code"] == "file_rejected"
    r2 = upload(api, b.client_id, data=b"", name="empty.pdf")
    assert r2.status_code == 422 and "empty" in r2.json()["message"]
    r3 = upload(api, b.client_id, data=b"%PDF-1.4 broken", name="broken.pdf")
    assert r3.status_code == 422 and r3.json()["code"] == "file_rejected"
    assert rows(svc_conn, "SELECT count(*) FROM documents WHERE client_id = :c", c=b.client_id)[0][0] == 0
    assert not api.store_root.exists() or not any(api.store_root.rglob("*.*"))


def test_D01_size_limit_comes_from_config(api, b, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "100")
    r = upload(api, b.client_id)
    assert r.status_code == 422 and r.json()["code"] == "file_rejected"


def test_D01_unknown_document_type_and_missing_actor(api, b):
    assert upload(api, b.client_id, doc_type="selfie").status_code == 422
    assert upload(api, b.client_id, headers={}).status_code == 400
    assert upload(api, "not-a-uuid").status_code == 404


def test_D02_same_file_twice_for_a_client_is_a_conflict_that_names_the_existing_document(api, b, other):
    first = upload(api, b.client_id)
    again = upload(api, b.client_id, name="renamed copy.pdf")
    assert again.status_code == 409
    assert again.json()["code"] == "duplicate_document"
    assert again.json()["details"]["document_id"] == first.json()["id"]
    elsewhere = upload(api, other.client_id)  # another client may hold the same bytes
    assert elsewhere.status_code == 201 and elsewhere.json()["id"] != first.json()["id"]


def test_D01_store_not_configured_is_503_store_unavailable(svc_conn, b, monkeypatch):
    monkeypatch.delenv("DOCUMENT_STORE_DIR", raising=False)
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        r = TestClient(app).post(f"/clients/{b.client_id}/documents", files={"file": ("a.pdf", INVOICE)},
                                 data={"doc_type": "other"}, headers=H)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"


def test_D01_tally_documents_need_xml_and_are_stored_as_xml(api, b):
    xml = b'<?xml version="1.0"?><ENVELOPE><HEADER/></ENVELOPE>'
    assert upload(api, b.client_id, data=xml, doc_type="tally_xml", name="t.xml").status_code == 201
    assert upload(api, b.client_id, data=xml, doc_type="purchase_invoice", name="t.xml").status_code == 422


# ------------------------------------------------------------------------------------------------ list, get, download


def test_D01_list_filters_and_get_detail(api, b):
    pdf = upload(api, b.client_id).json()
    img = upload(api, b.client_id, data=PNG, name="photo.png", doc_type="expense_bill").json()
    listed = api.get(f"/clients/{b.client_id}/documents", headers=H).json()
    assert {d["id"] for d in listed} == {pdf["id"], img["id"]}
    assert [d["id"] for d in api.get(f"/clients/{b.client_id}/documents?doc_type=expense_bill", headers=H).json()] == [img["id"]]
    assert [d["id"] for d in api.get(f"/clients/{b.client_id}/documents?q=PHOTO", headers=H).json()] == [img["id"]]
    assert api.get(f"/clients/{b.client_id}/documents?status=done", headers=H).json() == []
    one = api.get(f"/clients/{b.client_id}/documents/{img['id']}").json()
    assert (one["content_type"], one["page_count"], one["texts"], one["extractions"], one["queue_item_id"], one["linked_voucher_ids"]) == (
        "image/png", 1, [], [], None, [])


def test_D02_download_streams_the_bytes_after_the_client_check_and_never_across_clients(api, b, other):
    doc = upload(api, b.client_id).json()
    r = api.get(f"/clients/{b.client_id}/documents/{doc['id']}/download", headers=H)
    assert r.status_code == 200 and r.content == INVOICE
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == "inline" and r.headers["x-content-type-options"] == "nosniff"
    stolen = api.get(f"/clients/{other.client_id}/documents/{doc['id']}/download", headers=H)
    assert stolen.status_code == 404
    assert api.get(f"/clients/{other.client_id}/documents/{doc['id']}", headers=H).status_code == 404
    assert api.get(f"/clients/{b.client_id}/documents/{doc['id']}/download").status_code == 400  # no X-User


# ------------------------------------------------------------------------------------------------ reading text


def test_D01_read_text_of_a_text_pdf_needs_no_ocr_and_is_stored_once_per_page(api, b, svc_conn):
    doc = upload(api, b.client_id).json()
    url = f"/clients/{b.client_id}/documents/{doc['id']}"
    r = api.post(f"{url}/read-text", json={"method": "auto"}, headers=H)
    assert r.status_code == 200, r.text
    pages = r.json()["pages"]
    assert [(p["page_no"], p["method"], p["mean_confidence"]) for p in pages] == [(1, "pdf_text", None), (2, "pdf_text", None)]
    assert pages[0]["char_count"] == len("Tax Invoice B-101 Supplier Sharma Traders Total 1,180.00")
    again = api.post(f"{url}/read-text", headers=H)  # no body = auto; nothing is added the second time
    assert again.status_code == 200
    assert rows(svc_conn, "SELECT count(*) FROM document_texts WHERE document_id = :d", d=doc["id"])[0][0] == 2
    page = api.get(f"{url}/pages/1/text?method=pdf_text").json()
    assert page["method"] == "pdf_text" and "Total 1,180.00" in page["text"] and page["blocks"] is None
    assert api.get(f"{url}/pages/3/text").status_code == 404
    detail = api.get(url).json()
    assert detail["status"] == "text_ready"
    assert [(t["page_no"], t["method"]) for t in detail["texts"]] == [(1, "pdf_text"), (2, "pdf_text")]


def test_D01_scanned_pdf_without_any_ocr_engine_says_ocr_unavailable_and_stores_nothing(api, b, svc_conn, monkeypatch):
    monkeypatch.setattr(ocr, "available_ocr", list)
    doc = upload(api, b.client_id, data=SCAN).json()
    r = api.post(f"/clients/{b.client_id}/documents/{doc['id']}/read-text", json={"method": "auto"}, headers=H)
    assert r.status_code == 409 and r.json()["code"] == "ocr_unavailable" and "Install" in r.json()["message"]
    assert rows(svc_conn, "SELECT count(*) FROM document_texts WHERE document_id = :d", d=doc["id"])[0][0] == 0
    assert rows(svc_conn, "SELECT status FROM documents WHERE id = :d", d=doc["id"])[0][0] == "uploaded"
    direct = api.post(f"/clients/{b.client_id}/documents/{doc['id']}/read-text", json={"method": "pdf_text"}, headers=H)
    assert direct.status_code == 409 and direct.json()["code"] == "no_text_layer"


def test_D01_explicit_ocr_method_with_the_library_missing_is_ocr_unavailable(api, b, monkeypatch):
    monkeypatch.setattr(ocr, "_have", lambda module: False)
    doc = upload(api, b.client_id, data=PNG, name="p.png", doc_type="expense_bill").json()
    for method in ("tesseract", "paddleocr"):
        r = api.post(f"/clients/{b.client_id}/documents/{doc['id']}/read-text", json={"method": method}, headers=H)
        assert r.status_code == 409 and r.json()["code"] == "ocr_unavailable", r.text
    assert api.post(f"/clients/{b.client_id}/documents/{doc['id']}/read-text", json={"method": "magic"}, headers=H).status_code == 422


def test_D01_auto_uses_the_ocr_engine_only_for_pages_without_a_text_layer(api, b, svc_conn, monkeypatch):
    class FakeOcr:
        method = "tesseract"

        def read_pages(self, data, content_type):
            return [ocr.PageText(1, "should not be used", "tesseract", "fake-1"),
                    ocr.PageText(2, "Scanned page two Total 500.00", "tesseract", "fake-1", Decimal("0.9100"),
                                 [{"text": "Total", "bbox": [0.1, 0.1, 0.2, 0.2], "confidence": "0.9100"}])]

    monkeypatch.setattr(ocr, "available_ocr", lambda: ["tesseract"])
    monkeypatch.setattr(ocr, "ocr_for", lambda method: FakeOcr())
    mixed = make_pdf(["Page one has a text layer", ""])
    doc = upload(api, b.client_id, data=mixed).json()
    r = api.post(f"/clients/{b.client_id}/documents/{doc['id']}/read-text", json={"method": "auto"}, headers=H)
    assert r.status_code == 200, r.text
    assert [(p["page_no"], p["method"], p["mean_confidence"]) for p in r.json()["pages"]] == [(1, "pdf_text", None), (2, "tesseract", "0.9100")]
    stored = rows(svc_conn, "SELECT page_no, method, engine_version, mean_confidence, blocks->0->>'text' FROM document_texts "
                            "WHERE document_id = :d ORDER BY page_no", d=doc["id"])
    assert [(s[0], s[1], s[2], s[3], s[4]) for s in stored][1] == (2, "tesseract", "fake-1", Decimal("0.9100"), "Total")
    assert stored[0][1] == "pdf_text"


def test_D01_xml_documents_have_no_pages_to_read(api, b):
    doc = upload(api, b.client_id, data=b'<?xml version="1.0"?><ENVELOPE/>', doc_type="tally_xml", name="t.xml").json()
    r = api.post(f"/clients/{b.client_id}/documents/{doc['id']}/read-text", headers=H)
    assert r.status_code == 409 or r.status_code == 422
    assert r.json()["code"] == "invalid_method"


# ------------------------------------------------------------------------------------------------ voucher links


def _draft_payment(svc_conn, b):
    result = vouchers.create_draft(svc_conn, draft(b, "payment", date(2026, 5, 3), "Link test",
                                                   [("Rent", Decimal("100.00"), None), ("Cash", None, Decimal("100.00"))]), actor="clerk")
    assert result.errors == []
    return result.voucher_id


def test_D01_link_a_draft_voucher_then_unlink_it(api, b, svc_conn):
    doc = upload(api, b.client_id).json()
    voucher_id = _draft_payment(svc_conn, b)
    url = f"/clients/{b.client_id}/documents/{doc['id']}"
    r = api.post(f"{url}/links", json={"voucher_id": str(voucher_id), "link_kind": "supporting"}, headers=H)
    assert r.status_code == 201, r.text
    assert api.post(f"{url}/links", json={"voucher_id": str(voucher_id)}, headers=H).status_code == 409
    assert api.get(url).json()["linked_voucher_ids"] == [str(voucher_id)]
    assert [d["linked_voucher_ids"] for d in api.get(f"/clients/{b.client_id}/documents").json()] == [[str(voucher_id)]]
    assert api.delete(f"{url}/links/{voucher_id}", headers=H).json() == {"ok": True}
    assert api.get(url).json()["linked_voucher_ids"] == []
    actions = [r[0] for r in rows(svc_conn, "SELECT action FROM audit_log WHERE entity = 'document' AND entity_id = :i ORDER BY id", i=doc["id"])]
    assert actions == ["document_uploaded", "document_linked", "document_unlinked"]


def test_D01_link_of_a_posted_voucher_cannot_be_removed(api, b):
    doc = upload(api, b.client_id).json()
    posted = b.voucher_ids["v1"]
    url = f"/clients/{b.client_id}/documents/{doc['id']}"
    assert api.post(f"{url}/links", json={"voucher_id": str(posted)}, headers=H).status_code == 201
    r = api.delete(f"{url}/links/{posted}", headers=H)
    assert r.status_code == 409 and r.json()["code"] == "voucher_not_draft"


def test_D01_a_document_cannot_be_linked_to_another_clients_voucher(api, b, other, svc_conn):
    doc = upload(api, b.client_id).json()
    foreign = _draft_payment(svc_conn, other)
    r = api.post(f"/clients/{b.client_id}/documents/{doc['id']}/links", json={"voucher_id": str(foreign)}, headers=H)
    assert r.status_code == 404
