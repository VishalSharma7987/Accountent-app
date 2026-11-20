"""Package D: the pure engine checks of an extracted invoice (D-03, D-05 .. D-17) and of a bank statement (D-18, D-19).

Hand-calculated invoice used by most tests (purchase, client = buyer, Maharashtra 27, date 10-05-2026, rule data of gst_helpers):
  line 1: HSN 8471, 2 x 1000.00, no discount  -> taxable 2000.00, 18%: CGST 180.00 + SGST 180.00
  line 2: SAC 9983, 1 x 500.00 - discount 50.00 -> taxable 450.00,  18%: CGST 40.50 + SGST 40.50
  totals: taxable 2450.00, CGST 220.50, SGST 220.50, grand total 2891.00 (round-off 0.00)
  inter-state variant (supplier in Karnataka 29): IGST 360.00 + 81.00 = 441.00, grand total 2891.00
Every wrong variant must give exactly the expected rule id and severity.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

from gst_helpers import RULES, registration

from app.engine import doc_bank, doc_check
from app.engine.doc_check import DocCheckContext, DuplicateCandidate
from app.engine.doc_types import (
    DocType,
    ExtractedInvoice,
    ExtractedLine,
    ExtractedTotals,
    Field,
    Severity,
    Source,
)
from app.engine.gst_types import StateCode

CLIENT_GSTIN = "27AAAPL1234C1ZE"      # Maharashtra
SUPPLIER_MH = "27CCCPM4321E1ZZ"       # Maharashtra
SUPPLIER_KA = "29BBBPS5678D1Z9"       # Karnataka
OTHER_BUYER = "07DDDPK9876F1Z3"       # Delhi
BAD_GSTIN = "27CCCPM4321E1ZA"         # wrong check character (right one is Z)
SRC = "test"
STATES = tuple(StateCode(c, n, "state", date(2017, 7, 1), None, SRC, "pending")
               for c, n in (("27", "Maharashtra"), ("29", "Karnataka"), ("07", "Delhi")))


def f(value, conf="0.95", page=1):
    return Field(value, Source(page) if page else None, D(conf) if conf else None)


def line(desc="Laptop", hsn="8471", qty="2", rate="1000.00", disc=None, taxable="2000.00", gst="18",
         cgst="180.00", sgst="180.00", igst=None, cess=None):
    return ExtractedLine(f(desc), f(hsn), f(qty), f("NOS"), f(rate), f(disc), f(taxable), f(gst), f(cgst), f(sgst), f(igst), f(cess))


LINE1 = line()
LINE2 = line("Installation", "9983", "1", "500.00", "50.00", "450.00", "18", "40.50", "40.50")
TOTALS = ExtractedTotals(f("2450.00"), f("220.50"), f("220.50"), f(None), f(None), f("0.00"), f("2891.00"))

INV = ExtractedInvoice(
    document_kind=f("Tax Invoice"), supplier_name=f("Shree Traders"), supplier_gstin=f(SUPPLIER_MH),
    buyer_name=f("Client Pvt Ltd"), buyer_gstin=f(CLIENT_GSTIN), invoice_no=f("INV-77"), invoice_date=f("10-05-2026"),
    place_of_supply=f("27-Maharashtra"), original_invoice_no=f(None), lines=(LINE1, LINE2), totals=TOTALS,
)

INTER_LINE1 = line(cgst=None, sgst=None, igst="360.00")
INTER_LINE2 = line("Installation", "9983", "1", "500.00", "50.00", "450.00", "18", None, None, "81.00")
INTER = replace(
    INV, supplier_gstin=f(SUPPLIER_KA), lines=(INTER_LINE1, INTER_LINE2),
    totals=ExtractedTotals(f("2450.00"), f(None), f(None), f("441.00"), f(None), f("0.00"), f("2891.00")),
)


def ctx(**kw):
    base = {"registrations": (registration("27", frm=date(2017, 7, 1)),), "rules": RULES, "state_codes": STATES,
            "today": date(2026, 11, 20), "doc_type": DocType.PURCHASE_INVOICE,
            "financial_years": ((date(2026, 4, 1), date(2027, 3, 31)),)}
    base.update(kw)
    return DocCheckContext(**base)


def client_reg():
    """The client's registration with the GSTIN used in these tests (gst_helpers' own GSTIN is a different literal)."""
    return replace(registration("27"), gstin=CLIENT_GSTIN)


def run(inv=INV, **kw):
    kw.setdefault("registrations", (client_reg(),))
    return doc_check.check_invoice(inv, ctx(**kw))


def ids(result, severity=None):
    return sorted((x.rule_id, x.severity.value, x.field_path) for x in result.findings if severity is None or x.severity == severity)


def only(result, rule_id):
    found = [x for x in result.findings if x.rule_id == rule_id]
    assert len(found) == 1, [x.as_dict() for x in result.findings]
    return found[0]


# ---------------------------------------------------------------------------------------------- clean invoices


def test_D10_to_D13_clean_intra_state_purchase_has_no_finding_and_recomputes_to_the_paisa():
    res = run()
    assert res.findings == ()
    assert res.direction == "purchase" and res.place_of_supply == "27" and res.invoice_date == date(2026, 5, 10)
    assert [(x.taxable_value, x.gst_rate, x.cgst, x.sgst, x.igst, x.cess) for x in res.lines] == [
        (D("2000.00"), D("18.0000"), D("180.00"), D("180.00"), D("0.00"), D("0.00")),
        (D("450.00"), D("18.0000"), D("40.50"), D("40.50"), D("0.00"), D("0.00"))]
    assert res.totals == {"taxable_total": D("2450.00"), "cgst_total": D("220.50"), "sgst_total": D("220.50"),
                          "igst_total": D("0.00"), "cess_total": D("0.00"), "round_off": D("0.00"), "grand_total": D("2891.00")}


def test_D12_clean_inter_state_purchase_uses_igst():
    res = run(INTER)
    assert res.findings == ()
    assert res.lines[0].igst == D("360.00") and res.lines[1].igst == D("81.00") and res.lines[0].cgst == D("0.00")
    assert res.totals["igst_total"] == D("441.00") and res.totals["grand_total"] == D("2891.00")


def test_D06_indian_commas_in_printed_amounts_are_tolerated():
    big = replace(INV, lines=(line(rate="1,00,000.00", qty="1", taxable="1,00,000.00", cgst="9,000.00", sgst="9,000.00"),),
                  totals=ExtractedTotals(f("1,00,000.00"), f("9,000.00"), f("9,000.00"), f(None), f(None), f(None), f("1,18,000.00")))
    res = run(big)
    assert res.findings == () and res.totals["grand_total"] == D("118000.00")


def test_D13_round_off_with_sign_is_part_of_the_grand_total():
    inv = replace(INV, totals=replace(TOTALS, round_off=f("-0.40"), grand_total=f("2890.60")))
    assert run(inv).findings == ()


# ---------------------------------------------------------------------------------------------- injected errors


def test_D13_wrong_grand_total_is_an_error_with_both_values():
    res = run(replace(INV, totals=replace(TOTALS, grand_total=f("2991.00"))))
    assert ids(res) == [("D-13", "error", "totals.grand_total")]
    x = only(res, "D-13")
    assert (x.printed, x.computed) == ("2991.00", "2891.00")
    assert "2,991.00" in x.message and "2,891.00" in x.message and "100.00" in x.message


def test_D13_rounding_difference_up_to_one_rupee_is_a_warning():
    res = run(replace(INV, totals=replace(TOTALS, grand_total=f("2891.50"))))
    assert ids(res) == [("D-13", "warning", "totals.grand_total")]


def test_D13_huge_round_off_cannot_hide_a_wrong_total():
    res = run(replace(INV, totals=replace(TOTALS, round_off=f("100.00"), grand_total=f("2991.00"))))
    assert ids(res) == [("D-13", "error", "totals.round_off")]


def test_D13_wrong_tax_total_and_taxable_total():
    res = run(replace(INV, totals=replace(TOTALS, cgst_total=f("200.00"), taxable_total=f("2500.00"))))
    # printed lines add up to 2,450.00 but the printed taxable total says 2,500.00: that is D-17 (not also D-13 for the same figure)
    assert ids(res) == [("D-13", "error", "totals.cgst_total"), ("D-17", "error", "totals.taxable_total")]


def test_D11_tax_amount_differs_from_the_gst_engine_is_an_error():
    res = run(replace(INV, lines=(line(cgst="170.00"), LINE2)))
    assert ids(res) == [("D-11", "error", "lines[0].cgst")]
    x = only(res, "D-11")
    assert (x.printed, x.computed) == ("170.00", "180.00")


def test_D11_small_tax_difference_is_a_warning():
    res = run(replace(INV, lines=(line(sgst="180.50"), LINE2)))
    assert ids(res) == [("D-11", "warning", "lines[0].sgst")]


def test_D11_printed_rate_in_force_but_not_the_rate_of_the_hsn():
    res = run(replace(INV, lines=(line(gst="5", cgst="50.00", sgst="50.00"), LINE2)))
    assert ids(res) == [("D-11", "error", "lines[0].gst_rate")]
    assert (only(res, "D-11").printed, only(res, "D-11").computed) == ("5", "18.0000")


def test_D15_printed_rate_that_is_not_a_slab_on_that_date():
    res = run(replace(INV, lines=(line(gst="12", cgst="120.00", sgst="120.00"), LINE2)))     # 12% ended 21-09-2025
    assert ids(res) == [("D-15", "error", "lines[0].gst_rate")]


def test_D15_rate_table_gap_is_reported_as_review_never_filled_in():
    res = run(replace(INV, lines=(line(hsn="7777", cgst="70.00", sgst="70.00"), LINE2)))     # gst_helpers: 7% rule is not a slab
    assert ids(res) == [("D-15", "review", "lines[0].hsn_sac")]
    assert res.lines[0] is None and res.lines[1] is not None
    assert res.totals == {}                                                                  # no totals from an incomplete recomputation


def test_D12_igst_printed_on_an_intra_state_supply():
    res = run(replace(INV, lines=(line(cgst=None, sgst=None, igst="360.00"), LINE2)))
    assert ids(res) == [("D-12", "error", "lines[0].igst")]


def test_D12_cgst_sgst_printed_on_an_inter_state_supply():
    res = run(replace(INTER, lines=(line(), INTER_LINE2)))
    first = [x for x in res.findings if x.rule_id == "D-12"]
    assert len(first) == 1 and first[0].severity == Severity.ERROR and first[0].field_path == "lines[0].cgst"


def test_D10_taxable_value_differs_from_quantity_times_rate():
    res = run(replace(INV, lines=(line(taxable="2100.00"), LINE2)))
    x = only(res, "D-10")
    assert (x.severity, x.field_path, x.printed, x.computed) == (Severity.ERROR, "lines[0].taxable_value", "2100.00", "2000.00")
    # tax is recomputed from 2,000.00 (matches the printed tax); the printed lines (2,100.00 + 450.00) no longer add up to the printed total
    assert ids(res) == [("D-10", "error", "lines[0].taxable_value"), ("D-17", "error", "totals.taxable_total")]


def test_D10_missing_quantity_uses_the_printed_taxable_value_with_a_warning():
    res = run(replace(INV, lines=(line(qty=None), LINE2)))
    assert ids(res) == [("D-10", "warning", "lines[0].quantity")]
    assert res.lines[0].taxable_value == D("2000.00") and res.lines[0].cgst == D("180.00")


def test_D17_a_missed_line_makes_printed_lines_disagree_with_the_printed_total():
    res = run(replace(INV, lines=(LINE1,)))
    assert ("D-17", "error", "totals.taxable_total") in ids(res)
    assert only(res, "D-17").printed == "2450.00" and only(res, "D-17").computed == "2000.00"
    assert [x for x in res.findings if x.rule_id == "D-13" and x.field_path == "totals.cgst_total"]


def test_D07_wrong_gstin_check_character_is_an_error_with_the_expected_character():
    res = run(replace(INV, supplier_gstin=f(BAD_GSTIN)))
    assert ids(res) == [("D-07", "error", "supplier_gstin")]
    x = res.findings[0]
    assert "check character" in x.message and "'Z'" in x.message


def test_D07_malformed_gstin_and_lowercase_with_spaces_is_normalised():
    assert [x.rule_id for x in run(replace(INV, buyer_gstin=f("27AAAPL1234"))).findings if x.rule_id == "D-07"] == ["D-07"]
    assert run(replace(INV, supplier_gstin=f(" 27cccpm4321e1zz "))).findings == ()


def test_D05_missing_required_fields_are_errors():
    res = run(replace(INV, invoice_no=f(None), invoice_date=f("  ")))
    assert ids(res, Severity.ERROR) == [("D-05", "error", "invoice_date"), ("D-05", "error", "invoice_no")]
    res = run(replace(INV, lines=()))
    assert ("D-05", "error", "lines") in ids(res)
    res = run(replace(INV, totals=replace(TOTALS, grand_total=f(None))))
    assert ("D-05", "error", "totals.grand_total") in ids(res)
    res = run(replace(INV, lines=(line(desc=None), LINE2)))
    assert ids(res) == [("D-05", "error", "lines[0].description")]


def test_D05_low_confidence_is_a_warning_and_the_threshold_is_a_parameter():
    res = run(replace(INV, invoice_date=f("10-05-2026", conf="0.60")))
    assert ids(res) == [("D-05", "warning", "invoice_date")]
    assert run(replace(INV, invoice_date=f("10-05-2026", conf="0.60")), min_confidence=D("0.50")).findings == ()
    assert run(replace(INV, invoice_no=f("INV-77", conf="0.85"))).findings == ()        # exactly the minimum is fine


def test_D05_value_without_page_or_confidence_is_a_warning_unless_the_extraction_was_typed_by_hand():
    inv = replace(INV, invoice_no=Field("INV-77", None, D("0.95")))
    assert ids(run(inv)) == [("D-05", "warning", "invoice_no")]
    inv = replace(INV, invoice_no=Field("INV-77", Source(1), None))
    assert ids(run(inv)) == [("D-05", "warning", "invoice_no")]
    assert run(replace(INV, invoice_no=Field("INV-77")), require_source=False).findings == ()


def test_D05_page_beyond_the_document_is_a_warning():
    res = run(replace(INV, invoice_no=f("INV-77", page=3)), page_count=2)
    assert ids(res) == [("D-05", "warning", "invoice_no")]


def test_D06_more_than_two_decimals_negative_and_text_amounts_are_errors_not_rounded():
    assert ("D-06", "error", "lines[0].unit_rate") in ids(run(replace(INV, lines=(line(rate="1000.005"), LINE2))))
    assert ("D-06", "error", "lines[0].taxable_value") in ids(run(replace(INV, lines=(line(taxable="-5.00"), LINE2))))
    assert ("D-06", "error", "totals.grand_total") in ids(run(replace(INV, totals=replace(TOTALS, grand_total=f("two thousand")))))
    assert ("D-06", "error", "lines[0].quantity") in ids(run(replace(INV, lines=(line(qty="1.2345"), LINE2))))
    assert ("D-06", "error", "lines[0].gst_rate") in ids(run(replace(INV, lines=(line(gst="eighteen"), LINE2))))


def test_D06_impossible_and_unreadable_dates_are_errors():
    for bad in ["31-02-2026", "2026/05/10x", "May 10", "10-13-2026"]:
        assert ids(run(replace(INV, invoice_date=f(bad)))) == [("D-06", "error", "invoice_date")], bad
    assert run(replace(INV, invoice_date=f("10/05/2026"))).findings == ()
    assert run(replace(INV, invoice_date=f("2026-05-10"))).findings == ()


def test_D06_only_inr_is_accepted():
    assert ids(run(replace(INV, currency="USD"))) == [("D-06", "error", "currency")]


def test_D14_date_outside_financial_years_locked_or_in_the_future():
    assert ids(run(replace(INV, invoice_date=f("10-05-2030")), today=date(2026, 11, 20))) == [("D-14", "error", "invoice_date")]
    out = run(replace(INV, invoice_date=f("10-05-2024")))
    assert ("D-14", "error", "invoice_date") in ids(out)
    locked = run(replace(INV, invoice_date=f("10-05-2026")), locked_periods=((date(2026, 5, 1), date(2026, 5, 31)),))
    assert ids(locked) == [("D-14", "error", "invoice_date")] and "locked" in only(locked, "D-14").message
    in_year = run(INV, financial_years=())
    assert in_year.findings == ()           # no financial year known: the voucher service's V-06 stays the authority


def test_D16_missing_or_non_numeric_hsn_is_a_review():
    assert ids(run(replace(INV, lines=(line(hsn=None), LINE2)))) == [("D-16", "review", "lines[0].hsn_sac")]
    assert ids(run(replace(INV, lines=(line(hsn="ABC"), LINE2)))) == [("D-16", "review", "lines[0].hsn_sac")]


# ---------------------------------------------------------------------------------------------- direction and registrations


def test_D08_purchase_whose_buyer_is_not_a_client_registration_is_an_error():
    res = run(replace(INV, buyer_gstin=f(OTHER_BUYER)))
    assert ("D-08", "error", "buyer_gstin") in ids(res)
    assert res.direction is None


def test_D08_sale_whose_supplier_is_not_a_client_registration_is_an_error():
    res = run(replace(INV, supplier_gstin=f(SUPPLIER_MH), buyer_gstin=f(OTHER_BUYER)), doc_type=DocType.SALES_INVOICE)
    assert ("D-08", "error", "supplier_gstin") in ids(res)


def test_D09_client_on_both_sides_is_a_review():
    res = run(replace(INV, supplier_gstin=f(CLIENT_GSTIN)))
    assert ids(res) == [("D-09", "review", None)]


def test_D09_client_on_neither_side_without_a_chosen_type_is_a_review():
    res = run(replace(INV, buyer_gstin=f(OTHER_BUYER)), doc_type=None)
    assert ids(res) == [("D-09", "review", None)]
    assert ids(run(replace(INV, buyer_gstin=f(OTHER_BUYER)), doc_type=DocType.OTHER)) == [("D-09", "review", None)]


def test_D09_document_looks_like_a_sale_but_was_uploaded_as_a_purchase():
    sale = replace(INV, supplier_gstin=f(CLIENT_GSTIN), buyer_gstin=f(OTHER_BUYER), place_of_supply=f("07-Delhi"),
                   lines=(INTER_LINE1, INTER_LINE2), totals=INTER.totals)
    res = run(sale, doc_type=DocType.PURCHASE_INVOICE)
    assert ids(res) == [("D-08", "error", "buyer_gstin"), ("D-09", "review", None)]
    assert run(sale, doc_type=DocType.SALES_INVOICE).direction == "sale"


def test_D08_client_without_any_gst_registration_skips_the_registration_checks_with_an_info():
    res = run(registrations=())
    assert [(x.rule_id, x.severity.value) for x in res.findings] == [("D-08", "info")]


def test_D11_composition_client_selling_charges_no_tax_so_printed_tax_is_flagged():
    comp = replace(client_reg(), registration_type="composition", composition_category="trader")
    sale = replace(INV, supplier_gstin=f(CLIENT_GSTIN), buyer_gstin=f(OTHER_BUYER), place_of_supply=f("27-Maharashtra"))
    res = run(sale, registrations=(comp,), doc_type=DocType.SALES_INVOICE)
    # a composition dealer charges no tax: the 18% printed on line 1 is wrong (rate nil), and the printed tax totals no longer match
    assert ("D-11", "error", "lines[0].gst_rate") in ids(res) and ("D-13", "error", "totals.cgst_total") in ids(res)


def test_D11_supplier_without_gstin_is_unregistered_and_cannot_charge_tax():
    res = run(replace(INV, supplier_gstin=f(None)))
    assert ("D-11", "error", "lines[0].gst_rate") in ids(res)
    assert res.lines[0].cgst == D("0.00")


def test_D12_place_of_supply_unreadable_is_a_review_and_override_is_used_when_given():
    unreadable = replace(INV, place_of_supply=f("somewhere"))
    assert ids(run(unreadable)) == [("D-12", "review", "place_of_supply")]
    missing = replace(INV, place_of_supply=f(None))
    res = run(missing)
    assert ids(res) == [("D-12", "info", "place_of_supply")]                               # taken from the buyer GSTIN state, said so
    assert res.place_of_supply == "27"
    nothing = replace(INV, place_of_supply=f(None), buyer_gstin=f(None))
    assert ("D-12", "review", "place_of_supply") in ids(run(nothing, registrations=()))
    assert run(nothing, registrations=(), place_of_supply_override="27").place_of_supply == "27"


def test_D12_place_of_supply_by_state_name_or_code():
    assert run(replace(INV, place_of_supply=f("Maharashtra"))).place_of_supply == "27"
    assert run(replace(INV, place_of_supply=f("27"))).place_of_supply == "27"
    assert run(INTER, ).place_of_supply == "27"


# ---------------------------------------------------------------------------------------------- duplicates


def test_D03_same_supplier_gstin_and_invoice_number_is_a_warning_naming_the_earlier_document():
    dup = DuplicateCandidate("voucher", "PUR/2026-27/0004", SUPPLIER_MH, "shree traders", " inv-77 ")
    res = run(duplicates=(dup,))
    assert ids(res) == [("D-03", "warning", "invoice_no")]
    assert "PUR/2026-27/0004" in only(res, "D-03").message
    other_no = DuplicateCandidate("voucher", "x", SUPPLIER_MH, None, "INV-78")
    other_supplier = DuplicateCandidate("extraction", "y", SUPPLIER_KA, None, "INV-77")
    assert run(duplicates=(other_no, other_supplier)).findings == ()


def test_D03_name_is_used_when_a_gstin_is_not_known():
    dup = DuplicateCandidate("extraction", "v2 of another document", None, "Shree  Traders", "INV-77")
    assert ids(run(duplicates=(dup,))) == [("D-03", "warning", "invoice_no")]


# ---------------------------------------------------------------------------------------------- bank statement


def bf(value, conf="0.95"):
    return Field(value, Source(1), D(conf) if conf else None)


def bline(date_="01-04-2026", narr="UPI/ABC", debit=None, credit=None, balance=None):
    return doc_bank.BankLine(bf(date_), bf(narr), bf(None), bf(debit), bf(credit), bf(balance))


STATEMENT = doc_bank.BankStatement(
    bf("Test Bank"), bf("<ACCOUNT_1>"), bf("01-04-2026"), bf("30-04-2026"), bf("1000.00"), bf("1800.00"),
    lines=(bline(credit="500.00", balance="1500.00"), bline("02-04-2026", "ATM", debit="200.00", balance="1300.00"),
           bline("03-04-2026", "SALARY", credit="500.00", balance="1800.00")))


def bank(st=STATEMENT, **kw):
    return doc_bank.check_bank_statement(st, doc_bank.BankCheckContext(today=date(2026, 11, 20), **kw))


def test_D18_clean_statement_has_no_finding():
    assert bank().findings == ()


def test_D18_running_balance_that_does_not_follow_the_movement_is_an_error_on_that_row_only():
    lines = list(STATEMENT.lines)
    lines[1] = bline("02-04-2026", "ATM", debit="200.00", balance="1200.00")      # should be 1,300.00
    res = bank(replace(STATEMENT, lines=tuple(lines)))
    # every row is checked against opening balance + movements so far; the other rows still agree, so only this row is flagged
    assert [(x.rule_id, x.severity.value, x.field_path) for x in res.findings] == [("D-18", "error", "lines[1].balance")]
    first = res.findings[0]
    assert (first.printed, first.computed) == ("1200.00", "1300.00")


def test_D18_closing_balance_must_equal_the_last_running_balance():
    res = bank(replace(STATEMENT, closing_balance=bf("1900.00")))
    assert [(x.rule_id, x.field_path) for x in res.findings] == [("D-18", "closing_balance")]


def test_D19_row_with_both_or_neither_debit_and_credit_is_an_error():
    both = replace(STATEMENT, lines=(bline(debit="10.00", credit="10.00", balance="1000.00"),), closing_balance=bf("1000.00"))
    assert next((x.rule_id, x.field_path) for x in bank(both).findings) == ("D-19", "lines[0]")
    neither = replace(STATEMENT, lines=(bline(balance="1000.00"),), closing_balance=bf("1000.00"))
    assert [(x.rule_id, x.field_path) for x in bank(neither).findings] == [("D-19", "lines[0]")]


def test_D06_bank_amounts_dates_and_required_fields():
    bad_amount = replace(STATEMENT, lines=(bline(credit="500.005", balance="1500.00"),) + STATEMENT.lines[1:])
    assert ("D-06", "lines[0].credit") in [(x.rule_id, x.field_path) for x in bank(bad_amount).findings]
    bad_date = replace(STATEMENT, lines=(bline("32-04-2026", credit="500.00", balance="1500.00"),) + STATEMENT.lines[1:])
    assert ("D-06", "lines[0].date") in [(x.rule_id, x.field_path) for x in bank(bad_date).findings]
    no_narr = replace(STATEMENT, lines=(bline(narr=None, credit="500.00", balance="1500.00"),) + STATEMENT.lines[1:])
    assert ("D-05", "lines[0].narration") in [(x.rule_id, x.field_path) for x in bank(no_narr).findings]
    assert ("D-05", "lines") in [(x.rule_id, x.field_path) for x in bank(replace(STATEMENT, lines=())).findings]


def test_D05_bank_low_confidence_is_a_warning_and_overdrawn_balance_is_signed():
    low = replace(STATEMENT, bank_name=bf("Test Bank", conf="0.5"))
    assert [(x.rule_id, x.severity.value, x.field_path) for x in bank(low).findings] == [("D-05", "warning", "bank_name")]
    od = replace(STATEMENT, opening_balance=bf("100.00"), closing_balance=bf("-100.00"),
                 lines=(bline(debit="200.00", balance="-100.00"),))
    assert bank(od).findings == ()
