"""Reads and writes for the GST return workings (Phase 3, package E). SQL only: no accounting rules here."""

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.gstr1 import DocRow, ItemRow, NumberRow
from app.engine.gstr3b import ItcRow, ReversalRow

CENTS = Decimal("0.01")
POSTED = ("posted",)


def _m(value: Decimal) -> Decimal:
    return value.quantize(CENTS)


def registration(conn: Connection, client_id: object, registration_id: object) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, gstin, state_code, registration_type, return_frequency, composition_category, "
            "effective_from, effective_to FROM gst_registrations WHERE id = :r AND client_id = :c"
        ),
        {"r": registration_id, "c": client_id},
    ).first()
    return None if row is None else dict(row._mapping)


def active_registration_count(conn: Connection, client_id: object) -> int:
    return conn.execute(
        text("SELECT count(*) FROM gst_registrations WHERE client_id = :c AND is_active"), {"c": client_id}
    ).scalar_one()


def ledger_roles(conn: Connection, registration_id: object) -> dict[str, object]:
    rows = conn.execute(
        text("SELECT role, ledger_id FROM gst_ledger_roles WHERE registration_id = :r"), {"r": registration_id}
    )
    return {r[0]: r[1] for r in rows}


def documents(
    conn: Connection, client_id: object, registration_id: object, start: date, end: date, types: tuple[str, ...],
    by_voucher_date: bool,
) -> list[DocRow]:
    """Posted invoice-mode documents of the registration in the period (reversed originals and reversal vouchers are
    out: their effect is nil). Outward documents are placed by invoice date, purchases by voucher date."""
    date_col = "v.voucher_date" if by_voucher_date else "g.invoice_date"
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_type, v.voucher_number, g.invoice_date, g.supply_category, g.place_of_supply, "
            "g.counterparty_gstin, COALESCE(l.name, ''), p.gst_registration_type, g.invoice_value, "
            "g.original_invoice_no, g.original_invoice_date, g.note_reason, v.reference_no "
            "FROM vouchers v JOIN voucher_gst g ON g.voucher_id = v.id "
            "LEFT JOIN ledgers l ON l.id = v.party_ledger_id AND l.client_id = v.client_id "
            "LEFT JOIN parties p ON p.ledger_id = v.party_ledger_id AND p.client_id = v.client_id "
            f"WHERE v.client_id = :c AND g.gst_registration_id = :r AND v.status = 'posted' "
            f"AND v.reverses_voucher_id IS NULL AND v.voucher_type = ANY(:t) AND {date_col} BETWEEN :s AND :e "
            "ORDER BY g.invoice_date, v.voucher_number"
        ),
        {"c": client_id, "r": registration_id, "t": list(types), "s": start, "e": end},
    ).all()
    items = _items(conn, [r[0] for r in rows])
    out = []
    for r in rows:
        # purchases carry the supplier's invoice number as the document number
        number = r[13] if r[1] in ("purchase", "debit_note") and r[13] else r[2]
        out.append(DocRow(
            voucher_id=str(r[0]), voucher_type=r[1], number=number, invoice_date=r[3], supply_category=r[4],
            place_of_supply=r[5], party_gstin=r[6], party_name=r[7], party_gst_type=r[8], invoice_value=_m(r[9]),
            items=tuple(items.get(r[0], ())), original_invoice_no=r[10], original_invoice_date=r[11], note_reason=r[12],
        ))
    return out


