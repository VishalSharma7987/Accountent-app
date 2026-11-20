"""Read-only loaders for the analytical checks A-15 and A-18 (Phase 8, package D): ledger totals this year and the previous year, flagged
(related-party) ledgers and their vouchers. SELECT only: nothing here writes to any table (the audit never changes the books)."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine import audit_checks_analytic as engine
from app.engine.audit_types import ZERO, AuditParams, LineFact, VoucherFact

_LIVE = ("posted", "reversed")  # a reversed original and its reversal net to zero in totals; drafts / approved are not in the books yet

_TOTALS = text(
    "SELECT l.id, l.name, g.code AS group_code, "
    "COALESCE(SUM(vl.debit - vl.credit) FILTER (WHERE v.voucher_date BETWEEN :from_date AND :to_date), 0) AS this_year, "
    "COALESCE(SUM(vl.debit - vl.credit) FILTER (WHERE v.voucher_date BETWEEN :prev_from AND :prev_to), 0) AS previous_year "
    "FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id AND v.client_id = vl.client_id "
    "JOIN ledgers l ON l.id = vl.ledger_id AND l.client_id = vl.client_id JOIN account_groups g ON g.id = l.group_id "
    "WHERE vl.client_id = :client_id AND v.status IN ('posted', 'reversed') "
    "AND v.voucher_date BETWEEN :min_date AND :to_date GROUP BY l.id, l.name, g.code ORDER BY l.name, l.id"
)

_RELATED = text(
    "SELECT r.ledger_id, l.name, r.relationship, r.active FROM audit_related_parties r "
    "JOIN ledgers l ON l.id = r.ledger_id AND l.client_id = r.client_id WHERE r.client_id = :client_id ORDER BY l.name, r.ledger_id"
)

_VOUCHERS = text(
    "SELECT v.id, v.voucher_type, v.voucher_number, v.voucher_date, v.status, v.narration, v.reference_no, v.party_ledger_id, "
    "v.posted_at, v.reverses_voucher_id, v.reversed_by_voucher_id FROM vouchers v "
    "WHERE v.client_id = :client_id AND v.status IN ('posted', 'reversed') AND v.voucher_date BETWEEN :from_date AND :to_date "
    "AND EXISTS (SELECT 1 FROM voucher_lines x WHERE x.voucher_id = v.id AND x.ledger_id = ANY(:ledger_ids)) "
    "ORDER BY v.voucher_date, v.id"
)

_LINES = text(
    "SELECT voucher_id, ledger_id, debit, credit FROM voucher_lines WHERE client_id = :client_id AND voucher_id = ANY(:voucher_ids) "
    "ORDER BY voucher_id, line_no"
)


def load_ledger_totals(conn: Connection, client_id: object, from_date: date, to_date: date) -> tuple[engine.LedgerTotals, ...]:
    """Net movement (debit minus credit) per ledger for the period and for the same period one year earlier."""
    prev_from, prev_to = engine.previous_period(from_date, to_date)
    rows = conn.execute(_TOTALS, {"client_id": client_id, "from_date": from_date, "to_date": to_date, "prev_from": prev_from,
                                  "prev_to": prev_to, "min_date": min(from_date, prev_from)}).all()
    return tuple(engine.LedgerTotals(r.id, r.name, r.group_code, Decimal(r.this_year), Decimal(r.previous_year)) for r in rows)


def load_related_ledgers(conn: Connection, client_id: object) -> tuple[engine.RelatedLedger, ...]:
    rows = conn.execute(_RELATED, {"client_id": client_id}).all()
    return tuple(engine.RelatedLedger(r.ledger_id, r.name, r.relationship, r.active) for r in rows)


def load_related_vouchers(conn: Connection, client_id: object, from_date: date, to_date: date, ledger_ids: list) -> tuple[VoucherFact, ...]:
    if not ledger_ids:
        return ()
    vrows = conn.execute(_VOUCHERS, {"client_id": client_id, "from_date": from_date, "to_date": to_date, "ledger_ids": ledger_ids}).all()
    if not vrows:
        return ()
    lines: dict[object, list[LineFact]] = defaultdict(list)
    for r in conn.execute(_LINES, {"client_id": client_id, "voucher_ids": [v.id for v in vrows]}).all():
        lines[r.voucher_id].append(LineFact(r.ledger_id, Decimal(r.debit), Decimal(r.credit)))
    return tuple(VoucherFact(
        v.id, v.voucher_type, v.voucher_number, v.voucher_date, v.status, v.narration or "", v.reference_no, v.party_ledger_id,
        tuple(lines[v.id]), posted_at=v.posted_at, reverses_voucher_id=v.reverses_voucher_id, reversed_by_voucher_id=v.reversed_by_voucher_id)
        for v in vrows)


def load_analytic_facts(conn: Connection, client_id: object, params: AuditParams) -> engine.AnalyticFacts:
    """Everything A-15 and A-18 need for a run (package A calls this once and passes the result to both checks)."""
    related = load_related_ledgers(conn, client_id)
    active_ids = [r.ledger_id for r in related if r.active]
    prev_from, prev_to = engine.previous_period(params.from_date, params.to_date)
    return engine.AnalyticFacts(
        ledger_totals=load_ledger_totals(conn, client_id, params.from_date, params.to_date),
        related=related,
        vouchers=load_related_vouchers(conn, client_id, params.from_date, params.to_date, active_ids),
        previous_from=prev_from, previous_to=prev_to)


__all__ = ["ZERO", "load_analytic_facts", "load_ledger_totals", "load_related_ledgers", "load_related_vouchers"]


def load_extra(conn: Connection, client_id: object, fy_start: object, fy_end: object, params: AuditParams, facts: object) -> dict:
    """The hook of the audit run (services/audit_runs.py): one `AnalyticFacts` for both checks, under the key `analytic`."""
    return {"analytic": load_analytic_facts(conn, client_id, params)}
