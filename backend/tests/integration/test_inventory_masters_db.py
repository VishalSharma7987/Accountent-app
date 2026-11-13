"""Phase 5 package A against the database: godowns, stock items, per-year policy, opening stock (S-02, S-03, S-04, S-07,
S-08, S-09, S-18) through the services and the API. Every test runs in a rolled-back transaction. Expected values typed
literally. Needs migration 0016."""

import uuid
from decimal import Decimal

import pytest
from dbfactory import Factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.engine.inventory_masters import OpeningInput
from app.main import app
from app.services import inventory_masters as svc
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

H = {"X-User": "clerk"}


@pytest.fixture
def f(svc_conn) -> Factory:
    return Factory(svc_conn.connection.driver_connection)


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


class World:
    """A client with FY 2026-27, two godowns and two goods items (Widget, Gadget) plus one service item."""

    def __init__(self, f: Factory, conn):
        self.conn = conn
        self.client_id, self.fy_id = f.setup()
        self.main = svc.create_godown(conn, self.client_id, name="Main", actor="t")
        self.shop = svc.create_godown(conn, self.client_id, name="Shop", actor="t")
        self.widget = self.item("Widget", "goods")
        self.gadget = self.item("Gadget", "goods")
        self.service = self.item("Repairs", "service")

    def item(self, name: str, kind: str) -> uuid.UUID:
        item_id = uuid.uuid4()
        self.conn.execute(
            text("INSERT INTO gst_items (id, client_id, name, item_kind, hsn_sac, uqc) VALUES (:i, :c, :n, :k, :h, :u)"),
            {"i": item_id, "c": self.client_id, "n": name, "k": kind, "h": "9987" if kind == "service" else "3004",
             "u": None if kind == "service" else "NOS"})
        return item_id

    def stock(self, item_id, sku, godown=None):
        svc.put_stock_item(self.conn, self.client_id, item_id, sku=sku, default_godown_id=godown or self.main, actor="t")

    def purchase_movement(self, f: Factory) -> None:
        """A posted purchase of 10 Widgets (120.00) into Main with its stock movement, built with raw SQL (movements are package C's)."""
        raw = f.conn
        reg = uuid.uuid4()
        raw.execute("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                    "VALUES (%s, %s, '27AAPFU0939F1ZV', '27', 'regular', '2026-04-01')", (reg, self.client_id))
        lines = f.balanced_lines(self.client_id)
        vid = f.draft(self.client_id, self.fy_id, lines, vtype="purchase")
        raw.execute("INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, "
                    "place_of_supply, invoice_date, invoice_value, engine_version) VALUES (%s, %s, %s, 'tax_invoice', 'b2b', '27', "
                    "'2026-04-05', 120.00, 't')", (vid, self.client_id, reg))
        raw.execute("INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, item_id, description, hsn_sac, uqc, "
                    "quantity, unit_rate, gross_amount, taxable_value, ledger_id, treatment, tax_in_cost) "
                    "VALUES (%s, %s, 1, %s, 'Widget', '3004', 'NOS', 10, 12.00, 120.00, 120.00, %s, 'exempt', false)",
                    (self.client_id, vid, self.widget, lines[0][0]))
        f.approve(vid)
        f.post(vid)
        raw.execute("INSERT INTO stock_movements (client_id, financial_year_id, item_id, godown_id, movement_date, kind, direction, "
                    "quantity, value, voucher_id, item_line_no, created_by) VALUES (%s, %s, %s, %s, '2026-04-05', 'purchase', 'in', "
                    "10, 120.00, %s, 1, 't')", (self.client_id, self.fy_id, self.widget, self.main, vid))

    def audit_count(self, entity: str) -> int:
        return self.conn.execute(text("SELECT count(*) FROM audit_log WHERE client_id = :c AND entity = :e"),
                                 {"c": self.client_id, "e": entity}).scalar_one()


@pytest.fixture
def w(f, svc_conn) -> World:
    return World(f, svc_conn)


def rule_ids(exc: VoucherRuleError) -> list[str]:
    return [e.rule_id for e in exc.errors]


def test_S07_godown_unique_name_and_audit(w):
    assert [g.name for g in svc.list_godowns(w.conn, w.client_id)] == ["Main", "Shop"]
    with pytest.raises(ServiceError) as exc:
        svc.create_godown(w.conn, w.client_id, name=" main ", actor="t")
    assert exc.value.code == "godown_exists"
    assert w.audit_count("godown") == 2


def test_S18_godown_with_stock_or_default_items_cannot_be_deactivated(w):
    w.stock(w.widget, "W-1", w.main)
    with pytest.raises(ServiceError) as exc:
        svc.update_godown(w.conn, w.client_id, w.main, is_active=False, actor="t")
    assert exc.value.code == "godown_in_use"  # Widget defaults to Main
    svc.update_godown(w.conn, w.client_id, w.shop, is_active=False, actor="t")  # empty and not a default
    svc.update_godown(w.conn, w.client_id, w.shop, is_active=True, name="Shop 2", actor="t")
    svc.replace_opening(w.conn, w.client_id, w.fy_id, [OpeningInput(w.widget, w.shop, "5", "50.00")], actor="t")
    with pytest.raises(ServiceError) as exc:
        svc.update_godown(w.conn, w.client_id, w.shop, is_active=False, actor="t")
    assert exc.value.code == "godown_in_use"  # holds 5 Widgets


def test_S03_only_active_goods_items_become_stock_items_and_sku_is_unique(w):
    with pytest.raises(VoucherRuleError) as exc:
        w.stock(w.service, "S-1")
    assert rule_ids(exc.value) == ["S-03"]
    w.stock(w.widget, "W-1")
    with pytest.raises(ServiceError) as exc2:
        w.stock(w.gadget, "w-1")
    assert exc2.value.code == "sku_exists"
    w.stock(w.widget, "W-1B")  # replace own SKU
    items = svc.list_stock_items(w.conn, w.client_id)
    assert [(i.name, i.sku, i.uqc, i.default_godown_name, i.has_entries) for i in items] == [("Widget", "W-1B", "NOS", "Main", False)]
    assert w.audit_count("stock_item") == 2


def test_S07_default_godown_must_belong_to_the_client(w, f):
    other_client, _ = f.setup()
    foreign = svc.create_godown(w.conn, other_client, name="Foreign", actor="t")
    with pytest.raises(VoucherRuleError) as exc:
        w.stock(w.widget, "W-1", foreign)
    assert rule_ids(exc.value) == ["S-07"]
    with pytest.raises(VoucherRuleError) as exc:
        w.stock(w.widget, "W-1", "not-a-uuid")
    assert rule_ids(exc.value) == ["S-07"]


def test_S04_no_policy_until_set_then_method_cannot_change_with_movements(w, f):
    with pytest.raises(ServiceError) as exc:
        svc.get_policy(w.conn, w.client_id, w.fy_id)
    assert exc.value.code == "no_policy"
    with pytest.raises(VoucherRuleError) as bad:
        svc.put_policy(w.conn, w.client_id, w.fy_id, valuation_method="lifo", negative_stock_mode="block", actor="t")
    assert rule_ids(bad.value) == ["S-04"]
    svc.put_policy(w.conn, w.client_id, w.fy_id, valuation_method="fifo", negative_stock_mode="block", actor="clerk")
    p = svc.get_policy(w.conn, w.client_id, w.fy_id)
    assert (p.valuation_method, p.negative_stock_mode, p.set_by) == ("fifo", "block", "clerk")
    svc.put_policy(w.conn, w.client_id, w.fy_id, valuation_method="fifo", negative_stock_mode="warn", actor="t")  # mode may change
    w.stock(w.widget, "W-1")
    w.purchase_movement(f)
    with pytest.raises(ServiceError) as exc2:
        svc.put_policy(w.conn, w.client_id, w.fy_id, valuation_method="wa_moving", negative_stock_mode="warn", actor="t")
    assert exc2.value.code == "policy_locked"
    with pytest.raises(ServiceError) as exc3:
        svc.update_godown(w.conn, w.client_id, w.main, is_active=False, actor="t")
    assert exc3.value.code == "godown_in_use"  # 10 Widgets in Main by movement
    with pytest.raises(ServiceError) as exc4:
        svc.put_stock_item(w.conn, w.client_id, w.widget, sku="W-1", default_godown_id=w.main, is_active=False, actor="t")
    assert exc4.value.code == "stock_item_in_use"


def test_S04_copy_policy_to_next_year(w, f):
    next_fy = f.fy(w.client_id, 2027)
    svc.put_policy(w.conn, w.client_id, w.fy_id, valuation_method="wa_periodic", negative_stock_mode="block", actor="t")
    svc.copy_policy(w.conn, w.client_id, from_financial_year_id=w.fy_id, to_financial_year_id=next_fy, actor="t")
    assert svc.get_policy(w.conn, w.client_id, next_fy).valuation_method == "wa_periodic"
    with pytest.raises(ServiceError) as exc:
        svc.copy_policy(w.conn, w.client_id, from_financial_year_id=w.fy_id, to_financial_year_id=next_fy, actor="t")
    assert exc.value.code == "policy_exists"
    third = f.fy(w.client_id, 2028)
    with pytest.raises(ServiceError) as exc2:
        svc.copy_policy(w.conn, w.client_id, from_financial_year_id=third, to_financial_year_id=w.fy_id, actor="t")
    assert exc2.value.code == "no_policy"


def test_S08_opening_replace_total_difference_and_audit(w, f):
    w.stock(w.widget, "W-1")
    w.stock(w.gadget, "G-1", w.shop)
    ledger = f.ledger(w.client_id, "Opening Stock", "stock_in_hand")
    assert svc.get_opening(w.conn, w.client_id, w.fy_id).ledger_opening_value == Decimal("0.00")
    w.conn.execute(text("INSERT INTO opening_balances (client_id, financial_year_id, ledger_id, debit, credit) "
                        "VALUES (:c, :fy, :l, 1000.00, 0)"), {"c": w.client_id, "fy": w.fy_id, "l": ledger})
    total = svc.replace_opening(w.conn, w.client_id, w.fy_id, [
        OpeningInput(w.widget, w.main, "100", "1000.00"), OpeningInput(w.widget, w.shop, "10.5", "105.00"),
        OpeningInput(w.gadget, w.shop, "4", "40.00")], actor="t")
    assert total == Decimal("1145.00")
    view = svc.get_opening(w.conn, w.client_id, w.fy_id)
    assert [(r.name, r.godown_name, str(r.quantity), str(r.value)) for r in view.rows] == [
        ("Gadget", "Shop", "4.000", "40.00"), ("Widget", "Main", "100.000", "1000.00"), ("Widget", "Shop", "10.500", "105.00")]
    assert (view.total_value, view.ledger_opening_value, view.difference) == (Decimal("1145.00"), Decimal("1000.00"), Decimal("145.00"))
    # replace: the earlier rows are gone
    assert svc.replace_opening(w.conn, w.client_id, w.fy_id, [OpeningInput(w.gadget, w.shop, "1", "9.99")], actor="t") == Decimal("9.99")
    assert len(svc.get_opening(w.conn, w.client_id, w.fy_id).rows) == 1
    assert w.audit_count("stock_opening") == 2
    items = svc.list_stock_items(w.conn, w.client_id, financial_year_id=w.fy_id)
    assert [(i.name, str(i.opening_qty), str(i.opening_value), i.has_entries) for i in items] == [
        ("Gadget", "1.000", "9.99", True), ("Widget", "0.000", "0.00", False)]


def test_S02_S08_bad_opening_rejects_everything_and_changes_nothing(w):
    w.stock(w.widget, "W-1")
    svc.replace_opening(w.conn, w.client_id, w.fy_id, [OpeningInput(w.widget, w.main, "5", "50.00")], actor="t")
    with pytest.raises(VoucherRuleError) as exc:
        svc.replace_opening(w.conn, w.client_id, w.fy_id, [
            OpeningInput(w.widget, w.main, "1.0005", "10.00"), OpeningInput(w.service, w.main, "1", "1.00"),
            OpeningInput(w.widget, w.shop, "1", "10.005")], actor="t")
    assert [(e.rule_id, e.line_no) for e in exc.value.errors] == [("S-02", 1), ("S-03", 2), ("S-08", 3)]
    assert [str(r.quantity) for r in svc.get_opening(w.conn, w.client_id, w.fy_id).rows] == ["5.000"]


def test_S09_opening_and_policy_blocked_when_a_period_is_locked(w, f):
    w.stock(w.widget, "W-1")
    period = f.period(w.client_id, w.fy_id, "2026-04-01", "2026-04-30")
    w.conn.execute(text("UPDATE periods SET status = 'locked', locked_at = now(), locked_by = 't' WHERE id = :p"), {"p": period})
    with pytest.raises(ServiceError) as exc:
        svc.replace_opening(w.conn, w.client_id, w.fy_id, [OpeningInput(w.widget, w.main, "5", "50.00")], actor="t")
    assert exc.value.code == "period_locked"
    with pytest.raises(ServiceError) as exc2:
        svc.put_policy(w.conn, w.client_id, w.fy_id, valuation_method="fifo", negative_stock_mode="block", actor="t")
    assert exc2.value.code == "period_locked"


def test_S18_unit_of_an_item_with_opening_stock_cannot_change(w):
    w.stock(w.widget, "W-1")
    svc.replace_opening(w.conn, w.client_id, w.fy_id, [OpeningInput(w.widget, w.main, "5", "50.00")], actor="t")
    with pytest.raises(Exception, match="cannot be changed"), w.conn.begin_nested():
        w.conn.execute(text("UPDATE gst_items SET uqc = 'KGS' WHERE id = :i"), {"i": w.widget})


def test_S02_S03_S04_S08_masters_api_round_trip(api, w):
    base = f"/clients/{w.client_id}"
    assert api.post(f"{base}/godowns", json={"name": "Yard"}, headers=H).status_code == 201
    assert api.post(f"{base}/godowns", json={"name": "yard"}, headers=H).json()["code"] == "godown_exists"
    assert api.post(f"{base}/godowns", json={"name": "Z"}).status_code == 400  # X-User missing
    assert [g["name"] for g in api.get(f"{base}/godowns").json()] == ["Main", "Shop", "Yard"]

    body = {"sku": "W-1", "default_godown_id": str(w.main)}
    assert api.put(f"{base}/stock-items/{w.widget}", json=body, headers=H).json() == {"ok": True}
    r = api.put(f"{base}/stock-items/{w.service}", json=body, headers=H)
    assert r.status_code == 422 and r.json()["errors"][0]["rule_id"] == "S-03"
    row = api.get(f"{base}/stock-items", params={"q": "wid", "financial_year_id": str(w.fy_id)}).json()[0]
    assert (row["sku"], row["uqc"], row["opening_qty"], row["opening_value"]) == ("W-1", "NOS", "0.000", "0.00")

    r = api.get(f"{base}/inventory/policy", params={"financial_year_id": str(w.fy_id)})
    assert r.json()["code"] == "no_policy"
    put = api.put(f"{base}/inventory/policy", params={"financial_year_id": str(w.fy_id)}, headers=H,
                  json={"valuation_method": "fifo", "negative_stock_mode": "block"})
    assert put.json() == {"ok": True}
    got = api.get(f"{base}/inventory/policy", params={"financial_year_id": str(w.fy_id)}).json()
    assert (got["valuation_method"], got["negative_stock_mode"], got["set_by"]) == ("fifo", "block", "clerk")

    rows = {"rows": [{"item_id": str(w.widget), "godown_id": str(w.main), "quantity": "3", "value": "10.00"}]}
    put = api.put(f"{base}/inventory/opening/{w.fy_id}", json=rows, headers=H)
    assert put.json() == {"ok": True, "total_value": "10.00"}
    op = api.get(f"{base}/inventory/opening", params={"financial_year_id": str(w.fy_id)}).json()
    assert op["rows"][0]["unit_cost"] == "3.3333" and op["rows"][0]["quantity"] == "3.000"
    assert (op["total_value"], op["ledger_opening_value"], op["difference"]) == ("10.00", None, None)
    rows["rows"][0]["quantity"] = "3.0005"
    bad = api.put(f"{base}/inventory/opening/{w.fy_id}", json=rows, headers=H)
    assert bad.status_code == 422 and bad.json()["errors"][0] == {"rule_id": "S-02", "message": bad.json()["errors"][0]["message"], "line_no": 1}
