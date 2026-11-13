"""SQL for invoice-mode vouchers (Phase 3, package B): context for the engine, and the voucher_gst / voucher_item_lines /
voucher_gst_line_roles rows. SQL only: no rules, no maths.

The rule tables are read here directly (one query) and returned as the frozen dataclasses of engine/gst_types.py. When the
rule loaders of package A (rules/gst_rules.py) are merged, `load_context` can take its rows from there; nothing else changes.
Numbers are cast to text in SQL so they reach Python as exact Decimals (never through a JSON float).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.gst_tax import RuleData
from app.engine.gst_types import BlockedRule, GstRegistration, RateRule, RateSlab, RcmRule


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


@dataclass(frozen=True)
class PartyInfo:
    gstin: str | None
    state_code: str | None
    bill_wise: bool


@dataclass(frozen=True)
class ContextRows:
    registration: GstRegistration | None
    round_off_invoices: bool
    party: PartyInfo | None
    rules: RuleData
    max_number_length: Decimal | None


_RULE_COLS = "effective_from, effective_to, source_reference, verification_status"
_IN_RANGE = "effective_from <= :hi AND (effective_to IS NULL OR effective_to >= :lo)"
_CONTEXT_SQL = f"""
SELECT
 (SELECT row_to_json(x) FROM (SELECT id::text, gstin, state_code, registration_type, return_frequency, composition_category,
        effective_from, effective_to, is_active, trade_name FROM gst_registrations WHERE id = :reg AND client_id = :c) x),
 (SELECT coalesce(json_object_agg(role, ledger_id::text), '{{}}'::json) FROM gst_ledger_roles WHERE registration_id = :reg),
 (SELECT round_off_invoices FROM clients WHERE id = :c),
 (SELECT row_to_json(p) FROM (SELECT gstin, state_code, bill_wise FROM parties WHERE client_id = :c AND ledger_id = :party) p),
 (SELECT coalesce(json_agg(json_build_object('id', id::text, 'rule_key', rule_key, 'code_kind', code_kind,
        'code_prefix', code_prefix, 'supply_kind', supply_kind, 'treatment', treatment, 'rate', rate::text,
        'cess_rate', cess_rate::text, 'cess_specific_amount', cess_specific_amount::text, 'cess_uqc', cess_uqc,
        'effective_from', effective_from, 'effective_to', effective_to, 'source_reference', source_reference,
        'verification_status', verification_status, 'is_example', is_example)), '[]'::json)
    FROM gst_rate_rules WHERE {_IN_RANGE}),
 (SELECT coalesce(json_agg(json_build_object('rate', rate::text, 'is_special', is_special, 'effective_from', effective_from,
        'effective_to', effective_to, 'source_reference', source_reference, 'verification_status', verification_status)), '[]'::json)
    FROM gst_rate_slabs WHERE {_IN_RANGE}),
 (SELECT coalesce(json_agg(json_build_object('category_key', category_key, 'section_ref', section_ref, 'supply_kind', supply_kind,
        'description', description, 'supplier_condition', supplier_condition, 'hsn_sac_prefix', hsn_sac_prefix,
        'effective_from', effective_from, 'effective_to', effective_to, 'source_reference', source_reference,
        'verification_status', verification_status, 'is_example', is_example)), '[]'::json)
    FROM gst_rcm_rules WHERE {_IN_RANGE}),
 (SELECT coalesce(json_agg(json_build_object('category_key', category_key, 'clause_ref', clause_ref, 'description', description,
        'has_exception', has_exception, 'exception_text', exception_text, 'effective_from', effective_from,
        'effective_to', effective_to, 'source_reference', source_reference, 'verification_status', verification_status)), '[]'::json)
    FROM gst_blocked_credit_rules WHERE {_IN_RANGE}),
 (SELECT coalesce(json_agg(code), '[]'::json) FROM gst_state_codes WHERE effective_from <= :on AND (effective_to IS NULL OR effective_to >= :on)),
 (SELECT numeric_value::text FROM gst_thresholds WHERE threshold_key = 'invoice_number_max_length'
        AND effective_from <= :on AND (effective_to IS NULL OR effective_to >= :on) ORDER BY effective_from DESC LIMIT 1)
