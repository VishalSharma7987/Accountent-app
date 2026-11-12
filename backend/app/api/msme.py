from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.schemas import money
from app.api.schemas_cash import MsmeDueOut, MsmeItemOut
from app.services import msme

router = APIRouter(tags=["reports"])


@router.get("/clients/{client_id}/reports/msme-due", response_model=MsmeDueOut)
def msme_due(client_id: str, as_on: date, conn: Connection = Depends(get_conn)):
    """Open bills of micro/small suppliers past their legal due date. `rule_status` stays "pending" until the
    legal rule rows are verified."""
    r = msme.msme_report(conn, parse_id(client_id, "Client"), as_on)
    return MsmeDueOut(
        as_on=r.as_on, rule_status=r.rule_status, rule_source=r.rule_source, total_outstanding=money(r.total_outstanding),
        items=[
            MsmeItemOut(
                party_ledger_id=i.party_ledger_id, party_name=i.party_name, bill_ref=i.bill_ref, bill_date=i.bill_date,
                legal_days=i.legal_days, legal_due_date=i.legal_due_date, days_overdue=i.days_overdue,
                outstanding=money(i.outstanding), rule_status=i.rule_status, rule_source=i.rule_source,
            )
            for i in r.items
        ],
    )
