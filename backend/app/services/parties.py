"""Party master use-cases: set (create or update) a party, read one, list them.

Rules P-01 .. P-07 come from the pure engine (engine/parties.py); P-08 needs the database and is checked here:
bill-wise cannot be switched on for a ledger that already has posted lines without allocations, or whose opening
balance is not covered by opening bills. Services take a Connection and never commit; every check runs before the
first write; every change is audit-logged.
"""

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_bills as repo_b
from app.engine import bills as bill_engine
from app.engine import parties as engine
from app.engine.models import ValidationError
from app.engine.money import format_inr
from app.services import audit
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


@dataclass(frozen=True)
class Party:
    ledger_id: uuid.UUID
    ledger_name: str
    nature: str  # debtor | creditor
    gstin: str | None
    pan: str | None
    state_code: str | None
    credit_days: int
    msme_category: str
    udyam_no: str | None
    msme_written_agreement: bool
    bill_wise: bool


def _snapshot(row: repo_b.PartyRow) -> dict:
    data = asdict(row)
    data["ledger_id"] = str(row.ledger_id)
    return data


def _credit_days(value: object) -> int | None:
    """The whole number behind a credit-days value already accepted by P-06."""
    return int(float(value)) if isinstance(value, float) else int(value)  # type: ignore[arg-type]


def _p08_errors(conn: Connection, client_id: object, ledger_id: object, name: str, existing: repo_b.PartyRow | None,
                bill_wise: bool) -> list[ValidationError]:
    if bill_wise and (existing is None or not existing.bill_wise):
        errors = []
        unallocated = repo_b.unallocated_posted_line_count(conn, client_id, ledger_id)
        if unallocated:
            errors.append(ValidationError(
                "P-08",
                f"Bill-wise cannot be switched on for '{name}': it already has {unallocated} posted voucher line(s) "
                "without bill allocation.",
            ))
        for cover in repo_b.opening_cover(conn, client_id, ledger_id):
            check = bill_engine.opening_bills_check(cover.bills_total, cover.ledger_opening)
            if not check.is_balanced:
                errors.append(ValidationError(
                    "P-08",
                    f"Bill-wise cannot be switched on for '{name}': the opening bills of the year starting "
                    f"{cover.start_date.strftime('%d-%m-%Y')} add up to {format_inr(check.total.amount)} "
                    f"{check.total.side or ''} but the opening balance is {format_inr(check.ledger.amount)} "
                    f"{check.ledger.side or ''} (difference {format_inr(check.difference.amount)} "
                    f"{check.difference.side}). Save the party without bill-wise, enter the opening bills, then switch it on.",
                ))
        return errors
    if not bill_wise and existing is not None and existing.bill_wise and repo_b.allocation_count(conn, client_id, ledger_id):
        return [ValidationError(
            "P-08", f"Bill-wise cannot be switched off for '{name}': it already has bill allocations."
        )]
    return []


def set_party(
    conn: Connection,
    client_id: object,
    ledger_id: object,
    *,
    gstin: str | None = None,
    pan: str | None = None,
    state_code: str | None = None,
    credit_days: object = 0,
    msme_category: str = "none",
    udyam_no: str | None = None,
    msme_written_agreement: bool = False,
    bill_wise: bool = True,
    actor: str,
) -> None:
    """Create or update the party details of a debtor/creditor ledger. On rule errors (P-01 .. P-08) raises
    VoucherRuleError carrying all of them and writes nothing."""
    actor = require_actor(actor)
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    groups = repo.groups_for_client(conn, client_id)
    gstin, pan, udyam_no = engine.normalise_id(gstin), engine.normalise_id(pan), engine.normalise_id(udyam_no)
    state_code = (state_code or "").strip() or None
    errors = engine.validate_party(
        ledger, groups, gstin=gstin, pan=pan, state_code=state_code, credit_days=credit_days,
        msme_category=msme_category, udyam_no=udyam_no,
    )
    existing = repo_b.party_rows_for(conn, client_id, [ledger_id]).get(ledger.id)
    if not any(e.rule_id == "P-07" for e in errors):
        errors += _p08_errors(conn, client_id, ledger.id, ledger.name, existing, bill_wise)
    if errors:
        raise VoucherRuleError(errors)

    row = repo_b.PartyRow(
        ledger.id, gstin, pan, state_code, _credit_days(credit_days), msme_category, udyam_no,
        bool(msme_written_agreement), bool(bill_wise),
    )
    repo_b.upsert_party(conn, client_id, row)
    audit.log(conn, AuditEntry(
        client_id, actor, "update" if existing else "create", "party", ledger.id,
        old=None if existing is None else _snapshot(existing), new=_snapshot(row),
    ))


def _party(ledger, nature: str, row: repo_b.PartyRow) -> Party:
    return Party(
        ledger.id, ledger.name, nature, row.gstin, row.pan, row.state_code, row.credit_days, row.msme_category,
        row.udyam_no, row.msme_written_agreement, row.bill_wise,
    )


def get_party(conn: Connection, client_id: object, ledger_id: object) -> Party:
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    row = None if ledger is None else repo_b.party_rows_for(conn, client_id, [ledger_id]).get(ledger.id)
    if ledger is None or row is None:
        raise ServiceError("not_found", "Party not found for this client.")
    nature = engine.party_nature(ledger, repo.groups_for_client(conn, client_id))
    return _party(ledger, nature or "", row)


def list_parties(conn: Connection, client_id: object, nature: str | None = None) -> list[Party]:
    """All parties of the client sorted by name, optionally only 'debtor' or 'creditor'."""
    if nature not in (None, "debtor", "creditor"):
        raise ServiceError("invalid_nature", "nature must be debtor or creditor.")
    if not repo.client_exists(conn, client_id):
        raise ServiceError("not_found", "Client not found.")
    rows = repo_b.list_party_rows(conn, client_id)
    if not rows:
        return []
    groups = repo.groups_for_client(conn, client_id)
    out = []
    for ledger in repo.ledgers_of_client(conn, client_id):
        row = rows.get(ledger.id)
        if row is None:
            continue
        kind = engine.party_nature(ledger, groups) or ""
        if nature is None or kind == nature:
            out.append(_party(ledger, kind, row))
    return out