"""


def load_context(
    conn: Connection, client_id: object, registration_id: object, party_ledger_id: object | None, on: date, other: date
) -> ContextRows:
    """Registration (+ ledger roles), client option, party, and the rule rows in force between the two dates
    (`on` = voucher date, `other` = invoice date; rules are picked by date later by the engine). One round trip."""
    row = conn.execute(
        text(_CONTEXT_SQL),
        {"c": client_id, "reg": registration_id, "party": party_ledger_id, "lo": min(on, other), "hi": max(on, other), "on": on},
    ).one()
    reg_json, roles, round_off, party, rates, slabs, rcms, blocked, states, max_len = row
    registration = None
    if reg_json is not None:
        registration = GstRegistration(
            reg_json["id"], reg_json["gstin"], reg_json["state_code"], reg_json["registration_type"],
            reg_json["return_frequency"], reg_json["composition_category"], _date(reg_json["effective_from"]),
            _date(reg_json["effective_to"]), reg_json["is_active"], reg_json["trade_name"],
            {role: uuid.UUID(ledger) for role, ledger in roles.items()},
        )
    rules = RuleData(
        tuple(
            RateRule(
                r["id"], r["rule_key"], r["code_kind"], r["code_prefix"], r["supply_kind"], r["treatment"], Decimal(r["rate"]),
                Decimal(r["cess_rate"]), Decimal(r["cess_specific_amount"]), r["cess_uqc"], _date(r["effective_from"]),
                _date(r["effective_to"]), r["source_reference"], r["verification_status"], r["is_example"],
            )
            for r in rates
        ),
        tuple(
            RateSlab(Decimal(s["rate"]), s["is_special"], _date(s["effective_from"]), _date(s["effective_to"]),
                     s["source_reference"], s["verification_status"])
            for s in slabs
        ),
        tuple(
            RcmRule(
                r["category_key"], r["section_ref"], r["supply_kind"], r["description"], r["supplier_condition"],
                r["hsn_sac_prefix"], _date(r["effective_from"]), _date(r["effective_to"]), r["source_reference"],
                r["verification_status"], r["is_example"],
            )
            for r in rcms
        ),
        tuple(
            BlockedRule(
                r["category_key"], r["clause_ref"], r["description"], r["has_exception"], r["exception_text"],
                _date(r["effective_from"]), _date(r["effective_to"]), r["source_reference"], r["verification_status"],
            )
            for r in blocked
        ),
        frozenset(states),
    )
    return ContextRows(
        registration, bool(round_off), None if party is None else PartyInfo(party["gstin"], party["state_code"], party["bill_wise"]),
        rules, None if max_len is None else Decimal(max_len),
    )


# ============================================================================================== write


def delete_invoice(conn: Connection, voucher_id: object) -> None:
    """Remove the GST rows of a DRAFT voucher (items and roles go with the header: ON DELETE CASCADE)."""
    conn.execute(text("DELETE FROM voucher_gst WHERE voucher_id = :v"), {"v": voucher_id})


def insert_invoice(
    conn: Connection, client_id: object, voucher_id: object, inv, result, counterparty_state: str | None
) -> None:
    """Header, item rows and line roles. `inv` is the (resolved) InvoiceIn, `result` the engine's InvoiceResult; the
    voucher's own lines must already be inserted in the same order as result.lines."""
    conn.execute(
        text(
            "INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, "
            "counterparty_gstin, counterparty_state_code, place_of_supply, invoice_date, original_invoice_no, "
            "original_invoice_date, note_reason, has_rcm, invoice_round_off, invoice_value, engine_version) "
            "VALUES (:v, :c, :reg, :kind, :cat, :gstin, :cstate, :pos, :idate, :ono, :odate, :reason, :rcm, :ro, :val, :ver)"
        ),
        {
            "v": voucher_id, "c": client_id, "reg": inv.gst_registration_id, "kind": inv.document_kind,
            "cat": inv.supply_category, "gstin": inv.counterparty_gstin, "cstate": counterparty_state,
            "pos": inv.place_of_supply, "idate": inv.invoice_date, "ono": inv.original_invoice_no,
            "odate": inv.original_invoice_date, "reason": inv.note_reason, "rcm": result.has_rcm,
            "ro": result.invoice_round_off, "val": result.invoice_value, "ver": result.engine_version,
        },
    )
    rows = []
    for entry, tax in zip(inv.items, result.items, strict=True):
        rows.append({
            "c": client_id, "v": voucher_id, "n": tax.item_line_no, "item": entry.item_id, "d": entry.description,
            "h": entry.hsn_sac, "u": entry.uqc, "q": entry.quantity, "r": entry.unit_rate, "g": tax.gross_amount,
            "disc": tax.discount, "t": tax.taxable_value, "l": entry.ledger_id, "tr": tax.treatment, "gr": tax.gst_rate,
            "cr": tax.cess_rate, "cs": tax.cess_specific_amount, "cg": tax.cgst, "sg": tax.sgst, "ig": tax.igst,
            "ce": tax.cess, "rule": tax.rate_rule_id, "dflt": tax.rate_is_default, "rcm": tax.rcm,
            "rk": entry.rcm_category_key, "cost": tax.tax_in_cost, "ik": entry.itc_category_key,
            "iec": entry.itc_exception_claimed, "ien": entry.itc_exception_note,
        })
    conn.execute(
        text(
            "INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, item_id, description, hsn_sac, uqc, quantity, "
            "unit_rate, gross_amount, discount, taxable_value, ledger_id, treatment, gst_rate, cess_rate, "
            "cess_specific_amount, cgst, sgst, igst, cess, rate_rule_id, rate_is_default, rcm, rcm_category_key, "
            "tax_in_cost, itc_category_key, itc_exception_claimed, itc_exception_note) "
            "VALUES (:c, :v, :n, :item, :d, :h, :u, :q, :r, :g, :disc, :t, :l, :tr, :gr, :cr, :cs, :cg, :sg, :ig, :ce, "
            ":rule, :dflt, :rcm, :rk, :cost, :ik, :iec, :ien)"
        ),
        rows,
    )
    conn.execute(
        text("INSERT INTO voucher_gst_line_roles (voucher_id, line_no, role, item_line_no) VALUES (:v, :n, :role, :i)"),
        [
            {"v": voucher_id, "n": number, "role": line.role, "i": line.item_line_no}
            for number, line in enumerate(result.lines, start=1)
        ],
    )


