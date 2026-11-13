"""Invoice mode: the engine builds the voucher lines (G-12 .. G-26). Expected figures are hand-calculated literals."""

from datetime import date
from decimal import Decimal as D

from gst_helpers import ROLES, ctx, invoice, item, registration

from app.engine.gst_invoice import (
    build_invoice,
    check_lines_match,
    check_number_length,
    typed_tax_errors,
)

D0 = D("0.00")


def lines_of(result):
    return [(x.ledger_id, x.debit, x.credit, x.role, x.item_line_no) for x in result.lines]


def ok(inv, c=None):
    out = build_invoice(inv, c or ctx())
    assert out.errors == [], out.errors
    return out.result


def rules_of(inv, c=None):
    out = build_invoice(inv, c or ctx())
    assert out.result is None
    return sorted({e.rule_id for e in out.errors})


# ---- booking of lines (sales) ---------------------------------------------------------------------------
def test_G13_sales_intra_state_lines():
    r = ok(invoice([item()]))
    assert lines_of(r) == [
        ("party", D("1180.00"), D0, "party", None),
        ("goods", D0, D("1000.00"), "taxable", 1),
        ("o-cgst", D0, D("90.00"), "tax_cgst", None),
        ("o-sgst", D0, D("90.00"), "tax_sgst", None),
    ]
    assert (r.invoice_value, r.invoice_round_off, r.has_rcm) == (D("1180.00"), D0, False)


def test_G13_sales_inter_state_lines_use_igst_only():
    r = ok(invoice([item()], pos="29"))
    assert [(x.ledger_id, x.credit) for x in r.lines if x.role.startswith("tax_")] == [("o-igst", D("180.00"))]


def test_G15_mixed_rates_each_line_rounded_and_summed_per_head():
    # line 1: taxable 1.00 at 5% -> 0.03 + 0.03; line 2: taxable 100.00 at 18% -> 9.00 + 9.00
    r = ok(invoice([item(hsn="1701", rate="1.00"), item(rate="100.00", ledger="goods2")]))
    assert lines_of(r) == [
        ("party", D("119.06"), D0, "party", None),
        ("goods", D0, D("1.00"), "taxable", 1),
        ("goods2", D0, D("100.00"), "taxable", 2),
        ("o-cgst", D0, D("9.03"), "tax_cgst", None),
        ("o-sgst", D0, D("9.03"), "tax_sgst", None),
    ]


def test_G21_exempt_line_has_no_tax_lines():
    r = ok(invoice([item(hsn="0713")], kind="bill_of_supply"))
    assert lines_of(r) == [("party", D("1000.00"), D0, "party", None), ("goods", D0, D("1000.00"), "taxable", 1)]


def test_G19_export_without_payment_zero_tax_pos_96():
    r = ok(invoice([item()], pos="96", category="export_without_payment"))
    assert r.invoice_value == D("1000.00") and len(r.lines) == 2 and r.items[0].treatment == "zero_rated"


def test_G19_export_with_payment_igst():
    r = ok(invoice([item()], pos="96", category="export_with_payment"))
    assert r.invoice_value == D("1180.00") and r.lines[2].ledger_id == "o-igst"


# ---- round-off (G-16) --------------------------------------------------------------------------------------
def test_G16_round_off_off_by_default_keeps_paise():
    r = ok(invoice([item(rate="100.10")]))
    assert r.invoice_value == D("118.12") and r.invoice_round_off == D0


def test_G16_round_off_down_goes_to_round_off_ledger_on_party_side():
    # taxable 100.10: 9.01 + 9.01 -> 118.12; rounded 118.00; round-off 0.12 on the party's (debit) side
    r = ok(invoice([item(rate="100.10")]), ctx(round_off=True))
    assert r.invoice_value == D("118.00") and r.invoice_round_off == D("-0.12")
    assert lines_of(r) == [
        ("party", D("118.00"), D0, "party", None),
        ("goods", D0, D("100.10"), "taxable", 1),
        ("o-cgst", D0, D("9.01"), "tax_cgst", None),
        ("o-sgst", D0, D("9.01"), "tax_sgst", None),
        ("round", D("0.12"), D0, "round_off", None),
    ]


def test_G16_half_rupee_rounds_up():
    # taxable 100.00 + qty: use rate 100.00 and 2 items to reach 118.50? simpler: taxable 100.42 -> 9.04 x2 -> 118.50
    r = ok(invoice([item(rate="100.42")]), ctx(round_off=True))
    assert (r.invoice_value, r.invoice_round_off) == (D("119.00"), D("0.50"))
    assert [(x.ledger_id, x.credit) for x in r.lines if x.role == "round_off"] == [("round", D("0.50"))]


# ---- purchase, RCM, blocked credit ------------------------------------------------------------------------
def purchase_ctx(**kw):
    return ctx(vtype="purchase", **kw)