def _items(conn: Connection, voucher_ids: list[object]) -> dict[object, list[ItemRow]]:
    if not voucher_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT voucher_id, item_line_no, hsn_sac, description, uqc, quantity, taxable_value, treatment, gst_rate, "
            "cgst, sgst, igst, cess, rcm FROM voucher_item_lines WHERE voucher_id = ANY(:ids) ORDER BY voucher_id, item_line_no"
        ),
        {"ids": voucher_ids},
    )
    out: dict[object, list[ItemRow]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(ItemRow(
            r[1], r[2], r[3], r[4], r[5], _m(r[6]), r[7], r[8],
            _m(r[9]), _m(r[10]), _m(r[11]), _m(r[12]), r[13]))
    return out


def numbers_issued(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[NumberRow]:
    rows = conn.execute(
        text(
            "SELECT v.voucher_type, v.voucher_number, (v.status = 'reversed' OR v.reverses_voucher_id IS NOT NULL) "
            "FROM vouchers v JOIN voucher_gst g ON g.voucher_id = v.id "
            "WHERE v.client_id = :c AND g.gst_registration_id = :r AND v.status IN ('posted', 'reversed') "
            "AND v.voucher_type IN ('sales', 'credit_note') AND v.voucher_date BETWEEN :s AND :e"
        ),
        {"c": client_id, "r": registration_id, "s": start, "e": end},
    )
    return [NumberRow(r[0], r[1], r[2]) for r in rows]


def itc_rows(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[ItcRow]:
    """ITC register entries whose claim month (claimed_in_period, else the voucher month) falls in the period."""
    rows = conn.execute(
        text(
            "SELECT * FROM (SELECT e.id, e.source, e.doc_type, e.status, "
            "COALESCE(e.claimed_in_period, date_trunc('month', v.voucher_date)::date) AS claim_date, "
            "g.supply_category, e.igst, e.cgst, e.sgst, e.cess "
            "FROM itc_entries e JOIN vouchers v ON v.id = e.voucher_id "
            "LEFT JOIN voucher_gst g ON g.voucher_id = e.voucher_id "
            "WHERE e.client_id = :c AND e.gst_registration_id = :r AND v.status IN ('posted', 'reversed')) t "
            "WHERE claim_date BETWEEN :s AND :e ORDER BY claim_date, id"
        ),
        {"c": client_id, "r": registration_id, "s": start, "e": end},
    )
    return [ItcRow(str(r[0]), r[1], r[2], r[3], r[4], r[5], _m(r[6]), _m(r[7]), _m(r[8]), _m(r[9])) for r in rows]


def itc_reversals(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[ReversalRow]:
    """Reversal journals that are posted, dated in the period (not the reclaim journals)."""
    rows = conn.execute(
        text(
            "SELECT r.id, v.voucher_date, r.igst, r.cgst, r.sgst, r.cess FROM itc_reversals r "
            "JOIN itc_entries e ON e.id = r.itc_entry_id AND e.client_id = r.client_id "
            "JOIN vouchers v ON v.id = r.reversal_voucher_id "
            "WHERE r.client_id = :c AND e.gst_registration_id = :r AND v.status = 'posted' "
            "AND v.voucher_date BETWEEN :s AND :e"
        ),
        {"c": client_id, "r": registration_id, "s": start, "e": end},
    )
    return [ReversalRow(str(r[0]), r[1], _m(r[2]), _m(r[3]), _m(r[4]), _m(r[5])) for r in rows]


def unposted_drafts(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_type, v.status, v.voucher_date, v.reference_no, g.invoice_value "
            "FROM vouchers v JOIN voucher_gst g ON g.voucher_id = v.id "
            "WHERE v.client_id = :c AND g.gst_registration_id = :r AND v.status IN ('draft', 'approved') "
            "AND v.voucher_date BETWEEN :s AND :e ORDER BY v.voucher_date, v.created_at"
        ),
        {"c": client_id, "r": registration_id, "s": start, "e": end},
    )
    return [{"voucher_id": str(r[0]), "voucher_type": r[1], "status": r[2], "voucher_date": r[3], "reference_no": r[4],
             "invoice_value": _m(r[5])} for r in rows]


def ledger_movement(conn: Connection, client_id: object, ledger_ids: list[object], start: date, end: date) -> dict[object, Decimal]:
    """Credit minus debit per ledger over posted and reversed vouchers (a reversal nets its original to nil)."""
    if not ledger_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT vl.ledger_id, COALESCE(sum(vl.credit - vl.debit), 0) FROM voucher_lines vl "
            "JOIN vouchers v ON v.id = vl.voucher_id WHERE v.client_id = :c AND vl.ledger_id = ANY(:l) "
            "AND v.status IN ('posted', 'reversed') AND v.voucher_date BETWEEN :s AND :e GROUP BY vl.ledger_id"
        ),
        {"c": client_id, "l": list(ledger_ids), "s": start, "e": end},
    )
    return {r[0]: _m(r[1]) for r in rows}


def sales_ledger_movement(conn: Connection, client_id: object, start: date, end: date) -> Decimal:
    """Credit minus debit of every ledger under Sales Accounts (directly or in sub-groups)."""
    value = conn.execute(
        text(
            "WITH RECURSIVE chain AS ("
            " SELECT l.id AS ledger_id, g.code, g.parent_id FROM ledgers l JOIN account_groups g ON g.id = l.group_id"
            "  WHERE l.client_id = :c"
            " UNION ALL SELECT c.ledger_id, p.code, p.parent_id FROM account_groups p JOIN chain c ON c.parent_id = p.id) "
            "SELECT COALESCE(sum(vl.credit - vl.debit), 0) FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
            "WHERE v.client_id = :c AND v.status IN ('posted', 'reversed') AND v.voucher_date BETWEEN :s AND :e "
            "AND vl.ledger_id IN (SELECT ledger_id FROM chain WHERE code = 'sales_accounts')"
        ),
        {"c": client_id, "s": start, "e": end},
    ).scalar_one()
    return _m(value)


def manual_tax_journals(
    conn: Connection, client_id: object, tax_ledger_ids: list[object], start: date, end: date
) -> list[dict]:
    """Posted vouchers WITHOUT an invoice header that touch a GST ledger: (voucher id, number, ledger id, credit - debit)."""
    if not tax_ledger_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_number, vl.ledger_id, sum(vl.credit - vl.debit) FROM voucher_lines vl "
            "JOIN vouchers v ON v.id = vl.voucher_id LEFT JOIN voucher_gst g ON g.voucher_id = v.id "
            "WHERE v.client_id = :c AND vl.ledger_id = ANY(:l) AND v.status IN ('posted', 'reversed') "
            "AND g.voucher_id IS NULL AND v.voucher_date BETWEEN :s AND :e "
            "GROUP BY v.id, v.voucher_number, vl.ledger_id ORDER BY v.voucher_number"
        ),
        {"c": client_id, "l": list(tax_ledger_ids), "s": start, "e": end},
    )
    return [{"voucher_id": str(r[0]), "number": r[1], "ledger_id": r[2], "net": _m(r[3])} for r in rows]


