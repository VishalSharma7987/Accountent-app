"""Phase 8 package C: the read-only loaders (services/audit_load_compliance.py) feeding the compliance checks, against the test schema.

One world (FY 2026-27), hand-calculated:
  v1  Payment 10-08-2026, Dr Raj Contractors (individual, default nature 'contractor') 1,00,000.00 / Cr Cash. No TDS item.
      The contractor rule (individual, 1%, single payment limit 30,000.00) gives 1,00,000.00 x 1% = 1,000.00 -> A-09 for v1.
  v2  Payment 15-08-2026, Dr Mehta Builders (individual) 1,00,000.00 / Cr Cash, with a TDS item of 400.00 on 1,00,000.00 -> computed 1,000.00,
      short by 600.00 -> A-10. That item is due 07-09-2026 (7th of the next month), nothing deposited, as on 01-10-2026: 24 days late -> A-11.
  Cash has no opening: Cr 1,00,000.00 on 10-08 and Cr 2,00,000.00 after 15-08 -> A-16 (first day 10-08-2026, lowest 2,00,000.00, 2 days).
The audit changes nothing: voucher and line counts are the same after the load and the checks.
"""

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from dbfactory import Factory, check_deferred

from app.engine import audit_checks_compliance as c
from app.engine.audit_types import AuditParams
from app.services import audit_load_compliance as load

pytestmark = pytest.mark.integration

ITEM_SQL = (
    "INSERT INTO tds_voucher_items (id, client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
    "financial_year_id, event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, rate_applied, "
    "rate_reason, tds_amount, tds_line_no, engine_version) "
    "VALUES (%s, %s, %s, 1, 'tds', %s, 'contractor', 'it_act_2025', '393(1) Sl.6(i)', %s, %s, %s, 100000.00, 0, 100000.00, 100000.00, 1, "
    "'normal', 400.00, 1, 't')"
)
PARAMS = AuditParams(date(2026, 4, 1), date(2026, 10, 1))


def test_A09_A10_A11_A16_loaders_and_checks_on_one_world_and_the_books_are_unchanged(svc_conn):
    f = Factory(svc_conn.connection.driver_connection)
    client_id, fy_id = f.setup()
    raj = f.ledger(client_id, "Raj Contractors", "sundry_creditors")
    mehta = f.ledger(client_id, "Mehta Builders", "sundry_creditors")
    cash = f.ledger(client_id, "Cash", "cash_in_hand")
    f.conn.execute("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type, default_nature_key) "
                   "VALUES (%s, %s, 'ABCDE1234F', 'valid', 'individual', 'contractor')", (raj, client_id))
    f.conn.execute("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type) "
                   "VALUES (%s, %s, 'ABCDF1234G', 'valid', 'individual')", (mehta, client_id))
    v1 = f.draft(client_id, fy_id, [(raj, "100000.00", "0.00"), (cash, "0.00", "100000.00")], vtype="payment", on="2026-08-10")
    v2 = f.draft(client_id, fy_id, [(mehta, "100000.00", "0.00"), (cash, "0.00", "100000.00")], vtype="payment", on="2026-08-15")
    f.conn.execute(ITEM_SQL, (uuid.uuid4(), client_id, v2, mehta, fy_id, date(2026, 8, 15), date(2026, 8, 15)))
    for v in (v1, v2):
        f.approve(v)
        f.post(v)
    check_deferred(f.conn)

    def counts():
        return svc_conn.exec_driver_sql(
            "SELECT (SELECT count(*) FROM vouchers WHERE client_id = %s), (SELECT count(*) FROM voucher_lines WHERE client_id = %s), "
            "(SELECT count(*) FROM tds_voucher_items WHERE client_id = %s)", (client_id, client_id, client_id)).one()

    before = counts()
    facts = load.load_compliance_facts(svc_conn, client_id, fy_id, PARAMS, today=date(2026, 11, 20))
    assert counts() == before

    # A-17 / A-08 / A-07: no stock, no GST registration, no bills: loaded, nothing to report, said so
    assert facts.stock is not None and facts.stock.movements == () and facts.msme.open_bills == ()
    assert facts.gst == () and "no active regular GST registration" in facts.notes["A-08"][0]

    a09 = c.check_tds_not_deducted(facts, PARAMS)
    assert [(x.subject_id, x.amount) for x in a09.findings] == [(v1, D("1000.00"))]
    e = a09.findings[0].evidence
    assert e["base"] == "100000.00" and e["base_source"] == "party_line" and e["deducted_tax"] == "0.00" and e["voucher_number"].startswith("JRN/")

    a10 = c.check_tds_short_deducted(facts, PARAMS)
    assert [(x.subject_id, x.amount) for x in a10.findings] == [(v2, D("600.00"))]
    assert a10.findings[0].evidence["computed_tax"] == "1000.00" and a10.findings[0].evidence["deducted_tax"] == "400.00"

    a11 = c.check_tds_late_deposit(facts, PARAMS)
    assert len(a11.findings) == 1
    late = a11.findings[0].evidence
    assert late["voucher_id"] == str(v2) and late["due_date"] == "2026-09-07" and late["days_late"] == "24" and late["undeposited"] == "400.00"

    a16 = c.check_negative_cash(facts, PARAMS)
    assert len(a16.findings) == 1
    cash_finding = a16.findings[0]
    assert cash_finding.subject_id == cash and cash_finding.amount == D("200000.00") and cash_finding.finding_date == date(2026, 8, 10)
    assert cash_finding.evidence["negative_day_count"] == "2" and cash_finding.evidence["days"][0]["voucher_ids"] == [str(v1)]

    assert c.check_negative_stock(facts, PARAMS).findings == () and c.check_msme(facts, PARAMS).findings == ()
    assert counts() == before
