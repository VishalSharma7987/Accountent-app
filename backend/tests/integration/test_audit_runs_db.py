"""Phase 8 package A: audit runs, findings and report through the HTTP API on the mini case (7 posted vouchers).

Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_runs_db.py`.
Check functions are registered here as small fakes (the real checks belong to packages B, C, D); the framework is what is tested:
facts loaded read-only, a failing check isolated, evidence stored, the report, and the books unchanged. Expected values typed literally.
"""

from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine import audit_checks_analytic, audit_checks_books, audit_checks_compliance
from app.engine import audit_types as t
from app.main import app
from app.services import audit_runs

pytestmark = pytest.mark.integration

H = {"X-User": "tester"}
seen: list = []


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _big_vouchers(facts, params, rules):
    """Fake A-12: every voucher of 50,000.00 or more."""
    seen.append(facts)
    hits = [v for v in facts.vouchers_in_period(params) if v.total >= Decimal("50000.00")]
    findings = tuple(
        t.Finding("A-12", f"A-12:{v.id}", t.Severity.INFO, "voucher", v.voucher_number, f"Voucher total {v.total:,.2f}",
                  {"voucher_ids": [v.id], "total": v.total}, subject_id=v.id, finding_date=v.voucher_date, amount=v.total,
                  rule_status="pending" if v.voucher_type == "sales" else None)
        for v in hits)
    return t.CheckResult("A-12", findings, tuple(v.id for v in facts.vouchers), notes=("fake check",))


def _broken(facts, params, rules):
    raise RuntimeError("bad data")


@pytest.fixture
def fakes(monkeypatch):
    seen.clear()
    monkeypatch.setattr(audit_checks_books, "CHECKS", {"A-12": _big_vouchers, "A-13": _broken})
    monkeypatch.setattr(audit_checks_analytic, "CHECKS", {})
    monkeypatch.setattr(audit_checks_compliance, "CHECKS", {})
    # the fakes need no package loader (once B, C, D are merged their real loaders must not run for fake checks)
    monkeypatch.setattr(audit_runs, "_LOADER_MODULES", {k: f"app.services.no_such_{k}" for k in audit_runs._LOADER_MODULES})


def _counts(conn):
    return conn.execute(text("SELECT (SELECT count(*) FROM vouchers), (SELECT count(*) FROM voucher_lines), "
                             "(SELECT md5(string_agg(id::text || status || voucher_date::text, ',' ORDER BY id)) FROM vouchers)")).one()


def test_A00_catalogue_and_rule_table_are_listed_with_their_status(api):
    checks = api.get("/audit/checks").json()
    assert [c["check_id"] for c in checks][:2] == ["A-01", "A-02"] and len(checks) == 18
    rules = api.get("/audit/rules").json()
    assert len(rules) == 6
    receipt_1961 = next(r for r in rules if r["rule_key"] == "cash_receipt_limit" and r["law"] == "it_act_1961")
    assert (receipt_1961["amount"], receipt_1961["breach_when"], receipt_1961["verification_status"]) == ("200000.00", "at_or_above", "secondary_verified")


def test_A00_a_run_stores_findings_with_evidence_and_leaves_the_books_untouched(api, books, svc_conn, fakes):
    b = books[0]
    before = _counts(svc_conn)
    fy = str(b.fy_id)
    r = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={"financial_year_id": fy, "check_ids": ["A-12", "A-13", "A-01"]})
    assert r.status_code == 201
    run = r.json()
    assert run["status"] == "completed" and run["finding_count"] == 2
    by = run["summary"]["by_check"]
    assert by["A-12"] == {"findings": 2, "population": 7, "notes": ["fake check"]}
    assert by["A-13"]["error"] == "check A-13 failed: RuntimeError: bad data"
    assert by["A-01"]["error"] == "check A-01 is not available in this build"
    assert run["summary"]["by_severity"] == {"info": 2}
    # facts: every posted voucher with its lines, ledgers resolved to their system group
    facts = seen[0]
    assert len(facts.vouchers) == 7 and sorted(len(v.lines) for v in facts.vouchers) == [2] * 7
    assert {lf.name: lf.group_code for lf in facts.ledgers.values()}["Cash"] == "cash_in_hand"
    assert {lf.name: lf.group_code for lf in facts.ledgers.values()}["Sharma Suppliers"] == "sundry_creditors"
    # findings, filters
    rid = run["id"]
    found = api.get(f"/clients/{b.client_id}/audit/runs/{rid}/findings").json()
    assert sorted(f["amount"] for f in found) == ["50000.00", "80000.00"]
    assert all(f["evidence"]["voucher_ids"] for f in found) and all(f["check_id"] == "A-12" for f in found)
    sales = next(f for f in found if f["amount"] == "80000.00")
    assert sales["rule_status"] == "pending" and sales["evidence"]["rule"] == {"verification_status": "pending"}
    assert sales["finding_date"] == "2026-04-05" and sales["subject_id"] == sales["evidence"]["voucher_ids"][0]
    assert len(api.get(f"/clients/{b.client_id}/audit/runs/{rid}/findings", params={"check_id": "A-05"}).json()) == 0
    assert len(api.get(f"/clients/{b.client_id}/audit/runs/{rid}/findings", params={"subject_id": sales["subject_id"]}).json()) == 1
    # run list / detail
    assert [x["id"] for x in api.get(f"/clients/{b.client_id}/audit/runs").json()] == [rid]
    detail = api.get(f"/clients/{b.client_id}/audit/runs/{rid}").json()
    assert detail["engine_version"] == "audit-1" and detail["check_ids"] == ["A-01", "A-12", "A-13"]
    assert detail["params"]["duplicate_window_days"] == 7 and detail["rules_used"] == []
    # audit log row
    n = svc_conn.execute(text("SELECT count(*) FROM audit_log WHERE entity = 'audit_run' AND action = 'run' AND actor = 'tester'")).scalar()
    assert n == 1
    assert _counts(svc_conn) == before