def other_period_documents(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[dict]:
    """Posted invoice-mode vouchers dated in the period whose invoice date is in another period."""
    rows = conn.execute(
        text(
            "SELECT v.voucher_number, g.invoice_date, g.invoice_value FROM vouchers v JOIN voucher_gst g ON g.voucher_id = v.id "
            "WHERE v.client_id = :c AND g.gst_registration_id = :r AND v.status = 'posted' AND v.reverses_voucher_id IS NULL "
            "AND v.voucher_type IN ('sales', 'credit_note') AND v.voucher_date BETWEEN :s AND :e "
            "AND g.invoice_date NOT BETWEEN :s AND :e"
        ),
        {"c": client_id, "r": registration_id, "s": start, "e": end},
    )
    return [{"number": r[0], "invoice_date": r[1], "invoice_value": _m(r[2])} for r in rows]


def threshold(conn: Connection, key: str, on: date) -> dict | None:
    row = conn.execute(
        text(
            "SELECT numeric_value, verification_status, source_reference FROM gst_thresholds WHERE threshold_key = :k "
            "AND effective_from <= :d AND (effective_to IS NULL OR effective_to >= :d) ORDER BY effective_from DESC LIMIT 1"
        ),
        {"k": key, "d": on},
    ).first()
    return None if row is None else {"value": row[0], "status": row[1], "source": row[2]}


def composition_rule(conn: Connection, category: str, on: date) -> dict | None:
    row = conn.execute(
        text(
            "SELECT category, rate, turnover_limit, turnover_basis, verification_status, source_reference "
            "FROM gst_composition_rules WHERE category = :k AND effective_from <= :d "
            "AND (effective_to IS NULL OR effective_to >= :d) ORDER BY effective_from DESC LIMIT 1"
        ),
        {"k": category, "d": on},
    ).first()
    return None if row is None else dict(row._mapping)


# ---- workings and filed returns ------------------------------------------------------------------------------------


def next_version(conn: Connection, registration_id: object, return_type: str, period_start: date) -> int:
    return conn.execute(
        text(
            "SELECT COALESCE(max(version), 0) + 1 FROM gst_return_workings WHERE gst_registration_id = :r "
            "AND return_type = :t AND period_start = :s"
        ),
        {"r": registration_id, "t": return_type, "s": period_start},
    ).scalar_one()


def insert_working(
    conn: Connection, client_id: object, registration_id: object, return_type: str, period_kind: str, start: date,
    end: date, version: int, data: dict, data_hash: str, rule_statuses: dict, actor: str,
) -> object:
    return conn.execute(
        text(
            "INSERT INTO gst_return_workings (client_id, gst_registration_id, return_type, period_kind, period_start, "
            "period_end, version, data, data_hash, rule_statuses, created_by) VALUES (:c, :r, :t, :k, :s, :e, :v, "
            "CAST(:d AS jsonb), :h, CAST(:rs AS jsonb), :a) RETURNING id"
        ),
        {"c": client_id, "r": registration_id, "t": return_type, "k": period_kind, "s": start, "e": end, "v": version,
         "d": json.dumps(data), "h": data_hash, "rs": json.dumps(rule_statuses), "a": actor},
    ).scalar_one()


def working(conn: Connection, working_id: object) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, client_id, gst_registration_id, return_type, period_kind, period_start, period_end, version, "
            "status, data, data_hash, rule_statuses, created_by, created_at FROM gst_return_workings WHERE id = :i"
        ),
        {"i": working_id},
    ).first()
    return None if row is None else dict(row._mapping)


