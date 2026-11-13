"""Reads and writes for the TDS return workings and certificates (Phase 4, package D). SQL only: no accounting here.

Reads the deduction items of POSTED, non-reversed vouchers (package B writes them), challans and allocations (package C).
"""

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.tds_returns import AllocRow, ChallanRow, ItemRow
from app.engine.tds_types import FormRule

FAR = date(9999, 12, 31)


def client(conn: Connection, client_id: object) -> dict | None:
    row = conn.execute(text("SELECT id, name, legal_name, pan, tan FROM clients WHERE id = :c"), {"c": client_id}).first()
    return None if row is None else dict(row._mapping)


def financial_year(conn: Connection, client_id: object, fy_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE id = :f AND client_id = :c"),
        {"f": fy_id, "c": client_id},
    ).first()
    return None if row is None else dict(row._mapping)


def forms(conn: Connection) -> list[FormRule]:
    rows = conn.execute(text(
        "SELECT form_key, act, form_no, description, rule_ref, effective_from, effective_to, verification_status, "
        "source_reference FROM tds_forms"))
    return [FormRule(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows]


def form_source(conn: Connection, form_key: str, act: str, form_no: str) -> str:
    return conn.execute(
        text("SELECT source_reference FROM tds_forms WHERE form_key = :k AND act = :a AND form_no = :n ORDER BY effective_from DESC"),
        {"k": form_key, "a": act, "n": form_no},
    ).scalar_one()


def items(conn: Connection, client_id: object, fy_id: object, start: date, end: date, deductee_ledger_id: object = None):
    """(ItemRow list, rule status entries [(table, status, source)]) of posted, non-reversed deductions with event date in [start, end]."""
    rows = conn.execute(
        text(
            "SELECT i.id, v.voucher_number, i.deductee_ledger_id, l.name, d.pan, d.pan_status, i.nature_key, n.rate_mode, i.kind, "
            "i.section_ref, sr.payment_code, i.act, i.event_date, i.payment_amount, i.taxable_base, i.rate_applied, i.rate_reason, "
            "i.tds_amount, c.certificate_no, r.verification_status, r.source_reference, sr.verification_status, sr.source_reference "
            "FROM tds_voucher_items i "
            "JOIN vouchers v ON v.id = i.voucher_id AND v.client_id = i.client_id "
            "JOIN ledgers l ON l.id = i.deductee_ledger_id AND l.client_id = i.client_id "
            "JOIN tds_deductees d ON d.ledger_id = i.deductee_ledger_id AND d.client_id = i.client_id "
            "JOIN tds_natures n ON n.nature_key = i.nature_key "
            "LEFT JOIN tds_section_refs sr ON sr.nature_key = i.nature_key AND sr.act = i.act "
            "  AND i.event_date >= sr.effective_from AND i.event_date <= COALESCE(sr.effective_to, :far) "
            "LEFT JOIN tds_lower_deduction_certs c ON c.id = i.lower_cert_id AND c.client_id = i.client_id "
            "LEFT JOIN tds_rates r ON r.id = i.rate_rule_id "
            "WHERE i.client_id = :c AND i.financial_year_id = :f AND i.event_date BETWEEN :s AND :e "
            "AND v.status = 'posted' AND v.reverses_voucher_id IS NULL "
            "AND (CAST(:d AS uuid) IS NULL OR i.deductee_ledger_id = CAST(:d AS uuid)) "
            "ORDER BY i.event_date, v.voucher_number, i.item_no"
        ),
        {"c": client_id, "f": fy_id, "s": start, "e": end, "d": deductee_ledger_id, "far": FAR},
    ).all()
    out: list[ItemRow] = []
    statuses: list[tuple[str, str, str]] = []
    for r in rows:
        out.append(ItemRow(
            item_id=str(r[0]), voucher_number=r[1], deductee_ledger_id=str(r[2]), deductee_name=r[3], pan=r[4], pan_status=r[5],
            nature_key=r[6], rate_mode=r[7], kind=r[8], section_ref=r[9], payment_code=r[10], act=r[11], event_date=r[12],
            payment_amount=Decimal(r[13]).quantize(Decimal("0.01")), taxable_base=Decimal(r[14]).quantize(Decimal("0.01")),
            rate_applied=Decimal(r[15]), rate_reason=r[16], tds_amount=Decimal(r[17]).quantize(Decimal("0.01")), certificate_no=r[18]))
        if r[19] is not None:
            statuses.append(("rate", r[19], r[20]))
        if r[21] is not None:
            statuses.append(("section_ref", r[21], r[22]))
    return out, statuses


def challans_and_allocations(conn: Connection, client_id: object, kind: str, fy_id: object, quarter: int | None,
                             item_ids: list[str]) -> tuple[list[ChallanRow], list[AllocRow]]:
    """Challans of the quarter plus any challan that holds an allocation to one of `item_ids`; allocations of those challans."""
    rows = conn.execute(
        text(
            "SELECT ch.id, ch.bsr_code, ch.deposit_date, ch.challan_serial_no, ch.tax_amount, ch.interest_amount, ch.fee_amount, "
            "ch.other_amount, ch.total_amount, ch.status, "
            "(CAST(:q AS integer) IS NOT NULL AND ch.financial_year_id = :f AND ch.quarter = CAST(:q AS integer)) "
            "FROM tds_challans ch WHERE ch.client_id = :c AND ch.kind = :k AND "
            "((CAST(:q AS integer) IS NOT NULL AND ch.financial_year_id = :f AND ch.quarter = CAST(:q AS integer)) "
            " OR ch.id IN (SELECT challan_id FROM tds_challan_allocations WHERE item_id = ANY(CAST(:ids AS uuid[])))) "
            "ORDER BY ch.deposit_date, ch.bsr_code, ch.challan_serial_no"
        ),
        {"c": client_id, "k": kind, "f": fy_id, "q": quarter, "ids": item_ids},
    ).all()
    challans = [ChallanRow(str(r[0]), r[1], r[2], r[3], *(Decimal(x).quantize(Decimal("0.01")) for x in r[4:9]), r[9], bool(r[10]))
                for r in rows]
    ids = [c.challan_id for c in challans]
    al = conn.execute(
        text("SELECT challan_id, item_id, amount FROM tds_challan_allocations WHERE challan_id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": ids},
    ).all()
    return challans, [AllocRow(str(a[0]), str(a[1]), Decimal(a[2]).quantize(Decimal("0.01"))) for a in al]


def lock_challans(conn: Connection, client_id: object, challan_ids: list[str]) -> None:
    conn.execute(
        text("UPDATE tds_challans SET status = 'locked' WHERE client_id = :c AND id = ANY(CAST(:ids AS uuid[])) AND status <> 'locked'"),
        {"c": client_id, "ids": challan_ids},
    )


def challan_ids_for_working(conn: Connection, client_id: object, bsr_rows: list[tuple]) -> list[str]:
    """Challan ids by (bsr_code, deposit_date, serial_no): the CIN is unique per client (T-20)."""
    out = []
    for bsr, dep, serial in bsr_rows:
        cid = conn.execute(
            text("SELECT id FROM tds_challans WHERE client_id = :c AND bsr_code = :b AND deposit_date = :d AND challan_serial_no = :s"),
            {"c": client_id, "b": bsr, "d": dep, "s": serial},
        ).scalar_one_or_none()
        if cid is not None:
            out.append(str(cid))
    return out


# ---- workings ------------------------------------------------------------------------------------------------------


def next_version(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str) -> int:
    return conn.execute(
        text("SELECT COALESCE(max(version), 0) + 1 FROM tds_return_workings WHERE client_id = :c AND financial_year_id = :f "
             "AND quarter = :q AND return_kind = :k"),
        {"c": client_id, "f": fy_id, "q": quarter, "k": return_kind},
    ).scalar_one()


def insert_working(conn: Connection, row: dict) -> object:
    return conn.execute(
        text(
            "INSERT INTO tds_return_workings (client_id, financial_year_id, quarter, return_kind, form_no, form_status, version, "
            "data, data_hash, rule_statuses, created_by) VALUES (:client_id, :fy, :quarter, :return_kind, :form_no, :form_status, "
            ":version, CAST(:data AS jsonb), :data_hash, CAST(:rule_statuses AS jsonb), :created_by) RETURNING id"
        ),
        {**row, "data": json.dumps(row["data"]), "rule_statuses": json.dumps(row["rule_statuses"])},
    ).scalar_one()


_WORKING_COLS = ("id, client_id, financial_year_id, quarter, return_kind, form_no, form_status, version, status, data, data_hash, "
                 "rule_statuses, created_by, created_at")


def working(conn: Connection, working_id: object, lock: bool = False) -> dict | None:
    row = conn.execute(
        text(f"SELECT {_WORKING_COLS} FROM tds_return_workings WHERE id = :i" + (" FOR UPDATE" if lock else "")), {"i": working_id}
    ).first()
    return None if row is None else dict(row._mapping)


def workings(conn: Connection, client_id: object, fy_id: object | None, quarter: int | None, return_kind: str | None) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, financial_year_id, quarter, return_kind, form_no, form_status, version, status, data_hash, created_by, created_at "
            "FROM tds_return_workings WHERE client_id = :c AND (CAST(:f AS uuid) IS NULL OR financial_year_id = CAST(:f AS uuid)) "
            "AND (CAST(:q AS integer) IS NULL OR quarter = CAST(:q AS integer)) AND (CAST(:k AS text) IS NULL OR return_kind = CAST(:k AS text)) "
            "ORDER BY financial_year_id, quarter, return_kind, version DESC"
        ),
        {"c": client_id, "f": fy_id, "q": quarter, "k": return_kind},
    )
    return [dict(r._mapping) for r in rows]


