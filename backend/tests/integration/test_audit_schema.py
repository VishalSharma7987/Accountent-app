"""Step 8.0: the Phase 8 tables of migration 0019 and seeds 0014 / 0015 (database guards hold).
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_schema.py`.

Each test builds its rows inside a transaction that is rolled back. Expected values are typed literally.
"""

import json
import uuid

import pytest
from dbfactory import Factory, rejected

pytestmark = pytest.mark.integration


@pytest.fixture
def f(clean_db) -> Factory:
    return Factory(clean_db)


def _run(f, client_id, fy_id):
    run_id = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO audit_runs (id, client_id, financial_year_id, from_date, to_date, check_ids, engine_version, status, created_by) "
        "VALUES (%s, %s, %s, '2026-04-01', '2027-03-31', ARRAY['A-05', 'A-12'], 'audit-1', 'completed', 'tester')",
        (run_id, client_id, fy_id))
    return run_id


def _finding(f, client_id, run_id, key="A-05:p1:2026-08-14", check="A-05", evidence=None, amount="25000.00"):
    fid = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO audit_findings (id, client_id, run_id, check_id, finding_key, severity, subject_kind, subject_ref, amount, message, evidence) "
        "VALUES (%s, %s, %s, %s, %s, 'error', 'party', 'Sharma Traders', %s, 'Cash paid 25,000.00 in one day', %s)",
        (fid, client_id, run_id, check, key, amount, json.dumps(evidence if evidence is not None else {"voucher_ids": ["v1"]})))
    return fid


def _paper(f, client_id, fy_id, run_id, check="A-05"):
    pid = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO audit_working_papers (id, client_id, financial_year_id, run_id, check_id, created_by) VALUES (%s, %s, %s, %s, %s, 'tester')",
        (pid, client_id, fy_id, run_id, check))
    return pid


def _item(f, client_id, paper_id, finding_id):
    iid = uuid.uuid4()
    f.conn.execute("INSERT INTO audit_paper_items (id, client_id, paper_id, finding_id) VALUES (%s, %s, %s, %s)",
                   (iid, client_id, paper_id, finding_id))
    return iid


def _decide(f, item_id, status="confirmed", note="agreed to voucher and bill"):
    f.conn.execute("UPDATE audit_paper_items SET status = %s, reviewer_note = %s, decided_by = 'rev', decided_at = now() WHERE id = %s",
                   (status, note, item_id))


def _sign(f, paper_id):
    f.conn.execute("UPDATE audit_working_papers SET status = 'in_review' WHERE id = %s", (paper_id,))
    f.conn.execute("UPDATE audit_working_papers SET status = 'signed_off', conclusion = 'exceptions confirmed', signed_off_by = 'rev', "
                   "signed_off_at = now() WHERE id = %s", (paper_id,))


def test_seeds_the_catalogue_and_the_limits_with_honest_statuses(f):
    ids = [r[0] for r in f.conn.execute("SELECT check_id FROM audit_checks ORDER BY check_id").fetchall()]
    assert ids == [f"A-{n:02d}" for n in range(1, 19)]
    rows = f.conn.execute(
        "SELECT rule_key, law, amount, breach_when, verification_status FROM audit_rule_limits ORDER BY rule_key, law").fetchall()
    assert [(r[0], r[1], str(r[2]), r[3], r[4]) for r in rows] == [
        ("cash_payment_daily_limit", "it_act_1961", "10000.0000", "above", "pending"),
        ("cash_payment_daily_limit", "it_act_2025", "10000.0000", "above", "pending"),
        ("cash_payment_daily_limit_transport", "it_act_1961", "35000.0000", "above", "pending"),
        ("cash_payment_daily_limit_transport", "it_act_2025", "35000.0000", "above", "pending"),
        ("cash_receipt_limit", "it_act_1961", "200000.0000", "at_or_above", "secondary_verified"),
        ("cash_receipt_limit", "it_act_2025", "200000.0000", "at_or_above", "pending"),
    ]
    assert f.conn.execute("SELECT count(*) FROM audit_rule_limits WHERE verification_status = 'verified'").fetchone()[0] == 0
    forms = f.conn.execute("SELECT form_key FROM audit_form_defs ORDER BY form_key").fetchall()
    assert [r[0] for r in forms] == ["form_26", "form_3cd"]
    assert f.conn.execute("SELECT count(*) FROM audit_form_clauses WHERE form_key = 'form_26'").fetchone()[0] == 0
    assert f.conn.execute("SELECT count(*) FROM audit_form_clauses WHERE form_key = 'form_3cd'").fetchone()[0] == 11


def test_rule_limits_reject_a_third_decimal_and_a_bad_breach_word_and_a_duplicate_row(f):
    ins = ("INSERT INTO audit_rule_limits (rule_key, law, section_ref, amount, breach_when, effective_from, source_reference, verification_status) "
           "VALUES ('cash_receipt_limit', 'it_act_1961', 's', %s, %s, %s, 'src', 'pending')")
    with rejected(f.conn, constraint="audit_rule_limits_amount_two_decimals"):
        f.conn.execute(ins, ("100.005", "above", "2030-01-01"))
    with rejected(f.conn, constraint="audit_rule_limits_breach_check"):
        f.conn.execute(ins, ("100.00", "over", "2030-01-01"))
    with rejected(f.conn, constraint="audit_rule_limits_key_law_from"):
        f.conn.execute(ins, ("100.00", "above", "2017-04-01"))


