"""Phase 8 package E against the database: working papers, exceptions, notes, sign-off, sampling, audit log, API.
Runs and findings are built with raw SQL (package A, the run service, is built in parallel; this file only needs the tables of migration
0019 and the shape of audit_runs.summary.by_check). Run once through the lock script:
`C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_papers_db.py`.
Expected values are typed literally.
"""

import json
import uuid

import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app
from app.services import audit_papers as svc
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

H = {"X-User": "reviewer"}
FINDINGS = [("A-05:p1:2026-08-14", "11000.00"), ("A-05:p2:2026-09-01", "6500.50"), ("A-05:p3:2026-09-20", "25000.00")]
DIGEST_V01_V10 = "983ff6325da5dd51c8d1611e524aa0d9138f304894778cea70d25e39ed614c7f"  # sha256 of v01..v10 joined by newline, hashed outside the code


def build_world(svc_conn, summary=None):
    """client + FY + one completed run (A-05 with three findings, A-12 with none) -> (client_id, run_id, [finding ids])."""
    raw = svc_conn.connection.driver_connection
    f = Factory(raw)
    client_id = f.client()
    fy_id = f.fy(client_id)
    run_id = uuid.uuid4()
    raw.execute(
        "INSERT INTO audit_runs (id, client_id, financial_year_id, from_date, to_date, check_ids, engine_version, status, summary, created_by) "
        "VALUES (%s, %s, %s, '2026-04-01', '2027-03-31', ARRAY['A-05', 'A-12'], 'audit-1', 'completed', %s, 'tester')",
        (run_id, client_id, fy_id, json.dumps(summary or {})))
    ids = []
    for key, amount in FINDINGS:
        fid = uuid.uuid4()
        raw.execute(
            "INSERT INTO audit_findings (id, client_id, run_id, check_id, finding_key, severity, subject_kind, subject_ref, amount, message, "
            "evidence) VALUES (%s, %s, %s, 'A-05', %s, 'error', 'party', 'Party', %s, 'Cash paid above the limit', %s)",
            (fid, client_id, run_id, key, amount, json.dumps({"voucher_ids": ["v1"], "day_total": amount})))
        ids.append(fid)
    return client_id, run_id, ids


def audit_rows(svc_conn, client_id, action):
    return svc_conn.execute(text("SELECT old_data, new_data, actor FROM audit_log WHERE client_id = :c AND action = :a ORDER BY id"),
                            {"c": client_id, "a": action}).all()


def code_of(fn, *a, **kw):
    with pytest.raises(ServiceError) as e:
        fn(*a, **kw)
    return e.value.code


def test_W01_paper_from_run_and_check_with_items_and_audit_log(svc_conn):
    client_id, run_id, _ = build_world(svc_conn)
    out = svc.create_paper(svc_conn, client_id, run_id, "A-05", "reviewer")
    assert (out["status"], out["population_count"], out["items"]) == ("open", 3, 3)  # findings are the population: run stored no ids
    paper = svc.get_paper(svc_conn, client_id, out["id"])
    assert str(paper["population_amount"]) == "42500.5000"
    assert [i["status"] for i in paper["items"]] == ["open", "open", "open"]
    assert [str(i["amount"]) for i in paper["items"]] == ["11000.0000", "6500.5000", "25000.0000"]
    assert paper["items"][0]["evidence"] == {"voucher_ids": ["v1"], "day_total": "11000.00"}
    # one paper per run + check; a check outside the run is refused; a check with no findings gets an empty paper
    assert code_of(svc.create_paper, svc_conn, client_id, run_id, "A-05", "reviewer") == "paper_exists"
    assert code_of(svc.create_paper, svc_conn, client_id, run_id, "A-07", "reviewer") == "unknown_check"
    assert code_of(svc.create_paper, svc_conn, client_id, uuid.uuid4(), "A-05", "reviewer") == "not_found"
    empty = svc.create_paper(svc_conn, client_id, run_id, "A-12", "reviewer")
    assert (empty["population_count"], empty["items"], empty["population_digest"]) == (0, 0, None)
    # W-07: logged with new values
    ((_, new, actor), *_) = audit_rows(svc_conn, client_id, "create")
    assert (new["check_id"], new["items"], new["population_source"], actor) == ("A-05", 3, "findings", "reviewer")
    # the findings are untouched (W-01)
    assert svc_conn.execute(text("SELECT count(*) FROM audit_findings WHERE run_id = :r"), {"r": run_id}).scalar() == 3


