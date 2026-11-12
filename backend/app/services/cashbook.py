"""Cash Book / Bank Book from the database: load, call the pure engine (engine/cashbook.py), return its result."""

from datetime import date

from sqlalchemy import Connection

from app.db import repositories as repo
from app.engine import cashbook as engine
from app.engine.models import OpeningBalance
from app.engine.validation import group_chain
from app.services.errors import ServiceError

NO_OPENING = OpeningBalance(engine.ZERO, engine.ZERO)
BOOK_GROUPS = ("cash_in_hand", "bank_accounts")


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def cash_book(conn: Connection, client_id: object, ledger_id: object, from_date: date, to_date: date) -> engine.CashBook:
    """Cash Book (Cash-in-hand ledger) or Bank Book (Bank Accounts ledger) between two dates of ONE financial year."""
    if to_date < from_date:
        raise ServiceError("invalid_range", "The end date is before the start date.")
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    if not set(group_chain(ledger.group_code, repo.groups_for_client(conn, client_id))) & set(BOOK_GROUPS):
        raise ServiceError("not_a_book_ledger", "The Cash Book / Bank Book is only for Cash-in-hand and Bank Accounts ledgers.")
    year = repo.financial_year_for_date(conn, client_id, from_date)
    if year is None:
        raise ServiceError("no_financial_year", f"No financial year of this client contains {_fmt(from_date)}.")
    if to_date > year.end_date:
        raise ServiceError(
            "invalid_range",
            f"A book covers one financial year ({_fmt(year.start_date)} to {_fmt(year.end_date)}); choose dates inside it.",
        )
    opening = repo.openings_for_year(conn, client_id, year.id).get(ledger.id, NO_OPENING)
    return engine.cash_book(ledger, opening, repo.lines_touching_ledger(conn, client_id, ledger.id, year.id), from_date, to_date)
