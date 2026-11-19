"""Phase 6 package C against the database: closing stock approval (F-41), ledger positions, Trading A/c, P&L, Balance Sheet and the
partnership appropriation over POSTED vouchers (F-40, F-42, F-43, F-44b, F-62), closing vouchers left out (F-40), company refused (F-47).
Every test runs in a rolled-back transaction. Expected values are typed by hand:

Proprietor, opening: Dr Opening Stock 2,00,000 + Cash 3,00,000 = Cr Capital 5,00,000. Posted: purchases 1,00,000 (cash); sales 2,50,000
(cash); salary 20,000 (cash); a DRAFT rent 999 (never counts). Closing stock cost 1,50,000 less write-down 10,000 = 1,40,000.
Trading: Dr 2,00,000 + 1,00,000 = 3,00,000; Cr 2,50,000 + 1,40,000 = 3,90,000; gross profit 90,000. Net profit 70,000. Cash 4,30,000.
Balance sheet: capital 5,00,000 + 70,000 = 5,70,000 = closing stock 1,40,000 + cash 4,30,000.
Partnership: sales 1,00,000, expenses 40,000, interest on capital 10,000 credited to A. Net before appropriation 60,000; balance 50,000;
A 60% = 30,000, B 40% = 20,000. Balance sheet: A 10,000 + 30,000, B 20,000 = bank 60,000.
"""

import datetime
import uuid

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine.inventory_masters import OpeningInput
from app.main import app
from app.services import final_closing_stock, final_statements
from app.services import inventory_masters as masters
from app.services.errors import ServiceError

pytestmark = pytest.mark.integration

H = {"X-User": "clerk"}


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


class World:
    def __init__(self, svc_conn, entity: str = "proprietorship", business: str = "trading"):
        self.conn = svc_conn
        self.raw = svc_conn.connection.driver_connection
        self.f = Factory(self.raw)
        self.c, self.fy = self.f.setup()
        self.raw.execute("UPDATE clients SET entity_type = %s, business_type = %s WHERE id = %s", (entity, business, self.c))

    def ledger(self, name, group):
        return self.f.ledger(self.c, name, group)

    def opening(self, ledger, debit="0.00", credit="0.00"):
        self.raw.execute("INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) VALUES (%s, %s, %s, %s, %s)",
                         (self.c, ledger, self.fy, debit, credit))

    def post(self, lines, on="2026-06-10"):
        vid = self.f.draft(self.c, self.fy, lines, on=on)
        self.f.approve(vid)
        self.f.post(vid)
        check_deferred(self.raw)
        return vid

    def stock_manual(self, cost="150000.00", wd="10000.00"):
        return final_closing_stock.approve_closing_stock(self.conn, self.c, self.fy, source="manual", as_on_date=datetime.date(2027, 3, 31),
                                                         cost_value=cost, write_down=wd, basis_note="physical count", actor="clerk")

    def proprietor_books(self):
        stock = self.ledger("Opening Stock", "stock_in_hand")
        cash = self.ledger("Cash", "cash_in_hand")
        capital = self.ledger("Capital", "capital_account")
        purchases = self.ledger("Purchases", "purchase_accounts")
        sales = self.ledger("Sales", "sales_accounts")
        salary = self.ledger("Salary", "indirect_expenses")
        rent = self.ledger("Rent", "indirect_expenses")
        self.opening(stock, debit="200000.00")
        self.opening(cash, debit="300000.00")
        self.opening(capital, credit="500000.00")
        self.post([(purchases, "100000.00", "0.00"), (cash, "0.00", "100000.00")])
        self.post([(cash, "250000.00", "0.00"), (sales, "0.00", "250000.00")])
        self.post([(salary, "20000.00", "0.00"), (cash, "0.00", "20000.00")])
        self.f.draft(self.c, self.fy, [(rent, "999.00", "0.00"), (cash, "0.00", "999.00")])
        return {"stock": stock, "cash": cash, "capital": capital, "sales": sales}


def amounts(lines):
    return {x["code"]: x["amount"] for x in lines}


def test_F41_manual_closing_stock_is_approved_audited_and_replaced(svc_conn, api):
    w = World(svc_conn)
    url = f"/clients/{w.c}/final/closing-stock/{w.fy}"
    body = {"source": "manual", "as_on_date": "2027-03-31", "cost_value": "260000.00", "write_down": "10000.00", "basis_note": "count"}
    r = api.put(url, json=body, headers=H)
    assert r.status_code == 200 and r.json() == {"ok": True, "carrying_value": "250000.00"}
    got = api.get(f"/clients/{w.c}/final/closing-stock", params={"financial_year_id": str(w.fy)}).json()
    assert got["approved"]["carrying_value"] == "250000.00" and got["approved"]["approved_by"] == "clerk" and got["proposal"] is None
    assert api.put(url, json={**body, "cost_value": "300000.00"}, headers=H).json()["carrying_value"] == "290000.00"
    actions = [r[0] for r in svc_conn.execute(text("SELECT action FROM audit_log WHERE client_id = :c AND entity = 'final_closing_stock' "
                                                   "ORDER BY id"), {"c": w.c})]
    assert actions == ["approve_closing_stock", "change_closing_stock"]
    # rejected, never rounded or guessed
    assert api.put(url, json={**body, "cost_value": "10.005"}, headers=H).status_code == 422
    assert api.put(url, json={**body, "write_down": "300001.00", "cost_value": "300000.00"}, headers=H).status_code == 422
    missing = api.put(url, json={**body, "basis_note": " "}, headers=H)
    assert missing.status_code == 422 and missing.json()["code"] == "closing_stock_missing"
    assert api.put(url, json={**body, "source": "none"}, headers=H).status_code == 422   # a trading client cannot say 'none'