def test_W03_W05_W06_decisions_notes_sign_off_and_immutability(svc_conn):
    client_id, run_id, _ = build_world(svc_conn)
    pid = svc.create_paper(svc_conn, client_id, run_id, "A-05", "preparer")["id"]
    items = svc.get_paper(svc_conn, client_id, pid)["items"]
    # W-03: a reason is mandatory
    assert code_of(svc.decide_item, svc_conn, client_id, pid, items[0]["id"], "cleared", "  ", "reviewer") == "decision_reason_required"
    assert code_of(svc.decide_item, svc_conn, client_id, pid, uuid.uuid4(), "cleared", "ok", "reviewer") == "not_found"
    # W-04 / W-05: sign-off only from in_review, with every exception decided and a conclusion
    assert code_of(svc.sign_off, svc_conn, client_id, pid, "Done", "reviewer") == "paper_status_invalid"
    svc.send_to_review(svc_conn, client_id, pid, "reviewer")
    assert code_of(svc.send_to_review, svc_conn, client_id, pid, "reviewer") == "paper_status_invalid"
    assert code_of(svc.sign_off, svc_conn, client_id, pid, "Done", "reviewer") == "open_exceptions"
    svc.decide_item(svc_conn, client_id, pid, items[0]["id"], "cleared", "Agreed to the bill and cash book", "reviewer")
    svc.decide_item(svc_conn, client_id, pid, items[1]["id"], "confirmed", "No bill produced", "reviewer")
    svc.decide_item(svc_conn, client_id, pid, items[1]["id"], "confirmed", "No bill produced; party confirmed in writing", "reviewer")
    assert code_of(svc.sign_off, svc_conn, client_id, pid, "Done", "reviewer") == "open_exceptions"
    svc.decide_item(svc_conn, client_id, pid, items[2]["id"], "confirmed", "Paid in cash on a Sunday", "reviewer")
    svc.add_note(svc_conn, client_id, pid, "Asked the client for the bills", "reviewer")
    assert code_of(svc.add_note, svc_conn, client_id, pid, " ", "reviewer") == "invalid_note"
    assert code_of(svc.sign_off, svc_conn, client_id, pid, " ", "reviewer") == "invalid_conclusion"
    svc.reopen(svc_conn, client_id, pid, "reviewer")
    svc.send_to_review(svc_conn, client_id, pid, "reviewer")
    out = svc.sign_off(svc_conn, client_id, pid, "Two exceptions confirmed, one cleared", "partner")
    assert out["ok"] is True and out["signed_off_at"] is not None
    paper = svc.get_paper(svc_conn, client_id, pid)
    assert (paper["status"], paper["conclusion"], paper["signed_off_by"]) == ("signed_off", "Two exceptions confirmed, one cleared", "partner")
    assert [(i["status"], i["decided_by"]) for i in paper["items"]] == [("cleared", "reviewer"), ("confirmed", "reviewer"), ("confirmed", "reviewer")]
    assert paper["items"][1]["reviewer_note"] == "No bill produced; party confirmed in writing"
    assert [n["note"] for n in paper["notes"]] == ["Asked the client for the bills"]
    # W-05 / W-06: nothing changes after sign-off
    assert code_of(svc.decide_item, svc_conn, client_id, pid, items[0]["id"], "confirmed", "changed my mind", "reviewer") == "paper_signed_off"
    assert code_of(svc.add_note, svc_conn, client_id, pid, "late note", "reviewer") == "paper_signed_off"
    assert code_of(svc.reopen, svc_conn, client_id, pid, "reviewer") == "paper_signed_off"
    assert code_of(svc.send_to_review, svc_conn, client_id, pid, "reviewer") == "paper_signed_off"
    assert code_of(svc.sign_off, svc_conn, client_id, pid, "again", "reviewer") == "paper_signed_off"
    assert code_of(svc.sample, svc_conn, client_id, pid, "random", "reviewer", seed=1, size=1) == "paper_signed_off"
    # W-07: old and new values are in the audit log
    decide = audit_rows(svc_conn, client_id, "decide")
    assert len(decide) == 4
    old, new, _ = decide[2]  # the second decision of the same item
    assert (old["status"], old["reviewer_note"], new["status"], new["reviewer_note"]) == (
        "confirmed", "No bill produced", "confirmed", "No bill produced; party confirmed in writing")
    ((old, new, actor),) = audit_rows(svc_conn, client_id, "sign_off")
    assert (old["status"], new["status"], new["conclusion"], actor) == ("in_review", "signed_off", "Two exceptions confirmed, one cleared", "partner")
    assert len(audit_rows(svc_conn, client_id, "review")) == 2 and len(audit_rows(svc_conn, client_id, "reopen")) == 1


