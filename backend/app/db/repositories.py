"""Reads that turn database rows into engine models. SQL only: no accounting rules and no accounting maths here.

Every function takes a SQLAlchemy Connection owned by the caller.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.duplicates import ExistingVoucher
from app.engine.models import Allocation, Group, Ledger, OpeningBalance, PostedLine

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class FinancialYearRow:
    id: object
    start_date: date
    end_date: date


def client_exists(conn: Connection, client_id: object) -> bool:
    return conn.execute(text("SELECT 1 FROM clients WHERE id = :c"), {"c": client_id}).first() is not None


def find_group_id(conn: Connection, client_id: object, group_code: str) -> object | None:
    """A system group, or one of this client's own groups, by code."""
    row = conn.execute(
        text("SELECT id FROM account_groups WHERE code = :code AND (client_id IS NULL OR client_id = :c)"),
        {"code": group_code, "c": client_id},
    ).first()
    return row[0] if row else None


def system_group_ids(conn: Connection) -> dict[str, object]:
    return {code: gid for code, gid in conn.execute(text("SELECT code, id FROM account_groups WHERE client_id IS NULL"))}


def get_ledger(conn: Connection, client_id: object, ledger_id: object) -> Ledger | None:
    row = conn.execute(
        text(
            "SELECT l.id, l.name, g.code, l.is_active, l.client_id FROM ledgers l "
            "JOIN account_groups g ON g.id = l.group_id WHERE l.id = :id AND l.client_id = :c"
        ),
        {"id": ledger_id, "c": client_id},
    ).first()
    return Ledger(row[0], row[1], row[2], row[3], row[4]) if row else None


def ledger_name_exists(conn: Connection, client_id: object, name: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM ledgers WHERE client_id = :c AND lower(name) = lower(:n)"), {"c": client_id, "n": name}
    ).first() is not None


def get_financial_year(conn: Connection, client_id: object, fy_id: object) -> FinancialYearRow | None:
    row = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE id = :id AND client_id = :c"),
        {"id": fy_id, "c": client_id},
    ).first()
    return FinancialYearRow(*row) if row else None


def latest_financial_year(conn: Connection, client_id: object) -> FinancialYearRow | None:
    row = conn.execute(
        text("SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c ORDER BY start_date DESC LIMIT 1"),
        {"c": client_id},
    ).first()
    return FinancialYearRow(*row) if row else None


def openings_for_year(conn: Connection, client_id: object, fy_id: object) -> dict[object, OpeningBalance]:
    rows = conn.execute(
        text("SELECT ledger_id, debit, credit FROM opening_balances WHERE client_id = :c AND financial_year_id = :fy"),
        {"c": client_id, "fy": fy_id},
    )
    return {ledger_id: OpeningBalance(debit.quantize(CENTS), credit.quantize(CENTS)) for ledger_id, debit, credit in rows}


def lines_touching_ledger(conn: Connection, client_id: object, ledger_id: object, fy_id: object) -> list[PostedLine]:
    """Every line of the posted/reversed vouchers of this year that have a line for the ledger (the other lines
    give the counter ledger names on the statement)."""
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_number, v.voucher_type, v.voucher_date, v.narration, v.status, vl.line_no, "
            "vl.ledger_id, l.name, vl.debit, vl.credit "
            "FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id JOIN ledgers l ON l.id = vl.ledger_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND v.status IN ('posted', 'reversed') "
            "AND v.id IN (SELECT voucher_id FROM voucher_lines WHERE ledger_id = :ledger) "
            "ORDER BY v.voucher_date, v.voucher_number, vl.line_no"
        ),
        {"c": client_id, "fy": fy_id, "ledger": ledger_id},
    )
    return [
        PostedLine(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9].quantize(CENTS), r[10].quantize(CENTS))
        for r in rows
    ]


def open_voucher_count_for_ledger(conn: Connection, client_id: object, ledger_id: object) -> int:
    """Draft or approved vouchers that have a line for the ledger."""
    return conn.execute(
        text(
            "SELECT count(DISTINCT v.id) FROM vouchers v JOIN voucher_lines vl ON vl.voucher_id = v.id "
            "WHERE v.client_id = :c AND vl.ledger_id = :ledger AND v.status IN ('draft', 'approved')"
        ),
        {"c": client_id, "ledger": ledger_id},
    ).scalar_one()