def test_G13_purchase_intra_state_books_input_tax():
    r = ok(invoice([item(ledger="purch")], on=date(2026, 5, 9)), purchase_ctx())
    assert lines_of(r) == [
        ("party", D0, D("1180.00"), "party", None),
        ("purch", D("1000.00"), D0, "taxable", 1),
        ("i-cgst", D("90.00"), D0, "tax_cgst", None),
        ("i-sgst", D("90.00"), D0, "tax_sgst", None),
    ]


def test_G20_rcm_purchase_from_unregistered_supplier():
    inv = invoice(
        [item(hsn="996511", ledger="freight", rate="10000.00", rcm_category_key="gta_services")],
        category="unregistered_supplier", kind="self_invoice", gstin=None, on=date(2026, 5, 9),
    )
    r = ok(inv, purchase_ctx())
    assert lines_of(r) == [
        ("party", D0, D("10000.00"), "party", None),
        ("freight", D("10000.00"), D0, "taxable", 1),
        ("i-cgst", D("250.00"), D0, "tax_cgst", None),
        ("i-sgst", D("250.00"), D0, "tax_sgst", None),
        ("r-cgst", D0, D("250.00"), "rcm_cgst", None),
        ("r-sgst", D0, D("250.00"), "rcm_sgst", None),
    ]
    assert r.has_rcm is True and r.invoice_value == D("10000.00") and r.items[0].rcm is True


def test_G30_blocked_credit_tax_goes_into_cost():
    inv = invoice([item(ledger="veh", itc_category_key="motor_vehicles")], on=date(2026, 5, 9))
    r = ok(inv, purchase_ctx())
    assert lines_of(r) == [("party", D0, D("1180.00"), "party", None), ("veh", D("1180.00"), D0, "taxable", 1)]
    assert r.items[0].tax_in_cost is True


def test_G30_exception_claimed_with_note_keeps_input_tax():
    inv = invoice([item(ledger="veh", itc_category_key="motor_vehicles", itc_exception_claimed=True,
                        itc_exception_note="used for passenger transport")], on=date(2026, 5, 9))
    r = ok(inv, purchase_ctx())
    assert r.items[0].tax_in_cost is False and len(r.lines) == 4


def test_G30_exception_without_note_or_where_none_exists_rejected():
    no_note = invoice([item(itc_category_key="motor_vehicles", itc_exception_claimed=True)], on=date(2026, 5, 9))
    assert rules_of(no_note, purchase_ctx()) == ["G-30"]
    none_exists = invoice([item(itc_category_key="food_beverages", itc_exception_claimed=True, itc_exception_note="x")],
                          on=date(2026, 5, 9))
    assert rules_of(none_exists, purchase_ctx()) == ["G-30"]


def test_G30_unknown_blocked_category_rejected_and_itc_tags_refused_on_sales():
    assert rules_of(invoice([item(itc_category_key="nope")], on=date(2026, 5, 9)), purchase_ctx()) == ["G-30"]
    assert rules_of(invoice([item(itc_category_key="motor_vehicles")])) == ["G-30"]


def test_G25_purchase_from_composition_supplier_carries_no_tax():
    inv = invoice([item(ledger="purch")], category="composition_supplier", kind="bill_of_supply", on=date(2026, 5, 9))
    r = ok(inv, purchase_ctx())
    assert lines_of(r) == [("party", D0, D("1000.00"), "party", None), ("purch", D("1000.00"), D0, "taxable", 1)]


def test_G25_supplier_invoice_date_after_voucher_date_rejected_and_gstin_required():
    late = invoice([item()], on=date(2026, 5, 11))
    assert rules_of(late, purchase_ctx(on=date(2026, 5, 10))) == ["G-25"]
    no_gstin = invoice([item()], gstin=None, on=date(2026, 5, 9))
    assert rules_of(no_gstin, purchase_ctx()) == ["G-25"]


# ---- notes (G-24) -------------------------------------------------------------------------------------------
def test_G24_credit_note_mirrors_sales_lines():
    inv = invoice([item()], original_invoice_no="SAL/2026-27/0001", original_invoice_date=date(2026, 5, 1),
                  note_reason="sales_return")
    r = ok(inv, ctx(vtype="credit_note"))
    assert lines_of(r) == [
        ("party", D0, D("1180.00"), "party", None),
        ("goods", D("1000.00"), D0, "taxable", 1),
        ("o-cgst", D("90.00"), D0, "tax_cgst", None),
        ("o-sgst", D("90.00"), D0, "tax_sgst", None),
    ]


