"""Step 3.0: the GST tables of migrations 0009-0011 and seeds 0004-0007 (rule data present, database guards hold).

Each test builds its rows inside a transaction that is rolled back. Expected values are typed literally.
"""

import uuid

import pytest
from dbfactory import Factory, check_deferred, rejected

pytestmark = pytest.mark.integration

RULE_TABLES = [
    "gst_state_codes", "gst_uqc", "gst_rate_slabs", "gst_rate_rules", "gst_rcm_rules",
    "gst_blocked_credit_rules", "gst_itc_conditions", "gst_thresholds", "gst_composition_rules",
]
GSTIN = "27AAPFU0939F1ZV"


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


def test_G_seeds_fill_every_rule_table_and_every_row_has_a_status_and_source(f):
    for table in RULE_TABLES:
        total, bad = f.conn.execute(
            f"SELECT count(*), count(*) FILTER (WHERE verification_status NOT IN ('verified','secondary_verified','pending') "
            f"OR btrim(source_reference) = '') FROM {table}"
        ).fetchone()
        assert total > 0, table
        assert bad == 0, table


def test_G03_state_codes_27_96_99_are_seeded(f):
    codes = {r[0] for r in f.conn.execute("SELECT code FROM gst_state_codes WHERE code IN ('27','96','99')").fetchall()}
    assert codes == {"27", "96", "99"}


def _registration(f, client_id):
    rid = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
        "VALUES (%s, %s, %s, '27', 'regular', '2026-04-01')",
        (rid, client_id, GSTIN),
    )
    return rid


def test_G04_registration_state_must_match_gstin_and_composition_needs_category(f):
    client_id, _ = f.setup()
    with rejected(f.conn, constraint="gst_registrations_state_matches_gstin"):
        f.conn.execute(
            "INSERT INTO gst_registrations (client_id, gstin, state_code, registration_type, effective_from) "
            "VALUES (%s, %s, '29', 'regular', '2026-04-01')", (client_id, GSTIN))
    with rejected(f.conn, constraint="gst_registrations_comp_needs_category"):
        f.conn.execute(
            "INSERT INTO gst_registrations (client_id, gstin, state_code, registration_type, effective_from) "
            "VALUES (%s, %s, '27', 'composition', '2026-04-01')", (client_id, GSTIN))


def _invoice(f):
    """client, registration, a draft Sales voucher with a voucher_gst header; returns ids."""
    client_id, fy_id = f.setup()
    reg = _registration(f, client_id)
    lines = f.balanced_lines(client_id)
    vid = f.draft(client_id, fy_id, lines, vtype="sales")
    f.conn.execute(
        "INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, place_of_supply, "
        "invoice_date, invoice_value, engine_version) VALUES (%s, %s, %s, 'tax_invoice', 'b2b', '27', '2026-04-05', 118.00, 't')",
        (vid, client_id, reg),
    )
    return client_id, fy_id, vid, lines


ITEM_SQL = (
    "INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, description, hsn_sac, uqc, quantity, unit_rate, "
    "gross_amount, taxable_value, ledger_id, treatment, gst_rate, cgst, sgst, igst) "
    "VALUES (%s, %s, 1, 'Item', '3004', 'NOS', 1, 100.00, 100.00, 100.00, %s, 'taxable', 18, %s, %s, %s)"
)


def test_G15_database_accepts_exact_tax_and_rejects_a_forged_amount(f):
    client_id, _, vid, lines = _invoice(f)
    f.conn.execute(ITEM_SQL, (client_id, vid, lines[0][0], "9.00", "9.00", "0.00"))
    f.conn.execute("DELETE FROM voucher_item_lines WHERE voucher_id = %s", (vid,))
    with rejected(f.conn, constraint="voucher_item_lines_tax_formula"):
        f.conn.execute(ITEM_SQL, (client_id, vid, lines[0][0], "9.01", "9.01", "0.00"))
    with rejected(f.conn, constraint="voucher_item_lines_tax_formula"):  # both heads at once
        f.conn.execute(ITEM_SQL, (client_id, vid, lines[0][0], "9.00", "9.00", "18.00"))