def mark_final(conn: Connection, working_id: object) -> None:
    conn.execute(text("UPDATE tds_return_workings SET status = 'final' WHERE id = :i"), {"i": working_id})


def latest_final_working(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str) -> dict | None:
    row = conn.execute(
        text(f"SELECT {_WORKING_COLS} FROM tds_return_workings WHERE client_id = :c AND financial_year_id = :f AND quarter = :q "
             "AND return_kind = :k AND status = 'final' ORDER BY version DESC LIMIT 1"),
        {"c": client_id, "f": fy_id, "q": quarter, "k": return_kind},
    ).first()
    return None if row is None else dict(row._mapping)


# ---- filed returns -------------------------------------------------------------------------------------------------


def filed(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str) -> dict | None:
    row = conn.execute(
        text("SELECT id, financial_year_id, quarter, return_kind, receipt_no, filed_on, data, entered_by, entered_at FROM tds_filed_returns "
             "WHERE client_id = :c AND financial_year_id = :f AND quarter = :q AND return_kind = :k"),
        {"c": client_id, "f": fy_id, "q": quarter, "k": return_kind},
    ).first()
    return None if row is None else dict(row._mapping)


def upsert_filed(conn: Connection, client_id: object, fy_id: object, quarter: int, return_kind: str, receipt_no, filed_on, data: dict,
                 actor: str) -> object:
    return conn.execute(
        text(
            "INSERT INTO tds_filed_returns (client_id, financial_year_id, quarter, return_kind, receipt_no, filed_on, data, entered_by) "
            "VALUES (:c, :f, :q, :k, :r, :o, CAST(:d AS jsonb), :a) "
            "ON CONFLICT (client_id, financial_year_id, quarter, return_kind) DO UPDATE SET receipt_no = EXCLUDED.receipt_no, "
            "filed_on = EXCLUDED.filed_on, data = EXCLUDED.data, entered_by = EXCLUDED.entered_by, entered_at = now() RETURNING id"
        ),
        {"c": client_id, "f": fy_id, "q": quarter, "k": return_kind, "r": receipt_no, "o": filed_on, "d": json.dumps(data), "a": actor},
    ).scalar_one()


