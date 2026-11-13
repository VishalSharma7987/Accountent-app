"""Inventory masters rules S-02, S-03, S-04, S-07, S-08 (pure engine). Expected values typed by hand."""

from decimal import Decimal

from app.engine.inventory_masters import (
    ItemFacts,
    OpeningInput,
    opening_difference,
    unit_cost,
    validate_opening,
    validate_policy,
    validate_quantity,
    validate_stock_item,
)

I1, I2, G1, G2 = "item-1", "item-2", "godown-1", "godown-2"
ITEMS = {I1: ItemFacts("goods", True), I2: ItemFacts("service", True), "off": ItemFacts("goods", False)}
GODOWNS = {G1: True, G2: True, "closed": False}


def ids(errors):
    return [e.rule_id for e in errors]


def test_S02_quantity_three_decimals_accepted_four_rejected():
    qty, errors = validate_quantity("12.345")
    assert (qty, errors) == (Decimal("12.345"), [])
    qty, errors = validate_quantity("1.0005")
    assert qty is None and ids(errors) == ["S-02"]
    assert "3 decimal" in errors[0].message


def test_S02_negative_and_garbage_quantity_rejected_zero_allowed_for_opening():
    assert ids(validate_quantity("-1")[1]) == ["S-02"]
    assert ids(validate_quantity("abc")[1]) == ["S-02"]
    assert ids(validate_quantity(1.5)[1]) == ["S-02"]  # floats are never accepted
    assert validate_quantity("0") == (Decimal("0.000"), [])
    assert ids(validate_quantity("0", allow_zero=False)[1]) == ["S-02"]


def test_S03_stock_item_must_be_active_goods():
    assert validate_stock_item("W-1", "goods", True, True) == []
    assert ids(validate_stock_item("W-1", "service", True, True)) == ["S-03"]
    assert ids(validate_stock_item("W-1", "goods", False, True)) == ["S-03"]
    assert ids(validate_stock_item("  ", "goods", True, True)) == ["S-03"]


def test_S07_default_godown_must_exist_and_be_active():
    assert ids(validate_stock_item("W-1", "goods", True, None)) == ["S-07"]
    assert ids(validate_stock_item("W-1", "goods", True, False)) == ["S-07"]


def test_S04_policy_values():
    assert validate_policy("fifo", "block") == []
    assert validate_policy("wa_periodic", "warn") == []
    assert validate_policy("wa_moving", "block") == []
    assert ids(validate_policy("lifo", "block")) == ["S-04"]
    assert ids(validate_policy("fifo", "ignore")) == ["S-04"]
    assert ids(validate_policy("", "")) == ["S-04", "S-04"]


def test_S08_valid_opening_rows_become_opening_stock():
    rows, errors = validate_opening(
        [OpeningInput(I1, G1, "100", "1000.00"), OpeningInput(I1, G2, "10.5", "105")], ITEMS, GODOWNS)
    assert errors == []
    assert [(r.item_id, r.godown_id, r.quantity, r.value) for r in rows] == [
        (I1, G1, Decimal("100.000"), Decimal("1000.00")), (I1, G2, Decimal("10.500"), Decimal("105.00"))]


def test_S08_one_row_per_item_and_godown():
    _, errors = validate_opening([OpeningInput(I1, G1, "1", "10"), OpeningInput(I1, G1, "2", "20")], ITEMS, GODOWNS)
    assert ids(errors) == ["S-08"] and errors[0].line_no == 2


def test_S08_value_two_decimals_and_needs_quantity():
    _, errors = validate_opening([OpeningInput(I1, G1, "5", "10.005")], ITEMS, GODOWNS)
    assert ids(errors) == ["S-08"]
    _, errors = validate_opening([OpeningInput(I1, G1, "0", "10.00")], ITEMS, GODOWNS)
    assert ids(errors) == ["S-08"]
    rows, errors = validate_opening([OpeningInput(I1, G1, "0", "0")], ITEMS, GODOWNS)
    assert errors == [] and rows[0].value == Decimal("0.00")


def test_S02_S03_S07_opening_row_errors_carry_the_line_number():
    _, errors = validate_opening([
        OpeningInput(I1, G1, "1.0005", "10"),   # line 1: S-02
        OpeningInput(I2, G1, "1", "10"),        # line 2: service item -> S-03
        OpeningInput("off", G1, "1", "10"),     # line 3: inactive item -> S-03
        OpeningInput("nope", G1, "1", "10"),    # line 4: unknown item -> S-03
        OpeningInput(I1, "closed", "1", "10"),  # line 5: inactive godown -> S-07
        OpeningInput(I1, "ghost", "1", "10"),   # line 6: unknown godown -> S-07
    ], ITEMS, GODOWNS)
    assert [(e.rule_id, e.line_no) for e in errors] == [
        ("S-02", 1), ("S-03", 2), ("S-03", 3), ("S-03", 4), ("S-07", 5), ("S-07", 6)]


def test_S08_difference_against_stock_in_hand_ledger():
    assert opening_difference(Decimal("1000.00"), Decimal("1000.00")) == Decimal("0.00")
    assert opening_difference(Decimal("1050.00"), Decimal("1000.00")) == Decimal("50.00")
    assert opening_difference(Decimal("900.00"), Decimal("1000.00")) == Decimal("-100.00")
    assert opening_difference(Decimal("900.00"), None) is None


def test_S08_unit_cost_four_decimals_half_up():
    assert unit_cost(Decimal(3), Decimal("10.00")) == Decimal("3.3333")
    assert unit_cost(Decimal(8), Decimal("1.00")) == Decimal("0.1250")
    assert unit_cost(Decimal(0), Decimal("0.00")) == Decimal("0.0000")
