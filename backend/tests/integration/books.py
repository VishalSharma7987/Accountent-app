"""The Step 1.3 mini case as committed books (used by the periods/reports and API tests).

See test_periods_reports.py for the hand-calculated numbers.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from app.engine.models import VoucherDraft, VoucherLine
from app.services import client_setup
from app.services.client_setup import ClientProfile


@dataclass
class Books:
    client_id: object
    fy_id: object
    ids: dict
    period_ids: dict  # "2026-04" -> period id
    voucher_ids: dict  # "v1" -> voucher id


def build_books(conn, name="ABC Traders") -> Books:
    created = client_setup.create_client(
        conn, ClientProfile(name, "proprietorship", "trading", "regular"),
        fy_start=date(2026, 4, 1), actor="setup", proprietor_name="Owner",
    )
    ids = dict(created.ledger_ids)
    for ledger, group in (("HDFC Bank", "bank_accounts"), ("Rahul Enterprises", "sundry_debtors"),
                          ("Sharma Suppliers", "sundry_creditors")):
        ids[ledger] = client_setup.add_ledger(conn, created.client_id, ledger, group, actor="setup")
    for ledger, debit, credit in (("Cash", "50000", None), ("HDFC Bank", "300000", None),
                                  ("Opening Stock", "100000", None), ("Owner Capital A/c", None, "450000")):
        client_setup.set_opening_balance(conn, created.client_id, created.financial_year_id, ids[ledger],
                                         debit, credit, actor="setup")
    period_ids = {
        start.strftime("%Y-%m"): pid for pid, start in conn.execute(
            text("SELECT id, period_start FROM periods WHERE financial_year_id = :fy"), {"fy": created.financial_year_id})
    }
    return Books(created.client_id, created.financial_year_id, ids, period_ids, {})


def draft(b, vtype, on, narration, lines, reference_no=None, party=None):
    return VoucherDraft(b.client_id, vtype, on, narration, reference_no, b.ids[party] if party else None,
                        tuple(VoucherLine(b.ids[n], dr, cr) for n, dr, cr in lines))


def mini_case(b):
    return {
        "v1": draft(b, "payment", date(2026, 4, 2), "April rent", [("Rent", "20000", None), ("Cash", None, "20000")]),
        "v2": draft(b, "purchase", date(2026, 4, 3), "Goods from Sharma", [("Purchases", "50000", None), ("Sharma Suppliers", None, "50000")], "SUP/889", "Sharma Suppliers"),
        "v3": draft(b, "sales", date(2026, 4, 5), "Goods to Rahul", [("Rahul Enterprises", "80000", None), ("Sales", None, "80000")], None, "Rahul Enterprises"),
        "v4": draft(b, "receipt", date(2026, 4, 10), "Received from Rahul", [("HDFC Bank", "30000", None), ("Rahul Enterprises", None, "30000")], None, "Rahul Enterprises"),
        "v5": draft(b, "payment", date(2026, 4, 12), "Paid Sharma", [("Sharma Suppliers", "15000", None), ("HDFC Bank", None, "15000")]),
        "v6": draft(b, "contra", date(2026, 4, 15), "Cash deposited", [("HDFC Bank", "10000", None), ("Cash", None, "10000")]),
        "v7": draft(b, "payment", date(2026, 4, 20), "Owner withdrew cash", [("Drawings A/c", "5000", None), ("Cash", None, "5000")]),
    }