def test_G24_debit_note_mirrors_purchase_lines():
    inv = invoice([item(ledger="purch")], original_invoice_no="B-1", original_invoice_date=date(2026, 5, 1),
                  note_reason="correction_in_invoice", on=date(2026, 5, 9))
    r = ok(inv, ctx(vtype="debit_note"))
    assert lines_of(r)[0] == ("party", D("1180.00"), D0, "party", None)
    assert lines_of(r)[2] == ("i-cgst", D0, D("90.00"), "tax_cgst", None)


def test_G24_note_needs_original_reference_valid_reason_and_date_order():
    base = {"original_invoice_no": "A-1", "original_invoice_date": date(2026, 5, 1), "note_reason": "sales_return"}
    c = ctx(vtype="credit_note")
    assert rules_of(invoice([item()]), c) == ["G-24"]
    assert rules_of(invoice([item()], **{**base, "note_reason": None}), c) == ["G-24"]
    assert rules_of(invoice([item()], **{**base, "note_reason": "because"}), c) == ["G-24"]
    assert rules_of(invoice([item()], **{**base, "original_invoice_date": date(2026, 5, 11)}), c) == ["G-24"]
    assert rules_of(invoice([item()], **base), ctx(vtype="sales")) == ["G-24"]  # references only on notes


# ---- header rules ----------------------------------------------------------------------------------------------
def test_G12_place_of_supply_must_be_a_known_state_code():
    assert rules_of(invoice([item()], pos="88")) == ["G-12"]
    assert rules_of(invoice([item()], pos="")) == ["G-12"]


def test_G19_pos_96_only_for_exports_and_exports_need_96():
    assert "G-19" in rules_of(invoice([item()], pos="96"))
    assert "G-19" in rules_of(invoice([item()], pos="29", category="export_with_payment"))


def test_G19_b2b_and_sez_need_a_buyer_gstin_and_b2c_must_not_carry_one():
    assert "G-19" in rules_of(invoice([item()], gstin=None))
    assert "G-19" in rules_of(invoice([item()], gstin=None, category="sez_with_payment", pos="29"))
    assert "G-19" in rules_of(invoice([item()], category="b2c"))


def test_G22_bad_gstin_reported_through_the_validator():
    def check(gstin):
        return ["some other problem"]

    out = build_invoice(invoice([item()]), ctx(gstin_check=check))
    assert [e.rule_id for e in out.errors] == ["G-22"]
    assert "some other problem" in out.errors[0].message


def test_G22_wrong_check_character_is_refused_in_invoice_mode():
    out = build_invoice(invoice([item()], gstin="27ABCDE1234F1Z5"), ctx())
    assert [e.rule_id for e in out.errors] == ["G-22"]
    assert "check character" in out.errors[0].message and "should be '0'" in out.errors[0].message
    assert build_invoice(invoice([item()], gstin="27ABCDE1234F1Z0"), ctx()).errors == []


def test_P04_party_state_differing_from_the_invoice_gstin_is_an_error():
    out = build_invoice(invoice([item()], gstin="29ABCDE1234F1ZW", pos="29"), ctx(cp_state="29", party_state="27"))
    assert [e.rule_id for e in out.errors] == ["P-04"]
    assert "27" in out.errors[0].message and "29ABCDE1234F1ZW" in out.errors[0].message
    ok = build_invoice(invoice([item()], gstin="29ABCDE1234F1ZW", pos="29"), ctx(cp_state="29", party_state="29"))
    assert ok.errors == []


def test_G22_gstin_format_checked_without_validator():
    assert rules_of(invoice([item()], gstin="27ABC")) == ["G-22"]


def test_G17_needs_at_least_one_item_and_reports_item_number():
    assert rules_of(invoice([])) == ["G-17"]
    out = build_invoice(invoice([item(), item(qty="0")]), ctx())
    assert [(e.rule_id, e.line_no) for e in out.errors] == [("G-17", 2)]


def test_G10_item_errors_are_collected_for_every_item():
    out = build_invoice(invoice([item(hsn="9018"), item(hsn="7777")]), ctx())
    assert [(e.rule_id, e.line_no) for e in out.errors] == [("G-10", 1), ("G-11", 2)]


def test_G18_composition_client_cannot_raise_a_tax_invoice():
    reg = registration(kind="composition")
    assert rules_of(invoice([item()]), ctx(reg=reg)) == ["G-18"]


def test_G18_composition_client_bill_of_supply_has_zero_tax():
    reg = registration(kind="composition")
    r = ok(invoice([item()], kind="bill_of_supply", category="b2c", gstin=None), ctx(reg=reg))
    assert lines_of(r) == [("party", D("1000.00"), D0, "party", None), ("goods", D0, D("1000.00"), "taxable", 1)]


def test_G18_composition_client_purchases_not_supported_in_invoice_mode():
    reg = registration(kind="composition")
    assert rules_of(invoice([item()], on=date(2026, 5, 9)), ctx(vtype="purchase", reg=reg)) == ["G-18"]