# ---- certificates --------------------------------------------------------------------------------------------------


def deductee(conn: Connection, client_id: object, ledger_id: object) -> dict | None:
    row = conn.execute(
        text("SELECT d.ledger_id, l.name, d.pan, d.pan_status FROM tds_deductees d JOIN ledgers l ON l.id = d.ledger_id AND l.client_id = d.client_id "
             "WHERE d.client_id = :c AND d.ledger_id = :l"),
        {"c": client_id, "l": ledger_id},
    ).first()
    return None if row is None else dict(row._mapping)


def next_certificate_version(conn: Connection, client_id: object, kind: str, ledger_id: object, fy_id: object, quarter: int | None) -> int:
    return conn.execute(
        text("SELECT COALESCE(max(version), 0) + 1 FROM tds_certificates WHERE client_id = :c AND certificate_kind = :k "
             "AND deductee_ledger_id = :l AND financial_year_id = :f AND quarter IS NOT DISTINCT FROM CAST(:q AS integer)"),
        {"c": client_id, "k": kind, "l": ledger_id, "f": fy_id, "q": quarter},
    ).scalar_one()


def insert_certificate(conn: Connection, row: dict) -> object:
    return conn.execute(
        text(
            "INSERT INTO tds_certificates (client_id, certificate_kind, deductee_ledger_id, financial_year_id, quarter, form_no, form_status, "
            "version, data, data_hash, created_by) VALUES (:client_id, :kind, :ledger_id, :fy, :quarter, :form_no, :form_status, :version, "
            "CAST(:data AS jsonb), :data_hash, :created_by) RETURNING id"
        ),
        {**row, "data": json.dumps(row["data"])},
    ).scalar_one()