def test_W02_samples_are_stored_with_seed_and_repeat_exactly(svc_conn):
    ids10 = [f"v{n:02d}" for n in range(1, 11)]
    amounts = dict(zip(ids10, ["80000.00", "49999.99", "50000.00", "10000.00"] + ["1.00"] * 6, strict=True))
    summary = {"by_check": {"A-12": {"findings": 0, "population": 10, "population_ids": ids10[::-1], "population_amounts": amounts,
                                      "population_amount": "190001.99"}}}
    client_id, run_id, _ = build_world(svc_conn, summary)
    out = svc.create_paper(svc_conn, client_id, run_id, "A-12", "reviewer")
    assert (out["population_count"], out["population_digest"]) == (10, DIGEST_V01_V10)
    pid = out["id"]
    one = svc.sample(svc_conn, client_id, pid, "random", "reviewer", seed=0, size=3)
    assert one["ids"] == ["v02", "v06", "v10"]   # hand-derived in tests/unit/test_audit_sampling.py
    assert one["params"] == {"size": 3, "population_source": "run"}
    assert (one["population_count"], one["population_digest"]) == (10, DIGEST_V01_V10)
    stored = svc.get_paper(svc_conn, client_id, pid)
    assert stored["sample"] == {"method": "random", "seed": 0, "params": {"size": 3, "population_source": "run"},
                                "ids": ["v02", "v06", "v10"]}
    assert svc.sample(svc_conn, client_id, pid, "random", "reviewer", seed=0, size=3)["ids"] == ["v02", "v06", "v10"]
    assert svc.sample(svc_conn, client_id, pid, "systematic", "reviewer", seed=42, size=3, start=1)["ids"] == ["v02", "v05", "v08"]
    sysd = svc.sample(svc_conn, client_id, pid, "systematic", "reviewer", seed=42, size=3)
    assert (sysd["ids"], sysd["params"]["interval"], sysd["params"]["start"]) == (["v02", "v05", "v08"], 3, 1)
    val = svc.sample(svc_conn, client_id, pid, "value", "reviewer", seed=0, threshold="50000.00", rest_size=0)
    assert val["ids"] == ["v01", "v03"] and val["params"]["threshold"] == "50000.00"
    # a new sample replaces the old one and every draw is logged (old and new)
    logs = audit_rows(svc_conn, client_id, "sample")
    assert len(logs) == 5 and logs[1][0]["sample_method"] == "random" and logs[1][1]["sample_ids"] == ["v02", "v06", "v10"]
    # invalid requests are refused with sample_invalid
    for kw in ({"seed": 1, "size": 0}, {"seed": 1, "size": 11}, {"seed": None, "size": 2}, {"seed": 1}):
        assert code_of(svc.sample, svc_conn, client_id, pid, "random", "reviewer", **kw) == "sample_invalid"
    assert code_of(svc.sample, svc_conn, client_id, pid, "value", "reviewer", seed=1, threshold="abc") == "sample_invalid"
    assert code_of(svc.sample, svc_conn, client_id, pid, "value", "reviewer", seed=1) == "sample_invalid"
    # a paper whose population came from the findings has amounts for a value sample too: 11,000.00 and 25,000.00 are at or above 10,000.00
    pid5 = svc.create_paper(svc_conn, client_id, run_id, "A-05", "reviewer")["id"]
    assert len(svc.sample(svc_conn, client_id, pid5, "value", "reviewer", seed=1, threshold="10000.00")["ids"]) == 2


