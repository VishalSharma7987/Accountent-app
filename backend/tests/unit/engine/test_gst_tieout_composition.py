from datetime import date
from decimal import Decimal as D

from gst_returns_helpers import doc, item

from app.engine.composition import CompositionRule, build_composition
from app.engine.gst_tieout import Cause, build_tieout, filed_gstr1_totals, filed_gstr3b_totals

Z = D(0)


def figs(taxable, igst="0", cgst="0", sgst="0", cess="0"):
    return {"taxable_value": D(taxable), "igst": D(igst), "cgst": D(cgst), "sgst": D(sgst), "cess": D(cess)}


def itc_heads(igst="0", cgst="0", sgst="0", cess="0"):
    return {"igst": D(igst), "cgst": D(cgst), "sgst": D(sgst), "cess": D(cess)}


def run(books, g1, g3, f1=None, f3=None, causes=()):
    return build_tieout(books, g1, g3, f1, f3, itc_heads(), itc_heads(), itc_heads(), itc_heads(), list(causes))


def test_G53_everything_agrees_ties_true():
    f = figs("1000", cgst="90", sgst="90")
    r = run(f, f, f)
    assert r.ties is True
    assert [row["d_books_gstr1"] for row in r.rows] == [Z] * 5


def test_G53_manual_journal_on_output_ledger_shows_difference_and_cause_not_forced():
    books = figs("1000", cgst="95", sgst="90")  # 5.00 extra credited to Output CGST by a manual journal
    g = figs("1000", cgst="90", sgst="90")
    cause = Cause("manual_journal_on_tax_ledger", "JRN/2026-27/0003", D("5.00"), "cgst")
    r = run(books, g, g, causes=[cause])
    cgst = next(x for x in r.rows if x["head"] == "cgst")
    assert cgst["d_books_gstr1"] == D(5) and cgst["d_gstr1_gstr3b"] == Z
    assert r.ties is False
    assert r.causes == [cause]


def test_G53_gstr1_and_gstr3b_working_differ():
    r = run(figs("1000"), figs("1000"), figs("900"))
    assert next(x for x in r.rows if x["head"] == "taxable_value")["d_gstr1_gstr3b"] == D(100)
    assert r.ties is False


def test_G53_filed_figures_enter_only_when_typed():
    f = figs("1000")
    assert run(f, f, f).rows[0]["filed_gstr1"] is None
    assert run(f, f, f).rows[0]["d_books_filed"] is None
    r = run(f, f, f, f1={"taxable_value": D(990), "igst": None, "cgst": None, "sgst": None, "cess": None})
    assert r.rows[0]["d_books_filed"] == D(10)
    assert r.rows[1]["d_books_filed"] is None
    assert r.ties is False


def test_G53_filed_totals_are_read_from_the_entered_data():
    assert filed_gstr1_totals({"totals": {"taxable_value": "1000.00", "igst": "0.00"}})["taxable_value"] == D("1000.00")
    assert filed_gstr1_totals({}) is None
    t31 = {"a_outward_taxable": {"taxable_value": "800.00"}, "c_nil_exempt": {"taxable_value": "50.00"}}
    assert filed_gstr3b_totals({"t3_1": t31})["taxable_value"] == D("850.00")
    assert filed_gstr3b_totals({"t3_1": t31})["igst"] is None


def test_G52_itc_difference_between_books_and_register_is_shown_per_head():
    f = figs("0")
    r = build_tieout(f, f, f, None, None, itc_heads(cgst="100"), itc_heads(cgst="80"), itc_heads(cgst="80"),
                     itc_heads(cgst="15"), [])
    assert r.itc["cgst"]["d_books_register_pending"] == D(5)  # 100 - 80 - 15
    assert r.itc["cgst"]["d_register_gstr3b"] == Z
    assert r.ties is False


RULE = CompositionRule("trader", D(1), D(15000000), "taxable_turnover", "pending")
FY = date(2026, 4, 1)


def cdoc(number, month, day, taxable, *, vtype="sales", treatment="taxable", tax="0"):
    return doc(number, vtype, "b2c", "27", taxable, [item(taxable, "0", treatment=treatment, cgst=tax)], month=month, day=day)


def test_G54_quarter_tax_is_turnover_times_rate_split_into_cgst_and_sgst():
    docs = [cdoc("S1", 4, 5, "100000"), cdoc("S2", 5, 5, "50000"), cdoc("C1", 6, 1, "10000", vtype="credit_note")]
    r = build_composition(RULE, docs, date(2026, 4, 1), date(2026, 6, 30), FY).working
    # 100,000 + 50,000 - 10,000 = 140,000; 1% = 1,400.00 = 700.00 + 700.00
    assert r["quarter_turnover"] == D(140000)
    assert r["tax"] == {"cgst": D("700.00"), "sgst": D("700.00"), "total": D("1400.00")}
    assert r["rate_status"] == "pending" and r["limit_crossed"] is False


def test_G54_taxable_turnover_basis_leaves_out_exempt_but_state_turnover_basis_keeps_it():
    docs = [cdoc("S1", 4, 5, "100000"), cdoc("S2", 4, 6, "20000", treatment="exempt")]
    q = (date(2026, 4, 1), date(2026, 6, 30))
    assert build_composition(RULE, docs, *q, FY).working["quarter_turnover"] == D(100000)
    all_rule = CompositionRule("trader", D(1), D(15000000), "turnover_in_state", "pending")
    assert build_composition(all_rule, docs, *q, FY).working["quarter_turnover"] == D(120000)


def test_G54_limit_crossed_uses_year_to_date_and_is_a_flag():
    docs = [cdoc("S1", 4, 5, "14000000"), cdoc("S2", 8, 5, "900000"), cdoc("S3", 8, 9, "200000")]
    r = build_composition(RULE, docs, date(2026, 7, 1), date(2026, 9, 30), FY)
    assert r.working["quarter_turnover"] == D(1100000)
    assert r.working["ytd_turnover"] == D(15100000)
    assert r.working["limit_crossed"] is True
    assert any("above the composition limit" in w for w in r.warnings)


def test_G54_ytd_exactly_at_limit_is_not_crossed():
    r = build_composition(RULE, [cdoc("S1", 4, 5, "15000000")], date(2026, 4, 1), date(2026, 6, 30), FY).working
    assert r["limit_crossed"] is False


def test_G54_invoice_with_tax_on_a_composition_client_is_listed():
    r = build_composition(RULE, [cdoc("S1", 4, 5, "1000", tax="9")], date(2026, 4, 1), date(2026, 6, 30), FY)
    assert r.working["invoices_with_tax"] == [{"voucher_number": "S1", "invoice_date": date(2026, 4, 5), "tax": D(9)}]


def test_G54_odd_paise_use_half_up_on_each_half():
    # 1% of 1.50 = 0.015 total -> each half 0.0075 -> 0.01 (half-up on the half, as the invoice tax does)
    r = build_composition(RULE, [cdoc("S1", 4, 5, "1.50")], date(2026, 4, 1), date(2026, 6, 30), FY).working
    assert r["tax"] == {"cgst": D("0.01"), "sgst": D("0.01"), "total": D("0.02")}