def test_G26_item_lines_are_immutable_after_posting(f):
    client_id, _, vid, lines = _invoice(f)
    f.conn.execute(ITEM_SQL, (client_id, vid, lines[0][0], "9.00", "9.00", "0.00"))
    f.approve(vid)
    f.post(vid, "SAL/2026-27/0001")
    check_deferred(f.conn)
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("UPDATE voucher_item_lines SET description = 'x' WHERE voucher_id = %s", (vid,))
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("UPDATE voucher_gst SET invoice_value = 1 WHERE voucher_id = %s", (vid,))
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("DELETE FROM voucher_item_lines WHERE voucher_id = %s", (vid,))


def test_G37_itc_entry_amounts_immutable_events_append_only(f):
    client_id, _, vid, lines = _invoice(f)
    reg = f.conn.execute("SELECT gst_registration_id FROM voucher_gst WHERE voucher_id = %s", (vid,)).fetchone()[0]
    f.conn.execute(ITEM_SQL, (client_id, vid, lines[0][0], "9.00", "9.00", "0.00"))
    entry = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO itc_entries (id, client_id, gst_registration_id, voucher_id, item_line_no, doc_type, source, "
        "supplier_invoice_date, cgst, sgst, status, pending_reason) "
        "VALUES (%s, %s, %s, %s, 1, 'invoice', 'regular', '2026-04-05', 9.00, 9.00, 'pending', 'not_in_2b')",
        (entry, client_id, reg, vid),
    )
    f.conn.execute("UPDATE itc_entries SET status = 'eligible', pending_reason = NULL WHERE id = %s", (entry,))
    with rejected(f.conn, message="only status, evidence and claim columns"):
        f.conn.execute("UPDATE itc_entries SET cgst = 10.00 WHERE id = %s", (entry,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM itc_entries WHERE id = %s", (entry,))
    f.conn.execute(
        "INSERT INTO itc_status_events (client_id, itc_entry_id, from_status, to_status, reason, actor) "
        "VALUES (%s, %s, 'pending', 'eligible', 'confirmed', 'tester')", (client_id, entry))
    with rejected(f.conn, message="append-only"):
        f.conn.execute("UPDATE itc_status_events SET reason = 'x' WHERE itc_entry_id = %s", (entry,))
    with rejected(f.conn, message="append-only"):
        f.conn.execute("DELETE FROM itc_status_events WHERE itc_entry_id = %s", (entry,))


def test_G40_imported_2b_documents_cannot_be_edited_and_a_final_working_is_frozen(f):
    client_id, _ = f.setup()
    reg = _registration(f, client_id)
    imp, doc, wk = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    f.conn.execute(
        "INSERT INTO gstr2b_imports (id, client_id, gst_registration_id, kind, return_period, source_format, file_name, "
        "file_hash, document_count, created_by) VALUES (%s, %s, %s, 'gstr2b', '2026-04-01', 'json', 'a.json', %s, 1, 't')",
        (imp, client_id, reg, "a" * 64))
    f.conn.execute(
        "INSERT INTO gstr2b_documents (id, client_id, import_id, row_no, section, doc_type, doc_no, doc_date) "
        "VALUES (%s, %s, %s, 1, 'b2b', 'invoice', 'INV-1', '2026-04-02')", (doc, client_id, imp))
    with rejected(f.conn, message="cannot be edited"):
        f.conn.execute("UPDATE gstr2b_documents SET taxable_value = 5 WHERE id = %s", (doc,))
    f.conn.execute(
        "INSERT INTO gst_return_workings (id, client_id, gst_registration_id, return_type, period_kind, period_start, "
        "period_end, version, status, data, data_hash, created_by) VALUES (%s, %s, %s, 'gstr1', 'month', '2026-04-01', "
        "'2026-04-30', 1, 'draft', '{}'::jsonb, 'h', 't')", (wk, client_id, reg))
    f.conn.execute("UPDATE gst_return_workings SET status = 'final' WHERE id = %s", (wk,))
    with rejected(f.conn, message="final return working cannot be changed"):
        f.conn.execute("UPDATE gst_return_workings SET data_hash = 'z' WHERE id = %s", (wk,))