def posted_voucher_exists(conn: Connection, client_id: object, fy_id: object) -> bool:
    """True once any voucher of the year is posted or reversed (opening balances are then frozen)."""
    return conn.execute(
        text(
            "SELECT 1 FROM vouchers WHERE client_id = :c AND financial_year_id = :fy "
            "AND status IN ('posted', 'reversed') LIMIT 1"
        ),
        {"c": client_id, "fy": fy_id},
    ).first() is not None


# ================================================================================================== vouchers


@dataclass(frozen=True)
class PeriodRow:
    start: date
    end: date
    status: str


@dataclass(frozen=True)
class VoucherLineRecord:
    line_no: int
    ledger_id: object
    ledger_name: str
    debit: Decimal
    credit: Decimal
    allocations: tuple[Allocation, ...] = ()  # Phase 2: bill-wise allocations of a party line (due date resolved)


@dataclass(frozen=True)
class VoucherRecord:
    id: object
    client_id: object
    financial_year_id: object
    voucher_type: str
    voucher_number: str | None
    voucher_date: date
    narration: str
    reference_no: str | None
    party_ledger_id: object | None
    status: str
    reverses_voucher_id: object | None
    reversed_by_voucher_id: object | None
    duplicate_override_reason: str | None
    created_by: str
    approved_by: str | None
    posted_by: str | None
    financial_year_start: date
    lines: tuple[VoucherLineRecord, ...]


_VOUCHER_SQL = (
    "SELECT v.id, v.client_id, v.financial_year_id, v.voucher_type, v.voucher_number, v.voucher_date, v.narration, "
    "v.reference_no, v.party_ledger_id, v.status, v.reverses_voucher_id, v.reversed_by_voucher_id, "
    "v.duplicate_override_reason, v.created_by, v.approved_by, v.posted_by, "
    "(SELECT f.start_date FROM financial_years f WHERE f.id = v.financial_year_id), "
    "(SELECT coalesce(json_agg(json_build_object('line_no', vl.line_no, 'ledger_id', vl.ledger_id, "
    "'ledger_name', l.name, 'debit', vl.debit::text, 'credit', vl.credit::text, 'allocations', "
    "(SELECT coalesce(json_agg(json_build_object('kind', a.kind, 'bill_ref', a.bill_ref, 'due_date', a.due_date, "
    "'amount', (a.debit + a.credit)::text) ORDER BY a.kind, a.bill_ref, a.due_date), '[]'::json) "
    "FROM bill_allocations a WHERE a.voucher_id = vl.voucher_id AND a.line_no = vl.line_no)) "
    "ORDER BY vl.line_no), '[]'::json) "
    "FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id WHERE vl.voucher_id = v.id) "
    "FROM vouchers v WHERE v.id = :id"
)


def load_voucher(conn: Connection, voucher_id: object, *, lock: bool = False) -> VoucherRecord | None:
    """The voucher with its lines, in one query. lock=True takes a row lock (FOR UPDATE OF v) until the
    transaction ends, so state changes of one voucher are serialised."""
    try:
        uuid.UUID(str(voucher_id))
    except ValueError:  # a malformed id is simply "not found" (never sent to the database: it would abort the transaction)
        return None
    row = conn.execute(text(_VOUCHER_SQL + (" FOR UPDATE OF v" if lock else "")), {"id": voucher_id}).first()
    if row is None:
        return None
    lines = tuple(
        VoucherLineRecord(
            x["line_no"], uuid.UUID(x["ledger_id"]), x["ledger_name"],
            Decimal(x["debit"]).quantize(CENTS), Decimal(x["credit"]).quantize(CENTS),
            tuple(
                Allocation(
                    a["kind"], Decimal(a["amount"]).quantize(CENTS), a["bill_ref"],
                    None if a["due_date"] is None else date.fromisoformat(a["due_date"]),
                )
                for a in x["allocations"]
            ),
        )
        for x in row[17]
    )
    return VoucherRecord(*row[:17], lines)


