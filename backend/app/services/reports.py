"""Reports from the database: load the data, call the pure engine functions, return their result.

No accounting maths here (CLAUDE.md principle 6): balances, running totals and groupings are computed by
app/engine/reports.py. Services take a SQLAlchemy Connection and never commit.
"""

from datetime import date

from sqlalchemy import Connection

from app.db import repositories as repo
from app.engine import reports as engine
from app.engine.models import OpeningBalance
from app.engine.money import parse_amount
from app.services.errors import ServiceError

NO_OPENING = OpeningBalance(parse_amount("0"), parse_amount("0"))


def _fmt(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _year_for(conn: Connection, client_id: object, on: date) -> repo.FinancialYearRow:
    year = repo.financial_year_for_date(conn, client_id, on)
    if year is None:
        if not repo.client_exists(conn, client_id):
            raise ServiceError("not_found", "Client not found.")
        raise ServiceError("no_financial_year", f"No financial year of this client contains {_fmt(on)}.")
    return year


def trial_balance(conn: Connection, client_id: object, as_on: date, *, hide_zero: bool = False) -> engine.TrialBalance:
    """Trial Balance of the client's financial year containing `as_on`, as on that date."""
    year = _year_for(conn, client_id, as_on)
    return engine.trial_balance(
        repo.ledgers_of_client(conn, client_id),
        repo.groups_for_client(conn, client_id),
        repo.openings_for_year(conn, client_id, year.id),
        repo.all_posted_lines(conn, client_id, year.id),
        as_on,
        hide_zero=hide_zero,
    )


def ledger_statement(
    conn: Connection, client_id: object, ledger_id: object, from_date: date, to_date: date
) -> engine.LedgerStatement:
    """Statement of one ledger between two dates of the SAME financial year."""
    if to_date < from_date:
        raise ServiceError("invalid_range", "The end date is before the start date.")
    ledger = repo.get_ledger(conn, client_id, ledger_id)
    if ledger is None:
        raise ServiceError("not_found", "Ledger not found for this client.")
    year = _year_for(conn, client_id, from_date)
    if to_date > year.end_date:
        raise ServiceError(
            "invalid_range",
            f"A statement covers one financial year ({_fmt(year.start_date)} to {_fmt(year.end_date)}); "
            "choose dates inside it.",
        )
    opening = repo.openings_for_year(conn, client_id, year.id).get(ledger.id, NO_OPENING)
    lines = repo.lines_touching_ledger(conn, client_id, ledger.id, year.id)
    return engine.ledger_statement(ledger, opening, lines, from_date, to_date)
