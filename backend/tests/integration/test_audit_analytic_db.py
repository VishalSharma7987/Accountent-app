"""Phase 8 package D: loaders for A-15 / A-18 and the related-party flag API on a small synthetic world (rolled back).
Run once through the lock script: `C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_analytic_db.py`.
Expected values are hand-calculated."""

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine import audit_checks_analytic as an
from app.engine.audit_types import AuditParams
from app.main import app
from app.services import audit_load_analytic as load

pytestmark = pytest.mark.integration
H = {"X-User": "tester"}


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def world(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    client = f.client()
    fy_prev, fy_now = f.fy(client, 2025), f.fy(client, 2026)
    sales = f.ledger(client, "Sales", "sales_accounts")
    bank = f.ledger(client, "Bank", "bank_accounts")
    director = f.ledger(client, "Rahul Sharma", "sundry_creditors")
    other_client = f.client()
    foreign = f.ledger(other_client, "Foreign", "sundry_creditors")

    def post(fy, on, dr, cr, amount):
        vid = f.draft(client, fy, [(dr, amount, "0.00"), (cr, "0.00", amount)], on=on)
        f.approve(vid)
        f.post(vid)
        return vid

    post(fy_prev, "2025-06-10", bank, sales, "700000.00")
    post(fy_now, "2026-06-10", bank, sales, "1200000.00")
    v_dir = post(fy_now, "2026-07-01", director, bank, "40000.00")
    v_rev = post(fy_now, "2026-08-01", director, bank, "700.00")
    f.reverse(client, fy_now, v_rev, [(director, "700.00", "0.00"), (bank, "0.00", "700.00")])
    draft = f.draft(client, fy_now, [(director, "999.00", "0.00"), (bank, "0.00", "999.00")], on="2026-09-01")
    check_deferred(f.conn)
    return {"client": client, "sales": sales, "bank": bank, "director": director, "foreign": foreign, "v_dir": v_dir, "draft": draft}


PARAMS = AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31))


def test_A15_loader_totals_this_and_previous_year(svc_conn, world):
    totals = {t.name: t for t in load.load_ledger_totals(svc_conn, world["client"], PARAMS.from_date, PARAMS.to_date)}
    assert totals["Sales"].this_year == D("-1200000.00") and totals["Sales"].previous_year == D("-700000.00")
    assert totals["Sales"].group_code == "sales_accounts"
    assert totals["Bank"].this_year == D("1160000.00") and totals["Bank"].previous_year == D("700000.00")
    assert totals["Rahul Sharma"].this_year == D("40000.00") and totals["Rahul Sharma"].previous_year == D("0.00")  # draft and reversed pair add nothing


def test_A15_end_to_end_finding_for_sales(svc_conn, world):
    facts = load.load_analytic_facts(svc_conn, world["client"], PARAMS)
    res = an.CHECKS["A-15"](facts, PARAMS, ())
    by_name = {f.subject_ref: f for f in res.findings}
    assert by_name["Sales"].evidence["change_percent"] == "71.43" and by_name["Sales"].amount == D("500000.00")
    assert by_name["Sales"].evidence["previous_from"] == "2025-04-01"
    assert "Rahul Sharma" not in by_name   # 40,000.00 change is below the 1,00,000.00 minimum
    assert by_name["Bank"].evidence["change_percent"] == "65.71"   # 4,60,000 / 7,00,000


def test_A18_loader_and_check_ignore_inactive_drafts_and_reversals(api, svc_conn, world):
    c = world["client"]
    assert load.load_analytic_facts(svc_conn, c, PARAMS).vouchers == ()   # nothing flagged yet
    r = api.post(f"/clients/{c}/audit/related-parties", json={"ledger_id": str(world["director"]), "relationship": "Director", "note": "KMP"}, headers=H)
    assert r.status_code == 201
    facts = load.load_analytic_facts(svc_conn, c, PARAMS)
    res = an.CHECKS["A-18"](facts, PARAMS, ())
    assert len(res.findings) == 1
    ev = res.findings[0].evidence
    assert ev["voucher_ids"] == [str(world["v_dir"])] and ev["total_debit"] == "40000.00" and ev["total_credit"] == "0.00"
    assert ev["relationship"] == "Director"


def test_flag_api_create_duplicate_update_list_and_audit_log(api, svc_conn, world):
    c = world["client"]
    base = f"/clients/{c}/audit/related-parties"
    body = {"ledger_id": str(world["director"]), "relationship": "Director"}
    r = api.post(base, json=body, headers=H)
    assert r.status_code == 201
    flag_id = r.json()["id"]
    dup = api.post(base, json=body, headers=H)
    assert dup.status_code == 409 and dup.json()["code"] == "already_flagged"
    assert api.post(base, json={"ledger_id": str(world["foreign"]), "relationship": "X"}, headers=H).status_code == 404
    assert api.post(base, json={"ledger_id": str(world["sales"]), "relationship": "  "}, headers=H).status_code == 422
    assert api.post(base, json=body).status_code == 400   # no X-User
    assert api.put(f"{base}/{flag_id}", json={"active": False, "note": "left the firm"}, headers=H).json() == {"ok": True}
    rows = api.get(base).json()
    assert len(rows) == 1 and rows[0]["ledger_name"] == "Rahul Sharma" and rows[0]["active"] is False and rows[0]["note"] == "left the firm"
    assert api.get(base, params={"active": "true"}).json() == []
    assert api.put(f"{base}/{uuid.uuid4()}", json={"active": True}, headers=H).status_code == 404
    api.put(f"{base}/{flag_id}", json={"active": True}, headers=H)
    actions = [r[0] for r in svc_conn.execute(
        text("SELECT action FROM audit_log WHERE client_id = :c AND entity = 'audit_related_party' ORDER BY id"), {"c": c}).all()]
    assert actions == ["flag", "deactivate", "reactivate"]
    new = svc_conn.execute(text("SELECT new_data FROM audit_log WHERE client_id = :c AND action = 'deactivate'"), {"c": c}).scalar_one()
    assert new["active"] is False and new["relationship"] == "Director"


def test_audit_does_not_change_books(svc_conn, world):
    c = world["client"]
    q = text("SELECT (SELECT count(*) FROM vouchers WHERE client_id = :c), (SELECT count(*) FROM voucher_lines WHERE client_id = :c)")
    before = svc_conn.execute(q, {"c": c}).one()
    load.load_analytic_facts(svc_conn, c, PARAMS)
    assert svc_conn.execute(q, {"c": c}).one() == before