def test_runs_and_findings_are_insert_only_evidence_and_every_finding_has_evidence(f):
    client_id, fy_id = f.setup()
    run_id = _run(f, client_id, fy_id)
    with rejected(f.conn, constraint="audit_findings_evidence_present"):
        _finding(f, client_id, run_id, evidence={})
    with rejected(f.conn, constraint="audit_findings_amount_two_decimals"):
        _finding(f, client_id, run_id, amount="10.005")
    fid = _finding(f, client_id, run_id)
    with rejected(f.conn, constraint="audit_findings_run_key"):
        _finding(f, client_id, run_id)
    with rejected(f.conn, message="insert only"):
        f.conn.execute("UPDATE audit_findings SET message = 'changed' WHERE id = %s", (fid,))
    with rejected(f.conn, message="insert only"):
        f.conn.execute("DELETE FROM audit_findings WHERE id = %s", (fid,))
    with rejected(f.conn, message="insert only"):
        f.conn.execute("UPDATE audit_runs SET finding_count = 9 WHERE id = %s", (run_id,))
    with rejected(f.conn, constraint="audit_runs_failed_has_reason"):
        f.conn.execute(
            "INSERT INTO audit_runs (client_id, financial_year_id, from_date, to_date, check_ids, engine_version, status, created_by) "
            "VALUES (%s, %s, '2026-04-01', '2027-03-31', ARRAY['A-05'], 'audit-1', 'failed', 'tester')", (client_id, fy_id))


def test_a_sample_needs_its_seed_and_an_exception_decision_needs_who_when_why(f):
    client_id, fy_id = f.setup()
    run_id = _run(f, client_id, fy_id)
    paper = _paper(f, client_id, fy_id, run_id)
    with rejected(f.conn, constraint="audit_working_papers_sample_reproducible"):
        f.conn.execute("UPDATE audit_working_papers SET sample_method = 'random', sample_ids = '[\"a\"]' WHERE id = %s", (paper,))
    f.conn.execute("UPDATE audit_working_papers SET sample_method = 'random', sample_seed = 42, sample_ids = '[\"a\"]' WHERE id = %s", (paper,))
    item = _item(f, client_id, paper, _finding(f, client_id, run_id))
    with rejected(f.conn, constraint="audit_paper_items_decision_complete"):
        f.conn.execute("UPDATE audit_paper_items SET status = 'cleared' WHERE id = %s", (item,))
    with rejected(f.conn, message="does not belong"):
        _item(f, client_id, paper, _finding(f, client_id, run_id, key="A-12:x", check="A-12"))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM audit_paper_items WHERE id = %s", (item,))


