"""Phase 5 valuation engine (package B): FIFO, weighted average (periodic, moving), returns, S-01, windows.

Every expected value is typed by hand. Hand check of the plan's worked example (re-derived, not copied):
  Opening 100 @ 10 = 1,000.  05-04 buy 200 = 2,400.  10-04 sell 150.  15-04 buy 100 = 1,500.  20-04 sell 180.
  Total available 1,000 + 2,400 + 1,500 = 4,900; closing qty 100+200-150+100-180 = 70.
  FIFO: sale 1 = 100x10 + 50x12 = 1,000 + 600 = 1,600; sale 2 = 150x12 + 30x15 = 1,800 + 450 = 2,250;
        outward 3,850; closing 70x15 = 1,050 = 4,900 - 3,850.
  WA periodic: 4,900 / 400 = 12.25; outward 330x12.25 = 4,042.50; closing 70x12.25 = 857.50.
  WA moving: after 05-04 3,400/300; sale 150 x 3,400/300 = 1,700; left 150, 1,700. After 15-04 250, 3,200 (12.80);
        sale 180 x 12.80 = 2,304; outward 1,700 + 2,304 = 4,004; closing 70, 4,900 - 4,004 = 896.
  The plan's figures are right.
"""

from datetime import date
from decimal import Decimal

from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    NegativeStockMode,
    OpeningStock,
)
from app.engine.inventory_types import MovementKind as K
from app.engine.inventory_types import ValuationMethod as VM
from app.engine.inventory_valuation import compute_valuation

D = Decimal
FY_START, FY_END = date(2026, 4, 1), date(2027, 3, 31)
_seq = [0]


def mv(movement_id, on, kind, qty, value=None, ref=None, item="I1", godown="G1"):
    _seq[0] += 1
    return Movement(movement_id, _seq[0], on, item, godown, kind, D(qty), None if value is None else D(value), ref)


def opening(qty, value, item="I1", godown="G1"):
    return OpeningStock(item, godown, D(qty), D(value))


def run(method, openings, movements, frm=FY_START, to=FY_END, mode=NegativeStockMode.BLOCK):
    return compute_valuation(InventoryPolicy(method, mode), frm, to, openings, movements)


def cost_of(result, movement_id):
    return next(c.value for c in result.costed if c.movement_id == movement_id)


def april():
    return [
        mv("P1", date(2026, 4, 5), K.PURCHASE, "200", "2400.00"),
        mv("S1", date(2026, 4, 10), K.SALE, "150"),
        mv("P2", date(2026, 4, 15), K.PURCHASE, "100", "1500.00"),
        mv("S2", date(2026, 4, 20), K.SALE, "180"),
    ]


OPEN = [opening("100", "1000.00")]


def only_row(result):
    assert len(result.register) == 1
    return result.register[0]


def test_S01_worked_example_fifo():
    r = run(VM.FIFO, OPEN, april())
    row = only_row(r)
    assert r.errors == []
    assert cost_of(r, "S1") == D("1600.00") and cost_of(r, "S2") == D("2250.00")
    assert (row.opening_qty, row.opening_value) == (D("100"), D("1000.00"))
    assert (row.inward_qty, row.inward_value) == (D("300"), D("3900.00"))
    assert (row.outward_qty, row.outward_value) == (D("330"), D("3850.00"))
    assert (row.closing_qty, row.closing_value) == (D("70"), D("1050.00"))
    assert row.by_godown_qty == {"G1": D("70")}


def test_S01_worked_example_wa_periodic():
    r = run(VM.WA_PERIODIC, OPEN, april())
    row = only_row(r)
    assert (row.outward_qty, row.outward_value) == (D("330"), D("4042.50"))
    assert (row.closing_qty, row.closing_value) == (D("70"), D("857.50"))
    assert cost_of(r, "S1") == D("1837.50") and cost_of(r, "S2") == D("2205.00")  # 150 x 12.25, 180 x 12.25


def test_S01_worked_example_wa_moving():
    r = run(VM.WA_MOVING, OPEN, april())
    row = only_row(r)
    assert cost_of(r, "S1") == D("1700.00") and cost_of(r, "S2") == D("2304.00")
    assert (row.outward_value, row.closing_value, row.closing_qty) == (D("4004.00"), D("896.00"), D("70"))