def list_workings(conn: Connection, client_id: object, registration_id: object | None, return_type: str | None) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, gst_registration_id, return_type, period_kind, period_start, version, status, data_hash, created_by, "
            "created_at FROM gst_return_workings WHERE client_id = :c AND (CAST(:r AS uuid) IS NULL OR gst_registration_id = :r) "
            "AND (CAST(:t AS text) IS NULL OR return_type = :t) ORDER BY period_start DESC, return_type, version DESC"
        ),
        {"c": client_id, "r": registration_id, "t": return_type},
    )
    return [dict(r._mapping) for r in rows]


def finalise_working(conn: Connection, working_id: object) -> None:
    conn.execute(text("UPDATE gst_return_workings SET status = 'final' WHERE id = :i"), {"i": working_id})


def filed_return(conn: Connection, registration_id: object, return_type: str, period_start: date) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, client_id, gst_registration_id, return_type, period_start, arn, filed_on, data, entered_by, entered_at "
            "FROM gst_filed_returns WHERE gst_registration_id = :r AND return_type = :t AND period_start = :s"
        ),
        {"r": registration_id, "t": return_type, "s": period_start},
    ).first()
    return None if row is None else dict(row._mapping)


def upsert_filed_return(
    conn: Connection, client_id: object, registration_id: object, return_type: str, period_start: date, arn: str | None,
    filed_on: date | None, data: dict, actor: str,
) -> object:
    return conn.execute(
        text(
            "INSERT INTO gst_filed_returns (client_id, gst_registration_id, return_type, period_start, arn, filed_on, data, "
            "entered_by) VALUES (:c, :r, :t, :s, :arn, :f, CAST(:d AS jsonb), :a) "
            "ON CONFLICT (gst_registration_id, return_type, period_start) DO UPDATE SET arn = EXCLUDED.arn, "
            "filed_on = EXCLUDED.filed_on, data = EXCLUDED.data, entered_by = EXCLUDED.entered_by, entered_at = now() "
            "RETURNING id"
        ),
        {"c": client_id, "r": registration_id, "t": return_type, "s": period_start, "arn": arn, "f": filed_on,
         "d": json.dumps(data), "a": actor},
    ).scalar_one()


def rate_rule_statuses(conn: Connection, client_id: object, registration_id: object, start: date, end: date) -> list[tuple[str, str]]:
    """(verification_status, source_reference) of every rate rule the period's invoice items were taxed with."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT r.verification_status, r.source_reference FROM voucher_item_lines i "
            "JOIN voucher_gst g ON g.voucher_id = i.voucher_id JOIN vouchers v ON v.id = i.voucher_id "
            "JOIN gst_rate_rules r ON r.id = i.rate_rule_id WHERE v.client_id = :c AND g.gst_registration_id = :r "
            "AND v.status = 'posted' AND v.voucher_date BETWEEN :s AND :e"
        ),
        {"c": client_id, "r": registration_id, "s": start, "e": end},
    )
    return [(r[0], r[1]) for r in rows]
