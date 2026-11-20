"""Step 7.0: the Phase 7 tables of migration 0018 (database guards hold).
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_documents_schema.py`.

Each test builds its rows inside a transaction that is rolled back. Expected values are typed literally.
"""

import json
import uuid

import pytest
from dbfactory import Factory, check_deferred, rejected

pytestmark = pytest.mark.integration


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


def _doc(f, client_id, n=1, **kw):
    doc_id = uuid.uuid4()
    cols = {"doc_type": "purchase_invoice", "content_type": "application/pdf", "sha256": f"{n:064x}",
            "storage_key": f"{str(client_id)[:8]}/{n:064x}.pdf", **kw}
    f.conn.execute(
        "INSERT INTO documents (id, client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by) "
        "VALUES (%s, %s, %s, 'bill 1.pdf', %s, 1000, %s, %s, 'tester')",
        (doc_id, client_id, cols["doc_type"], cols["content_type"], cols["sha256"], cols["storage_key"]))
    return doc_id


def _extraction(f, client_id, doc_id, version=1):
    ext_id = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO extractions (id, client_id, document_id, version, source, schema_version, payload, status, created_by) "
        "VALUES (%s, %s, %s, %s, 'manual', 'invoice-extract-1', %s, 'valid', 'tester')",
        (ext_id, client_id, doc_id, version, json.dumps({"invoice_no": {"value": "B-1"}})))
    return ext_id


def _queue(f, client_id, doc_id, ext_id, draft=None, blocking=0):
    q = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO approval_queue_items (id, client_id, kind, document_id, extraction_id, draft_voucher_id, blocking_count, created_by) "
        "VALUES (%s, %s, 'invoice', %s, %s, %s, %s, 'tester')", (q, client_id, doc_id, ext_id, draft, blocking))
    return q


def _reject(f, q, reason="wrong file"):
    f.conn.execute("UPDATE approval_queue_items SET status = 'rejected', rejected_by = 't', rejected_at = now(), reject_reason = %s, "
                   "draft_voucher_id = NULL WHERE id = %s", (reason, q))


def test_D02_D01_documents_are_unique_per_client_by_hash_and_the_storage_key_is_path_safe(f):
    client_id, _ = f.setup()
    other = f.client()
    _doc(f, client_id, 1)
    _doc(f, other, 1, storage_key="other/same-file.pdf")  # another client may hold the same file
    with rejected(f.conn, constraint="documents_client_hash_key"):
        _doc(f, client_id, 1, storage_key="x/another-key.pdf")
    keys = ["../etc/passwd", "/abs/path.pdf", "C:/files/a.pdf", "a//b.pdf", "a/../b.pdf", "UPPER/a.pdf", "dir/"]
    for n, key in enumerate(keys, start=10):
        with rejected(f.conn, constraint="documents_storage_key_safe"):
            _doc(f, client_id, n, storage_key=key)
    with rejected(f.conn, constraint="documents_filename_ok"):
        f.conn.execute(
            "INSERT INTO documents (client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by) "
            "VALUES (%s, 'other', %s, 'application/pdf', 5, %s, 'ok/key.pdf', 't')", (client_id, "..\\x.pdf", f"{99:064x}"))
    with rejected(f.conn, constraint="documents_content_type_check"):
        _doc(f, client_id, 50, content_type="text/html")


