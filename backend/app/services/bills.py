"""Bill-wise use-cases: allocation checks for the voucher flow, opening bills, open bills, outstanding and ageing.

All calculations are done by the pure engine (engine/bills.py); this file loads the data, writes the result and
logs it. Services take a Connection and never commit; every check runs before the first write.

A ledger without a `parties` row (or a party that is not bill-wise) behaves exactly as in Phase 1: no allocation.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_bills as repo_b
from app.engine import bills as engine
from app.engine import parties as party_engine
from app.engine.models import OpenBill, ValidationError, VoucherDraft, VoucherLine
from app.engine.money import format_inr
from app.services import audit, reports
from app.services.audit import AuditEntry
from app.services.errors import ServiceError, VoucherRuleError, require_actor


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


# ===================================================================================== voucher integration


def _as_uuid(value: object) -> object:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return value


def _normalised(lines: tuple[VoucherLine, ...]) -> list[VoucherLine]:
    """Lines with ledger ids as UUIDs, so they compare equal to the ids read from the database."""
    return [replace(x, ledger_id=_as_uuid(x.ledger_id)) for x in lines]


def _party_infos(conn: Connection, client_id: object, ctx: repo.ValidationContext, lines: list[VoucherLine]):
    ids = [x.ledger_id for x in lines if isinstance(x.ledger_id, uuid.UUID)]
    rows = repo_b.party_rows_for(conn, client_id, ids)
    by_id = {ledger.id: ledger for ledger in ctx.ledgers.values()}
    infos: dict[object, engine.PartyInfo] = {}
    for ledger_id, row in rows.items():
        ledger = by_id.get(ledger_id)
        nature = None if ledger is None else party_engine.party_nature(ledger, ctx.groups)
        if ledger is not None and nature is not None:
            infos[ledger_id] = engine.PartyInfo(ledger.name, nature, row.bill_wise, row.credit_days)
    return infos


def draft_errors(
    conn: Connection,
    draft: VoucherDraft,
    ctx: repo.ValidationContext,
    exclude_voucher_id: object | None = None,
    *,
    is_reversal: bool = False,
) -> list[ValidationError]:
    """B-01 .. B-05 for a voucher draft. exclude_voucher_id is the voucher being edited/approved/posted: its own
    stored allocations do not count as "already used" references. One extra query for a voucher without any party
    ledger and no allocations."""
    lines = _normalised(draft.lines)
    infos = _party_infos(conn, draft.client_id, ctx, lines)
    if not infos and not any(x.allocations for x in lines):
        return []
    state: dict = {}
    used: set = set()
    allocated = [x.ledger_id for x in lines if x.allocations and x.ledger_id in infos and infos[x.ledger_id].bill_wise]
    if allocated:
        year = next((y for y in ctx.years if y.start_date <= draft.voucher_date <= y.end_date), None)
        if year is None:  # V-06 reports it
            return []
        state = engine.bill_state(
            repo_b.opening_bill_rows(conn, draft.client_id, year.id, allocated),
            repo_b.allocation_rows(conn, draft.client_id, year.id, None, allocated),
        )
        used = repo_b.used_refs(conn, draft.client_id, allocated, exclude_voucher_id)
    return engine.validate_allocations(lines, infos, draft.voucher_date, state, used, is_reversal=is_reversal)


def persist_allocations(
    conn: Connection, voucher_id: object, draft: VoucherDraft, ctx: repo.ValidationContext
) -> None:
    """Store the allocations of a VALID draft (due dates resolved). Call after the voucher lines are inserted."""
    if not any(x.allocations for x in draft.lines):
        return
    lines = _normalised(draft.lines)
    infos = _party_infos(conn, draft.client_id, ctx, lines)
    repo_b.insert_allocations(conn, draft.client_id, voucher_id, engine.resolve_allocations(lines, infos, draft.voucher_date))


def lock_parties(conn: Connection, client_id: object, lines) -> None:
    """Before posting a voucher with allocations: queue behind other posts settling the same parties' bills."""
    ids = [x.ledger_id for x in lines if x.allocations]
    if ids:
        repo_b.lock_party_rows(conn, client_id, ids)


def opening_cover_errors(
    conn: Connection, client_id: object, financial_year_id: object, ledger_ids
) -> list[ValidationError]:
    """B-07: a voucher may not be posted while a bill-wise party on it has opening bills that do not add up to its
    ledger opening balance (the difference is shown)."""
    rows = repo_b.party_rows_for(conn, client_id, ledger_ids)
    errors = []
    names = None
    for ledger_id, row in rows.items():
        if not row.bill_wise:
            continue
        for cover in repo_b.opening_cover(conn, client_id, ledger_id, financial_year_id):
            check = engine.opening_bills_check(cover.bills_total, cover.ledger_opening)
            if check.is_balanced:
                continue
            if names is None:
                names = {x.id: x.name for x in repo.ledgers_of_client(conn, client_id)}
            errors.append(ValidationError(
                "B-07",
                f"The opening bills of '{names[ledger_id]}' add up to {format_inr(check.total.amount)} "
                f"{check.total.side or ''} but its opening balance is {format_inr(check.ledger.amount)} "
                f"{check.ledger.side or ''} (difference {format_inr(check.difference.amount)} "
                f"{check.difference.side}). Fix the opening bills before posting.",
            ))
    return errors


# ================================================================================================ opening bills


@dataclass(frozen=True)
class OpeningBillsView:
    bills: list[engine.OpeningBillRow]
    check: engine.BillsCheck


def _require_party(conn: Connection, client_id: object, ledger_id: object) -> repo_b.PartyRow:
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    row = None if ledger is None else repo_b.party_rows_for(conn, client_id, [ledger.id]).get(ledger.id)
    if row is None:
        raise ServiceError("not_found", "Party not found for this client; set up the party first.")
    return row


