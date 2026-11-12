"""Builders for importer tests: small .xlsx files made with openpyxl."""

import io
import re
import zipfile
from datetime import date

from openpyxl import Workbook

from app.importers.voucher_excel import COLUMNS


def make_xlsx(rows, *, header=COLUMNS, sheet_title="Vouchers") -> bytes:
    """rows = list of lists (one list per Excel row below the header; None = empty cell)."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def inject_cached_value(data: bytes, cell_ref: str, value: str) -> bytes:
    """Give a formula cell the 'saved result' Excel would have stored (openpyxl writes formulas without one)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                text = content.decode("utf-8")
                pattern = re.compile(rf'(<c r="{cell_ref}"[^>]*><f>[^<]*</f>)<v\s*/>')
                assert pattern.search(text), "formula cell not found"
                content = pattern.sub(rf"\g<1><v>{value}</v>", text).encode("utf-8")
            target.writestr(name, content)
    return out.getvalue()


# a correct two-line payment and a correct two-line sale, as rows of the sheet
APRIL_5 = date(2026, 4, 5)
GOOD_ROWS = [
    ["V1", APRIL_5, "payment", "Rent", 10000, None, "April rent", None, None],
    ["V1", APRIL_5, "payment", "Cash", None, 10000, "April rent", None, None],
    ["V2", "2026-04-06", "sales", "Rahul Enterprises", "5,000.50", None, "Sale to Rahul", "INV-1", "Rahul Enterprises"],
    ["V2", "2026-04-06", "sales", "Sales", None, "5000.50", "Sale to Rahul", "INV-1", "Rahul Enterprises"],
]
