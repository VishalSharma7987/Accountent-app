"""Phase 5 package E against the database: stock register, item ledger, closing stock at lower of cost and NRV, NRV entries
(S-01, S-09, S-13, S-15, S-16) through the API and services. Movements are inserted with raw SQL (packages C and D write
them in real life). Every test runs in a rolled-back transaction. Expected values typed by hand (plan worked example, FIFO):
Widget opening 100 @ 10 = 1,000 in Main; buy 200 = 2,400 into Shop (05-04); sell 150 from Shop (10-04, cost 1,600);
buy 100 = 1,500 into Main (15-04); sell 180 from Main (20-04, cost 2,250); closing 70 = 1,050 (Main 20, Shop 50).
Gadget: opening 10 @ 50 = 500 in Main, no movement."""

import uuid
from io import BytesIO

import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine.inventory_masters import OpeningInput
from app.main import app
from app.services import inventory_masters as masters

pytestmark = pytest.mark.integration

H = {"X-User": "clerk"}


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


class World:
    def __init__(self, svc_conn, mode: str = "block", method: str = "fifo"):
        self.conn = svc_conn
        self.raw = svc_conn.connection.driver_connection
        self.f = Factory(self.raw)
        self.client_id, self.fy_id = self.f.setup()
        c = self.client_id
        self.main = masters.create_godown(svc_conn, c, name="Main", actor="t")
        self.shop = masters.create_godown(svc_conn, c, name="Shop", actor="t")
        self.widget = self.item("Widget", "W-1")
        self.gadget = self.item("Gadget", "G-1")
        masters.put_policy(svc_conn, c, self.fy_id, valuation_method=method, negative_stock_mode=mode, actor="t")
        masters.replace_opening(svc_conn, c, self.fy_id, [OpeningInput(self.widget, self.main, "100", "1000.00"),
                                                         OpeningInput(self.gadget, self.main, "10", "500.00")], actor="t")
        self.reg = uuid.uuid4()
        self.raw.execute("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                         "VALUES (%s, %s, '27AAPFU0939F1ZV', '27', 'regular', '2026-04-01')", (self.reg, c))

    def item(self, name: str, sku: str) -> uuid.UUID:
        item_id = uuid.uuid4()
        self.conn.execute(
            text("INSERT INTO gst_items (id, client_id, name, item_kind, hsn_sac, uqc) VALUES (:i, :c, :n, 'goods', '3004', 'NOS')"),
            {"i": item_id, "c": self.client_id, "n": name})
        masters.put_stock_item(self.conn, self.client_id, item_id, sku=sku, default_godown_id=self.main, actor="t")
        return item_id

    def voucher(self, vtype: str, number: str, lines: list[tuple]):
        """A posted invoice with item lines (item, qty, rate, godown, date) and one stock movement per line."""
        raw, c = self.raw, self.client_id
        vid = self.f.draft(c, self.fy_id, self.f.balanced_lines(c), vtype=vtype)
        raw.execute("INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, "
                    "place_of_supply, invoice_date, invoice_value, engine_version) VALUES (%s, %s, %s, 'tax_invoice', 'b2b', '27', "
                    "'2026-04-05', 100.00, 't')", (vid, c, self.reg))
        ledger = raw.execute("SELECT ledger_id FROM voucher_lines WHERE voucher_id = %s AND line_no = 1", (vid,)).fetchone()[0]
        for n, (item_id, qty, rate, _, _) in enumerate(lines, start=1):
            gross = f"{int(qty) * int(rate)}.00"
            raw.execute("INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, item_id, description, hsn_sac, uqc, "
                        "quantity, unit_rate, gross_amount, taxable_value, ledger_id, treatment, tax_in_cost) "
                        "VALUES (%s, %s, %s, %s, 'x', '3004', 'NOS', %s, %s, %s, %s, %s, 'exempt', false)",
                        (c, vid, n, item_id, qty, f"{rate}.00", gross, gross, ledger))
        self.f.approve(vid)
        self.f.post(vid, number)
        kind = "purchase" if vtype == "purchase" else "sale"
        for n, (item_id, qty, rate, godown, on) in enumerate(lines, start=1):
            gross = f"{int(qty) * int(rate)}.00"
            raw.execute("INSERT INTO stock_movements (client_id, financial_year_id, item_id, godown_id, movement_date, kind, "
                        "direction, quantity, value, voucher_id, item_line_no, created_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 't')",
                        (c, self.fy_id, item_id, godown, on, kind, "in" if kind == "purchase" else "out", qty,
                         gross if kind == "purchase" else None, vid, n))

    def worked_example(self):
        self.voucher("purchase", "PUR/2026-27/0001", [(self.widget, "200", "12", self.shop, "2026-04-05"),
                                                       (self.widget, "100", "15", self.main, "2026-04-15")])
        self.voucher("sales", "SAL/2026-27/0001", [(self.widget, "150", "20", self.shop, "2026-04-10"),
                                                    (self.widget, "180", "20", self.main, "2026-04-20")])

    def url(self, path: str) -> str:
        return f"/clients/{self.client_id}/{path}"

    def audit_count(self, entity: str) -> int:
        return self.conn.execute(text("SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = :e"),
                                 {"c": self.client_id, "e": entity}).scalar_one()


def _by_name(rows: list[dict]) -> dict:
    return {r["name"]: r for r in rows}


def test_S16_register_ledger_and_by_godown_fifo(svc_conn, api):
    w = World(svc_conn)
    w.worked_example()
    fy = {"financial_year_id": str(w.fy_id)}
    body = api.get(w.url("inventory/stock-register"), params=fy).json()
    assert body["policy"]["valuation_method"] == "fifo" and body["errors"] == [] and body["warnings"] == []
    assert (body["from"], body["to"]) == ("2026-04-01", "2027-03-31")
    rows = _by_name(body["rows"])
    widget = rows["Widget"]
    assert [widget[k] for k in ("opening_qty", "opening_value", "inward_qty", "inward_value", "outward_qty", "outward_value",
                                "closing_qty", "closing_value")] == [
        "100.000", "1000.00", "300.000", "3900.00", "330.000", "3850.00", "70.000", "1050.00"]
    assert [(g["godown_name"], g["closing_qty"]) for g in widget["by_godown"]] == [("Main", "20.000"), ("Shop", "50.000")]
    assert (rows["Gadget"]["opening_value"], rows["Gadget"]["closing_value"]) == ("500.00", "500.00")
    assert body["totals"] == {"opening_value": "1500.00", "inward_value": "3900.00", "outward_value": "3850.00",
                              "closing_value": "1550.00"}
    # by godown: quantities only, value columns null
    shop = api.get(w.url("inventory/stock-register"), params={**fy, "godown_id": str(w.shop)}).json()
    (srow,) = shop["rows"]
    assert (srow["name"], srow["opening_qty"], srow["inward_qty"], srow["outward_qty"], srow["closing_qty"]) == (
        "Widget", "0.000", "200.000", "150.000", "50.000")
    assert srow["closing_value"] is None and shop["totals"] is None
    # item ledger with the engine's computed cost (S-13)
    ledger = api.get(w.url(f"stock-items/{w.widget}/ledger"), params=fy).json()
    got = [(r["document_number"], r["kind"], r["in_qty"], r["in_value"], r["out_qty"], r["out_value"], r["balance_qty"],
            r["balance_value"]) for r in ledger["rows"]]
    assert got == [
        ("PUR/2026-27/0001", "purchase", "200.000", "2400.00", "0.000", "0.00", "300.000", "3400.00"),
        ("SAL/2026-27/0001", "sale", "0.000", "0.00", "150.000", "1600.00", "150.000", "1800.00"),
        ("PUR/2026-27/0001", "purchase", "100.000", "1500.00", "0.000", "0.00", "250.000", "3300.00"),
        ("SAL/2026-27/0001", "sale", "0.000", "0.00", "180.000", "2250.00", "70.000", "1050.00"),
    ]
    # a window and an item filter
    win = api.get(w.url("inventory/stock-register"), params={**fy, "from": "2026-04-10", "to": "2026-04-30",
                                                             "item_id": str(w.widget)}).json()
    (wrow,) = win["rows"]
    assert (wrow["opening_qty"], wrow["opening_value"], wrow["closing_value"]) == ("300.000", "3400.00", "1050.00")
    bad = api.get(w.url("inventory/stock-register"), params={**fy, "from": "2026-03-01"})
    assert bad.status_code == 422


def test_S15_closing_stock_lower_of_cost_and_nrv_item_by_item_and_nrv_audit(svc_conn, api):
    w = World(svc_conn)
    w.worked_example()
    fy = {"financial_year_id": str(w.fy_id)}
    # no NRV entered: stock at cost, a warning per item, no write-down (never guessed)
    first = api.get(w.url("inventory/closing-stock"), params=fy).json()
    assert first["as_on"] == "2027-03-31"
    assert sorted(first["items_without_nrv"]) == sorted([str(w.widget), str(w.gadget)])
    assert [e["rule_id"] for e in first["warnings"]] == ["S-15", "S-15"] and first["errors"] == []
    assert "Widget" in " ".join(e["message"] for e in first["warnings"])  # names, not ids
    assert first["totals"] == {"cost_value": "1550.00", "write_down": "0.00", "carrying_value": "1550.00"}
    # NRV: Widget 13.50 (70 x 13.50 = 945.00 < cost 1,050.00), Gadget 60.00 (above cost, no write-down)
    put = api.put(w.url(f"inventory/nrv/{w.fy_id}"), headers=H, json={"as_on_date": "2027-03-31", "rows": [
        {"item_id": str(w.widget), "nrv_per_unit": "13.50", "basis_note": "Market quote"},
        {"item_id": str(w.gadget), "nrv_per_unit": "60.00", "basis_note": "Price list"}]})
    assert put.status_code == 200
    second = api.get(w.url("inventory/closing-stock"), params=fy).json()
    rows = _by_name(second["rows"])
    assert (rows["Widget"]["cost_value"], rows["Widget"]["nrv_value"], rows["Widget"]["write_down"],
            rows["Widget"]["carrying_value"]) == ("1050.00", "945.00", "105.00", "945.00")
    assert (rows["Gadget"]["nrv_value"], rows["Gadget"]["write_down"], rows["Gadget"]["carrying_value"]) == (
        "600.00", "0.00", "500.00")
    assert second["totals"] == {"cost_value": "1550.00", "write_down": "105.00", "carrying_value": "1445.00"}
    assert second["items_without_nrv"] == [] and second["warnings"] == []
    # edit one, delete the other (null NRV), all audited
    api.put(w.url(f"inventory/nrv/{w.fy_id}"), headers=H, json={"as_on_date": "2027-03-31", "rows": [
        {"item_id": str(w.widget), "nrv_per_unit": "16.00", "basis_note": "Revised quote"},
        {"item_id": str(w.gadget), "nrv_per_unit": None}]})
    got = api.get(w.url(f"inventory/nrv/{w.fy_id}"), params={"as_on": "2027-03-31"}).json()["rows"]
    assert [(r["name"], r["nrv_per_unit"], r["basis_note"], r["entered_by"]) for r in got] == [
        ("Widget", "16.00", "Revised quote", "clerk")]
    third = api.get(w.url("inventory/closing-stock"), params=fy).json()
    assert third["totals"] == {"cost_value": "1550.00", "write_down": "0.00", "carrying_value": "1550.00"}
    assert third["items_without_nrv"] == [str(w.gadget)]
    assert w.audit_count("stock_nrv") == 4  # 2 creates, 1 update, 1 delete
    old_new = svc_conn.execute(text("SELECT action, old_data->>'nrv_per_unit', new_data->>'nrv_per_unit' FROM audit_log "
                                    "WHERE client_id = :c AND entity = 'stock_nrv' AND action = 'update'"),
                               {"c": w.client_id}).all()
    assert [tuple(r) for r in old_new] == [("update", "13.50", "16.00")]


def test_S15_nrv_rejects_three_decimals_negative_blank_basis_and_non_stock_items(svc_conn, api):
    w = World(svc_conn)
    url = w.url(f"inventory/nrv/{w.fy_id}")
    for nrv, note, item, rule in (("13.505", "quote", w.widget, "S-15"), ("-1.00", "quote", w.widget, "S-15"),
                                  ("13.50", "  ", w.widget, "S-15"), ("13.50", "quote", uuid.uuid4(), "S-03")):
        r = api.put(url, headers=H, json={"as_on_date": "2027-03-31", "rows": [
            {"item_id": str(item), "nrv_per_unit": nrv, "basis_note": note}]})
        assert r.status_code == 422, (nrv, note)
        assert [e["rule_id"] for e in r.json()["errors"]] == [rule]
    out = api.put(url, headers=H, json={"as_on_date": "2028-03-31", "rows": []})  # outside the year
    assert out.status_code == 422 and out.json()["errors"][0]["rule_id"] == "S-15"
    assert w.audit_count("stock_nrv") == 0


def test_S09_nrv_blocked_when_a_period_of_the_year_is_locked(svc_conn, api):
    w = World(svc_conn)
    period = w.f.period(w.client_id, w.fy_id, "2026-04-01", "2026-04-30")
    w.raw.execute("UPDATE periods SET status = 'locked' WHERE id = %s", (period,))
    r = api.put(w.url(f"inventory/nrv/{w.fy_id}"), headers=H, json={"as_on_date": "2027-03-31", "rows": [
        {"item_id": str(w.widget), "nrv_per_unit": "13.50", "basis_note": "quote"}]})
    assert r.status_code == 422 and r.json()["code"] == "period_locked"
    assert w.audit_count("stock_nrv") == 0


def test_S16_warn_mode_negative_stock_is_reported_with_its_date_and_exports_open(svc_conn, api):
    w = World(svc_conn, mode="warn")
    # Gadget: 10 in hand, sells 25 on 10-04 -> goes to -15
    w.voucher("sales", "SAL/2026-27/0001", [(w.gadget, "25", "60", w.main, "2026-04-10")])
    fy = {"financial_year_id": str(w.fy_id)}
    body = api.get(w.url("inventory/stock-register"), params=fy).json()
    assert [e["rule_id"] for e in body["warnings"]] == ["S-01"]  # the dated finding (warn mode)
    assert body["warnings"][0]["date"] == "2026-04-10" and "Gadget" in body["warnings"][0]["message"]
    assert [e["rule_id"] for e in body["errors"]] == ["S-01"]  # the item cannot be costed, so it is left out
    assert [r["name"] for r in body["rows"]] == ["Widget"]  # Gadget cannot be costed: left out, with the warning above
    # Excel exports carry the method and the as-on date in the header
    reg = api.get(w.url("inventory/stock-register/export"), params=fy)
    assert reg.status_code == 200 and reg.content[:2] == b"PK"
    ws = load_workbook(BytesIO(api.get(w.url("inventory/closing-stock/export"), params=fy).content)).active
    assert ws["B2"].value == "FIFO" and ws["B4"].value == "2027-03-31"
