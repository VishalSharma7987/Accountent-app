"""Shared read-only loaders of the audit (Phase 8, package A): ledgers with their system group, non-draft vouchers with lines, legal limit rows.

SELECT only. Builds the plain facts of engine/audit_types.py; no rule is applied here.
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import Connection, text

from app.db import repositories_audit as repo
from app.engine.audit_registry import AuditFacts
from app.engine.audit_types import LedgerFact, LimitRule, LineFact, VoucherFact

CENTS = Decimal("0.01")


def load_ledgers(conn: Connection, client_id: object) -> dict[object, LedgerFact]:
    """Every ledger of the client. `group_code` is the code of the nearest SYSTEM group (a client's own sub-group resolves to its parent)."""
    rows = conn.execute(text(
        "WITH RECURSIVE chain AS ("
        " SELECT l.id AS ledger_id, g.id AS gid, g.code, g.parent_id, g.is_system FROM ledgers l JOIN account_groups g ON g.id = l.group_id"
        "  WHERE l.client_id = :c"
        " UNION ALL"
        " SELECT c.ledger_id, p.id, p.code, p.parent_id, p.is_system FROM account_groups p JOIN chain c ON c.parent_id = p.id WHERE NOT c.is_system) "
        "SELECT l.id, l.name, c.code FROM ledgers l JOIN chain c ON c.ledger_id = l.id WHERE l.client_id = :c AND c.is_system"),
        {"c": client_id})
    return {r[0]: LedgerFact(r[0], r[1], r[2]) for r in rows}


def load_vouchers(conn: Connection, client_id: object, fy_id: object) -> tuple[VoucherFact, ...]:
    """All posted / reversed vouchers of the financial year with their lines, in date and number order (drafts and approved are not books)."""
    lines: dict[object, list[LineFact]] = defaultdict(list)
    for r in conn.execute(text(
            "SELECT vl.voucher_id, vl.ledger_id, vl.debit, vl.credit FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND v.status IN ('posted', 'reversed') ORDER BY vl.voucher_id, vl.line_no"),
            {"c": client_id, "fy": fy_id}):
        lines[r[0]].append(LineFact(r[1], r[2].quantize(CENTS), r[3].quantize(CENTS)))
    rows = conn.execute(text(
        "SELECT id, voucher_type, voucher_number, voucher_date, status, narration, reference_no, party_ledger_id, posted_at, "
        "reverses_voucher_id, reversed_by_voucher_id FROM vouchers WHERE client_id = :c AND financial_year_id = :fy "
        "AND status IN ('posted', 'reversed') ORDER BY voucher_date, voucher_type, voucher_number"),
        {"c": client_id, "fy": fy_id})
    return tuple(VoucherFact(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(lines[r[0]]), r[8], r[9], r[10]) for r in rows)


def load_rules(conn: Connection) -> list[LimitRule]:
    return repo.rule_limits(conn)


def load_common(conn: Connection, client_id: object, fy_id: object) -> AuditFacts:
    return AuditFacts(ledgers=load_ledgers(conn, client_id), vouchers=load_vouchers(conn, client_id, fy_id))
