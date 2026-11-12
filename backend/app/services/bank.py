"""Bank statements: saved column mappings (formats), preview, import, listing, delete.

Statements are stored SEPARATELY from the books (tables bank_statements / bank_statement_lines); importing never
touches a voucher. Services take a SQLAlchemy Connection and never commit; every change is audit-logged.
Bank wording: `debit` = withdrawal, `credit` = deposit.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.engine.money import MoneyError
from app.importers.bank_statement import (
    MappingError,
    ParsedStatement,
    RowProblem,
    parse_balance_text,
    parse_statement,
    validate_mapping,
)
from app.services import queries
from app.services.audit import AuditEntry, log
from app.services.errors import ServiceError, require_actor

TWO = Decimal("0.01")


def _d(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(TWO)


def _fmt_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


@dataclass(frozen=True)
class BankFormat:
    id: object
    name: str
    mapping: dict


@dataclass(frozen=True)
class ImportedStatement:
    statement_id: object
    lines: int
    opening_balance: Decimal
    closing_balance: Decimal


@dataclass(frozen=True)
class StatementRow:
    id: object
    bank_ledger_id: object
    file_name: str
    period_from: date
    period_to: date
    opening_balance: Decimal
    closing_balance: Decimal
    line_count: int
    matched_count: int


@dataclass(frozen=True)
class StatementLineRow:
    id: object
    line_no: int
    txn_date: date
    description: str
    reference: str | None
    debit: Decimal
    credit: Decimal
    balance: Decimal | None
    match_id: object | None


# ====================================================================================================== formats


def save_format(conn: Connection, client_id: object, name: str, mapping: object, *, actor: str) -> uuid.UUID:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    name = (name or "").strip()
    if not name:
        raise ServiceError("invalid_format", "The format name is required.")
    try:
        clean = validate_mapping(mapping)
    except MappingError as problem:
        raise ServiceError("invalid_mapping", str(problem)) from None
    taken = conn.execute(
        text("SELECT 1 FROM bank_formats WHERE client_id = :c AND lower(btrim(name)) = lower(:n)"),
        {"c": client_id, "n": name},
    ).first()
    if taken:
        raise ServiceError("format_exists", f"A bank format named '{name}' already exists for this client.")
    format_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO bank_formats (id, client_id, name, mapping, created_by) "
            "VALUES (:id, :c, :n, CAST(:m AS jsonb), :by)"
        ),
        {"id": format_id, "c": client_id, "n": name, "m": json.dumps(clean), "by": actor},
    )
    log(conn, AuditEntry(client_id, actor, "create", "bank_format", format_id, new={"name": name, "mapping": clean}))
    return format_id


def list_formats(conn: Connection, client_id: object) -> list[BankFormat]:
    queries.require_client(conn, client_id)
    rows = conn.execute(
        text("SELECT id, name, mapping FROM bank_formats WHERE client_id = :c ORDER BY lower(name)"), {"c": client_id}
    ).all()
    return [BankFormat(r.id, r.name, r.mapping) for r in rows]


def _format_mapping(conn: Connection, client_id: object, format_id: object) -> dict:
    row = conn.execute(
        text("SELECT mapping FROM bank_formats WHERE id = :f AND client_id = :c"), {"f": format_id, "c": client_id}
    ).first()
    if row is None:
        raise ServiceError("not_found", "Bank format not found.")
    return row.mapping


# ====================================================================================================== parsing


def _balance_argument(value: object, what: str) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return parse_balance_text(value)
    except MoneyError as problem:
        raise ServiceError("invalid_amount", f"The {what} is not valid: {problem}") from None


def _parse(content: bytes, mapping: dict, opening: object, closing: object) -> ParsedStatement:
    return parse_statement(
        content, mapping, _balance_argument(opening, "opening balance"), _balance_argument(closing, "closing balance")
    )


def preview_statement(
    conn: Connection, client_id: object, content: bytes, *, format_id: object = None, mapping: object = None,
    opening_balance: object = None, closing_balance: object = None,
) -> ParsedStatement:
    """Parse only; nothing is written. Problems are returned in the result, not raised."""
    queries.require_client(conn, client_id)
    if (format_id is None) == (mapping is None):
        raise ServiceError("invalid_mapping", "Give either a saved format or a mapping.")
    if format_id is not None:
        mapping = _format_mapping(conn, client_id, format_id)
    else:
        try:
            mapping = validate_mapping(mapping)
        except MappingError as problem:
            raise ServiceError("invalid_mapping", str(problem)) from None
    return _parse(content, mapping, opening_balance, closing_balance)


# ====================================================================================================== import


def _require_bank_ledger(conn: Connection, client_id: object, ledger_id: object) -> None:
    row = conn.execute(
        text(
            "WITH RECURSIVE chain AS ("
            " SELECT g.id, g.parent_id, g.code FROM account_groups g JOIN ledgers l ON l.group_id = g.id"
            "  WHERE l.id = :l AND l.client_id = :c"
            " UNION ALL SELECT p.id, p.parent_id, p.code FROM account_groups p JOIN chain ON chain.parent_id = p.id)"
            " SELECT l.name, l.is_active, EXISTS (SELECT 1 FROM chain WHERE code = 'bank_accounts') AS is_bank"
            " FROM ledgers l WHERE l.id = :l AND l.client_id = :c"
        ),
        {"l": ledger_id, "c": client_id},
    ).first()
    if row is None:
        raise ServiceError("invalid_bank_ledger", "The bank ledger does not exist for this client.")
    if not row.is_bank:
        raise ServiceError(
            "invalid_bank_ledger", f"Ledger '{row.name}' is not under Bank Accounts; a statement can only be imported for a bank ledger."
        )
    if not row.is_active:
        raise ServiceError("invalid_bank_ledger", f"Ledger '{row.name}' is inactive.")


def import_statement(
    conn: Connection, client_id: object, bank_ledger_id: object, format_id: object, file_name: str, content: bytes,
    opening_balance: object = None, closing_balance: object = None, *, actor: str,
) -> ImportedStatement:
    actor = require_actor(actor)
    queries.require_client(conn, client_id)
    _require_bank_ledger(conn, client_id, bank_ledger_id)
    mapping = _format_mapping(conn, client_id, format_id)
    file_name = (file_name or "").strip() or "statement"
    digest = hashlib.sha256(content).hexdigest()

    same = conn.execute(
        text(
            "SELECT file_name, period_from, period_to FROM bank_statements "
            "WHERE client_id = :c AND bank_ledger_id = :l AND file_sha256 = :h"
        ),
        {"c": client_id, "l": bank_ledger_id, "h": digest},
    ).first()
    if same:
        raise ServiceError(
            "statement_duplicate",
            f"This file was already imported as '{same.file_name}' ({_fmt_date(same.period_from)} to "
            f"{_fmt_date(same.period_to)}).",
        )

    parsed = _parse(content, mapping, opening_balance, closing_balance)
    if parsed.problems:
        raise ServiceError(
            "statement_invalid",
            f"The statement cannot be imported: {parsed.problems[0].message}",
            _problems_json(parsed.problems),
        )

    clash = conn.execute(
        text(
            "SELECT file_name, period_from, period_to FROM bank_statements "
            "WHERE client_id = :c AND bank_ledger_id = :l AND period_from <= :to AND period_to >= :from "
            "ORDER BY period_from LIMIT 1"
        ),
        {"c": client_id, "l": bank_ledger_id, "from": parsed.period_from, "to": parsed.period_to},
    ).first()
    if clash:
        raise ServiceError(
            "statement_overlap",
            f"This statement ({_fmt_date(parsed.period_from)} to {_fmt_date(parsed.period_to)}) overlaps the statement "
            f"'{clash.file_name}' already imported for this bank ledger ({_fmt_date(clash.period_from)} to "
            f"{_fmt_date(clash.period_to)}).",
        )

    statement_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO bank_statements (id, client_id, bank_ledger_id, format_id, file_name, file_sha256, "
            "period_from, period_to, opening_balance, closing_balance, imported_by) "
            "VALUES (:id, :c, :l, :f, :n, :h, :pf, :pt, :ob, :cb, :by)"
        ),
        {
            "id": statement_id, "c": client_id, "l": bank_ledger_id, "f": format_id, "n": file_name, "h": digest,
            "pf": parsed.period_from, "pt": parsed.period_to, "ob": parsed.opening_balance,
            "cb": parsed.closing_balance, "by": actor,
        },
    )
    conn.execute(
        text(
            "INSERT INTO bank_statement_lines (client_id, statement_id, line_no, txn_date, description, reference, "
            "debit, credit, balance) VALUES (:c, :s, :no, :d, :desc, :ref, :dr, :cr, :bal)"
        ),
        [
            {
                "c": client_id, "s": statement_id, "no": number, "d": x.txn_date, "desc": x.description,
                "ref": x.reference, "dr": x.debit, "cr": x.credit, "bal": x.balance,
            }
            for number, x in enumerate(parsed.lines, start=1)
        ],
    )
    log(conn, AuditEntry(
        client_id, actor, "create", "bank_statement", statement_id,
        new={
            "file_name": file_name, "bank_ledger_id": bank_ledger_id, "period_from": parsed.period_from,
            "period_to": parsed.period_to, "opening_balance": parsed.opening_balance,
            "closing_balance": parsed.closing_balance, "lines": len(parsed.lines), "file_sha256": digest,
        },
    ))
    return ImportedStatement(statement_id, len(parsed.lines), _d(parsed.opening_balance), _d(parsed.closing_balance))


def _problems_json(problems: list[RowProblem]) -> list[dict]:
    return [{"row": p.row, "message": p.message} for p in problems]


# ====================================================================================================== listing


def list_statements(conn: Connection, client_id: object, bank_ledger_id: object = None) -> list[StatementRow]:
    queries.require_client(conn, client_id)
    rows = conn.execute(
        text(
            "SELECT s.id, s.bank_ledger_id, s.file_name, s.period_from, s.period_to, s.opening_balance, "
            "s.closing_balance, count(l.id) AS line_count, count(m.id) AS matched_count "
            "FROM bank_statements s "
            "LEFT JOIN bank_statement_lines l ON l.statement_id = s.id "
            "LEFT JOIN recon_match_items m ON m.bank_line_id = l.id "
            "WHERE s.client_id = :c AND (CAST(:l AS uuid) IS NULL OR s.bank_ledger_id = :l) "
            "GROUP BY s.id ORDER BY s.period_from, s.imported_at"
        ),
        {"c": client_id, "l": bank_ledger_id},
    ).all()
    return [
        StatementRow(r.id, r.bank_ledger_id, r.file_name, r.period_from, r.period_to, _d(r.opening_balance),
                     _d(r.closing_balance), r.line_count, r.matched_count)
        for r in rows
    ]


def _statement(conn: Connection, statement_id: object):
    row = conn.execute(
        text(
            "SELECT id, client_id, bank_ledger_id, file_name, period_from, period_to, opening_balance, "
            "closing_balance FROM bank_statements WHERE id = :s"
        ),
        {"s": statement_id},
    ).first()
    if row is None:
        raise ServiceError("not_found", "Bank statement not found.")
    return row


def statement_lines(conn: Connection, statement_id: object) -> list[StatementLineRow]:
    _statement(conn, statement_id)
    rows = conn.execute(
        text(
            "SELECT l.id, l.line_no, l.txn_date, l.description, l.reference, l.debit, l.credit, l.balance, "
            "m.match_id FROM bank_statement_lines l LEFT JOIN recon_match_items m ON m.bank_line_id = l.id "
            "WHERE l.statement_id = :s ORDER BY l.line_no"
        ),
        {"s": statement_id},
    ).all()
    return [
        StatementLineRow(r.id, r.line_no, r.txn_date, r.description, r.reference, _d(r.debit), _d(r.credit),
                         _d(r.balance), r.match_id)
        for r in rows
    ]


# ====================================================================================================== delete


def delete_statement(conn: Connection, statement_id: object, *, actor: str) -> None:
    """Remove a whole imported statement. Refused while any of its lines is matched or has a draft voucher link."""
    actor = require_actor(actor)
    s = _statement(conn, statement_id)
    matched = conn.execute(
        text(
            "SELECT count(*) FROM recon_match_items m JOIN bank_statement_lines l ON l.id = m.bank_line_id "
            "WHERE l.statement_id = :s"
        ),
        {"s": statement_id},
    ).scalar_one()
    if matched:
        raise ServiceError(
            "statement_in_use",
            f"{matched} line(s) of '{s.file_name}' are matched in the reconciliation; un-match them first.",
        )
    drafts = conn.execute(
        text(
            "SELECT count(*) FROM bank_line_drafts d JOIN bank_statement_lines l ON l.id = d.bank_line_id "
            "WHERE l.statement_id = :s"
        ),
        {"s": statement_id},
    ).scalar_one()
    if drafts:
        raise ServiceError(
            "statement_in_use",
            f"{drafts} line(s) of '{s.file_name}' have a draft voucher created from them; delete those drafts first.",
        )
    count = conn.execute(
        text("SELECT count(*) FROM bank_statement_lines WHERE statement_id = :s"), {"s": statement_id}
    ).scalar_one()
    conn.execute(text("DELETE FROM bank_statement_lines WHERE statement_id = :s"), {"s": statement_id})
    conn.execute(text("DELETE FROM bank_statements WHERE id = :s"), {"s": statement_id})
    log(conn, AuditEntry(
        s.client_id, actor, "delete", "bank_statement", statement_id,
        old={
            "file_name": s.file_name, "bank_ledger_id": s.bank_ledger_id, "period_from": s.period_from,
            "period_to": s.period_to, "opening_balance": s.opening_balance, "closing_balance": s.closing_balance,
            "lines": count,
        },
    ))