def test_S01_window_fifo_opening_is_the_state_before_the_window():
    r = run(VM.FIFO, OPEN, april(), frm=date(2026, 4, 10), to=date(2026, 4, 20))
    row = only_row(r)
    # before 10-04: 100 @ 10 + 200 @ 12 = 3,400 on 300 units
    assert (row.opening_qty, row.opening_value) == (D("300"), D("3400.00"))
    assert (row.inward_qty, row.inward_value, row.outward_value, row.closing_value) == (
        D("100"), D("1500.00"), D("3850.00"), D("1050.00"))
    assert {c.movement_id for c in r.costed} == {"S1", "P2", "S2"}


def test_S01_window_wa_periodic_opening_is_one_earlier_period():
    # window 10-04..20-04: opening = 100 + 200 units, 1,000 + 2,400, nothing sold before -> 300 / 3,400; then as April
    r = run(VM.WA_PERIODIC, OPEN, april(), frm=date(2026, 4, 10), to=date(2026, 4, 20))
    row = only_row(r)
    assert (row.opening_qty, row.opening_value) == (D("300"), D("3400.00"))
    assert (row.outward_value, row.closing_value) == (D("4042.50"), D("857.50"))
    # window 15-04..: earlier period 01-04..14-04: pool 300 / 3,400, sold 150 x 3,400/300 = 1,700 -> 150 / 1,700;
    # window pool 250 / 3,200 = 12.80; sold 180 x 12.80 = 2,304; closing 70 / 896
    r2 = run(VM.WA_PERIODIC, OPEN, april(), frm=date(2026, 4, 15))
    row2 = only_row(r2)
    assert (row2.opening_qty, row2.opening_value) == (D("150"), D("1700.00"))
    assert (row2.outward_value, row2.closing_value) == (D("2304.00"), D("896.00"))


def test_S01_window_moving_opening():
    r = run(VM.WA_MOVING, OPEN, april(), frm=date(2026, 4, 11), to=date(2026, 4, 30))
    row = only_row(r)
    assert (row.opening_qty, row.opening_value) == (D("150"), D("1700.00"))  # after the 10-04 sale
    assert (row.closing_qty, row.closing_value) == (D("70"), D("896.00"))


def test_S01_partial_layer_consumption_fifo():
    # 10 @ 10 = 100, buy 10 @ 12 = 120; sell 15 = 10x10 + 5x12 = 160; left 5 @ 12 = 60
    movs = [mv("P", date(2026, 4, 2), K.PURCHASE, "10", "120.00"), mv("S", date(2026, 4, 3), K.SALE, "15")]
    r = run(VM.FIFO, [opening("10", "100.00")], movs)
    assert cost_of(r, "S") == D("160.00")
    assert (only_row(r).closing_qty, only_row(r).closing_value) == (D("5"), D("60.00"))


def test_S01_sales_return_at_original_cost_fifo():
    # 20-04 sale cost 2,250 / 180 = 12.50 per unit; 10 back = 125.00; closing 80 = 1,050 + 125 = 1,175
    movs = [*april(), mv("R1", date(2026, 4, 25), K.SALES_RETURN, "10", ref="S2")]
    r = run(VM.FIFO, OPEN, movs)
    assert cost_of(r, "R1") == D("125.00")
    row = only_row(r)
    assert (row.closing_qty, row.closing_value) == (D("80"), D("1175.00"))
    assert (row.inward_qty, row.inward_value) == (D("310"), D("4025.00"))
    # the returned layer is the newest: selling 75 takes 70 @ 15 then 5 @ 12.50 = 1,050 + 62.50
    r2 = run(VM.FIFO, OPEN, [*movs, mv("S3", date(2026, 4, 26), K.SALE, "75")])
    assert cost_of(r2, "S3") == D("1112.50")
    assert only_row(r2).closing_value == D("62.50")