def test_signed_off_paper_items_and_notes_are_immutable(f):
    client_id, fy_id = f.setup()
    run_id = _run(f, client_id, fy_id)
    paper = _paper(f, client_id, fy_id, run_id)
    item = _item(f, client_id, paper, _finding(f, client_id, run_id))
    other = _finding(f, client_id, run_id, key="A-05:p2:2026-08-15")
    f.conn.execute("INSERT INTO audit_paper_notes (client_id, paper_id, note, created_by) VALUES (%s, %s, 'asked for bills', 'rev')",
                   (client_id, paper))
    with rejected(f.conn, message="cannot move from open to signed_off"):
        f.conn.execute("UPDATE audit_working_papers SET status = 'signed_off', conclusion = 'c', signed_off_by = 'r', signed_off_at = now() "
                       "WHERE id = %s", (paper,))
    f.conn.execute("UPDATE audit_working_papers SET status = 'in_review' WHERE id = %s", (paper,))
    with rejected(f.conn, message="open exceptions"):
        f.conn.execute("UPDATE audit_working_papers SET status = 'signed_off', conclusion = 'c', signed_off_by = 'r', signed_off_at = now() "
                       "WHERE id = %s", (paper,))
    _decide(f, item)
    with rejected(f.conn, constraint="audit_working_papers_signoff_complete"):
        f.conn.execute("UPDATE audit_working_papers SET status = 'signed_off' WHERE id = %s", (paper,))
    _sign(f, paper)
    with rejected(f.conn, message="signed off"):
        f.conn.execute("UPDATE audit_working_papers SET conclusion = 'edited later' WHERE id = %s", (paper,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM audit_working_papers WHERE id = %s", (paper,))
    with rejected(f.conn, message="signed off"):
        _decide(f, item, "cleared", "changed my mind")
    with rejected(f.conn, message="signed off"):
        _item(f, client_id, paper, other)
    with rejected(f.conn, message="signed off"):
        f.conn.execute("INSERT INTO audit_paper_notes (client_id, paper_id, note, created_by) VALUES (%s, %s, 'late note', 'rev')",
                       (client_id, paper))
    with rejected(f.conn, message="insert only"):
        f.conn.execute("UPDATE audit_paper_notes SET note = 'x' WHERE paper_id = %s", (paper,))
    assert f.conn.execute("SELECT status FROM audit_working_papers WHERE id = %s", (paper,)).fetchone()[0] == "signed_off"


def test_ai_summary_is_a_suggestion_only_and_the_gateway_log_accepts_the_audit_purpose(f):
    client_id, fy_id = f.setup()
    run_id = _run(f, client_id, fy_id)
    call_id = uuid.uuid4()
    f.conn.execute("INSERT INTO llm_calls (id, client_id, purpose, provider, prompt_version, status, created_by) "
                   "VALUES (%s, %s, 'audit_summary', 'openrouter', 'audit-summary-1', 'blocked', 'tester')", (call_id, client_id))
    ins = ("INSERT INTO audit_ai_summaries (client_id, run_id, llm_call_id, summary_text, is_suggestion, created_by) "
           "VALUES (%s, %s, %s, 'Two cash payments look high.', %s, 'tester')")
    with rejected(f.conn, constraint="audit_ai_summaries_suggestion_only"):
        f.conn.execute(ins, (client_id, run_id, call_id, False))
    f.conn.execute(ins, (client_id, run_id, call_id, True))
    with rejected(f.conn, message="insert only"):
        f.conn.execute("UPDATE audit_ai_summaries SET summary_text = 'x' WHERE run_id = %s", (run_id,))


def test_form_sets_finalise_once_and_derived_entries_name_their_run(f):
    client_id, fy_id = f.setup()
    run_id = _run(f, client_id, fy_id)
    set_id = uuid.uuid4()
    f.conn.execute("INSERT INTO audit_form_sets (id, client_id, financial_year_id, form_key, created_by) VALUES (%s, %s, %s, 'form_3cd', 't')",
                   (set_id, client_id, fy_id))
    ins = ("INSERT INTO audit_form_entries (client_id, form_set_id, clause_no, field_key, value, origin, run_id, entered_by) "
           "VALUES (%s, %s, %s, 'total', %s, %s, %s, 't')")
    with rejected(f.conn, constraint="audit_form_entries_derived_has_run"):
        f.conn.execute(ins, (client_id, set_id, "21", json.dumps("25000.00"), "derived", None))
    f.conn.execute(ins, (client_id, set_id, "21", json.dumps("25000.00"), "derived", run_id))
    f.conn.execute(ins, (client_id, set_id, "12", json.dumps("yes"), "manual", None))
    f.conn.execute("UPDATE audit_form_sets SET status = 'finalised', finalised_by = 'ca', finalised_at = now() WHERE id = %s", (set_id,))
    with rejected(f.conn, message="finalised"):
        f.conn.execute("UPDATE audit_form_entries SET value = '\"1.00\"' WHERE form_set_id = %s", (set_id,))
    with rejected(f.conn, message="finalised"):
        f.conn.execute("DELETE FROM audit_form_entries WHERE form_set_id = %s", (set_id,))
    with rejected(f.conn, message="finalised"):
        f.conn.execute(ins, (client_id, set_id, "35", json.dumps("1.00"), "manual", None))
    with rejected(f.conn, message="finalised"):
        f.conn.execute("UPDATE audit_form_sets SET status = 'draft' WHERE id = %s", (set_id,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM audit_form_sets WHERE id = %s", (set_id,))


def test_related_party_flags_are_history_and_stay_inside_the_client(f):
    client_id, _ = f.setup()
    other = f.client()
    ledger = f.ledger(client_id, "Director Loan", "loans_liability")
    foreign = f.ledger(other, "Other Client Ledger", "loans_liability")
    ins = "INSERT INTO audit_related_parties (client_id, ledger_id, relationship, flagged_by) VALUES (%s, %s, 'director', 'ca')"
    with rejected(f.conn, constraint="audit_related_parties_ledger_fk"):
        f.conn.execute(ins, (client_id, foreign))
    f.conn.execute(ins, (client_id, ledger))
    with rejected(f.conn, constraint="audit_related_parties_ledger_key"):
        f.conn.execute(ins, (client_id, ledger))
    f.conn.execute("UPDATE audit_related_parties SET active = false WHERE ledger_id = %s", (ledger,))
    with rejected(f.conn, message="cannot be deleted"):
        f.conn.execute("DELETE FROM audit_related_parties WHERE ledger_id = %s", (ledger,))
    f.conn.execute("INSERT INTO audit_holidays (client_id, holiday_date, name, kind, created_by) VALUES (%s, '2026-10-20', 'Dussehra', 'national', 'ca')", (client_id,))
    with rejected(f.conn, constraint="audit_holidays_client_date_key"):
        f.conn.execute("INSERT INTO audit_holidays (client_id, holiday_date, name, created_by) VALUES (%s, '2026-10-20', 'again', 'ca')", (client_id,))
