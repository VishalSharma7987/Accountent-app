"""Phase 8 package B on the real database: the read-only loader (document links, number counters, lock events, holidays) feeding the pure
books checks, and the holiday API. Run once through the lock script:
`C:/temp/Account/scripts/dbrun.sh <venv python> -m pytest -m integration tests/integration/test_audit_books_db.py`.

Each test works inside the rolled-back `svc_conn` transaction. Expected values are typed literally (14-08-2026 is a Friday).
"""

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine import audit_checks_books as b
from app.engine.audit_types import AuditParams, LimitRule
from app.main import app
from app.services import audit_holidays, periods
from app.services.audit_load_books import load_books_facts

pytestmark = pytest.mark.integration

PARAMS = AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31))
LIMIT = LimitRule("cash_payment_daily_limit", "it_act_2025", "s.x", D("10000.00"), "above", D(100), date(2026, 4, 1), None, "pending")


def _paid(f, cid, fy, cash, party, amount, number):
    vid = f.draft(cid, fy, [(party, amount, "0.00"), (cash, "0.00", amount)], vtype="payment", on="2026-08-14")
    f.conn.execute("UPDATE vouchers SET party_ledger_id = %s WHERE id = %s", (party, vid))
    f.approve(vid)
    f.post(vid, number)
    return vid


def test_A01_to_A14_loader_and_checks_on_real_rows(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    cid, fy = f.setup()
    with f.conn.pipeline():
        cash = f.ledger(cid, "Cash", "cash_in_hand")
        sharma = f.ledger(cid, "Sharma Traders", "sundry_creditors")
    v1 = _paid(f, cid, fy, cash, sharma, "6000.00", "PAY/2026-27/0001")
    v3 = _paid(f, cid, fy, cash, sharma, "5000.00", "PAY/2026-27/0003")   # 0002 never existed: a gap
    check_deferred(f.conn)
    f.conn.execute("INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type, last_number) "
                   "VALUES (%s, %s, 'payment', 1)", (cid, fy))
    f.conn.execute("UPDATE voucher_number_sequences SET last_number = 2 WHERE client_id = %s AND voucher_type = 'payment'", (cid,))
    f.conn.execute("UPDATE voucher_number_sequences SET last_number = 3 WHERE client_id = %s AND voucher_type = 'payment'", (cid,))
    period_id = f.period(cid, fy, "2026-08-01", "2026-08-31")
    periods.lock_period(svc_conn, cid, period_id, actor="ca")
    periods.unlock_period(svc_conn, cid, period_id, "late bill", actor="ca")
    audit_holidays.add_holiday(svc_conn, cid, date(2026, 8, 14), "Eve of Independence Day", "client", None, actor="ca")

    facts = load_books_facts(svc_conn, cid, fy)
    assert {str(v.id) for v in facts.vouchers} == {str(v1), str(v3)}
    assert facts.number_counters == {"payment": 3}
    assert facts.holidays == {date(2026, 8, 14): "Eve of Independence Day"}
    assert [(e.action, e.reason) for e in facts.lock_events] == [("lock", None), ("unlock", "late bill")]
    assert facts.document_voucher_ids == frozenset()

    gap = b.CHECKS["A-04"](facts, PARAMS, ())
    assert [x.evidence["missing_numbers"] for x in gap.findings] == [["PAY/2026-27/0002"]]
    cash_f = b.CHECKS["A-05"](facts, PARAMS, (LIMIT,))
    assert [(x.finding_key[:5], x.amount, x.disallowance_amount) for x in cash_f.findings] == [("A-05:", D("11000.00"), D("11000.00"))]
    assert len(b.CHECKS["A-03"](facts, PARAMS, ()).findings) == 2          # no document linked to either payment
    assert len(b.CHECKS["A-13"](facts, PARAMS, ()).findings) == 2          # both on the listed holiday
    assert b.CHECKS["A-14"](facts, PARAMS, ()).findings == ()              # posted before the lock and well inside 30 days

    doc_id = uuid.uuid4()
    f.conn.execute(
        "INSERT INTO documents (id, client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by) "
        "VALUES (%s, %s, 'expense_bill', 'b.pdf', 'application/pdf', 10, %s, %s, 'ca')", (doc_id, cid, "a" * 64, f"c/{doc_id}.pdf"))
    f.conn.execute("INSERT INTO document_vouchers (client_id, document_id, voucher_id, linked_by) VALUES (%s, %s, %s, 'ca')", (cid, doc_id, v1))
    linked = load_books_facts(svc_conn, cid, fy)
    assert linked.document_voucher_ids == frozenset({v1})
    assert [x.subject_id for x in b.CHECKS["A-03"](linked, PARAMS, ()).findings] == [v3]


def test_holiday_api_add_duplicate_sunday_list_delete_and_audit_log(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    cid, _ = f.setup()
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        h = {"X-User": "ca"}
        url = f"/clients/{cid}/audit/holidays"
        created = api.post(url, json={"holiday_date": "2026-10-20", "name": "Dussehra", "kind": "national"}, headers=h)
        assert created.status_code == 201
        again = api.post(url, json={"holiday_date": "2026-10-20", "name": "Dussehra"}, headers=h)
        assert again.status_code == 409 and again.json()["code"] == "duplicate_holiday"
        sunday = api.post(url, json={"holiday_date": "2026-11-22", "name": "Sunday"}, headers=h)
        assert sunday.status_code == 422 and sunday.json()["code"] == "invalid_holiday"
        listed = api.get(url, params={"year": 2026}).json()
        assert [(r["holiday_date"], r["name"], r["kind"]) for r in listed] == [("2026-10-20", "Dussehra", "national")]
        assert api.get(url, params={"year": 2025}).json() == []
        assert api.delete(f"{url}/{created.json()['id']}", headers=h).json() == {"ok": True}
        assert api.get(url).json() == []
        logged = svc_conn.execute(text("SELECT action FROM audit_log WHERE client_id = :c AND entity = 'audit_holiday' ORDER BY id"),
                                  {"c": cid}).scalars().all()
        assert logged == ["create", "delete"]
    finally:
        app.dependency_overrides.pop(get_conn, None)
