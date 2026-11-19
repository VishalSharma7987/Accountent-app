"""Phase 6 package E against the database: Cash Flow (F-49, F-50) and Excel / PDF export (F-70, F-71) over POSTED vouchers.
Hand-calculated expected values, same books as test_final_statements_db.proprietor_books:
Opening: Dr Opening Stock 2,00,000 + Cash 3,00,000 = Cr Capital 5,00,000. Posted: purchases 1,00,000 (cash), sales 2,50,000 (cash),
salary 20,000 (cash). Closing stock 1,50,000 less 10,000 = 1,40,000. Net profit 70,000 (trading profit 90,000 less salary 20,000).
Cash flow: profit 70,000 + decrease in stock (2,00,000 - 1,40,000) 60,000 = 1,30,000 from operations; investing 0; financing 0;
cash 3,00,000 -> 4,30,000 (net 1,30,000), equal to the balance sheet cash.
"""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from test_final_statements_db import World

from app.api.deps import get_conn
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def api(svc_conn):
    app.dependency_overrides[get_conn] = lambda: svc_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_F49_F50_cash_flow_and_F71_export_over_posted_books(svc_conn, api):
    w = World(svc_conn)
    w.proprietor_books()
    q = {"financial_year_id": str(w.fy)}
    base = f"/clients/{w.c}/final"

    # no approved closing stock: the cash flow is blocked and nothing is exported (F-41 -> F-71)
    blocked = api.get(f"{base}/cash-flow", params=q)
    assert blocked.status_code == 422 and blocked.json()["code"] == "statement_blocked"
    refused = api.get(f"{base}/export", params={**q, "format": "xlsx"})
    assert refused.status_code == 422 and refused.json()["code"] == "export_blocked"

    w.stock_manual()
    cf = api.get(f"{base}/cash-flow", params=q)
    assert cf.status_code == 200
    body = cf.json()
    assert body["key"] == "cash_flow"
    assert body["totals"] == {"cash_from_operations": "130000.00", "investing": "0.00", "financing": "0.00", "net_increase": "130000.00",
                              "opening_cash": "300000.00", "closing_cash": "430000.00", "balance_sheet_cash": "430000.00", "difference": "0.00"}

    xlsx = api.get(f"{base}/export", params={**q, "format": "xlsx", "statements": "trading,profit_loss,balance_sheet,cash_flow"})
    assert xlsx.status_code == 200 and "attachment" in xlsx.headers["content-disposition"] and ".xlsx" in xlsx.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(xlsx.content))
    assert wb.sheetnames == ["Trading", "Profit and Loss", "Balance Sheet", "Cash Flow", "Ledgers"]
    cells = [str(c.value) for row in wb["Cash Flow"].iter_rows() for c in row if c.value is not None]
    assert "fin-1" in cells and any("01-04-2026" in c for c in cells)
    assert any(c.hyperlink for row in wb["Trading"].iter_rows() for c in row)

    pdf = api.get(f"{base}/export", params={**q, "format": "pdf", "layout": "vertical"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    for kind in ("register", "adjustments"):
        r = api.get(f"{base}/export/{kind}", params={**q, "format": "xlsx"})
        assert r.status_code == 200, r.text
    assert api.get(f"{base}/export/nonsense", params=q).status_code == 422
    assert api.get(f"{base}/export", params={**q, "format": "doc"}).status_code == 422
