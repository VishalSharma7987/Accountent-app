"""Package E: Excel output of the inventory reports (S-16 header: method and as-on date; numbers as numbers)."""

from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from app.services.inventory_export import closing_stock_to_xlsx, register_to_xlsx

POLICY = {"valuation_method": "wa_periodic", "negative_stock_mode": "block"}


def test_S16_closing_stock_export_header_and_numbers():
    report = {"policy": POLICY, "as_on": "2027-03-31", "errors": [], "warnings": [
        {"severity": "warning", "rule_id": "S-15", "date": "2027-03-31", "message": "No NRV"}],
        "rows": [{"sku": "W-1", "name": "Widget", "uqc": "NOS", "closing_qty": "70.000", "cost_value": "1050.00",
                  "nrv_per_unit": "13.50", "nrv_value": "945.00", "write_down": "105.00", "carrying_value": "945.00"}],
        "totals": {"cost_value": "1050.00", "write_down": "105.00", "carrying_value": "945.00"}}
    wb = load_workbook(BytesIO(closing_stock_to_xlsx(report)))
    ws = wb["Closing stock"]
    assert ws["B2"].value == "Weighted average (periodic)" and ws["B4"].value == "2027-03-31"
    assert [c.value for c in ws[6]][:3] == ["SKU", "Item", "Unit"]
    assert ws["E7"].value == Decimal("1050.00") and ws["H7"].value == Decimal("105.00")
    assert ws["H8"].value == Decimal("105.00")
    assert wb["Findings"]["B2"].value == "S-15"


def test_S16_register_export_by_godown_has_empty_value_cells():
    report = {"policy": POLICY, "from": "2026-04-01", "to": "2026-04-30", "godown_name": "Shop", "errors": [], "warnings": [],
              "totals": None,
              "rows": [{"sku": "W-1", "name": "Widget", "uqc": "NOS", "opening_qty": "0.000", "opening_value": None,
                        "inward_qty": "200.000", "inward_value": None, "outward_qty": "150.000", "outward_value": None,
                        "closing_qty": "50.000", "closing_value": None}]}
    ws = load_workbook(BytesIO(register_to_xlsx(report)))["Stock register"]
    assert ws["B4"].value == "2026-04-01 to 2026-04-30" and ws["B6"].value == "Shop"
    assert ws["F8"].value == Decimal("200.000") and ws["G8"].value is None and ws["J8"].value == Decimal("50.000") and ws["K8"].value is None
