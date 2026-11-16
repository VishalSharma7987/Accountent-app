"""Internal consistency of the Phase 5 pack docs/test-packs/phase5-fresh-pharma-apr-2026 (no database, no service).

Plain csv / Decimal addition only; the figures asserted here are typed literally (hand-calculated, see WORKING.md).
"""

import csv
from decimal import Decimal as D
from pathlib import Path

from pack_loader_p5 import METHODS, load_pack_p5

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase5-fresh-pharma-apr-2026"
A, B = "Paracetamol 500 strip", "Cough Syrup 100ml"


def rows(name: str, method: str | None = None) -> list[dict]:
    with open(PACK / name, encoding="utf-8", newline="") as f:
        data = list(csv.DictReader(f))
    return [r for r in data if method is None or r["method"] == method]


def reg(method: str, item: str) -> dict:
    return next(r for r in rows("expected_register.csv", method) if r["item_name"] == item)


def test_pack_loads_and_counts():
    pack = load_pack_p5(PACK)
    assert len(pack.vouchers) == 10 and len(pack.journals) == 2 and len(pack.wrong_cases) == 7
    assert len(pack.items) == 3 and pack.godowns == ["Main", "Shop"] and len(pack.nrv) == 2
    assert [v.date for v in pack.vouchers] == sorted(v.date for v in pack.vouchers)
    assert {v.voucher_type for v in pack.vouchers} == {"purchase", "sales", "credit_note", "debit_note"}
    assert set(pack.expected) >= {"expected_register", "expected_closing_stock", "expected_movement_cost"}


def test_every_document_has_an_expected_number():
    pack = load_pack_p5(PACK)
    refs = {v.ref_id for v in pack.vouchers} | {j.ref_id for j in pack.journals}
    assert {r["ref_id"] for r in rows("expected_vouchers.csv")} == refs


def test_register_rows_add_up_and_closing_quantity_is_the_same_in_every_method():
    for method in METHODS:
        for r in rows("expected_register.csv", method):
            assert D(r["opening_qty"]) + D(r["inward_qty"]) - D(r["outward_qty"]) == D(r["closing_qty"]), (method, r["item_name"])
            assert D(r["opening_value"]) + D(r["inward_value"]) - D(r["outward_value"]) == D(r["closing_value"]), (method, r["item_name"])
    assert {m: reg(m, A)["closing_qty"] for m in METHODS} == {m: "80.000" for m in METHODS}
    assert {m: reg(m, B)["closing_qty"] for m in METHODS} == {m: "26.000" for m in METHODS}


def test_the_three_methods_give_different_closing_values_typed_by_hand():
    assert [reg(m, A)["closing_value"] for m in METHODS] == ["1175.00", "980.00", "1024.00"]
    assert [reg(m, B)["closing_value"] for m in METHODS] == ["1560.00", "1443.00", "1475.50"]
    assert {t["method"]: t["closing_value"] for t in rows("expected_register_totals.csv")} == {
        "fifo": "3735.00", "wa_periodic": "3423.00", "wa_moving": "3499.50"}


def test_register_totals_are_the_sum_of_the_item_rows():
    for t in rows("expected_register_totals.csv"):
        mine = rows("expected_register.csv", t["method"])
        for col in ("opening_value", "inward_value", "outward_value", "closing_value"):
            assert sum(D(r[col]) for r in mine) == D(t[col]), (t["method"], col)


def test_periodic_closing_is_pool_less_net_outward_at_the_average():
    assert D(reg("wa_periodic", A)["closing_value"]) == D(4900) - D(320) * D("12.25")  # pool 4,900.00 over 400, 330 sold less 10 back
    assert D(reg("wa_periodic", B)["closing_value"]) == D(26) * D("55.50")  # pool 8,325.00 over 150
    assert D(reg("fifo", A)["inward_value"]) == D(2400) + D(1500) + D(125)  # purchases plus the return at the cost of the sale
    assert D(reg("wa_moving", A)["inward_value"]) == D(2400) + D(1500) + D(128)


