"""Phase 6 package F against the database: year-end close and reopen (F-60..F-67). Every test runs in a rolled-back transaction.
Expected values are typed by hand.

Proprietor, FY 2026-27. Opening: Stock 2,00,000 + Cash 3,00,000 = Capital 5,00,000. Posted: purchases 1,00,000, sales 2,50,000, salary 20,000,
drawings 30,000, all in cash (cash 4,00,000). Closing stock 1,50,000 less write-down 10,000 = 1,40,000.
Trading: Dr 2,00,000 + 1,00,000 = 3,00,000; Cr 2,50,000 + 1,40,000 = 3,90,000; gross profit 90,000. Net profit 90,000 - 20,000 = 70,000.
Voucher 1: Dr Sales 2,50,000; Cr Stock 60,000 (1,40,000 - 2,00,000 = -60,000), Purchases 1,00,000, Trading A/c 90,000.
Voucher 2: Dr Trading A/c 90,000; Cr Salary 20,000, P&L A/c 70,000. Voucher 3: Dr P&L 70,000; Cr Drawings 30,000, Capital 40,000.
Carried to FY 2027-28: Dr Stock 1,40,000 + Cash 4,00,000 = 5,40,000; Cr Capital 5,00,000 + 40,000 = 5,40,000.
"""

import datetime

import pytest
from dbfactory import Factory, check_deferred
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.main import app
from app.services import client_setup, final_closing_stock

pytestmark = pytest.mark.integration

H = {"X-User": "clerk"}
CARRIED = sorted([("Capital", "0", "540000"), ("Stock", "140000", "0"), ("Cash", "400000", "0")])


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


class World:
    def __init__(self, svc_conn, stock=True):
        self.conn = svc_conn
        self.raw = svc_conn.connection.driver_connection
        self.f = Factory(self.raw)
        self.c, self.fy = self.f.setup()
        self.n = 0
        for start, end in client_setup._month_periods(datetime.date(2026, 4, 1)):
            self.f.period(self.c, self.fy, start.isoformat(), end.isoformat())
        mk = self.f.ledger
        self.stock, self.cash = mk(self.c, "Stock", "stock_in_hand"), mk(self.c, "Cash", "cash_in_hand")
        self.cap, self.draw = mk(self.c, "Capital", "capital_account"), mk(self.c, "Drawings", "capital_account")
        self.pur, self.sales = mk(self.c, "Purchases", "purchase_accounts"), mk(self.c, "Sales", "sales_accounts")
        self.sal = mk(self.c, "Salary", "indirect_expenses")
        self.tr, self.pl = mk(self.c, "Trading A/c", "reserves_surplus"), mk(self.c, "Profit and Loss A/c", "reserves_surplus")
        for role, ledger in (("stock_ledger", self.stock), ("trading_account", self.tr), ("profit_and_loss", self.pl)):
            self.raw.execute("INSERT INTO final_ledger_roles (client_id, role, ledger_id, set_by) VALUES (%s, %s, %s, 'tester')", (self.c, role, ledger))
        for ledger, side, amount in ((self.stock, "debit", "200000.00"), (self.cash, "debit", "300000.00"), (self.cap, "credit", "500000.00")):
            self.raw.execute(f"INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, {side}) VALUES (%s, %s, %s, %s)",
                             (self.c, ledger, self.fy, amount))
        self.post([(self.pur, "100000.00", "0.00"), (self.cash, "0.00", "100000.00")])
        self.post([(self.cash, "250000.00", "0.00"), (self.sales, "0.00", "250000.00")])
        self.post([(self.sal, "20000.00", "0.00"), (self.cash, "0.00", "20000.00")])
        self.post([(self.draw, "30000.00", "0.00"), (self.cash, "0.00", "30000.00")])
        if stock:
            final_closing_stock.approve_closing_stock(svc_conn, self.c, self.fy, source="manual", as_on_date=datetime.date(2027, 3, 31),
                                                      cost_value="150000.00", write_down="10000.00", basis_note="count", actor="clerk")

    def post(self, lines, on="2026-06-10"):
        self.n += 1
        vid = self.f.draft(self.c, self.fy, lines, on=on)
        self.f.approve(vid)
        self.f.post(vid, number=f"TST/2026-27/{self.n:04d}")
        check_deferred(self.raw)
        return vid

    def scalar(self, sql, **p):
        return self.conn.execute(text(sql), {"c": self.c, **p}).scalar_one()

    def voucher_lines(self, voucher_id):
        rows = self.conn.execute(text("SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
                                      "WHERE vl.voucher_id = :v ORDER BY vl.line_no"), {"v": voucher_id})
        return sorted((r[0], f"{r[1]:.0f}", f"{r[2]:.0f}") for r in rows)

    def openings(self, fy):
        rows = self.conn.execute(text("SELECT l.name, o.debit, o.credit FROM opening_balances o JOIN ledgers l ON l.id = o.ledger_id "
                                      "WHERE o.financial_year_id = :f"), {"f": fy})
        return sorted((r[0], f"{r[1]:.0f}", f"{r[2]:.0f}") for r in rows)


