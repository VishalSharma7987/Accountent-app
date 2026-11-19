"""Phase 6 package D against the database: Schedule III classification (group defaults, overrides, audit) and the company Balance Sheet
and Statement of Profit and Loss with notes and comparatives (F-44, F-44b, F-45, F-46). One world, one rolled-back transaction.
Expected values are the hand-worked company mini-example of docs/PHASE6_PLAN.md: Balance Sheet total 8,75,000, profit 1,90,000."""

import json
import uuid

import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app

pytestmark = pytest.mark.integration

H = {"X-User": "clerk"}

# name, group, opening (signed), movement (signed; Dr positive) in the year
BOOKS = [
    ("Opening Stock", "stock_in_hand", 200000, 0), ("Purchases", "purchase_accounts", 0, 800000),
    ("Freight", "direct_expenses", 0, 30000), ("Salary", "indirect_expenses", 0, 120000), ("Rent", "indirect_expenses", 0, 65000),
    ("Electricity", "indirect_expenses", 0, 18000), ("Depreciation", "indirect_expenses", 0, 10000),
    ("Bad Debts", "indirect_expenses", 0, 10000), ("Provision Expense", "indirect_expenses", 0, 12000),
    ("Furniture", "fixed_assets", 100000, 0), ("Accumulated Depreciation", "fixed_assets", 0, -10000),
    ("Sundry Debtors", "sundry_debtors", 150000, 90000), ("Provision for Doubtful Debts", "provisions", 0, -12000),
    ("Cash", "cash_in_hand", 30000, -5000), ("Bank", "bank_accounts", 120000, 160000), ("Prepaid Expenses", "current_assets", 0, 2000),
    ("Share Capital", "capital_account", -500000, 0), ("Loan", "loans_liability", -20000, 0),
    ("Sundry Creditors", "sundry_creditors", -80000, -80000), ("Outstanding Expenses", "current_liabilities", 0, -5000),
    ("Sales", "sales_accounts", 0, -1200000), ("Interest Income", "indirect_incomes", 0, -5000),
]
OVERRIDES = {"Salary": "employee_benefits_expense", "Depreciation": "depreciation_amortisation", "Loan": "long_term_borrowings",
             "Prepaid Expenses": "other_current_assets", "Outstanding Expenses": "other_current_liabilities",
             "Provision for Doubtful Debts": "trade_receivables"}


class World:
    def __init__(self, svc_conn):
        self.conn = svc_conn
        raw = svc_conn.connection.driver_connection
        f = Factory(raw)
        self.client_id, self.fy_id = f.setup()
        raw.execute("UPDATE clients SET entity_type = 'company', business_type = 'trading' WHERE id = %s", (self.client_id,))
        self.ids = {}
        with raw.pipeline():
            for name, group, _, _ in BOOKS:
                self.ids[name] = f.ledger(self.client_id, name, group)
        with raw.pipeline():
            for name, _, opening, _ in BOOKS:
                if opening:
                    raw.execute("INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) "
                                "VALUES (%s, %s, %s, %s, %s)", (self.client_id, self.ids[name], self.fy_id,
                                                                 max(opening, 0), max(-opening, 0)))
        lines = [(self.ids[n], f"{max(m, 0)}.00", f"{max(-m, 0)}.00") for n, _, _, m in BOOKS if m]
        vid = f.draft(self.client_id, self.fy_id, lines, narration="Year's entries (test)", on="2026-09-30")
        f.approve(vid)
        f.post(vid)
        raw.execute("SET CONSTRAINTS ALL IMMEDIATE")
        raw.execute("INSERT INTO final_closing_stock (client_id, financial_year_id, as_on_date, source, cost_value, write_down, "
                    "carrying_value, basis_note, approved_by) VALUES (%s, %s, '2027-03-31', 'manual', 260000, 10000, 250000, "
                    "'test: one item at NRV', 'tester')", (self.client_id, self.fy_id))
        self.f, self.raw = f, raw


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def amounts(statement):
    return {ln["code"]: ln["amount"] for ln in statement["left"]}