def copy_invoice(conn: Connection, original_id: object, reversal_id: object) -> None:
    """The reversal voucher mirrors the original's lines (same line numbers), so its GST rows are copies."""
    params = {"o": original_id, "r": reversal_id}
    copied = conn.execute(
        text(
            "INSERT INTO voucher_gst (voucher_id, client_id, gst_registration_id, document_kind, supply_category, "
            "counterparty_gstin, counterparty_state_code, place_of_supply, invoice_date, original_invoice_no, "
            "original_invoice_date, note_reason, has_rcm, invoice_round_off, invoice_value, engine_version) "
            "SELECT :r, client_id, gst_registration_id, document_kind, supply_category, counterparty_gstin, "
            "counterparty_state_code, place_of_supply, invoice_date, original_invoice_no, original_invoice_date, "
            "note_reason, has_rcm, invoice_round_off, invoice_value, engine_version FROM voucher_gst WHERE voucher_id = :o"
        ),
        params,
    ).rowcount
    if not copied:  # the original is not an invoice-mode voucher
        return
    conn.execute(
        text(
            "INSERT INTO voucher_item_lines (client_id, voucher_id, item_line_no, item_id, description, hsn_sac, uqc, "
            "quantity, unit_rate, gross_amount, discount, taxable_value, ledger_id, treatment, gst_rate, cess_rate, "
            "cess_specific_amount, cgst, sgst, igst, cess, rate_rule_id, rate_is_default, rcm, rcm_category_key, "
            "tax_in_cost, itc_category_key, itc_exception_claimed, itc_exception_note) "
            "SELECT client_id, :r, item_line_no, item_id, description, hsn_sac, uqc, quantity, unit_rate, gross_amount, "
            "discount, taxable_value, ledger_id, treatment, gst_rate, cess_rate, cess_specific_amount, cgst, sgst, igst, "
            "cess, rate_rule_id, rate_is_default, rcm, rcm_category_key, tax_in_cost, itc_category_key, "
            "itc_exception_claimed, itc_exception_note FROM voucher_item_lines WHERE voucher_id = :o"
        ),
        params,
    )
    conn.execute(
        text(
            "INSERT INTO voucher_gst_line_roles (voucher_id, line_no, role, item_line_no) "
            "SELECT :r, line_no, role, item_line_no FROM voucher_gst_line_roles WHERE voucher_id = :o"
        ),
        params,
    )