def set_opening_bills(
    conn: Connection,
    client_id: object,
    financial_year_id: object,
    ledger_id: object,
    bills: list[engine.OpeningBillIn],
    *,
    actor: str,
) -> None:
    """Replace the opening bills of a party for a financial year (an empty list removes them). Refused once any
    voucher of the year is posted (like opening balances). Whether they add up to the ledger opening balance is
    reported by get_opening_bills and enforced when posting (B-07)."""
    actor = require_actor(actor)
    party = _require_party(conn, client_id, ledger_id)
    if repo.get_financial_year(conn, client_id, financial_year_id) is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    if repo.posted_voucher_exists(conn, client_id, financial_year_id):
        raise ServiceError(
            "opening_locked",
            "Opening bills cannot be changed after vouchers have been posted for this financial year.",
        )
    errors = engine.validate_opening_bills(bills)
    if errors:
        raise VoucherRuleError(errors)
    rows = engine.resolve_opening_bills(ledger_id, bills, party.credit_days)
    old = repo_b.opening_bill_rows(conn, client_id, financial_year_id, [ledger_id])

    def snap(items):
        return [{"bill_ref": r.bill_ref, "bill_date": r.bill_date.isoformat(), "due_date": r.due_date.isoformat(),
                 "amount": f"{abs(r.amount):.2f}", "side": "Dr" if r.amount > 0 else "Cr"} for r in items]

    repo_b.replace_opening_bills(conn, client_id, financial_year_id, ledger_id, rows)
    audit.log(conn, AuditEntry(
        client_id, actor, "set_opening_bills", "opening_bills", ledger_id,
        old={"financial_year_id": str(financial_year_id), "bills": snap(old)},
        new={"financial_year_id": str(financial_year_id), "bills": snap(rows)},
    ))


def get_opening_bills(
    conn: Connection, client_id: object, financial_year_id: object, ledger_id: object
) -> OpeningBillsView:
    _require_party(conn, client_id, ledger_id)
    if repo.get_financial_year(conn, client_id, financial_year_id) is None:
        raise ServiceError("not_found", "Financial year not found for this client.")
    rows = repo_b.opening_bill_rows(conn, client_id, financial_year_id, [ledger_id])
    opening = repo.openings_for_year(conn, client_id, financial_year_id).get(_as_uuid(ledger_id))
    total = sum((r.amount for r in rows), engine.ZERO)
    return OpeningBillsView(rows, engine.opening_bills_check(total, opening))


# ============================================================================== open bills, outstanding, ageing


def _bill_wise_parties(conn: Connection, client_id: object) -> dict[object, engine.PartyInfo]:
    rows = repo_b.list_party_rows(conn, client_id)
    if not rows:
        return {}
    groups = repo.groups_for_client(conn, client_id)
    out = {}
    for ledger in repo.ledgers_of_client(conn, client_id):
        row = rows.get(ledger.id)
        nature = party_engine.party_nature(ledger, groups) if row is not None else None
        if row is not None and row.bill_wise and nature is not None:
            out[ledger.id] = engine.PartyInfo(ledger.name, nature, True, row.credit_days)
    return out


def _year_for(conn: Connection, client_id: object, as_on: date):
    year = repo.financial_year_for_date(conn, client_id, as_on)
    if year is None:
        if not repo.client_exists(conn, client_id):
            raise ServiceError("not_found", "Client not found.")
        raise ServiceError("no_financial_year", f"No financial year of this client contains {_fmt(as_on)}.")
    return year


def _open_bills(conn, client_id, year, as_on, parties, party_ids) -> list[OpenBill]:
    return engine.open_bills(
        repo_b.opening_bill_rows(conn, client_id, year.id, party_ids),
        repo_b.allocation_rows(conn, client_id, year.id, as_on, party_ids),
        {pid: info.name for pid, info in parties.items()},
    )


def open_bills(
    conn: Connection, client_id: object, as_on: date, party_ledger_id: object | None = None
) -> list[OpenBill]:
    """Open bills, advances and on-account amounts of the bill-wise parties as on a date, inside the financial year
    that contains it (opening bills of the year + posted allocations dated up to the date). Signed: Dr +, Cr -."""
    year = _year_for(conn, client_id, as_on)
    parties = _bill_wise_parties(conn, client_id)
    ids = None
    if party_ledger_id is not None:
        party_ledger_id = _as_uuid(party_ledger_id)
        if party_ledger_id not in parties:
            raise ServiceError("not_found", "Party not found for this client, or it is not bill-wise.")
        ids = [party_ledger_id]
    elif not parties:
        return []
    return _open_bills(conn, client_id, year, as_on, parties, ids)


def ageing_report(conn: Connection, client_id: object, kind: str, as_on: date) -> engine.AgeingReport:
    """Outstanding bills with ageing buckets for kind 'receivable' (debtors) or 'payable' (creditors). Each party
    carries a tie check: the open items must add up to the party ledger's closing balance on the date."""
    if kind not in ("receivable", "payable"):
        raise ServiceError("invalid_kind", "kind must be receivable or payable.")
    year = _year_for(conn, client_id, as_on)
    parties = _bill_wise_parties(conn, client_id)
    if not parties:
        return engine.ageing([], as_on, kind, {}, {})
    items = _open_bills(conn, client_id, year, as_on, parties, None)
    trial = reports.trial_balance(conn, client_id, as_on)
    balances = {
        row.ledger_id: row.debit - row.credit
        for section in trial.sections for row in section.rows if row.ledger_id in parties
    }
    return engine.ageing(items, as_on, kind, parties, balances)


outstanding_report = ageing_report  # same data; the API shapes it as bills or as a bucket table
