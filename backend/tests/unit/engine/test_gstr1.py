from datetime import date
from decimal import Decimal as D

import pytest
from gst_returns_helpers import REG, X, april_docs, doc, item

from app.engine.gstr1 import NumberRow, build_gstr1, period_end

LIMIT = D(250000)


def run(docs=None, numbers=()):
    return build_gstr1(docs if docs is not None else april_docs(), list(numbers), REG, LIMIT)


def test_G50_b2b_groups_by_party_and_merges_rates_inside_an_invoice():
    t = run().tables
    assert [p["party_gstin"] for p in t["b2b"]] == ["27AAAAA0000A1Z5", "29BBBBB1111B1Z6"]
    x = t["b2b"][0]["invoices"]
    assert [i["invoice_no"] for i in x] == ["SAL/0001", "SAL/0002"]
    assert x[1]["items"] == [
        {"rate": D(5), "taxable_value": D(200), "igst": D(0), "cgst": D(5), "sgst": D(5), "cess": D(0)},
        {"rate": D(18), "taxable_value": D(500), "igst": D(0), "cgst": D(45), "sgst": D(45), "cess": D(0)},
    ]
    assert x[1]["invoice_value"] == D(790)


def test_G50_inter_state_b2c_above_limit_is_b2cl_and_the_rest_is_b2cs():
    t = run().tables
    assert [r["place_of_supply"] for r in t["b2cl"]] == ["29"]
    assert t["b2cl"][0]["invoices"][0]["invoice_no"] == "SAL/0004"
    # SAL/0005 + SAL/0006 aggregate by place of supply and rate: taxable 100 + 200, cgst 9 + 18
    assert t["b2cs"] == [{"place_of_supply": "27", "rate": D(18), "taxable_value": D(300),
                          "igst": D(0), "cgst": D(27), "sgst": D(27), "cess": D(0)}]


def test_G50_b2c_inter_state_exactly_at_the_limit_stays_b2cs():
    d = doc("SAL/1", "sales", "b2c", "29", "250000", [item("211864.41", igst="38135.59")])
    t = run([d]).tables
    assert t["b2cl"] == []
    assert t["b2cs"][0]["place_of_supply"] == "29"


def test_G50_export_without_payment_is_listed_with_type():
    t = run().tables
    assert [e["export_type"] for e in t["exports"]] == ["without_payment"]
    assert t["exports"][0]["invoices"][0]["place_of_supply"] == "96"


def test_G50_credit_note_to_registered_party_goes_to_cdnr_as_type_C():
    t = run().tables
    n = t["cdnr"][0]["notes"][0]
    assert t["cdnr"][0]["party_gstin"] == X
    assert (n["note_no"], n["note_type"], n["original_invoice_no"]) == ("CN/0001", "C", "SAL/0001")
    assert n["items"][0]["taxable_value"] == D(100)


def test_G50_credit_note_to_unregistered_goes_to_cdnur():
    cn = doc("CN/2", "credit_note", "b2c", "27", "118", [item("100", cgst="9", sgst="9")], orig="SAL/5")
    t = run([cn]).tables
    assert t["cdnur"][0]["note_no"] == "CN/2"
    assert t["cdnur"][0]["unregistered_type"] == "B2CL"
    assert t["cdnr"] == []


def test_G21_nil_item_goes_to_table_8_only_and_is_not_in_b2cs():
    t = run().tables
    assert t["nil_exempt_non_gst"]["intra_unregistered"] == {"nil_rated": D(400), "exempt": D(0), "non_gst": D(0)}
    assert all(r["taxable_value"] != D(400) for r in t["b2cs"])


def test_G50_mixed_invoice_splits_taxable_to_b2b_and_exempt_to_table_8():
    d = doc("SAL/9", "sales", "b2b", "27", "1090", [item("1000", cgst="45", sgst="45", no=1),
                                                     item("50", "0", treatment="exempt", no=2, hsn="0402")], gstin=X)
    t = run([d]).tables
    assert t["b2b"][0]["invoices"][0]["items"][0]["taxable_value"] == D(1000)
    assert t["nil_exempt_non_gst"]["intra_registered"]["exempt"] == D(50)


def test_G50_document_that_fits_no_table_is_reported_not_guessed():
    d = doc("SAL/10", "sales", "b2b", "27", "118", [item("100", cgst="9", sgst="9")], gstin=None)
    r = run([d])
    assert r.tables["b2b"] == []
    assert r.tables["unclassified"][0]["voucher_number"] == "SAL/10"
    assert "cannot be placed" in r.warnings[0]


def test_G51_totals_net_of_credit_notes_and_hsn_equals_item_totals():
    t = run().tables
    # hand-added: taxable 309,300.00, igst 54,360.00, cgst = sgst = 158.00
    assert t["totals"] == {"taxable_value": D(309300), "igst": D(54360), "cgst": D(158), "sgst": D(158), "cess": D(0)}
    hsn = t["hsn_summary"]
    assert sum(r["taxable_value"] for r in hsn) == t["totals"]["taxable_value"]
    assert sum(r["igst"] for r in hsn) == D(54360)
    r1001 = next(r for r in hsn if r["hsn_sac"] == "1001" and r["rate"] == D(18))
    # 1001 at 18%: invoices 1 (qty 10), 2 (qty 1), 3, 4, 5, 6 (qty 1 each) less the credit note (qty 1): 10+1+1+1+1+1-1 = 14
    assert r1001["quantity"] == D(14)
    assert r1001["taxable_value"] == D(303700)  # 1000+500+2000+300000+100+200-100
    assert r1001["total_value"] == D(303700) + D(54360) + D(153) + D(153)


def test_G50_documents_issued_counts_cancelled_and_net():
    nums = [NumberRow("sales", f"SAL/{i:04d}", i == 2) for i in (1, 2, 3, 4)] + [NumberRow("sales", "SAL/0005", True),
                                                                                  NumberRow("credit_note", "CN/0001", False)]
    di = run(numbers=nums).tables["documents_issued"]
    assert di == [
        {"nature": "Invoices for outward supply", "from_no": "SAL/0001", "to_no": "SAL/0005", "total": 5, "cancelled": 2, "net_issued": 3},
        {"nature": "Credit Note", "from_no": "CN/0001", "to_no": "CN/0001", "total": 1, "cancelled": 0, "net_issued": 1},
    ]


def test_G55_portal_table_numbers_are_flagged_pending():
    t = run().tables
    assert t["portal_tables"]["b2b"] == "4"
    assert t["portal_tables_status"] == "pending"


@pytest.mark.parametrize(
    ("kind", "start", "end"),
    [("month", date(2026, 4, 1), date(2026, 4, 30)), ("month", date(2028, 2, 1), date(2028, 2, 29)),
     ("quarter", date(2026, 4, 1), date(2026, 6, 30)), ("quarter", date(2026, 10, 1), date(2026, 12, 31)),
     ("quarter", date(2027, 1, 1), date(2027, 3, 31))],
)
def test_G56_period_end(kind, start, end):
    assert period_end(kind, start) == end


@pytest.mark.parametrize(("kind", "start"), [("month", date(2026, 4, 2)), ("quarter", date(2026, 5, 1)), ("year", date(2026, 4, 1))])
def test_G56_period_start_must_be_a_real_period_start(kind, start):
    with pytest.raises(ValueError):
        period_end(kind, start)
