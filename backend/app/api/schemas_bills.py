"""Request and response models for parties, opening bills, open bills, outstanding and ageing (Phase 2).

Amounts are strings with 2 decimals; a `Balance` is {amount (positive), side}. Report amounts are in the report's
direction (receivable: Dr; payable: Cr), so an advance or on-account amount shows on the opposite side.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.api.schemas import BalanceOut, balance_out, money
from app.engine.bills import AgeingReport
from app.engine.models import Balance
from app.services.parties import Party

# ------------------------------------------------------------------------------------------------- parties


class PartyIn(BaseModel):
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    credit_days: int | float | str = 0
    msme_category: str = "none"
    udyam_no: str | None = None
    msme_written_agreement: bool = False
    bill_wise: bool = True
    msme_activity: str | None = None  # manufacturing | services | trading
    udyam_registration_date: date | None = None
    msme_agreed_days: int | None = None  # 1..45, only with a written agreement


class PartyOut(BaseModel):
    ledger_id: uuid.UUID
    ledger_name: str
    nature: str
    gstin: str | None
    pan: str | None
    state_code: str | None
    credit_days: int
    msme_category: str
    udyam_no: str | None
    msme_written_agreement: bool
    bill_wise: bool
    msme_activity: str | None
    udyam_registration_date: date | None
    msme_agreed_days: int | None


def party_out(p: Party) -> PartyOut:
    return PartyOut(**p.__dict__)


# ---------------------------------------------------------------------------------------------- opening bills


class OpeningBillIn(BaseModel):
    bill_ref: str | None = None
    bill_date: date
    due_date: date | None = None
    amount: str | None = None
    side: str


class OpeningBillsIn(BaseModel):
    bills: list[OpeningBillIn]


class OpeningBillOut(BaseModel):
    bill_ref: str
    bill_date: date
    due_date: date
    amount: str
    side: str


class OpeningBillsOut(BaseModel):
    bills: list[OpeningBillOut]
    total: BalanceOut
    ledger_opening: BalanceOut
    difference: BalanceOut
    is_balanced: bool


# ------------------------------------------------------------------------------------------ open bills, reports


class OpenBillOut(BaseModel):
    party_ledger_id: uuid.UUID
    party_name: str
    bill_ref: str | None
    kind: str
    bill_date: date | None
    due_date: date | None
    original: BalanceOut
    outstanding: BalanceOut


class OutstandingItemOut(BaseModel):
    bill_ref: str | None
    kind: str
    bill_date: date | None
    due_date: date | None
    original: BalanceOut
    outstanding: BalanceOut
    days_past_due: int
    bucket: str


class OutstandingPartyOut(BaseModel):
    party_ledger_id: uuid.UUID
    party_name: str
    bills: list[OutstandingItemOut]
    total: BalanceOut
    ledger_balance: BalanceOut
    ties: bool


class OutstandingOut(BaseModel):
    kind: str
    as_on: date
    parties: list[OutstandingPartyOut]
    buckets: dict[str, str]
    total: BalanceOut
    ties: bool


def _bal(report: AgeingReport, value: Decimal) -> BalanceOut:
    """A figure in the report's direction as a Balance: receivable positive = Dr, payable positive = Cr."""
    return balance_out(Balance.from_signed(value if report.kind == "receivable" else -value))


def outstanding_out(report: AgeingReport) -> OutstandingOut:
    return OutstandingOut(
        kind=report.kind, as_on=report.as_on,
        parties=[
            OutstandingPartyOut(
                party_ledger_id=p.party_ledger_id, party_name=p.party_name,
                bills=[
                    OutstandingItemOut(
                        bill_ref=i.bill_ref, kind=i.kind, bill_date=i.bill_date, due_date=i.due_date,
                        original=_bal(report, i.original), outstanding=_bal(report, i.outstanding),
                        days_past_due=i.days_past_due, bucket=i.bucket,
                    )
                    for i in p.items
                ],
                total=_bal(report, p.total), ledger_balance=_bal(report, p.ledger_balance), ties=p.ties,
            )
            for p in report.parties
        ],
        buckets={k: money(v) for k, v in report.buckets.items()}, total=_bal(report, report.total), ties=report.ties,
    )


def ageing_out(report: AgeingReport) -> dict:
    """Party-wise bucket table with flat keys (not_due, "0-30", ...); a negative bucket figure means the party's
    advances / on-account amounts exceed its bills in that bucket."""
    return {
        "kind": report.kind,
        "as_on": report.as_on.isoformat(),
        "rows": [
            {"party_ledger_id": str(p.party_ledger_id), "party_name": p.party_name,
             **{k: money(v) for k, v in p.buckets.items()}, "total": money(p.total)}
            for p in report.parties
        ],
        "totals": {**{k: money(v) for k, v in report.buckets.items()}, "total": money(report.total)},
    }
