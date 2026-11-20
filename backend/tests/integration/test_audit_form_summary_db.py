"""Phase 8 package F against the database: tax audit form data (form choice, derivation, manual entry, finalise, export) and the AI summary of
exceptions (blocked / ok / rejected, stored as a suggestion). The model is ALWAYS the fake client: no network, no key.
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_form_summary_db.py`.
Runs, findings and papers are built with raw SQL (package A, the run service, is built in parallel; this test depends only on migration 0019).
"""

import io
import json
import uuid

import openpyxl
import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai.fake import FakeLlmClient
from app.ai.llm import LlmError
from app.api import audit_summary as summary_api
from app.api.deps import get_conn
from app.main import app
from app.services import ai_settings, audit_form, audit_summary
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}
MSG1 = "Cash payments to Sharma Traders on 14-08-2026 total 11,000.00, above the daily limit of 10,000.00 (limit pending verification)"
MSG2 = "Cash payments to Gupta Stores on 01-09-2026 total 25,000.50, above the daily limit of 10,000.00 (limit pending verification)"
MSG3 = "Cash receipts from Mehta & Co on 03-09-2026 total 2,00,000.00"
GOOD = ("F1 and F2 (check A-05) are cash payments above the limit of 10,000.00: 11,000.00 to Sharma Traders on 14-08-2026 and 25,000.50 "
        "to Gupta Stores on 01-09-2026. F3 (check A-06) is a cash receipt of 2,00,000.00 from Mehta & Co on 03-09-2026.")


@pytest.fixture(autouse=True)
def _model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "fake/model")


@pytest.fixture
def world(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    client = f.client()
    fy25, fy26 = f.fy(client, 2025), f.fy(client, 2026)
    run = _run(f, client, fy26, ["A-05", "A-06"])
    ids = [_finding(f, client, run, "A-05:p1:2026-08-14", "A-05", MSG1, "2026-08-14", "11000.00", "11000.00", True),
           _finding(f, client, run, "A-05:p2:2026-09-01", "A-05", MSG2, "2026-09-01", "25000.50", "25000.50", True),
           _finding(f, client, run, "A-06:p3:2026-09-03", "A-06", MSG3, "2026-09-03", "200000.00", None, False)]
    return {"f": f, "client": client, "fy25": fy25, "fy26": fy26, "run": run, "findings": ids}


def _run(f, client, fy, checks, summary=None):
    run = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO audit_runs (id, client_id, financial_year_id, from_date, to_date, check_ids, engine_version, status, summary, created_by) "
        "SELECT %s, %s, id, start_date, end_date, %s, 'audit-1', 'completed', %s::jsonb, 'tester' FROM financial_years WHERE id = %s",
        (run, client, checks, json.dumps(summary or {}), fy))
    return run


def _finding(f, client, run, key, check, message, day, amount, disallow, pending):
    fid = uuid.uuid4()
    evidence = {"voucher_ids": ["v1"], **({"rule": {"verification_status": "pending"}} if pending else {})}
    f.conn.execute(
        "INSERT INTO audit_findings (id, client_id, run_id, check_id, finding_key, severity, subject_kind, subject_ref, finding_date, amount, "
        "disallowance_amount, message, evidence) VALUES (%s, %s, %s, %s, %s, 'error', 'party', 'ref', %s, %s, %s, %s, %s)",
        (fid, client, run, check, key, day, amount, disallow, message, json.dumps(evidence)))
    return fid


def entries(svc_conn, set_id):
    rows = svc_conn.execute(text("SELECT clause_no, field_key, value, origin FROM audit_form_entries WHERE form_set_id = :s"), {"s": set_id})
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


# ---------------------------------------------------------------------------------------------------- form data


def test_A_form_the_form_follows_the_fy_end_date_and_pending_clauses_are_shown(svc_conn, world):
    old = audit_form.form_for_year(svc_conn, world["client"], world["fy25"])
    assert old["form_key"] == "form_3cd" and old["verification_status"] == "secondary_verified"
    assert [c["clause_no"] for c in old["clauses"]] == ["18", "21", "22", "23", "26", "27", "31", "34", "35", "40", "44"]
    assert {c["verification_status"] for c in old["clauses"]} == {"pending"}
    assert [c["clause_no"] for c in old["clauses"] if not c["derivable_here"]] == ["18", "35", "40", "44"]
    new = audit_form.form_for_year(svc_conn, world["client"], world["fy26"])
    assert new["form_key"] == "form_26" and new["clauses"] == [] and "not verified against the official form" in new["note"]