def test_A00_report_json_and_excel_show_population_evidence_and_failed_checks(api, books, fakes):
    b = books[0]
    rid = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={"financial_year_id": str(b.fy_id), "check_ids": ["A-12", "A-13"]}).json()["id"]
    rep = api.get(f"/clients/{b.client_id}/audit/runs/{rid}/report").json()
    assert [c["check_id"] for c in rep["checks"]] == ["A-12", "A-13"]
    a12, a13 = rep["checks"]
    assert (a12["title"], a12["population"], len(a12["findings"]), a12["notes"]) == ("Round-amount entries", 7, 2, ["fake check"])
    assert a13["error"] == "check A-13 failed: RuntimeError: bad data"
    assert rep["totals"] == {"findings": 2, "by_severity": {"info": 2}, "disallowance_amount": "0.00"}
    x = api.get(f"/clients/{b.client_id}/audit/runs/{rid}/report", params={"format": "xlsx"})
    assert x.status_code == 200 and "spreadsheetml" in x.headers["content-type"]
    wb = load_workbook(BytesIO(x.content))
    assert wb.sheetnames == ["Summary", "A-12", "A-13"]
    assert wb["A-12"].max_row == 3 and "voucher_ids" in [c.value for c in wb["A-12"][1]]


def test_A00_period_defaults_to_the_year_and_a_period_outside_it_is_refused(api, books, fakes):
    b = books[0]
    ok = api.post(f"/clients/{b.client_id}/audit/runs", headers=H,
                  json={"financial_year_id": str(b.fy_id), "check_ids": ["A-12"], "from_date": "2026-04-10", "to_date": "2026-04-30"}).json()
    assert ok["finding_count"] == 0 and ok["summary"]["by_check"]["A-12"]["population"] == 7   # whole year loaded, the check applies the period
    r = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={"financial_year_id": str(b.fy_id), "to_date": "2027-04-01"})
    assert r.status_code == 422 and r.json()["code"] == "no_period"
    r = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={"financial_year_id": "00000000-0000-0000-0000-000000000001"})
    assert r.status_code == 422 and r.json()["code"] == "no_period"


def test_A00_unknown_check_bad_parameter_and_missing_actor_are_refused_and_nothing_is_stored(api, books, svc_conn, fakes):
    b = books[0]
    body = {"financial_year_id": str(b.fy_id)}
    r = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={**body, "check_ids": ["A-99"]})
    assert r.status_code == 422 and r.json()["code"] == "unknown_check"
    r = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={**body, "check_ids": ["A-12"], "params": {"round_unit": "10.005"}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_params"
    assert api.post(f"/clients/{b.client_id}/audit/runs", json=body).status_code == 400
    assert api.get(f"/clients/{b.client_id}/audit/runs").json() == []


def test_A00_another_clients_run_is_not_visible(api, books, fakes):
    b, other = books
    rid = api.post(f"/clients/{b.client_id}/audit/runs", headers=H, json={"financial_year_id": str(b.fy_id), "check_ids": ["A-12"]}).json()["id"]
    assert api.get(f"/clients/{other.client_id}/audit/runs/{rid}").status_code == 404
    assert api.get(f"/clients/{other.client_id}/audit/runs/{rid}/findings").status_code == 404
    assert api.get(f"/clients/{other.client_id}/audit/runs").json() == []
