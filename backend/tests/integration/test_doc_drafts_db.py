"""Phase 7 package E on the test schema: saved mappings (CRUD, audit, API), the draft builder through the real voucher service,
rebuild in place (D-27), and the database gate that refuses approve / post of a queued draft until its queue item is accepted (D-62).

Package D's extraction checks are injected (no checks = no prior findings); extractions are literal manual rows. No network, no LLM.
Rates come from the seeded EXAMPLE rule rows: 8415 is 18% from 22-09-2025. Expected figures are hand-calculated literals.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_conn
from app.db import connection, migrate
from app.engine.doc_types import DocType
from app.main import app
from app.services import client_setup, doc_drafts, doc_mappings, parties, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

GSTIN_SELF = "27ABCDE1234F1Z0"
GSTIN_SUPPLIER = "29ABCDE1234F1ZW"
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


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("Draft Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Ramesh Kumar")
        ids = dict(created.ledger_ids)
        for name, group in (("Sharma Suppliers", "sundry_creditors"), ("Other Suppliers", "sundry_creditors"),
                            ("Packing Expense", "indirect_expenses")):
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, group, actor="setup")
        for name in ROLE_LEDGERS.values():
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, "duties_taxes", actor="setup")
        reg_id = uuid.uuid4()
        conn.execute(text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                          "VALUES (:r, :c, :g, '27', 'regular', '2026-04-01')"), {"r": reg_id, "c": created.client_id, "g": GSTIN_SELF})
        for role, name in ROLE_LEDGERS.items():
            conn.execute(text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                         {"r": reg_id, "c": created.client_id, "role": role, "l": ids[name]})
        parties.set_party(conn, created.client_id, ids["Sharma Suppliers"], gstin=GSTIN_SUPPLIER, state_code="29", bill_wise=False,
                          actor="setup")
        other = client_setup.create_client(
            conn, ClientProfile("Other Client", "proprietorship", "trading", "regular"), fy_start=date(2026, 4, 1), actor="setup",
            proprietor_name="Somebody")
        ids["other_ledger"] = client_setup.add_ledger(conn, other.client_id, "Their Supplier", "sundry_creditors", actor="setup")
        w = World(created.client_id, ids)
    yield w
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


# ---- literal extraction (what package D stores) ------------------------------------------------------------------
def fld(v):
    return {"value": v, "page": 1, "bbox": None, "confidence": "0.99"}


def payload(*, qty="2", hsn="8415", supplier_gstin=GSTIN_SUPPLIER, supplier="Sharma Suppliers Pvt. Ltd.", desc="Air conditioner"):
    return {
        "document_kind": fld("purchase_invoice"), "supplier_name": fld(supplier), "supplier_gstin": fld(supplier_gstin),
        "buyer_name": fld("Draft Traders"), "buyer_gstin": fld(GSTIN_SELF), "invoice_no": fld("SS/101"),
        "invoice_date": fld("05-04-2026"), "place_of_supply": fld("27-Maharashtra"), "original_invoice_no": fld(None),
        "lines": [{"description": fld(desc), "hsn_sac": fld(hsn), "quantity": fld(qty), "unit": fld("NOS"),
                   "unit_rate": fld("10000.00"), "discount": fld("0.00"), "taxable_value": fld(None), "gst_rate": fld(None),
                   "cgst": fld(None), "sgst": fld(None), "igst": fld(None), "cess": fld(None)}],
        "totals": {}, "currency": "INR", "notes": [],
    }


def make_doc(conn, w, n=1):
    """A document row and a manual valid extraction row (returns document_id, extraction_id)."""
    doc, ext = uuid.uuid4(), uuid.uuid4()
    sha = f"{n:064x}"
    conn.execute(text("INSERT INTO documents (id, client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, "
                      "uploaded_by) VALUES (:i, :c, 'purchase_invoice', 'bill.pdf', 'application/pdf', 10, :s, :k, 'tester')"),
                 {"i": doc, "c": w.client_id, "s": sha, "k": f"test/{doc}.pdf"})
    conn.execute(text("INSERT INTO extractions (id, client_id, document_id, version, source, schema_version, payload, status, created_by) "
                      "VALUES (:i, :c, :d, 1, 'manual', 'invoice-extract-1', CAST(:p AS jsonb), 'valid', 'tester')"),
                 {"i": ext, "c": w.client_id, "d": doc, "p": json.dumps(payload())})
    return doc, ext


def save_mappings(conn, w):
    doc_mappings.put_party_mapping(conn, w.client_id, match_kind="gstin", match_key=GSTIN_SUPPLIER,
                                   party_ledger_id=w.ids["Sharma Suppliers"], actor="acc")
    doc_mappings.put_line_mapping(conn, w.client_id, match_kind="hsn_sac", match_key="8415", ledger_id=w.ids["Purchases"], actor="acc")


def build(conn, w, doc, ext, p=None, prior=()):
    from app.engine.doc_build import invoice_from_payload

    return doc_drafts.build_draft(
        conn, client_id=w.client_id, document_id=doc, extraction_id=ext, extracted=invoice_from_payload(p or payload()),
        doc_type=DocType.PURCHASE_INVOICE, prior_findings=prior, actor="builder")


def lines_of(conn, voucher_id):
    return [(r[0], r[1], r[2]) for r in conn.execute(
        text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
             "WHERE vl.voucher_id = :v ORDER BY vl.line_no"), {"v": voucher_id})]


def count(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


# ---- mappings: CRUD, audit, normalisation --------------------------------------------------------------------------
def test_D26_mapping_crud_audit_conflict_and_other_client(svc_conn, world):
    w = world
    mid = doc_mappings.put_party_mapping(svc_conn, w.client_id, match_kind="name", match_key="  Sharma  Suppliers Pvt. Ltd. ",
                                         party_ledger_id=w.ids["Sharma Suppliers"], actor="acc")
    (row,) = doc_mappings.list_party_mappings(svc_conn, w.client_id, "sharma")
    assert (row["match_key"], row["party_ledger_name"], row["use_count"]) == ("sharma suppliers pvt ltd", "Sharma Suppliers", 0)
    # same key, same ledger: unchanged and no second row
    assert doc_mappings.put_party_mapping(svc_conn, w.client_id, match_kind="name", match_key="sharma suppliers pvt ltd",
                                          party_ledger_id=w.ids["Sharma Suppliers"], actor="acc") == mid
    # same key pointing elsewhere: refused unless replace
    with pytest.raises(ServiceError) as e:
        doc_mappings.put_party_mapping(svc_conn, w.client_id, match_kind="name", match_key="Sharma Suppliers Pvt Ltd",
                                       party_ledger_id=w.ids["Other Suppliers"], actor="acc")
    assert e.value.code == "mapping_exists"
    doc_mappings.put_party_mapping(svc_conn, w.client_id, match_kind="name", match_key="Sharma Suppliers Pvt Ltd",
                                   party_ledger_id=w.ids["Other Suppliers"], replace=True, actor="acc")
    assert doc_mappings.list_party_mappings(svc_conn, w.client_id)[0]["party_ledger_name"] == "Other Suppliers"
    # another client's ledger is not found; a bad GSTIN is invalid
    with pytest.raises(ServiceError) as e:
        doc_mappings.put_party_mapping(svc_conn, w.client_id, match_kind="name", match_key="x", party_ledger_id=w.ids["other_ledger"],
                                       actor="acc")
    assert e.value.code == "not_found"
    with pytest.raises(ServiceError) as e:
        doc_mappings.put_party_mapping(svc_conn, w.client_id, match_kind="gstin", match_key="bad", party_ledger_id=mid, actor="acc")
    assert e.value.code == "invalid_mapping"
    # line mapping with party scope
    lid = doc_mappings.put_line_mapping(svc_conn, w.client_id, match_kind="description", match_key="Air  Conditioner",
                                        ledger_id=w.ids["Purchases"], party_ledger_id=w.ids["Sharma Suppliers"], actor="acc")
    assert doc_mappings.list_line_mappings(svc_conn, w.client_id, "air")[0]["party_ledger_name"] == "Sharma Suppliers"
    doc_mappings.delete_line_mapping(svc_conn, w.client_id, lid, actor="acc")
    doc_mappings.delete_party_mapping(svc_conn, w.client_id, mid, actor="acc")
    with pytest.raises(ServiceError) as e:
        doc_mappings.delete_party_mapping(svc_conn, w.client_id, mid, actor="acc")
    assert e.value.code == "mapping_missing"
    actions = [r[0] for r in svc_conn.execute(text(
        "SELECT action || ':' || entity FROM audit_log WHERE client_id = :c AND entity IN ('party_mapping', 'line_mapping') "
        "ORDER BY created_at, id"), {"c": w.client_id})]
    assert sorted(actions) == sorted(["create:party_mapping", "update:party_mapping", "create:line_mapping", "delete:line_mapping",
                                      "delete:party_mapping"])


def test_D26_learn_never_overwrites_a_different_mapping(svc_conn, world):
    w = world
    assert doc_mappings.learn_party_mapping(svc_conn, w.client_id, match_kind="gstin", match_key=GSTIN_SUPPLIER,
                                            party_ledger_id=w.ids["Sharma Suppliers"], actor="acc") == "created"
    assert doc_mappings.learn_party_mapping(svc_conn, w.client_id, match_kind="gstin", match_key=GSTIN_SUPPLIER,
                                            party_ledger_id=w.ids["Sharma Suppliers"], actor="acc") == "unchanged"
    assert doc_mappings.learn_party_mapping(svc_conn, w.client_id, match_kind="gstin", match_key=GSTIN_SUPPLIER,
                                            party_ledger_id=w.ids["Other Suppliers"], actor="acc") == "conflict"
    assert doc_mappings.list_party_mappings(svc_conn, w.client_id)[0]["use_count"] == 1


def test_D26_mapping_api_put_get_conflict_delete(svc_conn, world):
    w = world
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        base = f"/clients/{w.client_id}/mappings/parties"
        body = {"match_kind": "gstin", "match_key": GSTIN_SUPPLIER, "party_ledger_id": str(w.ids["Sharma Suppliers"])}
        r = api.put(base, json=body, headers=H)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        assert api.get(base, headers=H).json()[0]["match_key"] == GSTIN_SUPPLIER
        r = api.put(base, json={**body, "party_ledger_id": str(w.ids["Other Suppliers"])}, headers=H)
        assert (r.status_code, r.json()["code"]) == (409, "mapping_exists")
        assert api.put(base, json=body).status_code == 400  # no X-User
        assert api.delete(f"{base}/{mid}", headers=H).json() == {"ok": True}
        assert api.delete(f"{base}/{mid}", headers=H).status_code == 422  # mapping_missing
        lb = f"/clients/{w.client_id}/mappings/lines"
        r = api.put(lb, json={"match_kind": "hsn_sac", "match_key": "8415", "ledger_id": str(w.ids["Purchases"])}, headers=H)
        assert r.status_code == 200 and api.get(lb, headers=H).json()[0]["ledger_name"] == "Purchases"
    finally:
        app.dependency_overrides.clear()


# ---- the builder through the real voucher service ------------------------------------------------------------------
def test_D25_mapped_purchase_becomes_a_draft_with_engine_tax_and_document_link(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext = make_doc(svc_conn, w)
    out = build(svc_conn, w, doc, ext)
    assert out.findings == () and out.status == "pending" and out.draft_voucher_id is not None
    # supplier state 29 vs place of supply 27: inter-state, IGST 18% of 2 x 10,000.00 = 3,600.00 (computed by the engine, not printed)
    assert sorted(lines_of(svc_conn, out.draft_voucher_id)) == [
        ("Input IGST", D("3600.0000"), D("0.0000")),
        ("Purchases", D("20000.0000"), D("0.0000")),
        ("Sharma Suppliers", D("0.0000"), D("23600.0000")),
    ]
    status, ref, party = svc_conn.execute(text("SELECT status, reference_no, party_ledger_id FROM vouchers WHERE id = :v"),
                                          {"v": out.draft_voucher_id}).one()
    assert (status, ref, party) == ("draft", "SS/101", w.ids["Sharma Suppliers"])
    assert svc_conn.execute(text("SELECT link_kind FROM document_vouchers WHERE document_id = :d AND voucher_id = :v"),
                            {"d": doc, "v": out.draft_voucher_id}).scalar_one() == "source"
    q = svc_conn.execute(text("SELECT status, blocking_count, warning_count, draft_voucher_id FROM approval_queue_items WHERE id = :i"),
                         {"i": out.queue_item_id}).one()
    assert tuple(q) == ("pending", 0, 0, out.draft_voucher_id)
    assert count(svc_conn, "SELECT status FROM documents WHERE id = :d", d=doc) == "queued"
    assert count(svc_conn, "SELECT use_count FROM party_mappings WHERE client_id = :c", c=w.client_id) == 1


def test_D20_D21_unknown_party_or_line_goes_to_review_nothing_created(svc_conn, world):
    w = world
    doc, ext = make_doc(svc_conn, w)
    ledgers_before = count(svc_conn, "SELECT count(*) FROM ledgers WHERE client_id = :c", c=w.client_id)
    out = build(svc_conn, w, doc, ext)  # no mappings saved at all
    assert out.draft_voucher_id is None
    assert sorted((f.rule_id, f.severity.value) for f in out.findings) == [("D-20", "review"), ("D-21", "review")]
    assert count(svc_conn, "SELECT count(*) FROM ledgers WHERE client_id = :c", c=w.client_id) == ledgers_before
    assert count(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=w.client_id) == 0
    assert count(svc_conn, "SELECT count(*) FROM party_mappings WHERE client_id = :c", c=w.client_id) == 0
    assert tuple(svc_conn.execute(text("SELECT blocking_count, draft_voucher_id FROM approval_queue_items WHERE id = :i"),
                                  {"i": out.queue_item_id}).one()) == (2, None)


def test_D25_voucher_service_rule_comes_back_as_error_finding(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext = make_doc(svc_conn, w)
    # a taxable item whose HSN has no rate rule: the GST rules of the voucher service refuse it; we surface them unchanged
    doc_mappings.put_line_mapping(svc_conn, w.client_id, match_kind="hsn_sac", match_key="0000", ledger_id=w.ids["Purchases"], actor="acc")
    out = build(svc_conn, w, doc, ext, payload(hsn="0000"))
    assert out.draft_voucher_id is None
    assert out.findings and all(f.rule_id == "D-25" and f.severity.value == "error" for f in out.findings)
    assert count(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=w.client_id) == 0


def test_D27_rebuild_updates_the_same_draft_and_removes_it_when_blocked(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext = make_doc(svc_conn, w)
    first = build(svc_conn, w, doc, ext)
    again = build(svc_conn, w, doc, ext, payload(qty="3"))
    assert (again.rebuilt, again.queue_item_id, again.draft_voucher_id) == (True, first.queue_item_id, first.draft_voucher_id)
    # 3 x 10,000.00 = 30,000.00; IGST 18% = 5,400.00; payable 35,400.00
    assert sorted(lines_of(svc_conn, first.draft_voucher_id))[2] == ("Sharma Suppliers", D("0.0000"), D("35400.0000"))
    assert count(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=w.client_id) == 1
    assert count(svc_conn, "SELECT count(*) FROM approval_queue_items WHERE extraction_id = :e", e=ext) == 1
    # now the supplier turns out to be unmapped: the draft is deleted, the queue item stays with the findings
    gone = build(svc_conn, w, doc, ext, payload(supplier_gstin="27ABCDE1234F1Z0", supplier="Nobody Ltd"))
    assert gone.draft_voucher_id is None and gone.queue_item_id == first.queue_item_id
    assert count(svc_conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=w.client_id) == 0
    assert count(svc_conn, "SELECT count(*) FROM document_vouchers WHERE document_id = :d", d=doc) == 0
    assert tuple(svc_conn.execute(text("SELECT status, draft_voucher_id FROM approval_queue_items WHERE id = :i"),
                                  {"i": gone.queue_item_id}).one()) == ("pending", None)
    actions = [r[0] for r in svc_conn.execute(text("SELECT action FROM audit_log WHERE entity = 'approval_queue_item' "
                                                   "AND entity_id = :i ORDER BY created_at, id"), {"i": gone.queue_item_id})]
    assert actions == ["queue_item_created", "queue_item_rebuilt", "queue_item_rebuilt"]


def test_D62_database_refuses_approve_and_post_until_the_queue_item_is_accepted(svc_conn, world):
    w = world
    save_mappings(svc_conn, w)
    doc, ext = make_doc(svc_conn, w)
    out = build(svc_conn, w, doc, ext)
    vid = out.draft_voucher_id
    # the voucher service refuses first with a friendly message (package F hook, D-62) ...
    with pytest.raises(ServiceError) as hook:
        vouchers.approve(svc_conn, vid, actor="approver")
    assert hook.value.code == "queue_not_accepted"
    # ... and the DB trigger vouchers_ai_queue_guard remains the backstop for a caller that bypasses the service
    with pytest.raises(DBAPIError) as e, svc_conn.begin_nested():
        svc_conn.execute(text("UPDATE vouchers SET status = 'approved', approved_by = 'x', approved_at = now() WHERE id = :v"), {"v": vid})
    assert "queue item has not been accepted" in str(e.value)
    assert count(svc_conn, "SELECT status FROM vouchers WHERE id = :v", v=vid) == "draft"
    # an item with a blocking count cannot be accepted by the database either
    with pytest.raises(DBAPIError), svc_conn.begin_nested():
        svc_conn.execute(text("UPDATE approval_queue_items SET status = 'accepted', accepted_by = 'p', accepted_at = now(), "
                              "blocking_count = 1 WHERE id = :i"), {"i": out.queue_item_id})
    # a person accepts (package F will do this through the queue service): now approve and post go through
    svc_conn.execute(text("UPDATE approval_queue_items SET status = 'accepted', accepted_by = 'partner', accepted_at = now() "
                          "WHERE id = :i"), {"i": out.queue_item_id})
    vouchers.approve(svc_conn, vid, actor="approver")
    assert vouchers.post(svc_conn, vid, actor="poster") == "PUR/2026-27/0001"
    assert count(svc_conn, "SELECT status FROM vouchers WHERE id = :v", v=vid) == "posted"