def test_F41_a_service_client_may_record_no_closing_stock(svc_conn, api):
    w = World(svc_conn, business="service")
    r = api.put(f"/clients/{w.c}/final/closing-stock/{w.fy}", json={"source": "none", "as_on_date": "2027-03-31", "basis_note": "services only"}, headers=H)
    assert r.status_code == 200 and r.json()["carrying_value"] == "0.00"


def test_F41_closing_stock_from_the_inventory_report_is_read_never_typed(svc_conn, api):
    w = World(svc_conn)
    godown = masters.create_godown(svc_conn, w.c, name="Main", actor="t")
    item = uuid.uuid4()
    svc_conn.execute(text("INSERT INTO gst_items (id, client_id, name, item_kind, hsn_sac, uqc) VALUES (:i, :c, 'Widget', 'goods', '3004', 'NOS')"),
                     {"i": item, "c": w.c})
    masters.put_stock_item(svc_conn, w.c, item, sku="W-1", default_godown_id=godown, actor="t")
    masters.put_policy(svc_conn, w.c, w.fy, valuation_method="fifo", negative_stock_mode="block", actor="t")
    masters.replace_opening(svc_conn, w.c, w.fy, [OpeningInput(item, godown, "100", "1000.00")], actor="t")
    url = f"/clients/{w.c}/final/closing-stock/{w.fy}"
    typed = api.put(url, json={"source": "inventory_report", "as_on_date": "2027-03-31", "cost_value": "5.00", "basis_note": "x"}, headers=H)
    assert typed.status_code == 422
    r = api.put(url, json={"source": "inventory_report", "as_on_date": "2027-03-31", "basis_note": "Phase 5 report"}, headers=H)
    assert r.status_code == 200 and r.json()["carrying_value"] == "1000.00"
    got = api.get(f"/clients/{w.c}/final/closing-stock", params={"financial_year_id": str(w.fy)}).json()
    assert got["approved"]["inventory_method"] == "fifo" and got["approved"]["detail"]["rows"][0]["sku"] == "W-1"
    assert got["proposal"]["totals"]["carrying_value"] == "1000.00"


def test_F42_F43_F44b_statements_over_posted_vouchers_only(svc_conn, api):
    w = World(svc_conn)
    ids = w.proprietor_books()
    q = {"financial_year_id": str(w.fy)}
    base = f"/clients/{w.c}/final"
    # before the closing stock is approved: the statements carry the F-41 error and never a guessed figure
    t0 = api.get(f"{base}/trading", params=q).json()
    assert [f["rule_id"] for f in t0["findings"] if f["severity"] == "error"] == ["F-41"]
    assert w.stock_manual()["carrying_value"] == "140000.00"
    t = api.get(f"{base}/trading", params=q).json()
    assert amounts(t["left"])["opening_stock"] == "200000.00" and amounts(t["left"])["gross_profit"] == "90000.00"
    assert amounts(t["right"])["closing_stock"] == "140000.00" and t["totals"]["gross_profit"] == "90000.00" and t["findings"] == []
    sales_line = next(x for x in t["right"] if x["label"] == "Sales")
    assert sales_line["drill"] == [{"ledger_id": str(ids["sales"]), "ledger_name": "Sales", "amount": "250000.00"}]
    p = api.get(f"{base}/profit-loss", params={**q, "format": "vertical"}).json()
    assert p["totals"]["net_profit"] == "70000.00" and amounts(p["left"])["net_profit"] == "70000.00"
    b = api.get(f"{base}/balance-sheet", params=q).json()
    assert amounts(b["left"])["capital"] == "570000.00" and amounts(b["right"])["closing_stock"] == "140000.00"
    assert amounts(b["right"])["cash_in_hand"] == "430000.00" and b["totals"]["total_assets"] == "570000.00" and b["findings"] == []
    v = api.get(f"{base}/balance-sheet", params={**q, "format": "vertical"}).json()
    assert v["totals"]["sources_total"] == "570000.00" and v["totals"]["application_total"] == "570000.00"
    pos = {x["name"]: x for x in api.get(f"{base}/ledger-positions", params=q).json()}
    assert (pos["Cash"]["opening"], pos["Cash"]["debit_total"], pos["Cash"]["credit_total"], pos["Cash"]["closing"]) == \
        ("300000.00", "250000.00", "120000.00", "430000.00")
    # a provisional statement as on an earlier date needs closing stock approved for that date
    early = api.get(f"{base}/trading", params={**q, "as_on": "2026-09-30"}).json()
    assert [f["rule_id"] for f in early["findings"]] == ["F-41"] and "31-03-2027" in early["findings"][0]["message"]
    assert api.get(f"{base}/trading", params={**q, "as_on": "2028-01-01"}).status_code == 422