@dataclass(frozen=True)
class ValidationContext:
    """Everything the engine needs to validate a voucher draft, loaded in ONE round trip."""

    client_exists: bool
    ledgers: dict[object, Ledger]  # keyed by the id as the caller wrote it; unknown/malformed ids are absent
    groups: dict[str, Group]
    years: list[FinancialYearRow]
    periods: list[PeriodRow]


_CONTEXT_SQL = (
    "SELECT EXISTS (SELECT 1 FROM clients WHERE id = :c), "
    "(SELECT coalesce(json_agg(json_build_object('id', l.id, 'name', l.name, 'group_code', g.code, "
    "'is_active', l.is_active, 'client_id', l.client_id)), '[]'::json) FROM ledgers l "
    "JOIN account_groups g ON g.id = l.group_id WHERE l.id = ANY(:ids)), "
    "(SELECT coalesce(json_agg(json_build_object('code', g.code, 'name', g.name, 'nature', g.nature, "
    "'report', g.report, 'parent', p.code)), '[]'::json) FROM account_groups g "
    "LEFT JOIN account_groups p ON p.id = g.parent_id WHERE g.client_id IS NULL OR g.client_id = :c), "
    "(SELECT coalesce(json_agg(json_build_object('id', f.id, 'start', f.start_date, 'end', f.end_date) "
    "ORDER BY f.start_date), '[]'::json) FROM financial_years f WHERE f.client_id = :c), "
    "(SELECT coalesce(json_agg(json_build_object('start', q.period_start, 'end', q.period_end, 'status', q.status) "
    "ORDER BY q.period_start), '[]'::json) FROM periods q WHERE q.client_id = :c)"
)


def load_validation_context(conn: Connection, client_id: object, ledger_ids: Iterable[object]) -> ValidationContext:
    """Ledgers (of ANY client, so the engine can report a foreign ledger), the client's groups, years and periods."""
    wanted = {}
    for raw in ledger_ids:
        try:
            wanted[raw] = uuid.UUID(str(raw))
        except ValueError:  # malformed ids are skipped, which makes them 'unknown ledger' to the engine
            continue
    try:
        client = uuid.UUID(str(client_id))
    except ValueError:
        return ValidationContext(False, {}, {}, [], [])
    row = conn.execute(text(_CONTEXT_SQL), {"c": client, "ids": list(set(wanted.values()))}).first()
    by_uuid = {
        uuid.UUID(x["id"]): Ledger(uuid.UUID(x["id"]), x["name"], x["group_code"], x["is_active"], uuid.UUID(x["client_id"]))
        for x in row[1]
    }
    return ValidationContext(
        client_exists=row[0],
        ledgers={raw: by_uuid[u] for raw, u in wanted.items() if u in by_uuid},
        groups={x["code"]: Group(x["code"], x["name"], x["nature"], x["report"], x["parent"]) for x in row[2]},
        years=[FinancialYearRow(uuid.UUID(x["id"]), date.fromisoformat(x["start"]), date.fromisoformat(x["end"])) for x in row[3]],
        periods=[PeriodRow(date.fromisoformat(x["start"]), date.fromisoformat(x["end"]), x["status"]) for x in row[4]],
    )


def candidate_duplicates(
    conn: Connection, client_id: object, voucher_type: str, reference_no: str | None
) -> list[ExistingVoucher]:
    """Vouchers of the same client and type with the same reference (trimmed, ignoring case): V-10 candidates."""
    if reference_no is None or not reference_no.strip():
        return []
    rows = conn.execute(
        text(
            "SELECT v.id, v.client_id, v.voucher_type, v.party_ledger_id, v.reference_no, "
            "COALESCE((SELECT sum(vl.debit) FROM voucher_lines vl WHERE vl.voucher_id = v.id), 0), "
            "v.status, v.voucher_number, v.voucher_date, v.reverses_voucher_id FROM vouchers v "
            "WHERE v.client_id = :c AND v.voucher_type = :t AND v.status <> 'reversed' "
            "AND lower(btrim(v.reference_no)) = lower(btrim(:ref)) ORDER BY v.voucher_date, v.created_at"
        ),
        {"c": client_id, "t": voucher_type, "ref": reference_no},
    )
    return [
        ExistingVoucher(r[0], r[1], r[2], r[3], r[4], r[5].quantize(CENTS), r[6], r[7], r[8], r[9]) for r in rows
    ]