def test_documents_keep_their_identity_are_never_deleted_but_status_can_move(f):
    client_id, _ = f.setup()
    doc_id = _doc(f, client_id)
    f.conn.execute("UPDATE documents SET status = 'text_ready', page_count = 2 WHERE id = %s", (doc_id,))
    with rejected(f.conn, message="file identity"):
        f.conn.execute("UPDATE documents SET sha256 = %s WHERE id = %s", (f"{7:064x}", doc_id))
    with rejected(f.conn, message="file identity"):
        f.conn.execute("UPDATE documents SET storage_key = 'moved/else.pdf' WHERE id = %s", (doc_id,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    _extraction(f, client_id, doc_id)
    with rejected(f.conn, message="after an extraction exists"):
        f.conn.execute("UPDATE documents SET doc_type = 'sales_invoice' WHERE id = %s", (doc_id,))


def test_D50_D51_D52_llm_calls_need_masking_evidence_hold_no_secret_and_are_insert_only(f):
    client_id, _ = f.setup()
    ok = ("INSERT INTO llm_calls (client_id, purpose, provider, model, prompt_version, prompt_masked, masking_applied, response_raw, "
          "status, created_by) VALUES (%s, 'invoice_extraction', 'openrouter', 'm/x', 'v1', %s, %s, %s, 'ok', 't')")
    f.conn.execute(ok, (client_id, "Invoice B-1 <GSTIN_1>", True, "{}"))
    with rejected(f.conn, constraint="llm_calls_masked_before_sending"):
        f.conn.execute(ok, (client_id, "raw text", False, "{}"))
    with rejected(f.conn, constraint="llm_calls_no_secret"):
        f.conn.execute(ok, (client_id, "Authorization sk-or-v1-abc", True, "{}"))
    f.conn.execute("INSERT INTO llm_calls (client_id, purpose, provider, prompt_version, status, error_message, created_by) "
                   "VALUES (%s, 'invoice_extraction', 'openrouter', 'v1', 'blocked', 'AI is off for this client', 't')", (client_id,))
    with rejected(f.conn, constraint="llm_calls_blocked_sent_nothing"):
        f.conn.execute("INSERT INTO llm_calls (client_id, purpose, provider, prompt_version, prompt_masked, status, created_by) "
                       "VALUES (%s, 'invoice_extraction', 'openrouter', 'v1', 'text', 'blocked', 't')", (client_id,))
    with rejected(f.conn, message="insert only"):
        f.conn.execute("UPDATE llm_calls SET status = 'error' WHERE client_id = %s", (client_id,))
    with rejected(f.conn, message="insert only"):
        f.conn.execute("DELETE FROM llm_calls WHERE client_id = %s", (client_id,))


def test_D51_enabling_the_llm_for_a_client_is_explicit_and_explained(f):
    client_id, _ = f.setup()
    with rejected(f.conn, constraint="client_ai_settings_enable_is_explicit"):
        f.conn.execute("INSERT INTO client_ai_settings (client_id, llm_enabled, updated_by) VALUES (%s, true, 't')", (client_id,))
    f.conn.execute("INSERT INTO client_ai_settings (client_id, llm_enabled, updated_by) VALUES (%s, false, 't')", (client_id,))
    f.conn.execute("UPDATE client_ai_settings SET llm_enabled = true, enabled_by = 'ca', enabled_at = now(), data_class = 'synthetic', "
                   "note = 'Synthetic pack only' WHERE client_id = %s", (client_id,))


def test_D61_an_extraction_is_evidence_never_edited_and_not_superseded_while_its_queue_item_lives(f):
    client_id, _ = f.setup()
    doc_id = _doc(f, client_id)
    ext_id = _extraction(f, client_id, doc_id)
    with rejected(f.conn, message="immutable"):
        f.conn.execute("UPDATE extractions SET payload = '{}'::jsonb WHERE id = %s", (ext_id,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM extractions WHERE id = %s", (ext_id,))
    q = _queue(f, client_id, doc_id, ext_id)
    with rejected(f.conn, message="reject that item"):
        f.conn.execute("UPDATE extractions SET superseded_at = now() WHERE id = %s", (ext_id,))
    _reject(f, q)
    f.conn.execute("UPDATE extractions SET superseded_at = now() WHERE id = %s", (ext_id,))
    with rejected(f.conn, constraint="extractions_invalid_has_reason"):
        f.conn.execute("INSERT INTO extractions (client_id, document_id, version, source, schema_version, payload, status, created_by) "
                       "VALUES (%s, %s, 2, 'manual', 's', '{}'::jsonb, 'invalid', 't')", (client_id, doc_id))


def test_D60_D62_a_queued_draft_cannot_be_approved_until_accepted_and_accept_needs_nothing_blocking(f):
    client_id, fy_id = f.setup()
    doc_id = _doc(f, client_id)
    ext_id = _extraction(f, client_id, doc_id)
    voucher = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    q = _queue(f, client_id, doc_id, ext_id, draft=voucher, blocking=1)
    with rejected(f.conn, message="queue item has not been accepted"):
        f.approve(voucher)
    accept = ("UPDATE approval_queue_items SET status = 'accepted', accepted_by = 'ca', accepted_at = now(), blocking_count = %s "
              "WHERE id = %s")
    with rejected(f.conn, constraint="approval_queue_accepted_complete"):
        f.conn.execute(accept, (1, q))                      # an unresolved error / review finding blocks acceptance
    f.conn.execute("UPDATE approval_queue_items SET status = 'in_review', reviewer = 'ca' WHERE id = %s", (q,))
    f.conn.execute(accept, (0, q))
    f.approve(voucher)                                      # now the normal voucher path is open
    f.post(voucher)
    check_deferred(f.conn)
    with rejected(f.conn, message="queue item cannot be changed"):
        f.conn.execute("UPDATE approval_queue_items SET findings = '[]'::jsonb WHERE id = %s", (q,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM approval_queue_items WHERE id = %s", (q,))


def test_D60_queue_status_path_reject_needs_reason_and_no_live_draft_and_accept_needs_a_draft(f):
    client_id, fy_id = f.setup()
    doc_id = _doc(f, client_id)
    ext_id = _extraction(f, client_id, doc_id)
    q = _queue(f, client_id, doc_id, ext_id)                # no draft yet: needs mapping
    with rejected(f.conn, message="draft voucher is still a draft"):
        f.conn.execute("UPDATE approval_queue_items SET status = 'accepted', accepted_by = 'ca', accepted_at = now() WHERE id = %s", (q,))
    with rejected(f.conn, constraint="approval_queue_in_review_has_reviewer"):
        f.conn.execute("UPDATE approval_queue_items SET status = 'in_review' WHERE id = %s", (q,))
    with rejected(f.conn, constraint="approval_queue_rejected_complete"):
        f.conn.execute("UPDATE approval_queue_items SET status = 'rejected', rejected_by = 'ca', rejected_at = now() WHERE id = %s", (q,))
    with rejected(f.conn, message="identity"):
        f.conn.execute("UPDATE approval_queue_items SET document_id = %s WHERE id = %s", (_doc(f, client_id, 2), q))
    with rejected(f.conn, message="created pending"):
        f.conn.execute("INSERT INTO approval_queue_items (client_id, kind, document_id, extraction_id, status, created_by) "
                       "VALUES (%s, 'invoice', %s, %s, 'in_review', 't')", (client_id, doc_id, _extraction(f, client_id, doc_id, 2)))
    voucher = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    f.conn.execute("UPDATE approval_queue_items SET draft_voucher_id = %s WHERE id = %s", (voucher, q))
    with rejected(f.conn, constraint="approval_queue_rejected_complete"):  # a rejected item must not point at a live draft
        f.conn.execute("UPDATE approval_queue_items SET status = 'rejected', rejected_by = 'ca', rejected_at = now(), "
                       "reject_reason = 'dup' WHERE id = %s", (q,))
    _reject(f, q, "dup")
    with rejected(f.conn, message="rejected queue item cannot be changed"):
        f.conn.execute("UPDATE approval_queue_items SET status = 'pending' WHERE id = %s", (q,))
    # one live item per extraction: a rejected one does not count
    _queue(f, client_id, doc_id, ext_id)
    with rejected(f.conn, constraint="approval_queue_extraction_open_key"):
        _queue(f, client_id, doc_id, ext_id)


def test_D37_a_tally_voucher_is_queued_once_and_a_master_mapping_needs_a_person_and_a_target(f):
    client_id, _ = f.setup()
    doc_id = _doc(f, client_id, 1, doc_type="tally_xml", content_type="application/xml", storage_key="t/one.xml")
    imp = uuid.uuid4()
    f.conn.execute("INSERT INTO tally_imports (id, client_id, document_id, created_by) VALUES (%s, %s, %s, 't')", (imp, client_id, doc_id))
    with rejected(f.conn, constraint="tally_imports_document_key"):
        f.conn.execute("INSERT INTO tally_imports (client_id, document_id, created_by) VALUES (%s, %s, 't')", (client_id, doc_id))
    item = ("INSERT INTO approval_queue_items (client_id, kind, document_id, tally_import_id, source_ref, created_by) "
            "VALUES (%s, 'tally_voucher', %s, %s, %s, 't')")
    f.conn.execute(item, (client_id, doc_id, imp, "guid-1"))
    with rejected(f.conn, constraint="approval_queue_tally_ref_key"):
        f.conn.execute(item, (client_id, doc_id, imp, "guid-1"))
    with rejected(f.conn, constraint="approval_queue_kind_refs"):
        f.conn.execute(item, (client_id, doc_id, imp, "  "))
    ledger = f.ledger(client_id, "Sales A/c", "sales_accounts")
    m = ("INSERT INTO tally_master_map (client_id, kind, source_name, source_name_key, import_id, decision, reason, target_ledger_id, "
         "decided_by, decided_at) VALUES (%s, 'ledger', 'Sales A/c', %s, %s, %s, 'same name', %s, %s, %s)")
    with rejected(f.conn, constraint="tally_master_map_confirmed_has_target"):
        f.conn.execute(m, (client_id, "sales a/c", imp, "confirmed", None, "ca", "2026-11-20"))
    with rejected(f.conn, constraint="tally_master_map_decided_by_person"):
        f.conn.execute(m, (client_id, "sales a/c", imp, "confirmed", ledger, None, None))
    f.conn.execute(m, (client_id, "sales a/c", imp, "confirmed", ledger, "ca", "2026-11-20"))
    with rejected(f.conn, constraint="tally_master_map_key"):
        f.conn.execute(m, (client_id, "sales a/c", imp, "confirmed", ledger, "ca", "2026-11-20"))


def test_D26_mappings_are_keyed_and_validated_and_party_scope_makes_a_distinct_row(f):
    client_id, _ = f.setup()
    supplier = f.ledger(client_id, "Supplier X", "sundry_creditors")
    freight = f.ledger(client_id, "Freight", "direct_expenses")
    p = "INSERT INTO party_mappings (client_id, match_kind, match_key, party_ledger_id, created_by) VALUES (%s, %s, %s, %s, 't')"
    f.conn.execute(p, (client_id, "gstin", "27AAPFU0939F1ZV", supplier))
    with rejected(f.conn, constraint="party_mappings_key"):
        f.conn.execute(p, (client_id, "gstin", "27AAPFU0939F1ZV", supplier))
    with rejected(f.conn, constraint="party_mappings_key_format"):
        f.conn.execute(p, (client_id, "gstin", "not-a-gstin", supplier))
    with rejected(f.conn, constraint="party_mappings_key_format"):
        f.conn.execute(p, (client_id, "name", "Supplier X ", supplier))   # names are stored normalised
    line = ("INSERT INTO line_mappings (client_id, match_kind, match_key, party_ledger_id, ledger_id, created_by) "
            "VALUES (%s, 'description', %s, %s, %s, 't')")
    f.conn.execute(line, (client_id, "transport charges", None, freight))
    f.conn.execute(line, (client_id, "transport charges", supplier, freight))   # party-scoped row is distinct
    with rejected(f.conn, constraint="line_mappings_key"):
        f.conn.execute(line, (client_id, "transport charges", None, freight))
    other_client, _ = f.setup()
    with rejected(f.conn, constraint="party_mappings_ledger_fk"):          # a client's mapping can only use that client's ledgers
        f.conn.execute(p, (other_client, "gstin", "29AAPFU0939F1ZV", supplier))


def test_D44_narration_rules_are_keyed_and_normalised_and_a_suggestion_needs_a_real_bank_line(f):
    client_id, _ = f.setup()
    rent = f.ledger(client_id, "Rent", "indirect_expenses")
    r = "INSERT INTO narration_rules (client_id, direction, narration_key, ledger_id, created_by) VALUES (%s, %s, %s, %s, 't')"
    f.conn.execute(r, (client_id, "debit", "neft office rent", rent))
    with rejected(f.conn, constraint="narration_rules_key"):
        f.conn.execute(r, (client_id, "debit", "neft office rent", rent))
    with rejected(f.conn, constraint="narration_rules_key_format"):
        f.conn.execute(r, (client_id, "debit", "NEFT Rent", rent))
    with rejected(f.conn, constraint="narration_suggestions_line_fk"):
        f.conn.execute("INSERT INTO narration_suggestions (client_id, bank_statement_line_id, source, suggested_ledger_id, reason, created_by) "
                       "VALUES (%s, %s, 'rule', %s, 'learned 3 times', 't')", (client_id, uuid.uuid4(), rent))


def test_document_links_are_removable_only_while_the_voucher_is_a_draft(f):
    client_id, fy_id = f.setup()
    doc_id = _doc(f, client_id)
    voucher = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    f.conn.execute("INSERT INTO document_vouchers (client_id, document_id, voucher_id, linked_by) VALUES (%s, %s, %s, 't')",
                   (client_id, doc_id, voucher))
    with rejected(f.conn, message="cannot be changed"):
        f.conn.execute("UPDATE document_vouchers SET link_kind = 'source' WHERE voucher_id = %s", (voucher,))
    f.approve(voucher)
    with rejected(f.conn, message="cannot be removed"):
        f.conn.execute("DELETE FROM document_vouchers WHERE voucher_id = %s", (voucher,))


def test_hooks_add_queue_item_audit_it_and_guard_the_voucher(svc_conn):
    from sqlalchemy import text

    from app.engine.doc_types import DocFinding, QueueKind, Severity
    from app.services import ai_hooks
    from app.services.errors import ServiceError

    f = Factory(svc_conn.connection.driver_connection)
    client_id, fy_id = f.setup()
    doc_id = _doc(f, client_id)
    ext_id = _extraction(f, client_id, doc_id)
    voucher = f.draft(client_id, fy_id, f.balanced_lines(client_id))
    assert ai_hooks.llm_enabled(svc_conn, client_id) is False
    with pytest.raises(ServiceError) as info:
        ai_hooks.require_llm_enabled(svc_conn, client_id)
    assert info.value.code == "llm_disabled"
    findings = [DocFinding("D-10", Severity.ERROR, "taxable differs"), DocFinding("D-05", Severity.WARNING, "low confidence")]
    qid = ai_hooks.add_queue_item(svc_conn, client_id=client_id, kind=QueueKind.INVOICE, document_id=doc_id, extraction_id=ext_id,
                                  findings=findings, created_by="tester", draft_voucher_id=voucher)
    row = svc_conn.execute(text("SELECT status, blocking_count, warning_count FROM approval_queue_items WHERE id = :i"), {"i": qid}).one()
    assert tuple(row) == ("pending", 1, 1)
    logged = svc_conn.execute(text("SELECT action, entity FROM audit_log WHERE entity_id = :i"), {"i": qid}).one()
    assert tuple(logged) == ("queue_item_created", "approval_queue_item")
    with pytest.raises(ServiceError) as info:
        ai_hooks.guard_voucher_change(svc_conn, client_id, voucher)
    assert info.value.code == "queue_not_accepted"