def test_S01_sales_return_moving_and_periodic():
    movs = [*april(), mv("R1", date(2026, 4, 25), K.SALES_RETURN, "10", ref="S2")]
    rm = run(VM.WA_MOVING, OPEN, movs)
    assert cost_of(rm, "R1") == D("128.00")  # 2,304 / 180 = 12.80 x 10
    assert (only_row(rm).closing_qty, only_row(rm).closing_value) == (D("80"), D("1024.00"))  # 896 + 128
    rp = run(VM.WA_PERIODIC, OPEN, movs)
    # outward qty 330 - 10 = 320 x 12.25 = 3,920.00; closing 80 x 12.25 = 980.00
    row = only_row(rp)
    assert (row.outward_qty, row.outward_value) == (D("320"), D("3920.00"))
    assert (row.closing_qty, row.closing_value) == (D("80"), D("980.00"))


def purchases_100_100():
    return [mv("PA", date(2026, 4, 2), K.PURCHASE, "100", "1100.00"), mv("PB", date(2026, 4, 3), K.PURCHASE, "100", "1300.00")]


def test_S12_purchase_return_valued_at_the_purchase_cost_all_methods():
    # 20 back to bill A at 11.00 = 220.00; closing 180 units, 2,400 - 220 = 2,180
    movs = [*purchases_100_100(), mv("PR", date(2026, 4, 5), K.PURCHASE_RETURN, "20", ref="PA")]
    for method in (VM.FIFO, VM.WA_MOVING, VM.WA_PERIODIC):
        r = run(method, [], movs)
        assert r.errors == [], method
        assert cost_of(r, "PR") == D("220.00"), method
        assert (only_row(r).closing_qty, only_row(r).closing_value) == (D("180"), D("2180.00")), method


def test_S12_fifo_purchase_return_needs_the_layer_to_still_hold_the_quantity():
    # bills A and B of 100 each; 90 sold come from A (oldest), so only 10 of A remain; stock is 110, but 20 cannot go back to A
    movs = [*purchases_100_100(), mv("S", date(2026, 4, 4), K.SALE, "90"),
            mv("PR", date(2026, 4, 5), K.PURCHASE_RETURN, "20", ref="PA")]
    r = run(VM.FIFO, [], movs)
    assert [e.rule_id for e in r.errors] == ["S-12"] and r.errors[0].movement_id == "PR"
    assert r.register == []  # an item that cannot be costed is not shown with a guessed value


def test_S12_return_without_a_reference_or_to_another_item_is_an_error():
    r = run(VM.FIFO, OPEN, [mv("R", date(2026, 4, 5), K.SALES_RETURN, "1")])
    assert [e.rule_id for e in r.errors] == ["S-12"]
    other = [mv("S", date(2026, 4, 4), K.SALE, "5", item="I2"), mv("R", date(2026, 4, 5), K.SALES_RETURN, "1", ref="S")]
    r2 = run(VM.FIFO, [opening("10", "100.00", item="I2"), opening("5", "50.00")], other)
    assert [e.rule_id for e in r2.errors] == ["S-12"]


def test_S17_reversal_mirrors_follow_the_return_rules():
    # reversal of the 20-04 sale: 180 back at 12.50 (FIFO) = 2,250.00; closing 250 = 1,050 + 2,250 = 3,300
    movs = [*april(), mv("RV", date(2026, 4, 21), K.REVERSAL_IN, "180", ref="S2")]
    r = run(VM.FIFO, OPEN, movs)
    assert cost_of(r, "RV") == D("2250.00")
    assert (only_row(r).closing_qty, only_row(r).closing_value) == (D("250"), D("3300.00"))
    # reversal of a purchase (moving): 200 units worth 2,400 removed again; back to the opening 100 / 1,000
    movs2 = [mv("P1", date(2026, 4, 5), K.PURCHASE, "200", "2400.00"), mv("RO", date(2026, 4, 6), K.REVERSAL_OUT, "200", ref="P1")]
    r2 = run(VM.WA_MOVING, OPEN, movs2)
    assert cost_of(r2, "RO") == D("2400.00")
    assert (only_row(r2).closing_qty, only_row(r2).closing_value) == (D("100"), D("1000.00"))


