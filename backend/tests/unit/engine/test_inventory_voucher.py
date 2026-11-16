"""Phase 5 package C engine: which invoice item lines move stock and the save-time rules S-02, S-03, S-06, S-07, S-12.

Expected values are typed by hand. Ids are plain strings (the engine only compares them)."""

from decimal import Decimal as D

from app.engine.inventory_types import MovementKind as K
from app.engine.inventory_voucher import (
    ItemFacts,
    LineFacts,
    OriginalFacts,
    StockLineIn,
    plan_stock,
)

WIDGET = ItemFacts("Widget", True, True, "NOS", "3004", "G-MAIN")
GODOWNS = {"G-MAIN": True, "G-SHOP": True, "G-OLD": False}


def line(n=1, item="I1", qty="10", uqc="NOS", hsn="3004", taxable="1200.00", cgst="0.00", sgst="0.00", igst="0.00", cess="0.00",
         in_cost=False):
    return LineFacts(n, item, D(qty), uqc, hsn, D(taxable), D(cgst), D(sgst), D(igst), D(cess), in_cost)


def plan(vtype, lines, stock=(), items=None, godowns=GODOWNS, originals=None):
    return plan_stock(vtype, lines, {s.item_line_no: s for s in stock}, items if items is not None else {"I1": WIDGET},
                      godowns, originals or {})


def rules(p):
    return sorted((e.rule_id, e.line_no) for e in p.errors)


def test_S03_a_sale_of_a_stock_item_moves_stock_from_the_default_godown():
    p = plan("sales", [line(qty="4.500")])
    assert p.errors == []
    assert [(m.item_line_no, m.godown_id, m.kind, m.quantity, m.value) for m in p.movements] == [
        (1, "G-MAIN", K.SALE, D("4.500"), None)]


def test_S03_a_line_of_an_untracked_item_or_a_service_moves_nothing():
    p = plan("sales", [line(item="OTHER"), line(2, item=None)])
    assert (p.errors, p.movements) == ([], [])


def test_S03_a_stock_block_on_a_line_that_is_not_a_stock_item_is_refused():
    p = plan("sales", [line(item="OTHER")], stock=[StockLineIn(1, "G-SHOP", None)])
    assert rules(p) == [("S-03", 1)]


def test_S03_an_inactive_stock_item_or_inactive_gst_item_cannot_move_stock():
    assert rules(plan("sales", [line()], items={"I1": ItemFacts("Widget", False, True, "NOS", "3004", "G-MAIN")})) == [("S-03", 1)]
    assert rules(plan("sales", [line()], items={"I1": ItemFacts("Widget", True, False, "NOS", "3004", "G-MAIN")})) == [("S-03", 1)]


def test_S02_a_fourth_decimal_in_the_quantity_is_rejected_not_rounded():
    assert rules(plan("sales", [line(qty="1.0005")])) == [("S-02", 1)]


def test_S02_quantity_must_be_above_zero():
    assert rules(plan("sales", [line(qty="0")])) == [("S-02", 1)]


def test_S06_unit_and_hsn_must_equal_the_items():
    assert rules(plan("sales", [line(uqc="KGS")])) == [("S-06", 1)]
    assert rules(plan("sales", [line(hsn="3005")])) == [("S-06", 1)]
    assert rules(plan("sales", [line(uqc=None)])) == [("S-06", 1)]


def test_S07_godown_override_must_exist_and_be_active():
    assert plan("sales", [line()], stock=[StockLineIn(1, "G-SHOP", None)]).movements[0].godown_id == "G-SHOP"
    assert rules(plan("sales", [line()], stock=[StockLineIn(1, "G-OLD", None)])) == [("S-07", 1)]
    assert rules(plan("sales", [line()], stock=[StockLineIn(1, "G-NONE", None)])) == [("S-07", 1)]


def test_S14_purchase_cost_is_taxable_value_plus_tax_only_when_it_is_part_of_the_cost():
    # 1,200.00 taxable; CGST 108.00 + SGST 108.00 recoverable -> cost 1,200.00
    p = plan("purchase", [line(cgst="108.00", sgst="108.00")])
    assert [(m.kind, m.value) for m in p.movements] == [(K.PURCHASE, D("1200.00"))]
    # blocked credit: tax joins the cost 1,200.00 + 108.00 + 108.00 + 12.00 = 1,428.00
    p = plan("purchase", [line(cgst="108.00", sgst="108.00", cess="12.00", in_cost=True)])
    assert p.movements[0].value == D("1428.00")


