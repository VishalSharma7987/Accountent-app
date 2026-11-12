"""Reads for the cash/bank, duplicate-payment and MSME features. SQL only: no accounting rules here."""

from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.cash_rules import CashMovement
from app.engine.duplicates import ExistingVoucher
from app.engine.msme import PartyFacts

CENTS = Decimal("0.01")


def party_facts(conn: Connection, client_id: object) -> dict[object, PartyFacts]:
    """MSME-relevant facts of every party ledger of the client (keyed by ledger id)."""
    rows = conn.execute(
        text("SELECT ledger_id, msme_category, credit_days, msme_written_agreement FROM parties WHERE client_id = :c"),
        {"c": client_id},
    )
    return {r[0]: PartyFacts(r[0], r[1], r[2], r[3]) for r in rows}


def cash_movements(conn: Connection, client_id: object, ledger_id: object, fy_id: object) -> list[CashMovement]:
    """Lines of the ledger in posted/reversed vouchers of the financial year (all dates)."""
    rows = conn.execute(
        text(
            "SELECT v.voucher_date, vl.debit, vl.credit FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND vl.ledger_id = :l "
            "AND v.status IN ('posted', 'reversed')"
        ),
        {"c": client_id, "fy": fy_id, "l": ledger_id},
    )
    return [CashMovement(r[0], r[1].quantize(CENTS), r[2].quantize(CENTS)) for r in rows]


def cash_ledgers_among(conn: Connection, client_id: object, ledger_ids: list[object]) -> dict[object, str]:
    """Of the given ledgers, those under Cash-in-hand (directly or through sub-groups): {ledger id: name}."""
    if not ledger_ids:
        return {}
    rows = conn.execute(
        text(
            "WITH RECURSIVE chain AS ("
            " SELECT l.id AS ledger_id, l.name, g.code, g.parent_id FROM ledgers l JOIN account_groups g ON g.id = l.group_id"
            "  WHERE l.client_id = :c AND l.id = ANY(:ids)"
            " UNION ALL"
            " SELECT c.ledger_id, c.name, p.code, p.parent_id FROM account_groups p JOIN chain c ON c.parent_id = p.id) "
            "SELECT DISTINCT ledger_id, name FROM chain WHERE code = 'cash_in_hand'"
        ),
        {"c": client_id, "ids": list(ledger_ids)},
    )
    return {r[0]: r[1] for r in rows}


def lock_ledgers(conn: Connection, ledger_ids: list[object]) -> None:
    """Row-lock ledgers (sorted, so two postings cannot deadlock) until the transaction ends: concurrent postings
    on the same cash ledger queue up and each sees the other's committed lines. NO KEY UPDATE does not block the
    foreign-key checks of ordinary inserts."""
    if ledger_ids:
        conn.execute(
            text("SELECT id FROM ledgers WHERE id = ANY(:ids) ORDER BY id FOR NO KEY UPDATE"),
            {"ids": sorted(ledger_ids, key=str)},
        )


def candidate_payments(conn: Connection, client_id: object, party_ledger_id: object) -> list[ExistingVoucher]:
    """Payments of the client to the party ledger that are not reversed and not reversals: D-01 candidates."""
    rows = conn.execute(
        text(
            "SELECT v.id, v.client_id, v.voucher_type, v.party_ledger_id, v.reference_no, "
            "COALESCE((SELECT sum(vl.debit) FROM voucher_lines vl WHERE vl.voucher_id = v.id), 0), "
            "v.status, v.voucher_number, v.voucher_date, v.reverses_voucher_id FROM vouchers v "
            "WHERE v.client_id = :c AND v.voucher_type = 'payment' AND v.party_ledger_id = :p "
            "AND v.status <> 'reversed' AND v.reverses_voucher_id IS NULL ORDER BY v.voucher_date, v.created_at"
        ),
        {"c": client_id, "p": party_ledger_id},
    )
    return [ExistingVoucher(r[0], r[1], r[2], r[3], r[4], r[5].quantize(CENTS), r[6], r[7], r[8], r[9]) for r in rows]


def msme_rule_rows(conn: Connection) -> list[tuple]:
    return list(conn.execute(text(
        "SELECT rule_key, category, applies, days_with_agreement, days_no_agreement, effective_from, effective_to, "
        "source_reference, verification_status FROM msme_payment_rules ORDER BY effective_from, rule_key, category"
    )))