_CERT_COLS = ("id, client_id, certificate_kind, deductee_ledger_id, financial_year_id, quarter, form_no, form_status, version, "
              "certificate_no, issued_on, data, data_hash, created_by, created_at")


def certificate(conn: Connection, client_id: object, cert_id: object) -> dict | None:
    row = conn.execute(text(f"SELECT {_CERT_COLS} FROM tds_certificates WHERE id = :i AND client_id = :c"), {"i": cert_id, "c": client_id}).first()
    return None if row is None else dict(row._mapping)


def certificate_by_id(conn: Connection, cert_id: object) -> dict | None:
    row = conn.execute(text(f"SELECT {_CERT_COLS} FROM tds_certificates WHERE id = :i"), {"i": cert_id}).first()
    return None if row is None else dict(row._mapping)


def certificates(conn: Connection, client_id: object, fy_id: object | None, quarter: int | None, ledger_id: object | None,
                 kind: str | None) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, certificate_kind, deductee_ledger_id, financial_year_id, quarter, form_no, form_status, version, certificate_no, "
            "issued_on, data_hash, created_by, created_at FROM tds_certificates WHERE client_id = :c "
            "AND (CAST(:f AS uuid) IS NULL OR financial_year_id = CAST(:f AS uuid)) AND (CAST(:q AS integer) IS NULL OR quarter = CAST(:q AS integer)) "
            "AND (CAST(:l AS uuid) IS NULL OR deductee_ledger_id = CAST(:l AS uuid)) AND (CAST(:k AS text) IS NULL OR certificate_kind = CAST(:k AS text)) "
            "ORDER BY financial_year_id, quarter, deductee_ledger_id, version DESC"
        ),
        {"c": client_id, "f": fy_id, "q": quarter, "l": ledger_id, "k": kind},
    )
    return [dict(r._mapping) for r in rows]


def update_certificate(conn: Connection, cert_id: object, certificate_no: str | None, issued_on: date | None) -> None:
    conn.execute(text("UPDATE tds_certificates SET certificate_no = :n, issued_on = :o WHERE id = :i"),
                 {"n": certificate_no, "o": issued_on, "i": cert_id})