def test_F40_year_end_closing_vouchers_are_left_out_of_the_statements(svc_conn):
    w = World(svc_conn)
    ids = w.proprietor_books()
    w.stock_manual()
    trading_ac = w.ledger("Trading Account", "reserves_surplus")
    closing = w.post([(ids["sales"], "250000.00", "0.00"), (trading_ac, "0.00", "250000.00")], on="2027-03-31")
    nxt = w.f.fy(w.c, 2027)
    close_id = uuid.uuid4()
    w.raw.execute("INSERT INTO year_end_closes (id, client_id, financial_year_id, next_financial_year_id, status, net_profit, closed_by) "
                  "VALUES (%s, %s, %s, %s, 'closed', 70000.00, 'tester')", (close_id, w.c, w.fy, nxt))
    w.raw.execute("INSERT INTO year_end_close_vouchers (close_id, client_id, step, kind, voucher_id) VALUES (%s, %s, 'trading', 'closing', %s)",
                  (close_id, w.c, closing))
    t = final_statements.trading(svc_conn, w.c, w.fy)
    assert amounts(t["right"])["ledger:" + str(ids["sales"])] == "250000.00" and t["findings"] == []
    pos = {x["name"]: x for x in final_statements.ledger_positions_out(svc_conn, w.c, w.fy)}
    assert pos["Sales"]["closing"] == "-250000.00" and pos["Trading Account"]["closing"] == "0.00"


def test_F47_a_company_is_pointed_to_schedule_III(svc_conn, api):
    w = World(svc_conn, entity="company")
    r = api.get(f"/clients/{w.c}/final/trading", params={"financial_year_id": str(w.fy)})
    assert r.status_code == 422 and r.json()["code"] == "invalid_company_use_sch3"


def test_F43_F62_partnership_appropriation_and_balance_sheet_over_posted_vouchers(svc_conn, api):
    w = World(svc_conn, entity="partnership")
    bank = w.ledger("Bank", "bank_accounts")
    sales = w.ledger("Sales", "sales_accounts")
    exp = w.ledger("Office Expenses", "indirect_expenses")
    ioc = w.ledger("Interest on Capital", "indirect_expenses")
    cap_a = w.ledger("A Capital", "capital_account")
    cap_b = w.ledger("B Capital", "capital_account")
    w.post([(bank, "100000.00", "0.00"), (sales, "0.00", "100000.00")])
    w.post([(exp, "40000.00", "0.00"), (bank, "0.00", "40000.00")])
    w.post([(ioc, "10000.00", "0.00"), (cap_a, "0.00", "10000.00")])
    w.raw.execute("INSERT INTO final_ledger_roles (client_id, role, ledger_id, set_by) VALUES (%s, 'interest_on_capital', %s, 't')", (w.c, ioc))
    pa, pb = uuid.uuid4(), uuid.uuid4()
    for pid, name, cap in ((pa, "A", cap_a), (pb, "B", cap_b)):
        w.raw.execute("INSERT INTO partners (id, client_id, name, capital_ledger_id) VALUES (%s, %s, %s, %s)", (pid, w.c, name, cap))
    q = {"financial_year_id": str(w.fy)}
    base = f"/clients/{w.c}/final"
    w.stock_manual(cost="0.00", wd="0.00")
    # no partner has a share yet: blocked (F-61), the profit stays unallocated and the balance sheet still balances
    none = api.get(f"{base}/appropriation", params=q).json()
    assert [f["rule_id"] for f in none["findings"]] == ["F-61"]
    for pid, share in ((pa, "60.0000"), (pb, "40.0000")):
        w.raw.execute("INSERT INTO partner_fy_terms (partner_id, client_id, financial_year_id, profit_share_percent, set_by) "
                      "VALUES (%s, %s, %s, %s, 't')", (pid, w.c, w.fy, share))
    a = api.get(f"{base}/appropriation", params=q).json()
    assert amounts(a["left"])[f"share:{pa}"] == "30000.00" and amounts(a["left"])[f"share:{pb}"] == "20000.00"
    assert a["totals"] == {"net_profit_before_appropriation": "60000.00", "balance_to_share": "50000.00"} and a["findings"] == []
    p = api.get(f"{base}/profit-loss", params=q).json()
    assert p["totals"]["net_profit"] == "60000.00"
    b = api.get(f"{base}/balance-sheet", params=q).json()
    assert amounts(b["left"])[f"share:{pa}"] == "30000.00" and amounts(b["left"])["total"] == "60000.00"
    assert amounts(b["right"]) == {"bank_accounts": "60000.00", "total": "60000.00"} and b["findings"] == []
    # appropriation exists only for a firm
    w2 = World(svc_conn)
    with pytest.raises(ServiceError) as info:
        final_statements.appropriation(svc_conn, w2.c, w2.fy)
    assert info.value.code == "invalid_not_a_firm"
