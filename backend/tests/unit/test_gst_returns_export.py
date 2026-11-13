"""Exports must carry exactly the figures of the working (round trip from the file). Literal expected values."""

import io
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent / "engine"))
from gst_returns_helpers import REG, april_docs

from app.engine.gstr1 import build_gstr1
from app.engine.gstr3b import build_gstr3b
from app.services import gst_export
from app.services.gst_returns import jsonable

STATUS = {"worst": "pending", "tables": {"thresholds": "pending"}, "pending_sources": ["B2CL limit source"]}


def envelope(tables):
    return {"gstin": "27AAPFU0939F1ZV", "period_start": "2026-04-01", "period_end": "2026-04-30", "generated_at": "x",
            "source_voucher_count": 9, "rule_status": STATUS, "warnings": ["a warning"], "tables": tables,
            "unposted_drafts_in_period": []}


def gstr1_env():
    return envelope(jsonable(build_gstr1(april_docs(), [], REG, D(250000)).tables))


def gstr3b_env():
    return envelope(jsonable(build_gstr3b(april_docs(), [], [], [], REG, date(2026, 4, 1), date(2026, 4, 30)).tables))


def test_G55_jsonable_formats_amounts_rates_and_quantities():
    out = jsonable({"taxable_value": D(1000), "rate": D("18.0000"), "quantity": D(14), "d": date(2026, 4, 1)})
    assert out == {"taxable_value": "1000.00", "rate": "18", "quantity": "14.000", "d": "2026-04-01"}


def test_G55_excel_first_sheet_lists_rule_status_pending_sources_and_warnings():
    wb = load_workbook(io.BytesIO(gst_export.working_to_xlsx(gstr1_env(), "GSTR-1 working")))
    first = [[c for c in row] for row in wb["Summary"].iter_rows(values_only=True)]
    assert ["Worst rule status", "pending"] in first
    assert ["PENDING rule, to be verified", "B2CL limit source"] in first
    assert ["Warning", "a warning"] in first


def test_G51_excel_hsn_sheet_has_numbers_equal_to_the_working():
    wb = load_workbook(io.BytesIO(gst_export.working_to_xlsx(gstr1_env(), "GSTR-1 working")))
    ws = wb["hsn_summary"]
    header = [c.value for c in ws[1]]
    rows = [dict(zip(header, [c.value for c in r], strict=True)) for r in ws.iter_rows(min_row=2)]
    r = next(x for x in rows if x["hsn_sac"] == "1001" and x["rate"] == D(18))
    assert isinstance(r["taxable_value"], (int, float, D))
    assert D(str(r["taxable_value"])) == D(303700)
    assert D(str(r["igst"])) == D(54360)
    assert D(str(r["quantity"])) == D(14)
    assert ws.cell(row=2, column=header.index("taxable_value") + 1).number_format == "0.00"


def test_G52_excel_gstr3b_sheet_lines_equal_the_working():
    wb = load_workbook(io.BytesIO(gst_export.working_to_xlsx(gstr3b_env(), "GSTR-3B working")))
    ws = wb["t3_1"]
    header = [c.value for c in ws[1]]
    rows = {r[header.index("line")].value: [c.value for c in r] for r in ws.iter_rows(min_row=2)}
    a = rows["a_outward_taxable"]
    assert D(str(a[header.index("taxable_value")])) == D(303900)
    assert D(str(a[header.index("cgst")])) == D(158)


def test_G50_gstr1_json_figures_equal_the_working():
    j = gst_export.gstr1_json(gstr1_env())
    assert j["gstin"] == "27AAPFU0939F1ZV" and j["fp"] == "042026"
    b2b_vals = [i["val"] for p in j["b2b"] for i in p["inv"]]
    assert b2b_vals == [1180.0, 790.0, 2360.0]
    assert j["b2b"][0]["inv"][1]["idt"] == "06-04-2026"
    assert j["b2cs"] == [{"sply_ty": "INTRA", "pos": "27", "typ": "OE", "rt": 18.0, "txval": 300.0, "iamt": 0.0,
                          "camt": 27.0, "samt": 27.0, "csamt": 0.0}]
    assert j["nil"]["inv"][3] == {"sply_ty": "INTRAB2C", "expt_amt": 0.0, "nil_amt": 400.0, "ngsup_amt": 0.0}
    assert j["hsn"]["data"][0]["hsn_sc"] == "0401"
    assert sum(r["txval"] for r in j["hsn"]["data"]) == 309300.0


def test_G52_gstr3b_json_figures_equal_the_working():
    j = gst_export.gstr3b_json(gstr3b_env())
    assert j["ret_period"] == "042026"
    assert j["sup_details"]["osup_det"] == {"txval": 303900.0, "iamt": 54360.0, "camt": 158.0, "samt": 158.0, "csamt": 0.0}
    assert j["sup_details"]["osup_zero"]["txval"] == 5000.0
    assert j["sup_details"]["osup_nil_exmp"]["txval"] == 400.0
    assert j["inter_sup"]["unreg_details"] == [{"pos": "29", "txval": 300000.0, "iamt": 54000.0}]