def test_A_form_a_set_is_created_once_per_year_and_derives_from_a_run(svc_conn, world):
    c, fy = world["client"], world["fy25"]
    run25 = _run(world["f"], c, fy, ["A-05", "A-06"])
    _finding(world["f"], c, run25, "A-05:x:1", "A-05", MSG1, "2026-01-10", "11000.00", "11000.00", True)
    _finding(world["f"], c, run25, "A-05:x:2", "A-05", MSG2, "2026-02-10", "25000.50", "25000.50", True)
    made = audit_form.create_set(svc_conn, c, fy, actor="tester")
    assert made["form_key"] == "form_3cd" and made["status"] == "draft"
    with pytest.raises(ServiceError) as e:
        audit_form.create_set(svc_conn, c, fy, actor="tester")
    assert e.value.code == "duplicate_form_set"
    out = audit_form.derive(svc_conn, c, made["id"], run25, actor="tester")
    got = entries(svc_conn, made["id"])
    assert got[("21", "cash_payment_exception_count")] == ("2", "derived")
    assert got[("21", "cash_payment_total_amount")] == ("36000.50", "derived")
    assert got[("21", "cash_payment_disallowable_amount")] == ("36000.50", "derived")
    assert got[("21", "legal_rule_status")] == ("pending", "derived")
    assert got[("31", "cash_receipts_count")] == ("0", "derived") and got[("31", "cash_receipts_amount")] == ("0.00", "derived")
    # clauses 22, 23, 26, 27, 34 need checks that this run did not execute; 18, 35, 40, 44 are not derivable: all left for hand entry
    assert [s["clause_no"] for s in out["skipped"]] == ["18", "22", "23", "26", "27", "34", "35", "40", "44"]
    assert not any(k[0] in ("22", "34", "18") for k in got)
    log = svc_conn.execute(text("SELECT action, new_data FROM audit_log WHERE entity = 'audit_form_set' AND entity_id = :i ORDER BY id"),
                           {"i": made["id"]}).all()
    assert [r[0] for r in log] == ["create", "derive"]


def test_A_form_a_run_of_another_year_is_refused_and_a_manual_entry_survives_a_new_derive(svc_conn, world):
    c = world["client"]
    made = audit_form.create_set(svc_conn, c, world["fy25"], actor="tester")
    with pytest.raises(ServiceError) as e:
        audit_form.derive(svc_conn, c, made["id"], world["run"], actor="tester")      # the run is of FY 2026-27
    assert e.value.code == "invalid_run"
    run25 = _run(world["f"], c, world["fy25"], ["A-06"])
    audit_form.enter_manual(svc_conn, c, made["id"], "31", "cash_receipts_amount", "123.00", actor="tester")
    out = audit_form.derive(svc_conn, c, made["id"], run25, actor="tester")
    assert out["kept_manual"] == [{"clause_no": "31", "field_key": "cash_receipts_amount"}]
    assert entries(svc_conn, made["id"])[("31", "cash_receipts_amount")] == ("123.00", "manual")
    assert entries(svc_conn, made["id"])[("31", "cash_receipts_count")] == ("0", "derived")


def test_A_form_manual_entry_rules_and_the_form_26_set_takes_hand_entries_only(svc_conn, world):
    c = world["client"]
    made = audit_form.create_set(svc_conn, c, world["fy26"], actor="tester")
    assert made["form_key"] == "form_26"
    audit_form.enter_manual(svc_conn, c, made["id"], "7", "turnover", "1000000.00", actor="tester")
    assert entries(svc_conn, made["id"]) == {("7", "turnover"): ("1000000.00", "manual")}
    for bad in (None, 12.5, "  "):
        with pytest.raises(ServiceError) as e:
            audit_form.enter_manual(svc_conn, c, made["id"], "7", "turnover", bad, actor="tester")
        assert e.value.code == "invalid_entry"
    out = audit_form.derive(svc_conn, c, made["id"], _run(world["f"], c, world["fy26"], ["A-05"]), actor="tester")
    assert out["entries"] == [] and out["skipped"] == []        # no Form 26 clause is seeded, so nothing is claimed to be derivable


