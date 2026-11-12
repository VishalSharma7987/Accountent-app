"""MSME payment-due report (M-01): open supplier bills of micro/small suppliers past their legal due date.

A report, never a block. The rule rows come from `msme_payment_rules` and carry their verification status
('pending' until the owner/CA has checked the legal text); the report shows that status."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories_cash as cash_repo
from app.engine import msme as engine
from app.engine.models import OpenBill
from app.rules.msme import load_msme_rules
from app.services import queries


def msme_report(
    conn: Connection, client_id: object, as_on: date, open_bills: Sequence[OpenBill] | None = None
) -> engine.MsmeReport:
    """open_bills: the client's open items as on `as_on`; when None they come from services.bills.open_bills."""
    queries.require_client(conn, client_id)
    if open_bills is None:
        from app.services.bills import (
            open_bills as load_open_bills,  # Phase 2 step 2.2 (same release)
        )

        open_bills = load_open_bills(conn, client_id, as_on)
    rules = load_msme_rules(conn)
    flags = engine.flag_msme_overdue(open_bills, cash_repo.party_facts(conn, client_id), rules, as_on)
    status, source = engine.rules_status(rules, as_on)
    total = sum((f.outstanding for f in flags), Decimal("0.00"))
    return engine.MsmeReport(as_on, status, source, tuple(flags), total)
