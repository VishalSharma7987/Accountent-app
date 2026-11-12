"""Voucher checks added in Phase 2 step 2.4: C-01 (cash never negative) and D-01 (duplicate payment).

Kept out of services/vouchers.py (which only calls these functions): the rules are in engine/cash_rules.py and
engine/payments.py; this file loads the data they need and takes the row lock on the cash ledgers.
"""

import uuid
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import Connection

from app.db import repositories as repo
from app.db import repositories_cash as cash_repo
from app.engine.cash_rules import CashMovement, check_cash_never_negative
from app.engine.models import OpeningBalance, ValidationError, VoucherDraft
from app.engine.money import parse_amount
from app.engine.payments import duplicate_payment_errors as _engine_duplicate_payment_errors
from app.services.errors import VoucherRuleError

ZERO = Decimal("0.00")


def _amount(raw: object) -> Decimal:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return ZERO
    return parse_amount(raw)


def cash_errors(
    conn: Connection, client_id: object, voucher_date, lines: Iterable[object]
) -> list[ValidationError]:
    """C-01 for a voucher about to be approved/posted/reversed. `lines` have ledger_id, debit, credit.

    Locks the voucher's cash ledgers (until the transaction ends) so concurrent postings queue, then looks at every
    date of the financial year. Lines of non-cash ledgers are ignored; a voucher with no cash line costs one query."""
    lines = list(lines)
    wanted = []
    for line in lines:
        try:
            wanted.append(uuid.UUID(str(line.ledger_id)))
        except ValueError:
            continue
    cash = cash_repo.cash_ledgers_among(conn, client_id, wanted)
    if not cash:
        return []
    year = repo.financial_year_for_date(conn, client_id, voucher_date)
    if year is None:  # V-06 reports this
        return []
    cash_repo.lock_ledgers(conn, list(cash))
    openings = repo.openings_for_year(conn, client_id, year.id)
    errors = []
    for ledger_id, name in sorted(cash.items(), key=lambda kv: kv[1]):
        new = [
            CashMovement(voucher_date, _amount(x.debit), _amount(x.credit))
            for x in lines if str(x.ledger_id) == str(ledger_id)
        ]
        opening = openings.get(ledger_id)
        error = check_cash_never_negative(
            name,
            opening if opening is not None else OpeningBalance(ZERO, ZERO),
            cash_repo.cash_movements(conn, client_id, ledger_id, year.id),
            new,
        )
        if error:
            errors.append(error)
    return errors


def raise_if_cash_negative(conn: Connection, client_id: object, voucher_date, lines: Iterable[object]) -> None:
    errors = cash_errors(conn, client_id, voucher_date, lines)
    if errors:
        raise VoucherRuleError(errors)


def duplicate_payment_errors(conn: Connection, draft: VoucherDraft, draft_id: object | None) -> list[ValidationError]:
    """D-01 for a draft being created or edited (no query unless it is a payment with a party and no override)."""
    if draft.voucher_type != "payment" or draft.party_ledger_id is None or (draft.duplicate_override_reason or "").strip():
        return []
    return _engine_duplicate_payment_errors(
        draft, cash_repo.candidate_payments(conn, draft.client_id, draft.party_ledger_id), draft_id=draft_id
    )
