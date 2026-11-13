from datetime import date
from decimal import Decimal as D

from gst_returns_helpers import REG, april_docs, doc, item

from app.engine.gstr3b import ItcRow, ReversalRow, build_gstr3b

START, END = date(2026, 4, 1), date(2026, 4, 30)
Z = D(0)


def heads(igst="0", cgst="0", sgst="0", cess="0"):
    return {"igst": D(igst), "cgst": D(cgst), "sgst": D(sgst), "cess": D(cess)}


def itc(eid, status, *, source="regular", dt="invoice", day=10, month=4, igst="0", cgst="0", sgst="0", cat=None):
    return ItcRow(eid, source, dt, status, date(2026, month, day), cat, D(igst), D(cgst), D(sgst), Z)


def run(in_docs=(), itc_rows=(), reversals=()):
    return build_gstr3b(april_docs(), list(in_docs), list(itc_rows), list(reversals), REG, START, END).tables


def test_G52_t3_1_outward_equals_the_sales_register_net_of_credit_notes():
    t = run()["t3_1"]
    # a: taxable, not export: 1000+500+200+2000+300000+100+200 less credit note 100 = 303,900.00
    assert t["a_outward_taxable"] == {"taxable_value": D(303900), "igst": D(54360), "cgst": D(158),
                                      "sgst": D(158), "cess": Z}
    assert t["b_zero_rated"]["taxable_value"] == D(5000)
    assert t["c_nil_exempt"]["taxable_value"] == D(400)
    assert t["e_non_gst"]["taxable_value"] == Z
    assert run()["outward_total"]["taxable_value"] == D(309300)


def test_G52_t3_2_inter_state_to_unregistered_by_place_of_supply():
    t = run()["t3_2"]
    assert t["unregistered"] == [{"place_of_supply": "29", "taxable_value": D(300000), "igst": D(54000)}]
    assert t["composition"] == [] and t["uin"] == []


def test_G52_t3_2_composition_and_uin_party_types_are_separate():
    d1 = doc("SAL/20", "sales", "b2b", "29", "118", [item("100", igst="18")], gstin="29CCCCC2222C1Z7", ptype="composition")
    d2 = doc("SAL/21", "sales", "b2b", "29", "236", [item("200", igst="36")], gstin="29DDDDD3333D1Z8", ptype="uin_holder")
    t = build_gstr3b([d1, d2], [], [], [], REG, START, END).tables["t3_2"]
    assert t["composition"] == [{"place_of_supply": "29", "taxable_value": D(100), "igst": D(18)}]
    assert t["uin"] == [{"place_of_supply": "29", "taxable_value": D(200), "igst": D(36)}]


def test_G52_inward_rcm_goes_to_3_1_d_and_t5_lists_nil_inward():
    rcm = doc("PUR/1", "purchase", "unregistered_supplier", "29", "1180", [item("1000", igst="180", rcm=True)], day=12)
    nil = doc("PUR/2", "purchase", "b2b", "27", "300", [item("300", "0", treatment="nil_rated")], gstin="27EEEEE4444E1Z9")
    comp = doc("PUR/3", "purchase", "composition_supplier", "27", "80", [item("80", "0")], gstin="27FFFFF5555F1Z1")
    t = run(in_docs=[rcm, nil, comp])
    assert t["t3_1"]["d_inward_rcm"] == {"taxable_value": D(1000), "igst": D(180), "cgst": Z, "sgst": Z, "cess": Z}
    assert t["t5"]["intra_nil"]["taxable_value"] == D(300)
    assert t["t5"]["intra_composition_exempt"]["taxable_value"] == D(80)
    assert t["t5"]["inter_nil"]["taxable_value"] == Z


def test_G52_t4_uses_eligible_entries_of_the_period_only_and_nets_debit_notes():
    rows = [
        itc("a", "eligible", cgst="90", sgst="90"),
        itc("b", "eligible", source="rcm", igst="180"),
        itc("c", "eligible", dt="debit_note", cgst="9", sgst="9"),
        itc("d", "eligible", month=5, cgst="500", sgst="500"),  # May: not in April
        itc("e", "pending", igst="50"),
        itc("f", "blocked", cgst="10", sgst="10"),
        itc("g", "eligible", igst="70", cat="import_of_service"),
    ]
    t4 = run(itc_rows=rows, reversals=[ReversalRow("r1", date(2026, 4, 20), D(20), Z, Z, Z),
                                       ReversalRow("r2", date(2026, 5, 2), D(99), Z, Z, Z)])["t4"]
    assert t4["a"]["all_other_itc"] == heads(cgst="81", sgst="81")
    assert t4["a"]["inward_rcm"] == heads(igst="180")
    assert t4["a"]["import_services"] == heads(igst="70")
    assert t4["a"]["total"] == heads(igst="250", cgst="81", sgst="81")
    assert t4["b"]["others"] == heads(igst="20")
    assert t4["c_net"] == heads(igst="230", cgst="81", sgst="81")
    assert t4["d_ineligible"] == heads(igst="50", cgst="10", sgst="10")


def test_G52_t6_1_shows_liability_and_itc_but_does_not_apply_a_utilisation_order():
    t6 = run(itc_rows=[itc("a", "eligible", cgst="90", sgst="90")])["t6_1"]
    assert t6["tax_payable"] == heads(igst="54360", cgst="158", sgst="158")
    assert t6["itc_available"] == heads(cgst="90", sgst="90")
    assert t6["utilisation"] == "not_computed" and t6["cash"] is None
