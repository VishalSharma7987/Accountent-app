"""Step 4.0: the TDS tables of migrations 0012-0014 and seeds 0008-0009 (rule data present, database guards hold).

Each test builds its rows inside a transaction that is rolled back. Expected values are typed literally.
"""

import pytest
from dbfactory import Factory, check_deferred, rejected

pytestmark = pytest.mark.integration

RULE_TABLES = ["tds_natures", "tds_section_refs", "tds_rates", "tds_provisions", "tds_due_dates", "tds_interest_rules", "tds_forms"]


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


def test_T_seeds_fill_every_rule_table_and_every_row_has_a_status_and_source(f):
    for table in RULE_TABLES:
        total, bad = f.conn.execute(
            f"SELECT count(*), count(*) FILTER (WHERE verification_status NOT IN ('verified','secondary_verified','pending') "
            f"OR btrim(source_reference) = '') FROM {table}"
        ).fetchone()
        assert total > 0, table
        assert bad == 0, table


def test_T02_both_acts_have_a_rate_row_for_the_contractor_on_each_side_of_1_april_2026(f):
    rows = f.conn.execute(
        "SELECT act, deductee_group, rate, effective_from, effective_to FROM tds_rates WHERE nature_key = 'contractor' "
        "ORDER BY effective_from, deductee_group"
    ).fetchall()
    assert [(r[0], r[1], str(r[2])) for r in rows] == [
        ("it_act_1961", "individual_huf", "1.0000"), ("it_act_1961", "others", "2.0000"),
        ("it_act_2025", "individual_huf", "1.0000"), ("it_act_2025", "others", "2.0000"),
    ]
    assert str(rows[0][4]) == "2026-03-31" and str(rows[2][3]) == "2026-04-01" and rows[3][4] is None


def _deductee(f, client_id, name="Raj Contractors"):
    ledger = f.ledger(client_id, name, "sundry_creditors")
    return ledger


def test_T10_deductee_pan_must_match_its_status(f):
    client_id, _ = f.setup()
    ledger = _deductee(f, client_id)
    with rejected(f.conn, constraint="tds_deductees_pan_needed"):
        f.conn.execute(
            "INSERT INTO tds_deductees (ledger_id, client_id, pan_status, deductee_type) VALUES (%s, %s, 'valid', 'individual')",
            (ledger, client_id))
    with rejected(f.conn, constraint="tds_deductees_pan_format"):
        f.conn.execute(
            "INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (%s, %s, 'abc', 'valid', 'individual')",
            (ledger, client_id))
    f.conn.execute(
        "INSERT INTO tds_deductees (ledger_id, client_id, pan_status, deductee_type) VALUES (%s, %s, 'missing', 'company')",
        (ledger, client_id))


ITEM_SQL = (
    "INSERT INTO tds_voucher_items (client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
    "financial_year_id, event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, rate_applied, "
    "rate_reason, tds_amount, tds_line_no, engine_version) "
    "VALUES (%s, %s, 1, 'tds', %s, 'contractor', 'it_act_1961', '194C', %s, '2026-03-10', '2026-03-10', 50000.00, 0, 50000.00, "
    "50000.00, 1, 'normal', 500.00, %s, 't')"
)


def _draft_with_deductee(f):
    client_id, fy_id = f.setup()
    lines = f.balanced_lines(client_id)
    vid = f.draft(client_id, fy_id, lines)
    party = _deductee(f, client_id)
    f.conn.execute(
        "INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) VALUES (%s, %s, 'ABCDE1234F', 'valid', 'individual')",
        (party, client_id))
    return client_id, fy_id, vid, party


def test_T11_item_amount_without_a_voucher_line_is_rejected_and_items_freeze_after_posting(f):
    client_id, fy_id, vid, party = _draft_with_deductee(f)
    with rejected(f.conn, constraint="tds_voucher_items_zero_has_no_line"):
        f.conn.execute(ITEM_SQL, (client_id, vid, party, fy_id, None))
    f.conn.execute(ITEM_SQL, (client_id, vid, party, fy_id, 1))
    f.approve(vid)
    f.post(vid, "PAY/2025-26/0001")
    check_deferred(f.conn)
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("UPDATE tds_voucher_items SET note = 'x' WHERE voucher_id = %s", (vid,))
    with rejected(f.conn, message="can only be changed while the voucher is draft"):
        f.conn.execute("DELETE FROM tds_voucher_items WHERE voucher_id = %s", (vid,))


def test_T22_challan_total_must_add_up_and_a_locked_challan_is_frozen(f):
    client_id, fy_id = f.setup()
    sql = (
        "INSERT INTO tds_challans (client_id, kind, financial_year_id, quarter, bsr_code, deposit_date, challan_serial_no, "
        "tax_amount, interest_amount, total_amount, created_by) VALUES (%s, 'tds', %s, 4, '0510308', '2026-04-07', '00123', 500.00, %s, %s, 't') "
        "RETURNING id"
    )
    with rejected(f.conn, constraint="tds_challans_total_adds_up"):
        f.conn.execute(sql, (client_id, fy_id, "10.00", "500.00"))
    cid = f.conn.execute(sql, (client_id, fy_id, "10.00", "510.00")).fetchone()[0]
    f.conn.execute("UPDATE tds_challans SET status = 'locked' WHERE id = %s", (cid,))
    with rejected(f.conn, message="a locked challan cannot be changed"):
        f.conn.execute("UPDATE tds_challans SET note = 'x' WHERE id = %s", (cid,))
    with rejected(f.conn, message="a locked challan cannot be deleted"):
        f.conn.execute("DELETE FROM tds_challans WHERE id = %s", (cid,))
