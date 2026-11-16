"""Phase 5 package C against the database: stock lines on invoice vouchers (S-01, S-02, S-04, S-05, S-06, S-07, S-12, S-14,
S-17, S-19) through create -> approve -> post -> reverse and the API. One committed world per module, every test in a
rolled-back transaction. Expected values are typed by hand.

World: client with FY 2026-27, FIFO + block policy, godowns Main (default) / Shop / Old (inactive), item Widget (HSN 8415, NOS, 18%).
Purchase: 10 Widgets at 100.00 = taxable 1,000.00 (IGST 180.00 recoverable, so the cost is 1,000.00).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_conn
from app.db import connection, migrate
from app.db import repositories_inventory_movements as repo
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.inventory_voucher import StockLineIn
from app.engine.models import VoucherDraft
from app.main import app
from app.services import client_setup, inventory_masters, vouchers
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

pytestmark = pytest.mark.integration

GSTIN_SELF = "27ABCDE1234F1Z0"
GSTIN_OTHER = "29ABCDE1234F1ZW"
ROLE_LEDGERS = {
    "output_cgst": "Output CGST", "output_sgst": "Output SGST", "output_igst": "Output IGST",
    "input_cgst": "Input CGST", "input_sgst": "Input SGST", "input_igst": "Input IGST",
    "rcm_cgst": "RCM CGST Payable", "rcm_sgst": "RCM SGST Payable", "rcm_igst": "RCM IGST Payable",
}
H = {"X-User": "clerk"}


def d(day: int, month: int = 4) -> date:
    return date(2026, month, day)


@dataclass
class World:
    client_id: object
    fy_id: object
    reg_id: object
    ids: dict
    main: object
    shop: object
    old: object
    widget: object


@pytest.fixture(scope="module")
def world(test_engine, test_conn):
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)
    with test_engine.begin() as conn:
        created = client_setup.create_client(
            conn, ClientProfile("Stock Traders", "proprietorship", "trading", "regular"),
            fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Ramesh Kumar",
        )
        ids = dict(created.ledger_ids)
        for name, group in (("Rahul Enterprises", "sundry_debtors"), ("Sharma Suppliers", "sundry_creditors")):
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, group, actor="setup")
        for name in ROLE_LEDGERS.values():
            ids[name] = client_setup.add_ledger(conn, created.client_id, name, "duties_taxes", actor="setup")
        reg_id = uuid.uuid4()
        conn.execute(
            text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                 "VALUES (:r, :c, :g, '27', 'regular', '2026-04-01')"),
            {"r": reg_id, "c": created.client_id, "g": GSTIN_SELF},
        )
        for role, name in ROLE_LEDGERS.items():
            conn.execute(
                text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                {"r": reg_id, "c": created.client_id, "role": role, "l": ids[name]},
            )
        main = inventory_masters.create_godown(conn, created.client_id, name="Main", actor="setup")
        shop = inventory_masters.create_godown(conn, created.client_id, name="Shop", actor="setup")
        old = inventory_masters.create_godown(conn, created.client_id, name="Old", actor="setup")
        widget = uuid.uuid4()
        conn.execute(
            text("INSERT INTO gst_items (id, client_id, name, item_kind, hsn_sac, uqc) VALUES (:i, :c, 'Widget', 'goods', '8415', 'NOS')"),
            {"i": widget, "c": created.client_id},
        )
        inventory_masters.put_stock_item(conn, created.client_id, widget, sku="W-1", default_godown_id=main, actor="setup")
        inventory_masters.put_policy(conn, created.client_id, created.financial_year_id, valuation_method="fifo",
                                     negative_stock_mode="block", actor="setup")
        inventory_masters.update_godown(conn, created.client_id, old, is_active=False, actor="setup")
        w = World(created.client_id, created.financial_year_id, reg_id, ids, main, shop, old, widget)
    yield w
    connection.clean_test_tables(test_conn)
    migrate.apply_seed_sql(test_conn)


def draft(w, vtype, qty, on, *, rate="100.00", stock=(), ref=None, item=None, uqc="NOS", hsn="8415", extra_items=()):
    """An invoice-mode draft with one Widget line (plus `extra_items`)."""
    ledger = {"sales": "Sales", "purchase": "Purchases", "credit_note": "Sales Returns", "debit_note": "Purchase Returns"}[vtype]
    party = "Rahul Enterprises" if vtype in ("sales", "credit_note") else "Sharma Suppliers"
    line = ItemLineIn("Widget", hsn, D(qty), D(rate), D("0.00"), str(w.ids[ledger]), str(item or w.widget), uqc)
    note = {}
    if vtype in ("credit_note", "debit_note"):
        note = {"original_invoice_no": "INV-1", "original_invoice_date": d(5), "note_reason": "sales_return"}
    inv = InvoiceIn(str(w.reg_id), "tax_invoice", "b2b", "29", on, (line, *extra_items), GSTIN_OTHER, **note)
    reference = ref or (f"B-{uuid.uuid4().hex[:6]}" if vtype in ("purchase", "debit_note") else None)
    return VoucherDraft(w.client_id, vtype, on, f"{vtype} of widgets", reference, w.ids[party], (), gst=inv, stock=tuple(stock))


def post(conn, w, vtype, qty, on, **kw):
    result = vouchers.create_draft(conn, draft(w, vtype, qty, on, **kw), actor="tester")
    assert result.errors == [], result.errors
    vouchers.approve(conn, result.voucher_id, actor="approver")
    vouchers.post(conn, result.voucher_id, actor="poster")
    return result.voucher_id


def movements(conn, w):
    return repo.load_movements(conn, w.client_id, w.fy_id)


def test_S05_S14_S01_purchase_and_sale_write_movements_and_cost_comes_from_the_engine(svc_conn, world):
    buy = post(svc_conn, world, "purchase", "10", d(5))
    (m,) = movements(svc_conn, world)
    # taxable 10 x 100.00 = 1,000.00; IGST 180.00 is recoverable input credit, not cost (S-14)
    assert (m.kind.value, m.quantity, m.value, str(m.godown_id)) == ("purchase", D("10.000"), D("1000.00"), str(world.main))
    part = vouchers.inventory_hooks.load_stock(svc_conn, world.client_id, buy)
    assert [(p["kind"], p["quantity"], p["godown_name"]) for p in part] == [("purchase", "10.000", "Main")]
    assert part[0]["movement_id"] == m.movement_id

    # preview of a sale of 4: FIFO cost 4 x 100.00 = 400.00; 6 left in Main
    from app.services import gst_hooks, inventory_movements
    sale = gst_hooks.expand_invoice(svc_conn, draft(world, "sales", "4", d(10), rate="150.00"))[0]
    check = inventory_movements.preview(svc_conn, sale)
    assert check.errors == []
    assert [(x["kind"], x["quantity"], x["cost"]) for x in check.movements] == [("sale", D("4.000"), D("400.00"))]
    assert [(s["godown_name"], s["quantity"]) for s in check.stock_after] == [("Main", D("6.000"))]

    post(svc_conn, world, "sales", "4", d(10), rate="150.00")
    assert [(x.kind.value, x.quantity) for x in movements(svc_conn, world)] == [("purchase", D("10.000")), ("sale", D("4.000"))]
    # audit: the posting logged its movements
    n = svc_conn.execute(text("SELECT count(*) FROM audit_log WHERE action = 'stock_posted' AND client_id = :c"),
                         {"c": world.client_id}).scalar_one()
    assert n == 2


def test_S01_S19_negative_stock_blocks_approval_a_backdated_sale_re_checks_the_whole_chain(svc_conn, world):
    post(svc_conn, world, "purchase", "10", d(5))
    post(svc_conn, world, "sales", "8", d(20))
    # 11 > 10 on hand: saved as a draft (S-01 is not a save rule), blocked at approval
    over = vouchers.create_draft(svc_conn, draft(world, "sales", "11", d(25)), actor="tester").voucher_id
    with pytest.raises(ServiceError) as e:
        vouchers.approve(svc_conn, over, actor="approver")
    assert e.value.code == "negative_stock"
    assert "Widget" in e.value.message and "Main" in e.value.message
    # backdated: 5 on 10-04 leaves 5; the posted sale of 8 on 20-04 would then go to -3 (S-19)
    back = vouchers.create_draft(svc_conn, draft(world, "sales", "5", d(10)), actor="tester").voucher_id
    with pytest.raises(ServiceError) as e:
        vouchers.approve(svc_conn, back, actor="approver")
    assert e.value.code == "negative_stock" and "20-04-2026" in e.value.message
    # warn mode: the same voucher is allowed, and the preview carries a warning
    svc_conn.execute(text("UPDATE inventory_settings SET negative_stock_mode = 'warn' WHERE client_id = :c"), {"c": world.client_id})
    vouchers.approve(svc_conn, back, actor="approver")
    vouchers.post(svc_conn, back, actor="poster")
    from app.services import gst_hooks, inventory_movements
    check = inventory_movements.preview(svc_conn, gst_hooks.expand_invoice(svc_conn, draft(world, "sales", "1", d(26)))[0])
    assert check.errors == [] and [w.rule_id for w in check.warnings] == ["S-01"]


def test_S04_no_policy_for_the_year_refuses_a_stock_voucher(svc_conn, world):
    svc_conn.execute(text("DELETE FROM inventory_settings WHERE client_id = :c"), {"c": world.client_id})
    result = vouchers.create_draft(svc_conn, draft(world, "purchase", "1", d(5)), actor="tester")
    assert [e.rule_id for e in result.errors] == ["S-04"] and result.voucher_id is None


def test_S06_S07_save_rules_name_the_line_and_save_nothing(svc_conn, world):
    other = [ItemLineIn("Widget", "8415", D(1), D("100.00"), D("0.00"), str(world.ids["Purchases"]), str(world.widget), "KGS"),
             ItemLineIn("Widget", "8415", D(1), D("100.00"), D("0.00"), str(world.ids["Purchases"]), str(world.widget), "NOS")]
    d1 = draft(world, "purchase", "1", d(5), extra_items=other)
    d1 = VoucherDraft(**{**d1.__dict__, "stock": (StockLineIn(3, str(world.old), None),)})
    result = vouchers.create_draft(svc_conn, d1, actor="tester")
    assert sorted((e.rule_id, e.line_no) for e in result.errors) == [("S-06", 2), ("S-07", 3)]
    assert result.voucher_id is None


def test_S12_returns_credit_note_needs_the_original_sale_and_only_what_is_left(svc_conn, world):
    post(svc_conn, world, "purchase", "10", d(5))
    post(svc_conn, world, "sales", "4", d(10), rate="150.00")
    sale_id = next(x for x in movements(svc_conn, world) if x.kind.value == "sale").movement_id

    def note(qty, block):
        return draft(world, "credit_note", qty, d(12), rate="150.00", stock=block)

    # no original named / 5 > 4 sold
    assert [e.rule_id for e in vouchers.create_draft(svc_conn, note("1", [StockLineIn(1)]), actor="t").errors] == ["S-12"]
    assert [e.rule_id for e in vouchers.create_draft(svc_conn, note("5", [StockLineIn(1, None, sale_id)]), actor="t").errors] == ["S-12"]
    # a value-only note (no stock block) is fine and moves nothing
    value_only = post(svc_conn, world, "credit_note", "1", d(12), rate="150.00")
    assert len(movements(svc_conn, world)) == 2 and value_only is not None
    # return of 1 into the Shop godown
    post(svc_conn, world, "credit_note", "1", d(13), rate="150.00", stock=[StockLineIn(1, str(world.shop), sale_id)])
    ret = movements(svc_conn, world)[-1]
    assert (ret.kind.value, ret.quantity, str(ret.godown_id), ret.ref_movement_id) == ("sales_return", D("1.000"), str(world.shop), sale_id)
    rows = repo.returnable(svc_conn, world.client_id, world.widget, None)
    sale_row = next(r for r in rows if r["kind"] == "sale")
    assert (sale_row["quantity"], sale_row["already_returned"], sale_row["returnable"]) == (D("4.000"), D("1.000"), D("3.000"))
    # 4 more cannot be returned: only 3 are left
    again = vouchers.create_draft(svc_conn, note("4", [StockLineIn(1, None, sale_id)]), actor="t")
    assert [e.rule_id for e in again.errors] == ["S-12"]


def test_S17_reversal_mirrors_movements_and_is_blocked_when_stock_would_go_negative(svc_conn, world):
    buy = post(svc_conn, world, "purchase", "10", d(5))
    sale = post(svc_conn, world, "sales", "4", d(10), rate="150.00")
    # reversing the purchase would leave 10 - 4 - 10 = -4: blocked, nothing written
    before = svc_conn.execute(text("SELECT count(*) FROM vouchers WHERE client_id = :c"), {"c": world.client_id}).scalar_one()
    with pytest.raises(VoucherRuleError) as e:
        vouchers.reverse(svc_conn, buy, d(11), "wrong bill", actor="poster")
    assert [x.rule_id for x in e.value.errors] == ["S-17"]
    after = svc_conn.execute(text("SELECT count(*) FROM vouchers WHERE client_id = :c"), {"c": world.client_id}).scalar_one()
    assert after == before and len(movements(svc_conn, world)) == 2
    # reversing the sale puts 4 back (reversal_in, same godown), then the purchase can be reversed
    vouchers.reverse(svc_conn, sale, d(11), "wrong buyer", actor="poster")
    mirror = movements(svc_conn, world)[-1]
    assert (mirror.kind.value, mirror.quantity, str(mirror.godown_id), mirror.date) == ("reversal_in", D("4.000"), str(world.main), d(11))
    # known engine limit (package B): the reversal_in opens a NEW FIFO layer, so the purchase layer stays partly consumed and
    # reversing the purchase is still refused (conservative, never a wrong cost)
    with pytest.raises(VoucherRuleError) as e:
        vouchers.reverse(svc_conn, buy, d(12), "wrong bill", actor="poster")
    assert [x.rule_id for x in e.value.errors] == ["S-17"]
    assert [x.kind.value for x in movements(svc_conn, world)] == ["purchase", "sale", "reversal_in"]


def test_S12_a_sale_with_a_live_return_cannot_be_reversed(svc_conn, world):
    post(svc_conn, world, "purchase", "10", d(5))
    sale = post(svc_conn, world, "sales", "4", d(10), rate="150.00")
    sale_mid = next(x for x in movements(svc_conn, world) if x.kind.value == "sale").movement_id
    post(svc_conn, world, "credit_note", "1", d(12), rate="150.00", stock=[StockLineIn(1, None, sale_mid)])
    with pytest.raises(VoucherRuleError) as e:
        vouchers.reverse(svc_conn, sale, d(13), "x", actor="poster")
    assert [x.rule_id for x in e.value.errors] == ["S-17"] and "reverse that note first" in e.value.errors[0].message


def test_S05_the_api_stock_block_preview_returnable_and_response(svc_conn, world):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    try:
        api = TestClient(app)
        post(svc_conn, world, "purchase", "10", d(5))

        def body(vtype, qty, on, stock=None, ledger="Sales", party="Rahul Enterprises"):
            item = {"item_id": str(world.widget), "description": "Widget", "hsn_sac": "8415", "uqc": "NOS", "quantity": qty,
                    "unit_rate": "150.00", "ledger_id": str(world.ids[ledger])}
            if stock is not None:
                item["stock"] = stock
            return {"voucher_type": vtype, "voucher_date": on, "narration": "api sale", "party_ledger_id": str(world.ids[party]),
                    "gst": {"gst_registration_id": str(world.reg_id), "document_kind": "tax_invoice", "supply_category": "b2b",
                            "place_of_supply": "29", "invoice_date": on, "counterparty_gstin": GSTIN_OTHER, "items": [item]}}

        pre = api.post(f"/clients/{world.client_id}/vouchers/stock-preview", json=body("sales", "4", "2026-04-10"), headers=H)
        assert pre.status_code == 200, pre.text
        j = pre.json()
        assert (j["errors"], j["warnings"]) == ([], [])
        assert [(m["kind"], m["quantity"], m["cost"]) for m in j["movements"]] == [("sale", "4.000", "400.00")]
        over = api.post(f"/clients/{world.client_id}/vouchers/stock-preview", json=body("sales", "11", "2026-04-10"), headers=H).json()
        assert [e["rule_id"] for e in over["errors"]] == ["S-01"] and over["errors"][0]["severity"] == "error"

        created = api.post(f"/clients/{world.client_id}/vouchers", json=body("sales", "4", "2026-04-10", {"godown_id": str(world.shop)}), headers=H)
        assert created.status_code == 201, created.text
        shown = api.get(f"/vouchers/{created.json()['voucher_id']}").json()
        stock = shown["gst"]["items"][0]["stock"]
        assert (stock["godown_name"], stock["kind"], stock["quantity"], stock["movement_id"]) == ("Shop", "sale", "4.000", None)
        # the Shop godown holds nothing: approving is refused (S-01 per godown) with a 422 negative_stock answer
        refused = api.post(f"/vouchers/{created.json()['voucher_id']}/approve", headers=H)
        assert refused.status_code == 422 and refused.json()["code"] == "negative_stock"
        # an untracked line shape: a stock block on a non-stock item is refused at save
        bad = body("sales", "1", "2026-04-10", {})
        bad["gst"]["items"][0]["item_id"] = None
        refused_block = api.post(f"/clients/{world.client_id}/vouchers", json=bad, headers=H)
        assert refused_block.status_code == 422 and refused_block.json()["errors"][0]["rule_id"] == "S-03"
        r = api.get(f"/clients/{world.client_id}/stock-items/{world.widget}/returnable")
        assert [(x["kind"], x["quantity"], x["returnable"]) for x in r.json()] == [("purchase", "10.000", "10.000")]
    finally:
        app.dependency_overrides.clear()
