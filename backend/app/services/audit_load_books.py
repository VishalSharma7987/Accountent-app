"""Read-only loader of the facts the books checks need (Phase 8, package B): vouchers with lines, ledgers with group codes, document links,
voucher number counters, holidays, periods and the lock / unlock events of audit_log. Only SELECTs: the audit never writes to the books.
"""

from sqlalchemy import Connection, text

from app.engine.audit_checks_books import BooksFacts, LockEvent, PeriodFact
from app.engine.audit_types import LedgerFact, LineFact, VoucherFact


def load_books_facts(conn: Connection, client_id: object, financial_year_id: object) -> BooksFacts:
    """Complete BooksFacts (vouchers, ledgers and the extras); the registry path uses `load_extra` instead (it already holds the vouchers)."""
    ids = {"c": client_id, "fy": financial_year_id}
    lines: dict[object, list[LineFact]] = {}
    for r in conn.execute(text(
            "SELECT l.voucher_id, l.ledger_id, l.debit, l.credit FROM voucher_lines l JOIN vouchers v ON v.id = l.voucher_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND v.status IN ('posted', 'reversed') ORDER BY l.voucher_id, l.line_no"), ids):
        lines.setdefault(r[0], []).append(LineFact(r[1], r[2], r[3]))
    vouchers = tuple(
        VoucherFact(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(lines.get(r[0], ())), posted_at=r[8],
                    reverses_voucher_id=r[9], reversed_by_voucher_id=r[10])
        for r in conn.execute(text(
            "SELECT id, voucher_type, voucher_number, voucher_date, status, narration, reference_no, party_ledger_id, posted_at, "
            "reverses_voucher_id, reversed_by_voucher_id FROM vouchers "
            "WHERE client_id = :c AND financial_year_id = :fy AND status IN ('posted', 'reversed') ORDER BY voucher_date, id"), ids))
    ledgers = tuple(LedgerFact(r[0], r[1], r[2]) for r in conn.execute(text(
        "SELECT l.id, l.name, g.code FROM ledgers l JOIN account_groups g ON g.id = l.group_id WHERE l.client_id = :c ORDER BY l.name"), ids))
    return BooksFacts(vouchers, ledgers, **load_books_extra(conn, client_id, financial_year_id))


def load_books_extra(conn: Connection, client_id: object, financial_year_id: object) -> dict:
    """Document links, number counters, holidays, periods and lock events (SELECT only)."""
    ids = {"c": client_id, "fy": financial_year_id}
    documents = frozenset(r[0] for r in conn.execute(text(
        "SELECT DISTINCT dv.voucher_id FROM document_vouchers dv JOIN vouchers v ON v.id = dv.voucher_id "
        "WHERE v.client_id = :c AND v.financial_year_id = :fy"), ids))
    counters = {r[0]: r[1] for r in conn.execute(text(
        "SELECT voucher_type, last_number FROM voucher_number_sequences WHERE client_id = :c AND financial_year_id = :fy"), ids)}
    holidays = {r[0]: r[1] for r in conn.execute(text("SELECT holiday_date, name FROM audit_holidays WHERE client_id = :c"), ids)}
    periods = tuple(PeriodFact(r[0], r[1], r[2]) for r in conn.execute(text(
        "SELECT id, period_start, period_end FROM periods WHERE client_id = :c AND financial_year_id = :fy ORDER BY period_start"), ids))
    events = tuple(LockEvent(r[0], r[1], r[2], r[3], r[4], r[5]) for r in conn.execute(text(
        "SELECT a.id, a.entity_id, a.action, a.created_at, a.actor, a.new_data ->> 'reason' FROM audit_log a "
        "WHERE a.client_id = :c AND a.entity = 'period' AND a.action IN ('lock', 'unlock') "
        "AND a.entity_id IN (SELECT id FROM periods WHERE client_id = :c AND financial_year_id = :fy) ORDER BY a.id"), ids))
    return {"document_voucher_ids": documents, "number_counters": counters, "holidays": holidays, "periods": periods, "lock_events": events}


def load_extra(conn: Connection, client_id: object, fy_start: object, fy_end: object, params: object, facts: object) -> dict:
    """Hook of the audit run (services/audit_runs.py): the books checks' extra facts under the key `books`."""
    fy_id = conn.execute(text("SELECT id FROM financial_years WHERE client_id = :c AND start_date = :s AND end_date = :e"),
                         {"c": client_id, "s": fy_start, "e": fy_end}).scalar_one()
    return {"books": load_books_extra(conn, client_id, fy_id)}
