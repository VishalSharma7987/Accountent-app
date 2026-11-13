"""Internal consistency of the Phase 3 pack docs/test-packs/phase3-sunrise-traders-apr-2026 (no database, no service).

Plain csv / Decimal addition only; the totals asserted here are typed literally (hand-calculated, see WORKING.md).
"""

import csv
from decimal import Decimal as D
from pathlib import Path

from pack_loader_p3 import load_pack_p3

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase3-sunrise-traders-apr-2026"


def rows(name: str) -> list[dict]:
    with open(PACK / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_pack_loads_and_counts():
    pack = load_pack_p3(PACK)
    assert len(pack.invoices) == 14 and len(pack.payments) == 4 and len(pack.wrong_cases) == 8
    assert set(pack.gstr2b) == {"gstr2b_042026.json", "gstr2b_052026.json"}
    assert sum(r["opening_dr"] for r in pack.ledgers) == sum(r["opening_cr"] for r in pack.ledgers) == D("700000.00")


def test_expected_items_add_up_to_the_party_amounts():
    items = rows("expected_invoice_items.csv")
    for inv in rows("expected_invoices.csv"):
        mine = [i for i in items if i["ref_id"] == inv["ref_id"]]
        taxable = sum(D(i["taxable_value"]) for i in mine)
        tax = sum(D(i[h]) for i in mine for h in ("cgst", "sgst", "igst", "cess"))
        if inv["has_rcm"] == "true":
            assert D(inv["party_amount"]) == taxable, inv["ref_id"]  # supplier is paid the taxable value only
        else:
            assert D(inv["party_amount"]) == taxable + tax, inv["ref_id"]


def test_gstr1_totals_equal_the_sum_of_the_sales_items_less_the_credit_note():
    items = rows("expected_invoice_items.csv")
    sign = {"S": 1, "C": -1}
    sales = [i for i in items if i["ref_id"][0] in "SC"]
    want = rows("expected_gstr1.csv")[-1]
    assert want["table"] == "totals"
    for column in ("taxable_value", "igst", "cgst", "sgst", "cess"):
        assert sum(sign[i["ref_id"][0]] * D(i[column]) for i in sales) == D(want[column]), column
    assert (D(want["taxable_value"]), D(want["igst"]), D(want["cgst"])) == (D("400660.00"), D("59220.00"), D("5116.50"))


def test_gstr3b_outward_equals_gstr1_totals_and_ledgers_tie():
    t3 = {r["row_key"]: r for r in rows("expected_gstr3b.csv") if r["table"] == "t3_1"}
    outward = sum(D(t3[k]["taxable_value"]) for k in ("a_outward_taxable", "b_zero_rated", "c_nil_exempt", "e_non_gst"))
    assert outward == D("400660.00")
    ledgers = {r["ledger_name"]: D(r["amount"]) for r in rows("expected_ledger_balances.csv")}
    assert ledgers["Sales"] + ledgers["Service Income"] - ledgers["Sales Returns"] == outward
    assert ledgers["Output CGST"] == ledgers["Output SGST"] == D(t3["a_outward_taxable"]["cgst"])
    assert ledgers["Output IGST"] == D(t3["a_outward_taxable"]["igst"])


def test_reconciliation_totals_are_the_sum_of_the_rows():
    t = {r["side"]: r for r in rows("expected_reconciliation_totals.csv")}
    for column in ("taxable_value", "igst", "cgst", "sgst", "cess"):
        assert D(t["doc_2b"][column]) - D(t["books"][column]) == D(t["difference"][column]), column


def test_itc_register_heads_agree_with_the_invoice_items():
    items = {(i["ref_id"]): i for i in rows("expected_invoice_items.csv")}
    for e in rows("expected_itc.csv"):
        i = items[e["ref_id"]]
        assert (D(e["cgst"]), D(e["sgst"]), D(e["igst"])) == (D(i["cgst"]), D(i["sgst"]), D(i["igst"])), e["ref_id"]


def test_exposure_fraction_is_outstanding_over_bill():
    p1 = next(r for r in rows("expected_exposure.csv") if r["ref_id"] == "P1")
    assert D(p1["outstanding"]) / D("129800.00") == D(p1["fraction"]) == D("0.5000")
    assert D(p1["cgst"]) == D("9900.00") * D(p1["fraction"])