def test_G18_regular_client_bill_of_supply_only_when_every_line_exempt_nil_or_non_gst():
    assert rules_of(invoice([item()], kind="bill_of_supply")) == ["G-18"]
    assert rules_of(invoice([item(hsn="0713")], kind="tax_invoice")) == ["G-18"]
    assert ok(invoice([item(hsn="0713"), item(hsn="0401")], kind="bill_of_supply"))


def test_G06_invoice_date_must_be_inside_the_registration_period():
    reg = registration(frm=date(2026, 6, 1))
    assert rules_of(invoice([item()]), ctx(reg=reg)) == ["G-06"]


def test_G08_missing_ledger_role_is_reported_by_name():
    roles = {k: v for k, v in ROLES.items() if k != "output_sgst"}
    out = build_invoice(invoice([item()]), ctx(reg=registration(roles=roles)))
    assert [e.rule_id for e in out.errors] == ["G-08"]
    assert "Output SGST" in out.errors[0].message


def test_G08_round_off_role_needed_only_when_a_round_off_arises():
    roles = {k: v for k, v in ROLES.items() if k != "round_off"}
    reg = registration(roles=roles)
    assert ok(invoice([item()]), ctx(reg=reg, round_off=True))  # 1,180.00 needs no round-off
    assert rules_of(invoice([item(rate="100.10")]), ctx(reg=reg, round_off=True)) == ["G-08"]


def test_G12_sales_invoice_date_must_equal_voucher_date():
    assert rules_of(invoice([item()], on=date(2026, 5, 9))) == ["G-12"]


def test_G20_import_of_service_needs_rcm_on_every_item_and_igst():
    inv = invoice(
        [item(hsn="998311", ledger="exp", rate="1000.00", rcm_category_key="import_of_services")],
        pos="27", category="import_of_service", kind="self_invoice", gstin=None, on=date(2026, 5, 9),
    )
    r = ok(inv, ctx(vtype="purchase", cp_state=None))
    assert [(x.ledger_id, x.debit, x.credit) for x in r.lines] == [
        ("party", D0, D("1000.00")), ("exp", D("1000.00"), D0), ("i-igst", D("180.00"), D0), ("r-igst", D0, D("180.00")),
    ]
    no_rcm = invoice([item(hsn="998311", ledger="exp")], category="import_of_service", kind="self_invoice", gstin=None,
                     on=date(2026, 5, 9))
    assert "G-20" in rules_of(no_rcm, ctx(vtype="purchase", cp_state=None))


def test_G12_purchase_needs_the_supplier_state_when_tax_is_charged():
    assert rules_of(invoice([item()], on=date(2026, 5, 9)), purchase_ctx(cp_state=None)) == ["G-12"]


# ---- G-14, G-23, G-26 -----------------------------------------------------------------------------------------
def test_G14_caller_lines_and_tax_amounts_are_rejected():
    assert [e.rule_id for e in typed_tax_errors(has_lines=True, item_extra_keys=[[]])] == ["G-14"]
    errs = typed_tax_errors(has_lines=False, item_extra_keys=[[], ["cgst", "gst_rate"]])
    assert [(e.rule_id, e.line_no) for e in errs] == [("G-14", 2)]
    assert typed_tax_errors(has_lines=False, item_extra_keys=[[]]) == []


def test_G23_voucher_number_longer_than_16_characters_blocked():
    assert check_number_length("SAL/2026-27/0001", D(16)) == []
    errs = check_number_length("SAL/2026-27/10000", D(16))
    assert [e.rule_id for e in errs] == ["G-23"] and "17" in errs[0].message
    assert [e.rule_id for e in check_number_length("SAL 2026-27/0001", D(16))] == ["G-23"]


def test_G26_booked_lines_must_equal_what_the_engine_builds():
    r = ok(invoice([item()]))
    good = [(x.ledger_id, x.debit, x.credit) for x in r.lines]
    assert check_lines_match(r, good) == []
    tampered = [(a, b - D("1.00") if b > 0 else b, c) for a, b, c in good]
    assert [e.rule_id for e in check_lines_match(r, tampered)] == ["G-26"]
    assert [e.rule_id for e in check_lines_match(r, good[:-1])] == ["G-26"]
    swapped = list(good)
    swapped[2], swapped[3] = (swapped[2][0], swapped[2][1], swapped[2][2]), ("i-igst", D0, D("90.00"))
    assert [e.rule_id for e in check_lines_match(r, swapped)] == ["G-26"]


def test_G13_engine_version_and_default_rate_warning():
    r = ok(invoice([item(hsn="998899", ledger="svc", uqc=None)], kind="tax_invoice"))
    assert r.engine_version == "gst-1"
    assert [(w[0], w[2]) for w in r.warnings] == [("G-10", 1)]
    assert r.items[0].rate_is_default is True