def test_A_form_finalised_set_rejects_every_change_and_the_export_marks_pending_clauses(svc_conn, world):
    c = world["client"]
    made = audit_form.create_set(svc_conn, c, world["fy25"], actor="tester")
    audit_form.enter_manual(svc_conn, c, made["id"], "21", "other_inadmissible", "500.00", actor="tester")
    audit_form.finalise(svc_conn, c, made["id"], actor="tester")
    run25 = _run(world["f"], c, world["fy25"], ["A-06"])
    for call in (lambda: audit_form.enter_manual(svc_conn, c, made["id"], "21", "other_inadmissible", "1.00", actor="tester"),
                 lambda: audit_form.derive(svc_conn, c, made["id"], run25, actor="tester"),
                 lambda: audit_form.finalise(svc_conn, c, made["id"], actor="tester")):
        with pytest.raises(ServiceError) as e:
            call()
        assert e.value.code == "form_finalised"
    assert entries(svc_conn, made["id"]) == {("21", "other_inadmissible"): ("500.00", "manual")}
    content, _, name = audit_form.export_xlsx(svc_conn, c, made["id"])
    ws = openpyxl.load_workbook(io.BytesIO(content)).active
    rows = [[cell.value for cell in r] for r in ws.iter_rows()]
    assert name == "tax_audit_form_3cd.xlsx"
    assert rows[1][0] == "Form status: secondary_verified (not verified against the official form)"
    first = rows[4]
    assert first[:5] == ["21", "Amounts debited to profit and loss that are inadmissible (capital, personal, 40A(3) cash payments and similar)",
                         "other_inadmissible", "500.00", "manual"]
    assert first[6] == "pending: not verified against the official form"
    assert len(rows) == 4 + 1 + 10           # header block, the entry, the ten clauses not entered


# ---------------------------------------------------------------------------------------------------- AI summary


def enable(svc_conn, client):
    ai_settings.set_settings(svc_conn, client, llm_enabled=True, data_class="synthetic", note="synthetic test data only", actor="owner")


def count(svc_conn, table, client):
    return svc_conn.execute(text(f"SELECT count(*) FROM {table} WHERE client_id = :c"), {"c": client}).scalar_one()


def test_A_summary_ai_switch_off_makes_no_call_and_stores_nothing_but_a_blocked_gateway_row(svc_conn, world):
    fake = FakeLlmClient([json.dumps({"summary": GOOD})])
    res = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", llm_client=fake)
    assert (res.status, res.reason) == ("blocked", "llm_disabled") and fake.requests == []
    row = svc_conn.execute(text("SELECT status, purpose, prompt_masked FROM llm_calls WHERE client_id = :c"), {"c": world["client"]}).one()
    assert tuple(row) == ("blocked", "audit_summary", None)
    assert count(svc_conn, "audit_ai_summaries", world["client"]) == 0


def test_A_summary_a_faithful_summary_is_stored_as_a_suggestion_with_the_exact_findings(svc_conn, world):
    enable(svc_conn, world["client"])
    fake = FakeLlmClient([json.dumps({"summary": GOOD})])
    res = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", llm_client=fake)
    assert res.status == "ok" and res.is_suggestion and res.summary_text == GOOD
    sent = fake.requests[0]
    assert sent.purpose == "audit_summary" and "Findings listed: 3 of 3" in sent.user and MSG3 in sent.user
    row = svc_conn.execute(text("SELECT summary_text, is_suggestion, llm_call_id, paper_id FROM audit_ai_summaries WHERE id = :i"),
                           {"i": res.id}).one()
    assert tuple(row) == (GOOD, True, res.llm_call_id, None)
    prompt = svc_conn.execute(text("SELECT prompt_masked FROM llm_calls WHERE id = :i"), {"i": res.llm_call_id}).scalar_one()
    assert MSG1 in prompt and MSG2 in prompt and MSG3 in prompt
    logged = svc_conn.execute(text("SELECT new_data FROM audit_log WHERE entity = 'audit_ai_summary' AND entity_id = :i"), {"i": res.id}).scalar_one()
    assert sorted(logged["finding_ids"]) == sorted(str(i) for i in world["findings"]) and logged["findings_total"] == 3
    # the summary never reaches a conclusion, a paper item or a finding
    assert svc_conn.execute(text("SELECT count(*) FROM audit_working_papers WHERE client_id = :c"), {"c": world["client"]}).scalar_one() == 0
    assert [s["summary_text"] for s in audit_summary.list_summaries(svc_conn, world["client"], world["run"])] == [GOOD]