def test_schedule_iii_company_end_to_end(svc_conn, api):
    w = World(svc_conn)
    base = f"/clients/{w.client_id}/final/sch3"
    fy = f"financial_year_id={w.fy_id}"

    # ---- classification: groups without a safe default are unclassified, non-firm defaults are listed
    cls = api.get(f"{base}/classification?{fy}")
    assert cls.status_code == 200
    body = cls.json()
    by_name = {x["name"]: x for x in body["ledgers"]}
    assert {x["name"] for x in body["ledgers"] if x["ledger_id"] in body["unclassified"]} == {
        "Loan", "Prepaid Expenses", "Outstanding Expenses"}
    assert by_name["Sales"]["source"] == "group_firm" and by_name["Sales"]["line_code"] == "revenue_from_operations"
    assert by_name["Share Capital"]["source"] == "group_default" and by_name["Share Capital"]["ledger_id"] in body["defaults"]
    assert all(r["verification_status"] == "pending" for r in body["lines"])

    # ---- F-44: the statements refuse to guess
    refused = api.get(f"{base}/balance-sheet?{fy}")
    assert refused.status_code == 422 and refused.json()["code"] == "unclassified"
    assert len(refused.json()["details"]["unclassified"]) == 3

    # ---- invalid classifications are rejected before any write
    loan = str(w.ids["Loan"])
    assert api.put(f"{base}/classification", headers=H, json={"rows": [{"ledger_id": loan, "line_code": "revenue_from_operations"}]}
                   ).status_code == 422
    assert api.put(f"{base}/classification", headers=H, json={"rows": [{"ledger_id": loan, "line_code": "nonsense"}]}).status_code == 422
    assert api.put(f"{base}/classification", json={"rows": [{"ledger_id": loan, "line_code": "long_term_borrowings"}]}).status_code == 400

    rows = [{"ledger_id": str(w.ids[n]), "line_code": line, "note": "accountant"} for n, line in OVERRIDES.items()]
    assert api.put(f"{base}/classification", headers=H, json={"rows": rows}).json() == {"ok": True}
    audit = svc_conn.execute(text("SELECT count(*) FROM audit_log WHERE client_id = :c AND action = 'classify' "
                                  "AND entity = 'client_ledger_fs_map'"), {"c": w.client_id}).scalar()
    assert audit == 6

    # the fixed-asset register feeds the PPE note (land-type asset: gross 1,00,000, accumulated 10,000)
    asset_id = uuid.uuid4()
    w.raw.execute("INSERT INTO fixed_assets (id, client_id, asset_no, name, asset_ledger_id, is_depreciable, created_by) "
                  "VALUES (%s, %s, 'FA-1', 'Furniture lot', %s, false, 'tester')", (asset_id, w.client_id, w.ids["Furniture"]))
    w.raw.execute("INSERT INTO fixed_asset_events (client_id, asset_id, kind, event_date, put_to_use_date, amount, accumulated_dep_bf, "
                  "created_by) VALUES (%s, %s, 'opening', '2026-04-01', '2026-04-01', 100000, 10000, 'tester')",
                  (w.client_id, asset_id))

    # ---- previous year: snapshot of the Balance Sheet only; the P&L is recomputed from the previous year's own data
    prev_fy = w.f.fy(w.client_id, 2025)
    w.raw.execute("INSERT INTO final_closing_stock (client_id, financial_year_id, as_on_date, source, cost_value, write_down, "
                  "carrying_value, basis_note, approved_by) VALUES (%s, %s, '2026-03-31', 'none', 0, 0, 0, 'test: nil', 'tester')",
                  (w.client_id, prev_fy))
    w.raw.execute("INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) VALUES (%s, %s, %s, 10000, 0), "
                  "(%s, %s, %s, 0, 10000)", (w.client_id, w.ids["Cash"], prev_fy, w.client_id, w.ids["Share Capital"], prev_fy))
    payload = {"left": [{"code": "ppe", "label": "PPE", "amount": "100000.00"}, {"code": "total_assets", "label": "T", "amount": "700000.00"}]}
    w.raw.execute("INSERT INTO statement_snapshots (client_id, financial_year_id, statement_key, format_key, payload, payload_sha256, "
                  "engine_version, is_final, generated_by) VALUES (%s, %s, 'balance_sheet', 'sch3', %s::jsonb, %s, 'fin-1', true, 'tester')",
                  (w.client_id, prev_fy, json.dumps(payload), "0" * 64))

    # ---- Balance Sheet
    bs_resp = api.get(f"{base}/balance-sheet?{fy}")
    assert bs_resp.status_code == 200
    bs = bs_resp.json()
    a = amounts(bs)
    assert (a["share_capital"], a["reserves_surplus"], a["long_term_borrowings"], a["trade_payables"],
            a["other_current_liabilities"], a["total_equity_liabilities"]) == (
        "500000.00", "190000.00", "20000.00", "160000.00", "5000.00", "875000.00")
    assert (a["ppe"], a["inventories"], a["trade_receivables"], a["cash_and_cash_equivalents"], a["other_current_assets"],
            a["total_assets"]) == ("90000.00", "250000.00", "228000.00", "305000.00", "2000.00", "875000.00")
    assert bs["totals"]["difference"] == "0.00"
    assert bs["previous_source"] == "snapshot"
    prev = {ln["code"]: ln["previous_amount"] for ln in bs["left"]}
    assert prev["ppe"] == "100000.00" and prev["total_assets"] == "700000.00" and prev["inventories"] == "0.00"
    assert not [f for f in bs["findings"] if f["severity"] == "error"]
    assert not [f for f in bs["findings"] if f["rule_id"] in ("F-45", "F-46")]
    assert bs["rule_status_summary"] == "pending" and bs["engine_version"] == "fin-1"
    assert {r["verification_status"] for r in bs["rule_status"]} == {"pending"}
    assert {r["table"] for r in bs["rule_status"]} == {"fs_lines", "fs_group_map"}
    assert bs["basis"] == {"closing_stock_method": None, "closing_stock_source": "manual", "entity_type": "company", "format": "sch3"}
    ppe_note = next(n for n in bs["notes"] if n["title"] == "Property, plant and equipment")
    assert {ln["code"]: ln["amount"] for ln in ppe_note["lines"]}["ppe_net_block"] == "90000.00"
    cash_note = next(n for n in bs["notes"] if n["note_no"] == 9)
    assert [(ln["label"], ln["amount"]) for ln in cash_note["lines"]] == [
        ("Bank", "280000.00"), ("Cash", "25000.00"), ("Total (Cash and cash equivalents)", "305000.00")]
    drill = next(ln for ln in bs["left"] if ln["code"] == "trade_receivables")["drill"]
    assert {d["ledger_name"]: d["amount"] for d in drill} == {
        "Sundry Debtors": "240000.00", "Provision for Doubtful Debts": "-12000.00"}

    # ---- Statement of Profit and Loss
    pl = api.get(f"{base}/profit-loss?{fy}").json()
    p = amounts(pl)
    assert (p["revenue_from_operations"], p["other_income"], p["purchases_stock_in_trade"], p["changes_in_inventories"],
            p["employee_benefits_expense"], p["depreciation_amortisation"], p["other_expenses"], p["total_expenses"],
            p["profit_before_tax"]) == ("1200000.00", "5000.00", "800000.00", "-50000.00", "120000.00", "10000.00",
                                        "135000.00", "1015000.00", "190000.00")
    assert pl["previous_source"] == "recomputed"
    assert {ln["code"]: ln["previous_amount"] for ln in pl["left"]}["revenue_from_operations"] == "0.00"

    notes = api.get(f"{base}/notes?{fy}").json()
    assert [n["note_no"] for n in notes["notes"]][:3] == [1, 2, 3] and "rule_status" in notes

    # ---- a provisional date needs its own closing stock approval (F-41), and a bad date is refused
    early = api.get(f"{base}/balance-sheet?{fy}&as_on=2026-09-30").json()
    assert [f["rule_id"] for f in early["findings"] if f["severity"] == "error"] == ["F-41"]
    assert api.get(f"{base}/balance-sheet?{fy}&as_on=2028-01-01").status_code == 422

    # ---- removing an override puts the ledger back on the group default (here: none -> unclassified again)
    assert api.put(f"{base}/classification", headers=H, json={"rows": [{"ledger_id": loan}]}).json() == {"ok": True}
    assert api.get(f"{base}/balance-sheet?{fy}").status_code == 422

    # ---- only companies
    w.raw.execute("UPDATE clients SET entity_type = 'partnership' WHERE id = %s", (w.client_id,))
    other = api.get(f"{base}/balance-sheet?{fy}")
    assert other.status_code == 409 and other.json()["code"] == "not_company"
