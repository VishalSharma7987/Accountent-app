"""SQL loaders and writers for parties, opening bills and bill allocations (Phase 2). SQL only: no rules, no maths.

Every function takes a SQLAlchemy Connection owned by the caller.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.bills import AllocationRow, OpeningBillRow, ResolvedAllocation
from app.engine.models import OpeningBalance

CENTS = Decimal("0.01")


def _uuids(values: Iterable[object]) -> list[uuid.UUID]:
    return [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in values]


# ===================================================================================================== parties


@dataclass(frozen=True)
class PartyRow:
    ledger_id: uuid.UUID
    gstin: str | None
    pan: str | None
    state_code: str | None
    credit_days: int
    msme_category: str
    udyam_no: str | None
    msme_written_agreement: bool
    bill_wise: bool
    msme_activity: str | None = None
    udyam_registration_date: date | None = None
    msme_agreed_days: int | None = None


_PARTY_COLUMNS = (
    "ledger_id, gstin, pan, state_code, credit_days, msme_category, udyam_no, msme_written_agreement, bill_wise, "
    "msme_activity, udyam_registration_date, msme_agreed_days"
)


def party_rows_for(conn: Connection, client_id: object, ledger_ids: Iterable[object]) -> dict[uuid.UUID, PartyRow]:
    ids = list(set(_uuids(ledger_ids)))
    if not ids:
        return {}
    rows = conn.execute(
        text(f"SELECT {_PARTY_COLUMNS} FROM parties WHERE client_id = :c AND ledger_id = ANY(:ids)"),
        {"c": client_id, "ids": ids},
    )
    return {r[0]: PartyRow(*r) for r in rows}


def list_party_rows(conn: Connection, client_id: object) -> dict[uuid.UUID, PartyRow]:
    rows = conn.execute(text(f"SELECT {_PARTY_COLUMNS} FROM parties WHERE client_id = :c"), {"c": client_id})
    return {r[0]: PartyRow(*r) for r in rows}


def upsert_party(conn: Connection, client_id: object, row: PartyRow) -> None:
    conn.execute(
        text(
            "INSERT INTO parties (ledger_id, client_id, gstin, pan, state_code, credit_days, msme_category, udyam_no, "
            "msme_written_agreement, bill_wise, msme_activity, udyam_registration_date, msme_agreed_days) "
            "VALUES (:l, :c, :gstin, :pan, :state, :days, :cat, :udyam, :agr, :bw, :act, :udate, :adays) "
            "ON CONFLICT (ledger_id) DO UPDATE SET gstin = EXCLUDED.gstin, pan = EXCLUDED.pan, "
            "state_code = EXCLUDED.state_code, credit_days = EXCLUDED.credit_days, "
            "msme_category = EXCLUDED.msme_category, udyam_no = EXCLUDED.udyam_no, "
            "msme_written_agreement = EXCLUDED.msme_written_agreement, bill_wise = EXCLUDED.bill_wise, "
            "msme_activity = EXCLUDED.msme_activity, udyam_registration_date = EXCLUDED.udyam_registration_date, "
            "msme_agreed_days = EXCLUDED.msme_agreed_days"
        ),
        {
            "l": row.ledger_id, "c": client_id, "gstin": row.gstin, "pan": row.pan, "state": row.state_code,
            "days": row.credit_days, "cat": row.msme_category, "udyam": row.udyam_no,
            "agr": row.msme_written_agreement, "bw": row.bill_wise, "act": row.msme_activity,
            "udate": row.udyam_registration_date, "adays": row.msme_agreed_days,
        },
    )


def unallocated_posted_line_count(conn: Connection, client_id: object, ledger_id: object) -> int:
    """Lines of posted/reversed vouchers for the ledger that carry no allocation (they predate bill-wise)."""
    return conn.execute(
        text(
            "SELECT count(*) FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
            "WHERE v.client_id = :c AND vl.ledger_id = :l AND v.status IN ('posted', 'reversed') "
            "AND NOT EXISTS (SELECT 1 FROM bill_allocations a WHERE a.voucher_id = vl.voucher_id AND a.line_no = vl.line_no)"
        ),
        {"c": client_id, "l": ledger_id},
    ).scalar_one()


def allocation_count(conn: Connection, client_id: object, ledger_id: object) -> int:
    """Allocations of the party in vouchers of any status (history that bill-wise tracking depends on)."""
    return conn.execute(
        text("SELECT count(*) FROM bill_allocations WHERE client_id = :c AND party_ledger_id = :l"),
        {"c": client_id, "l": ledger_id},
    ).scalar_one()


def lock_party_rows(conn: Connection, client_id: object, ledger_ids: Iterable[object]) -> None:
    """Take row locks on the parties, so two posts settling the same bill queue up (checked again after the lock)."""
    ids = sorted(set(_uuids(ledger_ids)))
    if ids:
        conn.execute(
            text("SELECT ledger_id FROM parties WHERE client_id = :c AND ledger_id = ANY(:ids) ORDER BY ledger_id FOR UPDATE"),
            {"c": client_id, "ids": ids},
        ).all()


# ============================================================================================== opening bills


def opening_bill_rows(
    conn: Connection, client_id: object, fy_id: object, party_ids: Sequence[object] | None = None
) -> list[OpeningBillRow]:
    sql = (
        "SELECT party_ledger_id, bill_ref, bill_date, due_date, debit - credit FROM opening_bills "
        "WHERE client_id = :c AND financial_year_id = :fy"
    )
    params: dict = {"c": client_id, "fy": fy_id}
    if party_ids is not None:
        sql += " AND party_ledger_id = ANY(:ids)"
        params["ids"] = _uuids(party_ids)
    rows = conn.execute(text(sql + " ORDER BY bill_date, lower(bill_ref)"), params)
    return [OpeningBillRow(r[0], r[1], r[2], r[3], r[4].quantize(CENTS)) for r in rows]


def replace_opening_bills(
    conn: Connection, client_id: object, fy_id: object, ledger_id: object, rows: Sequence[OpeningBillRow]
) -> None:
    conn.execute(
        text("DELETE FROM opening_bills WHERE client_id = :c AND financial_year_id = :fy AND party_ledger_id = :l"),
        {"c": client_id, "fy": fy_id, "l": ledger_id},
    )
    if rows:
        conn.execute(
            text(
                "INSERT INTO opening_bills (client_id, financial_year_id, party_ledger_id, bill_ref, bill_date, "
                "due_date, debit, credit) VALUES (:c, :fy, :l, :ref, :bd, :dd, :d, :cr)"
            ),
            [
                {
                    "c": client_id, "fy": fy_id, "l": ledger_id, "ref": r.bill_ref, "bd": r.bill_date,
                    "dd": r.due_date, "d": max(r.amount, Decimal(0)), "cr": max(-r.amount, Decimal(0)),
                }
                for r in rows
            ],
        )


@dataclass(frozen=True)
class OpeningCover:
    """One financial year of one party: its ledger opening balance and the signed total of its opening bills."""

    financial_year_id: object
    start_date: date
    ledger_opening: OpeningBalance | None
    bills_total: Decimal


def opening_cover(
    conn: Connection, client_id: object, ledger_id: object, fy_id: object | None = None
) -> list[OpeningCover]:
    """Years in which the ledger has an opening balance or opening bills (or just the given year)."""
    rows = conn.execute(
        text(
            "SELECT y.id, y.start_date, ob.debit, ob.credit, "
            "(SELECT coalesce(sum(b.debit - b.credit), 0) FROM opening_bills b "
            " WHERE b.party_ledger_id = :l AND b.financial_year_id = y.id) "
            "FROM financial_years y LEFT JOIN opening_balances ob ON ob.financial_year_id = y.id AND ob.ledger_id = :l "
            "WHERE y.client_id = :c AND (CAST(:fy AS uuid) IS NULL OR y.id = :fy) ORDER BY y.start_date"
        ),
        {"c": client_id, "l": ledger_id, "fy": fy_id},
    )
    out = []
    for year_id, start, debit, credit, total in rows:
        opening = None if debit is None else OpeningBalance(debit.quantize(CENTS), credit.quantize(CENTS))
        total = total.quantize(CENTS)
        if opening is None and total == 0:
            continue
        out.append(OpeningCover(year_id, start, opening, total))
    return out


# ================================================================================================ allocations


def allocation_rows(
    conn: Connection, client_id: object, fy_id: object, as_on: date | None, party_ids: Sequence[object] | None
) -> list[AllocationRow]:
    """Allocations of the posted/reversed vouchers of the year dated up to as_on (all if None)."""
    sql = (
        "SELECT a.party_ledger_id, a.kind, a.bill_ref, v.voucher_date, a.due_date, a.debit - a.credit, v.goods_received_date "
        "FROM bill_allocations a JOIN vouchers v ON v.id = a.voucher_id "
        "WHERE a.client_id = :c AND v.financial_year_id = :fy AND v.status IN ('posted', 'reversed')"
    )
    params: dict = {"c": client_id, "fy": fy_id}
    if as_on is not None:
        sql += " AND v.voucher_date <= :on"
        params["on"] = as_on
    if party_ids is not None:
        sql += " AND a.party_ledger_id = ANY(:ids)"
        params["ids"] = _uuids(party_ids)
    rows = conn.execute(text(sql + " ORDER BY v.voucher_date, v.voucher_number, a.line_no"), params)
    return [AllocationRow(r[0], r[1], r[2], r[3], r[4], r[5].quantize(CENTS), r[6]) for r in rows]


def used_refs(
    conn: Connection, client_id: object, party_ids: Sequence[object], exclude_voucher_id: object | None
) -> set[tuple[object, str]]:
    """Every bill reference ever created for the parties, in any year and any voucher status (drafts included,
    except the voucher being checked): a reference is never reused."""
    rows = conn.execute(
        text(
            "SELECT party_ledger_id, lower(btrim(bill_ref)) FROM bill_allocations "
            "WHERE client_id = :c AND party_ledger_id = ANY(:ids) AND kind IN ('new_ref', 'advance') "
            "AND (CAST(:ex AS uuid) IS NULL OR voucher_id <> :ex) "
            "UNION SELECT party_ledger_id, lower(btrim(bill_ref)) FROM opening_bills "
            "WHERE client_id = :c AND party_ledger_id = ANY(:ids)"
        ),
        {"c": client_id, "ids": _uuids(party_ids), "ex": exclude_voucher_id},
    )
    return {(r[0], r[1]) for r in rows}


def insert_allocations(
    conn: Connection, client_id: object, voucher_id: object, rows: Sequence[ResolvedAllocation]
) -> None:
    if not rows:
        return
    conn.execute(
        text(
            "INSERT INTO bill_allocations (client_id, voucher_id, line_no, party_ledger_id, kind, bill_ref, due_date, "
            "debit, credit) VALUES (:c, :v, :n, :p, :k, :ref, :due, :d, :cr)"
        ),
        [
            {
                "c": client_id, "v": voucher_id, "n": r.line_no, "p": r.party_ledger_id, "k": r.kind,
                "ref": r.bill_ref, "due": r.due_date, "d": r.debit, "cr": r.credit,
            }
            for r in rows
        ],
    )