# =============================================================================================== read

_STORED_SQL = """
SELECT row_to_json(h),
  (SELECT coalesce(json_agg(json_build_object(
      'item_line_no', i.item_line_no, 'item_id', i.item_id::text, 'description', i.description, 'hsn_sac', i.hsn_sac,
      'uqc', i.uqc, 'quantity', i.quantity::text, 'unit_rate', i.unit_rate::text, 'gross_amount', i.gross_amount::text,
      'discount', i.discount::text, 'taxable_value', i.taxable_value::text, 'ledger_id', i.ledger_id::text,
      'treatment', i.treatment, 'gst_rate', i.gst_rate::text, 'cess_rate', i.cess_rate::text,
      'cess_specific_amount', i.cess_specific_amount::text, 'cgst', i.cgst::text, 'sgst', i.sgst::text,
      'igst', i.igst::text, 'cess', i.cess::text, 'rate_rule_id', i.rate_rule_id::text, 'rate_is_default', i.rate_is_default,
      'rcm', i.rcm, 'rcm_category_key', i.rcm_category_key, 'tax_in_cost', i.tax_in_cost,
      'itc_category_key', i.itc_category_key, 'itc_exception_claimed', i.itc_exception_claimed,
      'itc_exception_note', i.itc_exception_note) ORDER BY i.item_line_no), '[]'::json)
   FROM voucher_item_lines i WHERE i.voucher_id = h.voucher_id),
  (SELECT coalesce(json_agg(json_build_object('line_no', r.line_no, 'role', r.role, 'item_line_no', r.item_line_no)
        ORDER BY r.line_no), '[]'::json) FROM voucher_gst_line_roles r WHERE r.voucher_id = h.voucher_id)
FROM (SELECT voucher_id, gst_registration_id::text AS gst_registration_id, document_kind, supply_category, counterparty_gstin,
        counterparty_state_code, place_of_supply, invoice_date, original_invoice_no, original_invoice_date, note_reason,
        has_rcm, invoice_round_off::text AS invoice_round_off, invoice_value::text AS invoice_value, engine_version
      FROM voucher_gst WHERE voucher_id = :v) h
"""


@dataclass(frozen=True)
class StoredInvoice:
    header: dict
    items: list[dict]
    roles: list[dict]


def load_stored(conn: Connection, voucher_id: object) -> StoredInvoice | None:
    try:
        uuid.UUID(str(voucher_id))
    except ValueError:
        return None
    row = conn.execute(text(_STORED_SQL), {"v": voucher_id}).first()
    if row is None:
        return None
    return StoredInvoice(row[0], row[1], row[2])


def ledger_names(conn: Connection, ids: list[object]) -> dict[str, str]:
    rows = conn.execute(text("SELECT id::text, name FROM ledgers WHERE id = ANY(:ids)"), {"ids": [uuid.UUID(str(i)) for i in ids]})
    return {r[0]: r[1] for r in rows}


def number_limit(conn: Connection, voucher_id: object, on: date) -> tuple[bool, Decimal | None]:
    """(is the voucher a GST document, the invoice-number length limit in force on `on`)."""
    row = conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM voucher_gst WHERE voucher_id = :v), "
            "(SELECT numeric_value::text FROM gst_thresholds WHERE threshold_key = 'invoice_number_max_length' "
            " AND effective_from <= :on AND (effective_to IS NULL OR effective_to >= :on) "
            " ORDER BY effective_from DESC LIMIT 1)"
        ),
        {"v": voucher_id, "on": on},
    ).one()
    return bool(row[0]), None if row[1] is None else Decimal(row[1])