def test_S12_a_credit_note_without_stock_block_is_value_only():
    p = plan("credit_note", [line()])
    assert (p.errors, p.movements) == ([], [])


def test_S12_a_credit_note_with_goods_back_needs_the_original_sale():
    assert rules(plan("credit_note", [line()], stock=[StockLineIn(1, None, None)])) == [("S-12", 1)]
    assert rules(plan("credit_note", [line()], stock=[StockLineIn(1, None, "M-X")])) == [("S-12", 1)]


def test_S12_return_goes_back_to_the_godown_of_the_original_unless_overridden():
    orig = {"M1": OriginalFacts("M1", "I1", K.SALE, D("10.000"), "G-SHOP", False, D(0))}
    p = plan("credit_note", [line(qty="4")], stock=[StockLineIn(1, None, "M1")], originals=orig)
    assert [(m.kind, m.godown_id, m.original_movement_id, m.value) for m in p.movements] == [(K.SALES_RETURN, "G-SHOP", "M1", None)]
    p = plan("credit_note", [line(qty="4")], stock=[StockLineIn(1, "G-MAIN", "M1")], originals=orig)
    assert p.movements[0].godown_id == "G-MAIN"


def test_S12_return_quantity_cannot_exceed_original_less_earlier_returns():
    # original 10, 3 already returned: 7 left. 7 ok, 8 not.
    orig = {"M1": OriginalFacts("M1", "I1", K.SALE, D("10.000"), "G-MAIN", False, D("3.000"))}
    assert plan("credit_note", [line(qty="7")], stock=[StockLineIn(1, None, "M1")], originals=orig).errors == []
    assert rules(plan("credit_note", [line(qty="8")], stock=[StockLineIn(1, None, "M1")], originals=orig)) == [("S-12", 1)]


def test_S12_two_lines_of_one_note_share_the_same_originals_balance():
    orig = {"M1": OriginalFacts("M1", "I1", K.SALE, D("10.000"), "G-MAIN", False, D(0))}
    p = plan("credit_note", [line(1, qty="6"), line(2, qty="6")],
             stock=[StockLineIn(1, None, "M1"), StockLineIn(2, None, "M1")], originals=orig)
    assert rules(p) == [("S-12", 2)]


def test_S12_original_must_be_a_sale_for_credit_note_a_purchase_for_debit_note_same_item_not_reversed():
    sale = {"M1": OriginalFacts("M1", "I1", K.SALE, D("10.000"), "G-MAIN", False, D(0))}
    buy = {"M2": OriginalFacts("M2", "I1", K.PURCHASE, D("10.000"), "G-MAIN", False, D(0))}
    assert rules(plan("debit_note", [line()], stock=[StockLineIn(1, None, "M1")], originals=sale)) == [("S-12", 1)]
    assert plan("debit_note", [line()], stock=[StockLineIn(1, None, "M2")], originals=buy).movements[0].kind == K.PURCHASE_RETURN
    assert rules(plan("credit_note", [line()], stock=[StockLineIn(1, None, "M2")], originals=buy)) == [("S-12", 1)]
    other = {"M1": OriginalFacts("M1", "I9", K.SALE, D("10.000"), "G-MAIN", False, D(0))}
    assert rules(plan("credit_note", [line()], stock=[StockLineIn(1, None, "M1")], originals=other)) == [("S-12", 1)]
    gone = {"M1": OriginalFacts("M1", "I1", K.SALE, D("10.000"), "G-MAIN", True, D(0))}
    assert rules(plan("credit_note", [line()], stock=[StockLineIn(1, None, "M1")], originals=gone)) == [("S-12", 1)]


def test_S12_error_messages_are_plain_language_with_the_item_name():
    orig = {"M1": OriginalFacts("M1", "I1", K.SALE, D("10.000"), "G-MAIN", False, D("3.000"))}
    p = plan("credit_note", [line(qty="8")], stock=[StockLineIn(1, None, "M1")], originals=orig)
    assert p.errors[0].message == ("Item 1 (Widget): 8.000 cannot be returned; only 7.000 of the original 10.000 "
                                   "is left to return (3.000 already returned).")


def test_other_voucher_types_never_move_stock():
    assert plan("journal", [line()]).movements == []
