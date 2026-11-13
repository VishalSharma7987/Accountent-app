"""AS 2 lower of cost and NRV (S-15) and purchase costing (S-14), by hand."""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.inventory_costing import purchase_cost, unit_cost
from app.engine.inventory_nrv import closing_stock_rows
from app.engine.inventory_types import NrvEntry, RegisterRow
from app.engine.money import MoneyError

D = Decimal
AS_ON = date(2026, 4, 30)


def reg(item, qty, value):
    return RegisterRow(item, D("0"), D("0.00"), D("0"), D("0.00"), D("0"), D("0.00"), D(qty), D(value))


def nrv(item, per_unit, on=AS_ON):
    return NrvEntry(item, on, D(per_unit), "market price list")


def test_S15_write_down_when_nrv_is_below_cost():
    # 70 x 13.50 = 945.00; cost 1,050.00 -> write-down 105.00, carrying 945.00
    rows, errors = closing_stock_rows([reg("I1", "70", "1050.00")], [nrv("I1", "13.50")], AS_ON)
    assert errors == []
    r = rows[0]
    assert (r.nrv_value, r.write_down, r.carrying_value, r.cost_value, r.nrv_per_unit) == (
        D("945.00"), D("105.00"), D("945.00"), D("1050.00"), D("13.50"))


def test_S15_no_write_down_when_nrv_is_above_cost():
    rows, _ = closing_stock_rows([reg("I1", "70", "1050.00")], [nrv("I1", "16.00")], AS_ON)
    assert (rows[0].nrv_value, rows[0].write_down, rows[0].carrying_value) == (D("1120.00"), D("0.00"), D("1050.00"))


def test_S15_item_by_item_never_netted():
    rows, _ = closing_stock_rows([reg("A", "10", "100.00"), reg("B", "10", "100.00")], [nrv("A", "5.00"), nrv("B", "20.00")], AS_ON)
    assert [r.write_down for r in rows] == [D("50.00"), D("0.00")]
    assert sum(r.carrying_value for r in rows) == D("150.00")  # not 100.00: B's gain does not cancel A's loss


def test_S15_missing_nrv_is_a_warning_with_no_write_down():
    rows, errors = closing_stock_rows([reg("I1", "70", "1050.00")], [], AS_ON)
    assert (rows[0].nrv_per_unit, rows[0].nrv_value, rows[0].write_down, rows[0].carrying_value) == (
        None, None, D("0.00"), D("1050.00"))
    assert [(e.rule_id, e.severity, e.item_id) for e in errors] == [("S-15", "warning", "I1")]


def test_S15_nrv_of_another_date_is_not_used():
    rows, errors = closing_stock_rows([reg("I1", "70", "1050.00")], [nrv("I1", "1.00", on=date(2026, 3, 31))], AS_ON)
    assert rows[0].write_down == D("0.00") and errors[0].severity == "warning"


def test_S15_nrv_with_three_decimals_or_negative_is_rejected_and_not_used():
    for bad in ("13.505", "-1.00"):
        rows, errors = closing_stock_rows([reg("I1", "70", "1050.00")], [nrv("I1", bad)], AS_ON)
        assert [(e.rule_id, e.severity) for e in errors] == [("S-15", "error")], bad
        assert rows[0].write_down == D("0.00") and rows[0].nrv_value is None


def test_S15_rounding_half_up_and_zero_stock():
    # 3 x 3.33 = 9.99 against cost 10.00: write-down 0.01. Zero stock needs no NRV and gives no warning.
    rows, errors = closing_stock_rows([reg("I1", "3", "10.00"), reg("I2", "0", "0.00")], [nrv("I1", "3.33")], AS_ON)
    assert (rows[0].nrv_value, rows[0].write_down) == (D("9.99"), D("0.01"))
    assert rows[1].write_down == D("0.00") and errors == []
    rows2, _ = closing_stock_rows([reg("I1", "0.5", "10.00")], [nrv("I1", "0.05")], AS_ON)
    assert rows2[0].nrv_value == D("0.03")  # 0.5 x 0.05 = 0.025 -> 0.03 half up


def test_S14_purchase_cost_excludes_recoverable_gst():
    assert purchase_cost(D("10000.00"), cgst=D("900.00"), sgst=D("900.00")) == D("10000.00")


def test_S14_purchase_cost_includes_gst_and_cess_when_blocked():
    assert purchase_cost(D("10000.00"), cgst=D("900.00"), sgst=D("900.00"), tax_in_cost=True) == D("11800.00")
    assert purchase_cost(D("10000.00"), igst=D("1800.00"), cess=D("100.00"), tax_in_cost=True) == D("11900.00")


def test_S14_purchase_cost_rejects_extra_decimals_and_negatives():
    with pytest.raises(MoneyError):
        purchase_cost(D("10000.005"))
    with pytest.raises(MoneyError):
        purchase_cost(D("100.00"), igst=D("-1.00"), tax_in_cost=True)


def test_S14_unit_cost_four_decimals_half_up():
    assert unit_cost(D("2400.00"), D("200")) == D("12.0000")
    assert unit_cost(D("10.00"), D("3")) == D("3.3333")
    assert unit_cost(D("0.05"), D("3")) == D("0.0167")