def test_A_summary_an_invented_amount_or_a_conclusion_is_rejected_and_not_stored(svc_conn, world):
    enable(svc_conn, world["client"])
    fake = FakeLlmClient([json.dumps({"summary": "F1 shows 12,500.00 paid in cash."}),
                          json.dumps({"summary": "In our opinion the books are compliant, F1 is cleared."}),
                          json.dumps({"text": "no summary key"})])
    first = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", llm_client=fake)
    assert (first.status, first.reason) == ("rejected", "unverified_text")
    assert first.problems == ["The summary quotes the number 12,500.00, which is not in the findings."]
    second = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", llm_client=fake)
    assert second.status == "rejected" and len(second.problems) == 3
    third = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", llm_client=fake)
    assert (third.status, third.reason) == ("rejected", "invalid_shape")
    assert count(svc_conn, "audit_ai_summaries", world["client"]) == 0
    assert count(svc_conn, "llm_calls", world["client"]) == 3        # the gateway rows stay as the record of what happened


def test_A_summary_provider_error_is_a_result_and_a_check_or_paper_selection_limits_the_findings(svc_conn, world):
    enable(svc_conn, world["client"])
    err = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", llm_client=FakeLlmClient([LlmError("timeout")]))
    assert (err.status, err.reason) == ("error", "provider_error")
    paper = uuid.uuid4()
    world["f"].conn.execute("INSERT INTO audit_working_papers (id, client_id, financial_year_id, run_id, check_id, created_by) "
                            "VALUES (%s, %s, %s, %s, 'A-06', 'tester')", (paper, world["client"], world["fy26"], world["run"]))
    fake = FakeLlmClient([json.dumps({"summary": "F1 (check A-06) is a cash receipt of 2,00,000.00 from Mehta & Co."})])
    ok = audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", paper_id=paper, llm_client=fake)
    assert ok.status == "ok" and "Findings listed: 1 of 1" in fake.requests[0].user and MSG1 not in fake.requests[0].user
    assert svc_conn.execute(text("SELECT paper_id FROM audit_ai_summaries WHERE id = :i"), {"i": ok.id}).scalar_one() == paper


def test_A_summary_bad_requests_raise(svc_conn, world):
    with pytest.raises(ServiceError) as e:
        audit_summary.summarise(svc_conn, world["client"], uuid.uuid4(), actor="tester")
    assert e.value.code == "not_found"
    with pytest.raises(ServiceError) as e:
        audit_summary.summarise(svc_conn, world["client"], world["run"], actor="tester", check_id="A-12")
    assert e.value.code == "invalid_selection"


# ---------------------------------------------------------------------------------------------------- API


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_A_api_summary_blocked_ok_and_list(api, svc_conn, world):
    base = f"/clients/{world['client']}/audit/runs/{world['run']}"
    r = api.post(f"{base}/summary", json={}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "blocked" and r.json()["reason"] == "llm_disabled"
    enable(svc_conn, world["client"])
    app.dependency_overrides[summary_api.get_llm_client] = lambda: FakeLlmClient([json.dumps({"summary": GOOD})])
    try:
        r = api.post(f"{base}/summary", json={"check_id": None}, headers=H)
    finally:
        app.dependency_overrides.pop(summary_api.get_llm_client, None)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["is_suggestion"] is True and body["summary_text"] == GOOD
    listed = api.get(f"{base}/summaries").json()
    assert [(s["id"], s["is_suggestion"]) for s in listed] == [(body["id"], True)]
    assert api.post(f"{base}/summary", json={"check_id": "A-12"}, headers=H).status_code == 422


def test_A_api_form_set_flow_and_finalised_conflict(api, world):
    base = f"/clients/{world['client']}/audit/forms"
    r = api.get(base, params={"financial_year_id": str(world["fy25"])})
    assert r.status_code == 200 and r.json()["form_key"] == "form_3cd"
    sid = api.post(f"{base}/sets", json={"financial_year_id": str(world["fy25"])}, headers=H).json()["id"]
    assert api.put(f"{base}/sets/{sid}/entries", json={"clause_no": "18", "field_key": "depreciation", "value": "900.00"}, headers=H).status_code == 200
    got = api.get(f"{base}/sets/{sid}").json()
    assert [(e["clause_no"], e["value"], e["origin"]) for e in got["entries"]] == [("18", "900.00", "manual")]
    assert api.post(f"{base}/sets/{sid}/finalise", headers=H).json() == {"ok": True}
    r = api.put(f"{base}/sets/{sid}/entries", json={"clause_no": "18", "field_key": "depreciation", "value": "1.00"}, headers=H)
    assert r.status_code == 409 and r.json()["code"] == "form_finalised"
    assert api.get(f"{base}/sets/{sid}", params={"format": "xlsx"}).status_code == 200