def test_S10_transfer_between_godowns_changes_quantities_never_value():
    opn = [opening("50", "500.00", godown="A")]
    movs = [mv("TO", date(2026, 4, 3), K.TRANSFER_OUT, "20", godown="A"), mv("TI", date(2026, 4, 3), K.TRANSFER_IN, "20", godown="B")]
    for method in (VM.FIFO, VM.WA_MOVING, VM.WA_PERIODIC):
        r = run(method, opn, movs)
        row = only_row(r)
        assert r.errors == []
        assert (row.inward_qty, row.inward_value, row.outward_qty, row.outward_value) == (
            D("0"), D("0.00"), D("0"), D("0.00")), method
        assert (row.closing_qty, row.closing_value) == (D("50"), D("500.00")), method
        assert row.by_godown_qty == {"A": D("30"), "B": D("20")}, method


def test_S10_write_off_takes_cost_out_of_stock():
    movs = [mv("W", date(2026, 4, 3), K.WRITE_OFF, "4")]
    for method in (VM.FIFO, VM.WA_MOVING, VM.WA_PERIODIC):
        r = run(method, [opening("10", "100.00")], movs)
        row = only_row(r)
        assert (row.outward_qty, row.outward_value, row.closing_qty, row.closing_value) == (
            D("4"), D("40.00"), D("6"), D("60.00")), method


def test_S01_negative_stock_blocked_with_a_plain_message():
    r = run(VM.FIFO, OPEN, [mv("S", date(2026, 4, 10), K.SALE, "150")])
    assert [(e.rule_id, e.severity, e.movement_id) for e in r.errors] == [("S-01", "error", "S")]
    assert "-50.000" in r.errors[0].message and "10-04-2026" in r.errors[0].message
    assert r.register == []


def test_S01_backdated_sale_cannot_hide_a_gap():
    # sale 150 on 05-04 with only 100 on hand, purchase of 200 only on 10-04: the gap exists on 05-04
    movs = [mv("P", date(2026, 4, 10), K.PURCHASE, "200", "2400.00"), mv("S", date(2026, 4, 5), K.SALE, "150")]
    r = run(VM.WA_MOVING, OPEN, movs)
    assert [e.rule_id for e in r.errors] == ["S-01"] and r.errors[0].on_date == date(2026, 4, 5)


def test_S01_same_day_order_is_decided_by_seq():
    movs = [Movement("S", 2, date(2026, 4, 5), "I1", "G1", K.SALE, D("150")),
            Movement("P", 1, date(2026, 4, 5), "I1", "G1", K.PURCHASE, D("200"), D("2400.00"))]
    r = run(VM.FIFO, OPEN, movs)
    assert r.errors == [] and only_row(r).closing_qty == D("150")


def test_S01_warn_mode_gives_a_warning_but_the_item_still_cannot_be_valued():
    r = run(VM.FIFO, OPEN, [mv("S", date(2026, 4, 10), K.SALE, "150")], mode=NegativeStockMode.WARN)
    assert [(e.rule_id, e.severity) for e in r.errors] == [("S-01", "warning"), ("S-01", "error")]
    assert r.register == []


def test_S01_one_godown_negative_while_the_item_is_not_is_reported_but_valued_in_warn_mode():
    opn = [opening("100", "1000.00", godown="A")]
    movs = [mv("S", date(2026, 4, 3), K.SALE, "10", godown="B")]
    r = run(VM.FIFO, opn, movs, mode=NegativeStockMode.WARN)
    assert [(e.rule_id, e.severity, e.godown_id) for e in r.errors] == [("S-01", "warning", "B")]
    assert only_row(r).closing_value == D("900.00")
    assert only_row(r).by_godown_qty == {"A": D("100"), "B": D("-10")}
    rb = run(VM.FIFO, opn, movs)
    assert [e.severity for e in rb.errors] == ["error"]


def test_S02_zero_negative_or_four_decimal_quantity_is_rejected():
    for bad in ("0", "-1", "1.0005"):
        r = run(VM.FIFO, OPEN, [mv("S", date(2026, 4, 3), K.SALE, bad)])
        assert [e.rule_id for e in r.errors] == ["S-02"], bad
    ok = run(VM.FIFO, [opening("10.500", "105.00")], [mv("S", date(2026, 4, 3), K.SALE, "0.250")])
    assert only_row(ok).closing_qty == D("10.250") and only_row(ok).closing_value == D("102.50")


def test_S14_a_purchase_without_cost_is_rejected_not_guessed():
    r = run(VM.FIFO, OPEN, [mv("P", date(2026, 4, 3), K.PURCHASE, "5")])
    assert [e.rule_id for e in r.errors] == ["S-14"]