def test_F60_missing_closing_stock_blocks_and_nothing_is_posted(svc_conn, api):
    w = World(svc_conn, stock=False)
    base = f"/clients/{w.c}/final/close"
    chk = api.get(f"{base}/check", params={"financial_year_id": str(w.fy), "create_next_year": "true"}).json()
    assert chk["ready"] is False and "F-41" in [i["rule_id"] for i in chk["items"] if not i["ok"]]
    r = api.post(base, json={"financial_year_id": str(w.fy), "create_next_year": True}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "close_blocked"
    assert w.scalar("SELECT count(*) FROM vouchers WHERE client_id = :c AND voucher_number LIKE 'JRN/%'") == 0
    assert w.scalar("SELECT count(*) FROM year_end_closes WHERE client_id = :c") == 0
    assert w.scalar("SELECT count(*) FROM financial_years WHERE client_id = :c") == 1      # the next year was not created either


def test_F63_F65_F64_close_then_reopen_then_close_again(svc_conn, api):
    w = World(svc_conn)
    base = f"/clients/{w.c}/final/close"
    chk = api.get(f"{base}/check", params={"financial_year_id": str(w.fy), "create_next_year": "true"}).json()
    assert chk["ready"] is True and chk["net_profit"] == "70000.00"
    assert chk["carry_preview"]["total_debit"] == "540000.00" and chk["carry_preview"]["total_credit"] == "540000.00"
    assert api.post(base, json={"financial_year_id": str(w.fy)}, headers=H).json()["code"] == "next_year_missing"

    r = api.post(base, json={"financial_year_id": str(w.fy), "create_next_year": True}, headers=H)
    assert r.status_code == 201, r.text
    body = r.json()
    v = body["voucher_ids"]
    assert body["net_profit"] == "70000.00"
    assert w.voucher_lines(v["trading"]) == sorted([("Sales", "250000", "0"), ("Purchases", "0", "100000"), ("Stock", "0", "60000"),
                                                    ("Trading A/c", "0", "90000")])
    assert w.voucher_lines(v["profit_loss"]) == sorted([("Trading A/c", "90000", "0"), ("Salary", "0", "20000"), ("Profit and Loss A/c", "0", "70000")])
    assert w.voucher_lines(v["appropriation"]) == sorted([("Profit and Loss A/c", "70000", "0"), ("Drawings", "0", "30000"), ("Capital", "0", "40000")])
    numbers = [w.scalar("SELECT voucher_number FROM vouchers WHERE id = :v", v=v[s]) for s in ("trading", "profit_loss", "appropriation")]
    assert numbers == ["JRN/2026-27/0001", "JRN/2026-27/0002", "JRN/2026-27/0003"]
    assert w.scalar("SELECT count(*) FROM periods WHERE client_id = :c AND financial_year_id = :f AND status = 'locked'", f=w.fy) == 12
    assert w.scalar("SELECT count(*) FROM statement_snapshots WHERE client_id = :c AND is_final AND superseded_at IS NULL") == 3
    nxt = w.scalar("SELECT next_financial_year_id FROM year_end_closes WHERE client_id = :c")
    assert w.scalar("SELECT count(*) FROM periods WHERE financial_year_id = :f", f=nxt) == 12
    assert w.openings(nxt) == CARRIED
    # the statements still show the year's trading and profit (F-40)
    tb = api.get(f"/clients/{w.c}/final/trading", params={"financial_year_id": str(w.fy)}).json()
    assert tb["totals"]["gross_profit"] == "90000.00"
    # closed: cannot be closed again, closing vouchers cannot be reversed alone, openings frozen
    assert api.post(base, json={"financial_year_id": str(w.fy), "create_next_year": True}, headers=H).json()["code"] == "already_closed"
    rv = api.post(f"/vouchers/{v['trading']}/reverse", json={"reversal_date": "2027-03-31", "reason": "x"}, headers=H)
    assert rv.status_code == 409 and rv.json()["code"] == "year_end_voucher"
    got = api.get(base, params={"financial_year_id": str(w.fy)}).json()
    assert got["status"] == "closed" and got["net_profit"] == "70000.00"
    with pytest.raises(client_setup.ServiceError) as err:
        client_setup.set_opening_balance(svc_conn, w.c, w.fy, w.cash, "1.00", "0", actor="clerk")
    assert err.value.code == "year_closed"

    # reopen
    close_id = got["close_id"]
    assert api.post(f"{base}/{close_id}/reopen", json={"reason": " "}, headers=H).status_code == 422
    r = api.post(f"{base}/{close_id}/reopen", json={"reason": "late bill found"}, headers=H)
    assert r.status_code == 200 and len(r.json()["reversal_voucher_ids"]) == 3
    assert w.scalar("SELECT count(*) FROM vouchers WHERE client_id = :c AND status = 'reversed'") == 3
    assert w.openings(nxt) == []
    assert w.scalar("SELECT status FROM year_end_closes WHERE client_id = :c") == "reopened"
    assert w.scalar("SELECT count(*) FROM statement_snapshots WHERE client_id = :c AND is_final AND superseded_at IS NULL") == 0
    assert w.scalar("SELECT count(*) FROM periods WHERE client_id = :c AND financial_year_id = :f AND status = 'locked'", f=w.fy) == 0
    assert api.get(f"/clients/{w.c}/final/trading", params={"financial_year_id": str(w.fy)}).json()["totals"]["gross_profit"] == "90000.00"
    assert api.post(f"{base}/{close_id}/reopen", json={"reason": "again"}, headers=H).json()["code"] == "not_closed"
    actions = [x[0] for x in svc_conn.execute(text("SELECT action FROM audit_log WHERE client_id = :c AND entity = 'year_end_close' ORDER BY id"), {"c": w.c})]
    assert actions == ["close", "reopen"]

    # close again: new vouchers, same figures
    r = api.post(base, json={"financial_year_id": str(w.fy)}, headers=H)
    assert r.status_code == 201, r.text
    assert w.openings(nxt) == CARRIED


def test_F64_reopen_is_refused_once_the_next_year_has_a_posted_voucher(svc_conn, api):
    w = World(svc_conn)
    base = f"/clients/{w.c}/final/close"
    r = api.post(base, json={"financial_year_id": str(w.fy), "create_next_year": True}, headers=H)
    assert r.status_code == 201, r.text
    nxt = w.scalar("SELECT next_financial_year_id FROM year_end_closes WHERE client_id = :c")
    vid = w.f.draft(w.c, nxt, [(w.sal, "100.00", "0.00"), (w.cash, "0.00", "100.00")], on="2027-04-10")
    w.f.approve(vid)
    w.f.post(vid, number="TST/2027-28/0001")
    check_deferred(w.raw)
    close_id = api.get(base, params={"financial_year_id": str(w.fy)}).json()["close_id"]
    r = api.post(f"{base}/{close_id}/reopen", json={"reason": "fix"}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "reopen_blocked"
    assert w.scalar("SELECT status FROM year_end_closes WHERE client_id = :c") == "closed"
    assert w.scalar("SELECT count(*) FROM vouchers WHERE client_id = :c AND status = 'reversed'") == 0