def test_E_api_flow_and_pure_preview(svc_conn):
    client_id, run_id, _ = build_world(svc_conn)
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        base = f"/clients/{client_id}/audit"
        r = api.post(f"{base}/papers", json={"run_id": str(run_id), "check_id": "A-05"}, headers=H)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        assert r.json()["items"] == 3 and r.json()["status"] == "open"
        assert api.post(f"{base}/papers", json={"run_id": str(run_id), "check_id": "A-05"}, headers=H).json()["code"] == "paper_exists"
        assert api.post(f"{base}/papers", json={"run_id": str(run_id), "check_id": "A-05"}).status_code == 400   # no X-User
        detail = api.get(f"{base}/papers/{pid}").json()
        assert detail["population_amount"] == "42500.50"
        assert detail["items"][0]["finding"]["amount"] == "11000.00"
        assert detail["items"][0]["finding"]["evidence"]["voucher_ids"] == ["v1"]
        assert [p["id"] for p in api.get(f"{base}/papers", params={"run_id": str(run_id), "status": "open"}).json()] == [pid]
        s = api.post(f"{base}/papers/{pid}/sample", json={"method": "random", "seed": 7, "size": 2}, headers=H)
        assert s.status_code == 200 and len(s.json()["ids"]) == 2 and s.json()["seed"] == 7
        assert api.post(f"{base}/papers/{pid}/sample", json={"method": "random", "seed": 7, "size": 9}, headers=H).json()["code"] == "sample_invalid"
        item_id = detail["items"][0]["id"]
        bad = api.put(f"{base}/papers/{pid}/items/{item_id}", json={"status": "cleared"}, headers=H)
        assert bad.json()["code"] == "decision_reason_required"
        for it in detail["items"]:
            ok = api.put(f"{base}/papers/{pid}/items/{it['id']}", json={"status": "confirmed", "reviewer_note": "Seen"}, headers=H)
            assert ok.json() == {"ok": True}
        assert api.post(f"{base}/papers/{pid}/notes", json={"note": "Follow up"}, headers=H).status_code == 201
        assert api.post(f"{base}/papers/{pid}/review", headers=H).json() == {"ok": True}
        assert api.post(f"{base}/papers/{pid}/reopen", headers=H).json() == {"ok": True}
        api.post(f"{base}/papers/{pid}/review", headers=H)
        assert api.post(f"{base}/papers/{pid}/sign-off", json={"conclusion": ""}, headers=H).json()["code"] == "invalid_conclusion"
        done = api.post(f"{base}/papers/{pid}/sign-off", json={"conclusion": "All three confirmed"}, headers=H)
        assert done.status_code == 200 and done.json()["ok"] is True
        assert api.post(f"{base}/papers/{pid}/notes", json={"note": "late"}, headers=H).json()["code"] == "paper_signed_off"
        assert api.post(f"{base}/papers/{pid}/sample", json={"method": "random", "seed": 7, "size": 1}, headers=H).json()["code"] == "paper_signed_off"
        # pure preview: the same seed gives the same ids; stores nothing
        body = {"ids": [f"v{n:02d}" for n in range(10, 0, -1)], "method": "random", "seed": 42, "size": 3}
        assert api.post(f"{base}/sampling/preview", json=body, headers=H).json() == {"ids": ["v03", "v04", "v05"]}
        val = {"ids": ["a", "b", "c", "d"], "method": "value", "seed": 0, "threshold": "50000.00", "rest_size": 1,
               "amounts": {"a": "80000.00", "b": "49999.99", "c": "50000.00", "d": "10000.00"}}
        assert api.post(f"{base}/sampling/preview", json=val, headers=H).json() == {"ids": ["a", "c", "d"]}
    finally:
        app.dependency_overrides.pop(get_conn, None)