# ============================================================================================ periods, reports


@dataclass(frozen=True)
class PeriodRecord:
    id: object
    financial_year_id: object
    start: date
    end: date
    status: str  # open | locked
    locked_at: object | None
    locked_by: str | None


_PERIOD_COLUMNS = "id, financial_year_id, period_start, period_end, status, locked_at, locked_by"


def get_period(conn: Connection, client_id: object, period_id: object, *, lock: bool = False) -> PeriodRecord | None:
    try:
        uuid.UUID(str(period_id))
    except ValueError:
        return None
    row = conn.execute(
        text(f"SELECT {_PERIOD_COLUMNS} FROM periods WHERE id = :id AND client_id = :c" + (" FOR UPDATE" if lock else "")),
        {"id": period_id, "c": client_id},
    ).first()
    return PeriodRecord(*row) if row else None


def list_periods(conn: Connection, client_id: object, fy_id: object | None = None) -> list[PeriodRecord]:
    rows = conn.execute(
        text(
            f"SELECT {_PERIOD_COLUMNS} FROM periods WHERE client_id = :c AND (CAST(:fy AS uuid) IS NULL OR financial_year_id = :fy) "
            "ORDER BY period_start"
        ),
        {"c": client_id, "fy": fy_id},
    )
    return [PeriodRecord(*r) for r in rows]


def open_vouchers_in_range(conn: Connection, client_id: object, start: date, end: date) -> list[dict]:
    """Draft and approved vouchers dated inside [start, end]: they block locking that period."""
    rows = conn.execute(
        text(
            "SELECT id, voucher_type, voucher_date, status, narration FROM vouchers WHERE client_id = :c "
            "AND status IN ('draft', 'approved') AND voucher_date BETWEEN :s AND :e ORDER BY voucher_date, created_at"
        ),
        {"c": client_id, "s": start, "e": end},
    )
    return [
        {"voucher_id": r[0], "voucher_type": r[1], "voucher_date": r[2], "status": r[3], "narration": r[4]} for r in rows
    ]


def financial_year_for_date(conn: Connection, client_id: object, on: date) -> FinancialYearRow | None:
    row = conn.execute(
        text(
            "SELECT id, start_date, end_date FROM financial_years WHERE client_id = :c AND :d BETWEEN start_date AND end_date"
        ),
        {"c": client_id, "d": on},
    ).first()
    return FinancialYearRow(*row) if row else None


def ledgers_of_client(conn: Connection, client_id: object) -> list[Ledger]:
    rows = conn.execute(
        text(
            "SELECT l.id, l.name, g.code, l.is_active, l.client_id FROM ledgers l "
            "JOIN account_groups g ON g.id = l.group_id WHERE l.client_id = :c ORDER BY l.name"
        ),
        {"c": client_id},
    )
    return [Ledger(*r) for r in rows]


def groups_for_client(conn: Connection, client_id: object) -> dict[str, Group]:
    rows = conn.execute(
        text(
            "SELECT g.code, g.name, g.nature, g.report, p.code FROM account_groups g "
            "LEFT JOIN account_groups p ON p.id = g.parent_id WHERE g.client_id IS NULL OR g.client_id = :c"
        ),
        {"c": client_id},
    )
    return {r[0]: Group(r[0], r[1], r[2], r[3], r[4]) for r in rows}


def all_posted_lines(conn: Connection, client_id: object, fy_id: object) -> list[PostedLine]:
    """Every line of every posted/reversed voucher of the year."""
    rows = conn.execute(
        text(
            "SELECT v.id, v.voucher_number, v.voucher_type, v.voucher_date, v.narration, v.status, vl.line_no, "
            "vl.ledger_id, l.name, vl.debit, vl.credit FROM voucher_lines vl "
            "JOIN vouchers v ON v.id = vl.voucher_id JOIN ledgers l ON l.id = vl.ledger_id "
            "WHERE v.client_id = :c AND v.financial_year_id = :fy AND v.status IN ('posted', 'reversed') "
            "ORDER BY v.voucher_date, v.voucher_number, vl.line_no"
        ),
        {"c": client_id, "fy": fy_id},
    )
    return [
        PostedLine(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9].quantize(CENTS), r[10].quantize(CENTS))
        for r in rows
    ]