def test_S01_last_unit_takes_the_whole_remaining_value_no_residue():
    # 3 units worth 10.00: 10 x 1/3 = 3.33 (left 6.67 on 2 units); 6.67 / 2 = 3.335 -> 3.34 (left 3.33); last unit 3.33.
    # FIFO (one layer) and moving give the same; total 3.33 + 3.34 + 3.33 = 10.00
    sales = [mv(f"S{i}", date(2026, 4, 2 + i), K.SALE, "1") for i in (1, 2, 3)]
    rf = run(VM.FIFO, [opening("3", "10.00")], sales)
    assert [cost_of(rf, f"S{i}") for i in (1, 2, 3)] == [D("3.33"), D("3.34"), D("3.33")]
    assert only_row(rf).closing_value == D("0.00") and only_row(rf).outward_value == D("10.00")
    rm = run(VM.WA_MOVING, [opening("3", "10.00")], sales)
    assert [cost_of(rm, f"S{i}") for i in (1, 2, 3)] == [D("3.33"), D("3.34"), D("3.33")]
    assert only_row(rm).closing_value == D("0.00")
    rp = run(VM.WA_PERIODIC, [opening("3", "10.00")], sales)
    assert only_row(rp).outward_value == D("10.00") and only_row(rp).closing_value == D("0.00")


def test_S01_rounding_half_up_on_outward_value():
    # 7 units worth 10.00 (1.428571..); sell 3 -> 4.285714 -> 4.29; left 5.71
    r = run(VM.WA_MOVING, [opening("7", "10.00")], [mv("S", date(2026, 4, 3), K.SALE, "3")])
    assert cost_of(r, "S") == D("4.29") and only_row(r).closing_value == D("5.71")
    # 200 units worth 1.00, sell 100 -> 0.50 exactly; 8 units worth 0.05, sell 4 -> 0.025 -> 0.03 (half up)
    r2 = run(VM.WA_PERIODIC, [opening("200", "1.00")], [mv("S", date(2026, 4, 3), K.SALE, "100")])
    assert only_row(r2).outward_value == D("0.50")
    r4 = run(VM.WA_MOVING, [opening("8", "0.05")], [mv("S", date(2026, 4, 3), K.SALE, "4")])
    assert cost_of(r4, "S") == D("0.03")
    r5 = run(VM.WA_PERIODIC, [opening("8", "0.05")], [mv("S", date(2026, 4, 3), K.SALE, "4")])
    assert only_row(r5).outward_value == D("0.03") and only_row(r5).closing_value == D("0.02")


def test_S01_items_are_independent_and_a_failing_item_does_not_hide_the_others():
    opn = [opening("100", "1000.00"), opening("10", "50.00", item="I2")]
    movs = [mv("S", date(2026, 4, 3), K.SALE, "40"), mv("S2", date(2026, 4, 3), K.SALE, "11", item="I2")]
    r = run(VM.FIFO, opn, movs)
    assert [e.item_id for e in r.errors] == ["I2"]
    assert [row.item_id for row in r.register] == ["I1"] and only_row(r).closing_value == D("600.00")


def test_S01_unit_cost_is_for_display_four_decimals():
    r = run(VM.FIFO, [opening("8", "100.00")], [])
    row = only_row(r)
    assert (row.closing_qty, row.closing_value) == (D("8"), D("100.00")) and r.costed == []
    r2 = run(VM.FIFO, [opening("8", "100.00")], [mv("S", date(2026, 4, 3), K.SALE, "3")])
    assert r2.costed[0].unit_cost == D("12.5000") and r2.costed[0].value == D("37.50")


def test_S19_later_gaps_are_reported_even_when_the_window_ends_before_them():
    movs = [mv("S", date(2026, 4, 10), K.SALE, "10"), mv("S9", date(2026, 5, 10), K.SALE, "500")]
    r = run(VM.FIFO, OPEN, movs, to=date(2026, 4, 30))
    assert [e.movement_id for e in r.errors] == ["S9"]
    assert (only_row(r).closing_qty, only_row(r).closing_value) == (D("90"), D("900.00"))  # the window itself is still valued
