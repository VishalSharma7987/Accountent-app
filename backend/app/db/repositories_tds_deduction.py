"""Database access of the TDS deduction on vouchers and of the TDS register (Phase 4, package B).

The rule tables and masters are read with plain SQL here (package A owns the editing side). Nothing here commits.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.tds_types import (
    Deductee,
    LowerDeductionCert,
    Nature,
    PriorPosition,
    RateRule,
    SectionRef,
)

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def load_natures(conn: Connection) -> dict[str, Nature]:
    rows = conn.execute(text("SELECT nature_key, kind, description, rate_mode, verification_status FROM tds_natures"))
    return {r[0]: Nature(*r) for r in rows}


def load_rates(conn: Connection, nature_keys: list[str]) -> list[RateRule]:
    rows = conn.execute(
        text(
            "SELECT id::text, nature_key, act, deductee_group, rate, no_pan_rate, single_payment_threshold, monthly_threshold, "
            "annual_threshold, threshold_mode, effective_from, effective_to, source_reference, verification_status "
            "FROM tds_rates WHERE nature_key = ANY(:keys)"
        ),
        {"keys": nature_keys},
    )
    return [RateRule(*r) for r in rows]


def load_section_refs(conn: Connection, nature_keys: list[str]) -> list[SectionRef]:
    rows = conn.execute(
        text(
            "SELECT nature_key, act, section_ref, table_ref, payment_code, effective_from, effective_to, source_reference, "
            "verification_status FROM tds_section_refs WHERE nature_key = ANY(:keys)"
        ),
        {"keys": nature_keys},
    )
    return [SectionRef(*r) for r in rows]


def load_deductees(conn: Connection, client_id: object, ledger_ids: list[object]) -> tuple[dict[object, Deductee], set[object], dict[object, str]]:
    """(active deductees by ledger id, ids of deductees that are switched off, ledger names)."""
    rows = conn.execute(
        text(
            "SELECT d.ledger_id, d.pan, d.pan_status, d.deductee_type, d.default_nature_key, d.is_active AND l.is_active, l.name "
            "FROM tds_deductees d JOIN ledgers l ON l.id = d.ledger_id WHERE d.client_id = :c AND d.ledger_id = ANY(:ids)"
        ),
        {"c": client_id, "ids": ledger_ids},
    ).all()
    active = {r[0]: Deductee(r[0], r[1], r[2], r[3], r[4]) for r in rows if r[5]}
    return active, {r[0] for r in rows if not r[5]}, {r[0]: r[6] for r in rows}


def load_certs(conn: Connection, client_id: object, cert_ids: list[object]) -> dict[object, LowerDeductionCert]:
    """Active certificates with the amount already used: the taxable bases of posted items under the certificate, capped at its limit."""
    if not cert_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT c.id, c.deductee_ledger_id, c.certificate_no, c.nature_key, c.rate, c.max_amount, c.valid_from, c.valid_to, "
            "least(c.max_amount, coalesce((SELECT sum(i.taxable_base) FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id "
            "WHERE i.lower_cert_id = c.id AND v.status = 'posted'), 0)) "
            "FROM tds_lower_deduction_certs c WHERE c.client_id = :c AND c.is_active AND c.id = ANY(:ids)"
        ),
        {"c": client_id, "ids": cert_ids},
    )
    return {r[0]: LowerDeductionCert(*r) for r in rows}


def load_buyer_flags(conn: Connection, client_id: object) -> dict[object, bool]:
    rows = conn.execute(
        text("SELECT financial_year_id, prev_year_turnover_over_threshold FROM tds_client_fy_flags WHERE client_id = :c"), {"c": client_id}
    )
    return {r[0]: r[1] for r in rows}


def load_roles(conn: Connection, client_id: object) -> list[tuple[str, str | None, object]]:
    rows = conn.execute(text("SELECT role, nature_key, ledger_id FROM tds_ledger_roles WHERE client_id = :c"), {"c": client_id})
    return [(r[0], r[1], r[2]) for r in rows]


def load_priors(conn: Connection, client_id: object, ledger_ids: list[object], nature_keys: list[str], fy_ids: list[object]) -> dict[tuple, PriorPosition]:
    """What the books hold per (deductee, nature, financial year): POSTED vouchers only (a reversed voucher drops out)."""
    rows = conn.execute(
        text(
            "SELECT i.deductee_ledger_id, i.nature_key, i.financial_year_id, to_char(i.event_date, 'YYYY-MM'), "
            "sum(i.payment_amount), sum(i.tds_amount) FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id "
            "WHERE i.client_id = :c AND v.status = 'posted' AND i.deductee_ledger_id = ANY(:l) AND i.nature_key = ANY(:n) "
            "AND i.financial_year_id = ANY(:f) GROUP BY 1, 2, 3, 4"
        ),
        {"c": client_id, "l": ledger_ids, "n": nature_keys, "f": fy_ids},
    )
    acc: dict[tuple, list] = {}
    for ledger, nature, fy, month, amount, tax in rows:
        cell = acc.setdefault((ledger, nature, fy), [ZERO, ZERO, {}])
        cell[0] += amount.quantize(CENTS)
        cell[1] += tax.quantize(CENTS)
        cell[2][month] = amount.quantize(CENTS)
    return {k: PriorPosition(v[0], v[1], v[2]) for k, v in acc.items()}


def ledger_names(conn: Connection, ids: list[object]) -> dict[object, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT id, name FROM ledgers WHERE id = ANY(:ids)"), {"ids": ids})}


def nature_kinds(conn: Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT nature_key, kind FROM tds_natures"))}


def delete_items(conn: Connection, voucher_id: object) -> None:
    conn.execute(text("DELETE FROM tds_voucher_items WHERE voucher_id = :v"), {"v": voucher_id})


def insert_items(conn: Connection, rows: list[dict]) -> None:
    conn.execute(
        text(
            "INSERT INTO tds_voucher_items (client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, "
            "table_ref, rate_rule_id, financial_year_id, event_date, credit_date, payment_date, payment_amount, cumulative_before, "
            "cumulative_after, threshold_crossed, taxable_base, rate_applied, rate_reason, lower_cert_id, tax_already_on_base, "
            "tds_amount, tds_line_no, engine_version, note) VALUES (:client_id, :voucher_id, :item_no, :kind, :deductee_ledger_id, "
            ":nature_key, :act, :section_ref, :table_ref, :rate_rule_id, :financial_year_id, :event_date, :credit_date, :payment_date, "
            ":payment_amount, :cumulative_before, :cumulative_after, :threshold_crossed, :taxable_base, :rate_applied, :rate_reason, "
            ":lower_cert_id, :tax_already_on_base, :tds_amount, :tds_line_no, :engine_version, :note)"
        ),
        rows,
    )


_ITEM_SQL = (
    "SELECT i.id, i.item_no, i.kind, i.deductee_ledger_id, l.name, i.nature_key, i.act, i.section_ref, i.table_ref, i.rate_rule_id, "
    "i.financial_year_id, i.event_date, i.credit_date, i.payment_date, i.payment_amount, i.cumulative_before, i.cumulative_after, "
    "i.threshold_crossed, i.taxable_base, i.rate_applied, i.rate_reason, i.lower_cert_id, i.tax_already_on_base, i.tds_amount, "
    "i.tds_line_no, i.engine_version, i.note, "
    "coalesce(r.verification_status, (SELECT s.verification_status FROM tds_section_refs s WHERE s.nature_key = i.nature_key "
    "AND s.act = i.act AND s.effective_from <= i.event_date AND (s.effective_to IS NULL OR s.effective_to >= i.event_date) "
    "ORDER BY s.effective_from DESC LIMIT 1)) "
    "FROM tds_voucher_items i JOIN ledgers l ON l.id = i.deductee_ledger_id LEFT JOIN tds_rates r ON r.id = i.rate_rule_id "
    "WHERE i.voucher_id = :v ORDER BY i.item_no"
)
ITEM_COLUMNS = (
    "id", "item_no", "kind", "deductee_ledger_id", "deductee_name", "nature_key", "act", "section_ref", "table_ref", "rate_rule_id",
    "financial_year_id", "event_date", "credit_date", "payment_date", "payment_amount", "cumulative_before", "cumulative_after",
    "threshold_crossed", "taxable_base", "rate_applied", "rate_reason", "lower_cert_id", "tax_already_on_base", "tds_amount",
    "tds_line_no", "engine_version", "note", "verification_status",
)


def load_items(conn: Connection, voucher_id: object) -> list[dict]:
    return [dict(zip(ITEM_COLUMNS, r, strict=True)) for r in conn.execute(text(_ITEM_SQL), {"v": voucher_id})]


# ---- register ------------------------------------------------------------------------------------------------------

_REGISTER_SQL = (
    "SELECT i.id, v.id, v.voucher_number, v.voucher_date, i.deductee_ledger_id, l.name, d.pan, i.nature_key, i.section_ref, "
    "i.event_date, i.payment_amount, i.taxable_base, i.rate_applied, i.rate_reason, i.tds_amount, "
    "coalesce((SELECT sum(a.amount) FROM tds_challan_allocations a WHERE a.item_id = i.id), 0), "
    "(SELECT max(c.deposit_date) FROM tds_challan_allocations a JOIN tds_challans c ON c.id = a.challan_id WHERE a.item_id = i.id), "
    "i.kind, i.act, r.verification_status, r.source_reference "
    "FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id JOIN ledgers l ON l.id = i.deductee_ledger_id "
    "JOIN tds_deductees d ON d.ledger_id = i.deductee_ledger_id LEFT JOIN tds_rates r ON r.id = i.rate_rule_id "
    "WHERE i.client_id = :c AND v.status = 'posted' "
    "AND (CAST(:fy AS uuid) IS NULL OR i.financial_year_id = :fy) "
    "AND (CAST(:nature AS text) IS NULL OR i.nature_key = :nature) "
    "AND (CAST(:ded AS uuid) IS NULL OR i.deductee_ledger_id = :ded) "
    "AND (CAST(:qs AS date) IS NULL OR (i.event_date >= :qs AND i.event_date <= :qe)) "
    "ORDER BY i.event_date, v.voucher_number, i.item_no"
)


def register_rows(conn: Connection, client_id: object, *, fy_id: object | None, nature_key: str | None, deductee: object | None,
                  quarter_start: date | None, quarter_end: date | None) -> list[dict]:
    cols = ("item_id", "voucher_id", "voucher_number", "voucher_date", "deductee_ledger_id", "deductee_name", "pan", "nature_key",
            "section_ref", "event_date", "payment_amount", "taxable_base", "rate_applied", "rate_reason", "tds_amount", "deposited",
            "deposited_on", "kind", "act", "rule_status", "rule_source")
    rows = conn.execute(
        text(_REGISTER_SQL),
        {"c": client_id, "fy": fy_id, "nature": nature_key, "ded": deductee, "qs": quarter_start, "qe": quarter_end},
    )
    return [dict(zip(cols, r, strict=True)) for r in rows]


def financial_year(conn: Connection, client_id: object, fy_id: object) -> tuple[date, date] | None:
    row = conn.execute(
        text("SELECT start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"), {"f": fy_id, "c": client_id}
    ).first()
    return None if row is None else (row[0], row[1])


def financial_year_of(conn: Connection, client_id: object, on: date) -> tuple[object, date, date] | None:
    row = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c AND start_date <= :d AND end_date >= :d"),
        {"c": client_id, "d": on},
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def by_deductee(conn: Connection, client_id: object, fy_id: object) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT i.deductee_ledger_id, l.name, i.nature_key, sum(i.payment_amount), sum(i.tds_amount), "
            "min(i.event_date) FILTER (WHERE i.threshold_crossed), "
            "(SELECT r.annual_threshold FROM tds_voucher_items i2 JOIN tds_rates r ON r.id = i2.rate_rule_id "
            "JOIN vouchers v2 ON v2.id = i2.voucher_id WHERE v2.status = 'posted' AND i2.client_id = i.client_id "
            "AND i2.deductee_ledger_id = i.deductee_ledger_id AND i2.nature_key = i.nature_key "
            "AND i2.financial_year_id = i.financial_year_id ORDER BY i2.event_date DESC, i2.created_at DESC LIMIT 1) "
            "FROM tds_voucher_items i JOIN vouchers v ON v.id = i.voucher_id JOIN ledgers l ON l.id = i.deductee_ledger_id "
            "WHERE i.client_id = :c AND i.financial_year_id = :f AND v.status = 'posted' "
            "GROUP BY i.client_id, i.financial_year_id, i.deductee_ledger_id, l.name, i.nature_key ORDER BY l.name, i.nature_key"
        ),
        {"c": client_id, "f": fy_id},
    )
    cols = ("deductee_ledger_id", "deductee_name", "nature_key", "cumulative_amount", "tax_deducted", "threshold_crossed_on", "threshold")
    return [dict(zip(cols, r, strict=True)) for r in rows]



def pending_rate_sources(conn: Connection, rule_ids: list[object]) -> list[str]:
    rows = conn.execute(
        text("SELECT DISTINCT source_reference FROM tds_rates WHERE id = ANY(:ids) AND verification_status = 'pending' ORDER BY 1"),
        {"ids": rule_ids},
    )
    return [r[0] for r in rows]