def test_closing_stock_is_lower_of_cost_and_nrv_item_by_item():
    for r in rows("expected_closing_stock.csv"):
        if r["nrv_per_unit"]:
            nrv_value = D(r["closing_qty"]) * D(r["nrv_per_unit"])
            assert D(r["nrv_value"]) == nrv_value, (r["method"], r["item_name"])
            assert D(r["write_down"]) == max(D(0), D(r["cost_value"]) - nrv_value), (r["method"], r["item_name"])
        else:
            assert (r["nrv_value"], r["write_down"]) == ("", "0.00") and r["cost_value"] == r["carrying_value"]
        assert D(r["cost_value"]) - D(r["write_down"]) == D(r["carrying_value"])
        assert r["cost_value"] == reg(r["method"], r["item_name"])["closing_value"]
    for t in rows("expected_closing_totals.csv"):
        mine = rows("expected_closing_stock.csv", t["method"])
        for col in ("cost_value", "write_down", "carrying_value"):
            assert sum(D(r[col]) for r in mine) == D(t[col]), (t["method"], col)
    assert {t["method"]: t["write_down"] for t in rows("expected_closing_totals.csv")} == {
        "fifo": "265.00", "wa_periodic": "13.00", "wa_moving": "45.50"}


def test_movement_costs_tie_to_the_register():
    """Outward costs (sale, write-off, purchase return) add up to the register outward value; in the periodic register the sales
    return is less outward instead of an inward."""
    for method in METHODS:
        for item in (A, B):
            mine = [r for r in rows("expected_movement_cost.csv", method) if r["item_name"] == item]
            out = sum(D(r["value"]) for r in mine if r["kind"] in ("sale", "write_off", "purchase_return"))
            inward = sum(D(r["value"]) for r in mine if r["kind"] == "purchase")
            returned = sum(D(r["value"]) for r in mine if r["kind"] == "sales_return")
            if method == "wa_periodic":
                out -= returned
            else:
                inward += returned
            expected = reg(method, item)
            assert (out, inward) == (D(expected["outward_value"]), D(expected["inward_value"])), (method, item)
    assert all(r["value"] == "0.00" for r in rows("expected_movement_cost.csv") if r["kind"].startswith("transfer"))


def test_transfer_keeps_the_quantity_and_by_godown_adds_up_to_the_closing_quantity():
    by: dict[str, D] = {}
    for r in rows("expected_by_godown.csv"):
        by[r["item_name"]] = by.get(r["item_name"], D(0)) + D(r["closing_qty"])
    assert by == {A: D(80), B: D(26), "Vitamin C 500 strip": D(10)}
    transfer = [r for r in rows("expected_movement_cost.csv", "fifo") if r["ref_id"] == "T-1"]
    assert sorted((r["kind"], r["quantity"]) for r in transfer) == [("transfer_in", "20.000"), ("transfer_out", "20.000")]


def test_returns_are_valued_at_the_original_cost_literally():
    cost = {(r["method"], r["ref_id"]): D(r["value"]) for r in rows("expected_movement_cost.csv")}
    assert cost[("fifo", "CN-A")] == D("2250.00") * 10 / 180  # 125.00
    assert cost[("wa_moving", "CN-A")] == D("2304.00") * 10 / 180  # 128.00
    assert cost[("wa_periodic", "CN-A")] == D("12.25") * 10  # 122.50
    assert all(cost[(m, "DN-B")] == D("275.00") for m in METHODS)  # 5 x 55.00 of purchase P-B1


def test_wrong_cases_name_the_rule():
    wrong = load_pack_p5(PACK).wrong_cases
    assert [w["expected_rule"] for w in wrong] == ["S-01", "S-01", "S-01", "G-17", "S-12", "S-10", "S-01"]
