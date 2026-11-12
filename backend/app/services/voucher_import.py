"""Excel voucher import: a dry run that checks every voucher, and a commit that saves chosen vouchers as DRAFTS.

The file is parsed by app/importers/voucher_excel.py (no database). Here each voucher gets its ledgers resolved
(case-insensitively; an unknown ledger is an error, the import never creates ledgers) and goes through the SAME
rules as the voucher screen (vouchers.validate_draft / create_draft). Import never approves or posts.

Services take a SQLAlchemy Connection and never commit (the caller owns the transaction).
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.db import repositories_bills as repo_b
from app.engine.duplicates import ExistingVoucher, find_possible_duplicate
from app.engine.models import Allocation, VoucherDraft, VoucherLine
from app.engine.money import MoneyError, format_inr, parse_amount
from app.importers.voucher_excel import ImportFileError, ParsedVoucher, parse_workbook
from app.services import vouchers
from app.services.errors import ServiceError, require_actor

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ImportIssue:
    rule_id: str | None  # V-xx for rule errors; None for file-format problems
    message: str
    line_no: int | None  # 1-based line of the voucher, None for voucher-level problems
    row: int  # Excel row to look at


@dataclass(frozen=True)
class AllocationInfo:
    """One bill allocation of a voucher line, as it will be saved. auto = built by the importer (New Ref for the
    full line, bill_ref = the voucher's reference_no), not given in the sheet."""

    line_no: int
    row: int
    kind: str
    bill_ref: str | None
    amount: str  # plain amount, e.g. "5000.50"; the text as entered when it is not a readable amount
    due_date: date | None
    auto: bool


@dataclass(frozen=True)
class VoucherCheck:
    ref_id: str
    first_row: int
    status: str  # "ok" | "error"
    errors: list[ImportIssue]
    allocations: list[AllocationInfo] = field(default_factory=list)


@dataclass(frozen=True)
class DryRunResult:
    vouchers: list[VoucherCheck]
    ok_count: int
    error_count: int


@dataclass(frozen=True)
class CreatedVoucher:
    ref_id: str
    voucher_id: object
    allocations: list[AllocationInfo] = field(default_factory=list)


@dataclass(frozen=True)
class SkippedVoucher:
    ref_id: str
    reason: str


@dataclass(frozen=True)
class CommitResult:
    created: list[CreatedVoucher]
    skipped: list[SkippedVoucher]


@dataclass
class _Prepared:
    parsed: ParsedVoucher
    draft: VoucherDraft | None = None
    issues: list[ImportIssue] = field(default_factory=list)
    allocations: list[AllocationInfo] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


# ================================================================================================== helpers


def _total_debit(draft: VoucherDraft) -> Decimal:
    total = ZERO
    for line in draft.lines:
        if line.debit is not None and not (isinstance(line.debit, str) and not line.debit.strip()):
            total += parse_amount(line.debit)
    return total


def _ledger_ids(conn: Connection, client_id: object) -> dict[str, object]:
    rows = conn.execute(text("SELECT lower(name), id FROM ledgers WHERE client_id = :c"), {"c": client_id})
    return {name: ledger_id for name, ledger_id in rows}


AUTO_TYPES = ("sales", "purchase")  # only these get the automatic New Ref (owner decision)


def _shown(raw: object) -> str:
    try:
        return str(parse_amount(raw))
    except MoneyError:
        return "" if raw is None else str(raw)


def _line_amount(line) -> Decimal | None:
    """The amount of a line with exactly one readable positive side, else None (V-02/V-03 report the rest)."""
    try:
        sides = [parse_amount(x) if x not in (None, "") else ZERO for x in (line.debit, line.credit)]
    except MoneyError:
        return None
    return sides[0] or sides[1] if (sides[0] > 0) != (sides[1] > 0) else None


def _prepare(conn: Connection, client_id: object, data: bytes) -> list[_Prepared]:
    try:
        parsed = parse_workbook(data)
    except ImportFileError as problem:
        raise ServiceError("invalid_file", str(problem)) from problem
    try:
        client_id = uuid.UUID(str(client_id))  # ids from the URL are text; the engine compares them with UUIDs
    except ValueError:
        raise ServiceError("not_found", "Client not found.") from None
    if conn.execute(text("SELECT 1 FROM clients WHERE id = :c"), {"c": client_id}).first() is None:
        raise ServiceError("not_found", "Client not found.")
    ledger_ids = _ledger_ids(conn, client_id)
    bill_wise = {i for i, row in repo_b.list_party_rows(conn, client_id).items() if row.bill_wise}

    prepared: list[_Prepared] = []
    accepted: list[ExistingVoucher] = []  # vouchers of this file that passed, for in-file duplicate detection
    for voucher in parsed.vouchers:
        item = _Prepared(voucher)
        item.issues.extend(ImportIssue(None, e.message, None, e.row) for e in voucher.errors)

        line_ids: list[object] = []
        for number, line in enumerate(voucher.lines, start=1):
            found = ledger_ids.get(line.ledger_name.lower()) if line.ledger_name else None
            if found is None and line.ledger_name:
                item.issues.append(ImportIssue(
                    "V-05",
                    f"Line {number}: ledger '{line.ledger_name}' does not exist for this client; "
                    "the import never creates ledgers.",
                    number, line.row,
                ))
            line_ids.append(found)
        party_id = None
        if voucher.party_ledger:
            party_id = ledger_ids.get(voucher.party_ledger.lower())
            if party_id is None:
                item.issues.append(ImportIssue(
                    "V-05",
                    f"The party ledger '{voucher.party_ledger}' does not exist for this client; "
                    "the import never creates ledgers.",
                    None, voucher.first_row,
                ))

        if item.ok:
            built: list[VoucherLine] = []
            no_reference: set[int] = set()  # lines that would get an automatic New Ref but the voucher has no reference
            for number, (ledger_id, x) in enumerate(zip(line_ids, voucher.lines, strict=True), start=1):
                allocations = [Allocation(a.kind, a.amount, a.bill_ref, a.due_date) for a in x.allocations]
                infos = [AllocationInfo(number, a.row, a.kind, a.bill_ref, _shown(a.amount), a.due_date, False)
                         for a in x.allocations]
                amount = _line_amount(x)
                if not allocations and ledger_id in bill_wise and voucher.voucher_type in AUTO_TYPES and amount is not None:
                    if voucher.reference_no:
                        allocations = [Allocation("new_ref", amount, voucher.reference_no, None)]
                        infos = [AllocationInfo(number, x.row, "new_ref", voucher.reference_no, str(amount), None, True)]
                    else:
                        no_reference.add(number)
                item.allocations.extend(infos)
                built.append(VoucherLine(ledger_id, x.debit, x.credit, tuple(allocations)))
            draft = VoucherDraft(
                client_id, voucher.voucher_type, voucher.voucher_date, voucher.narration,
                voucher.reference_no or None, party_id, tuple(built),
            )
            item.draft = draft
            for error in vouchers.validate_draft(conn, draft):
                if error.rule_id == "B-01" and error.line_no in no_reference:
                    continue  # reported below (or by V-14 for a purchase) instead of "allocate the full amount"
                row = voucher.lines[error.line_no - 1].row if error.line_no else voucher.first_row
                item.issues.append(ImportIssue(error.rule_id, error.message, error.line_no, row))
            if voucher.voucher_type == "sales":
                for number in sorted(no_reference):
                    item.issues.append(ImportIssue(
                        "B-03",
                        f"Voucher {voucher.ref_id}, line {number}: '{voucher.lines[number - 1].ledger_name}' is a "
                        "bill-wise party, so a bill reference is required: fill reference_no (it becomes the New Ref) "
                        "or give the bill allocation columns.",
                        number, voucher.lines[number - 1].row,
                    ))
            if item.ok:
                match = find_possible_duplicate(draft, accepted)
                if match:
                    item.issues.append(ImportIssue(
                        "V-10",
                        f"This voucher repeats voucher {match.id} of the same file: same type, party, Reference No "
                        f"'{voucher.reference_no}' and amount {format_inr(match.total)}.",
                        None, voucher.first_row,
                    ))
                else:
                    accepted.append(ExistingVoucher(
                        voucher.ref_id, client_id, draft.voucher_type, draft.party_ledger_id, draft.reference_no,
                        _total_debit(draft), "draft", None, draft.voucher_date,
                    ))
        prepared.append(item)
    return prepared


# ===================================================================================================== API


def dry_run(conn: Connection, client_id: object, file_bytes: bytes) -> DryRunResult:
    """Check every voucher of the file with the voucher rules. Saves nothing."""
    prepared = _prepare(conn, client_id, file_bytes)
    checks = [
        VoucherCheck(p.parsed.ref_id, p.parsed.first_row, "ok" if p.ok else "error", p.issues, p.allocations)
        for p in prepared
    ]
    ok = sum(1 for c in checks if c.status == "ok")
    return DryRunResult(checks, ok, len(checks) - ok)


def commit(
    conn: Connection, client_id: object, file_bytes: bytes, ref_ids: list[str] | None, *, actor: str
) -> CommitResult:
    """Create DRAFT vouchers for the chosen ref_ids (None or empty = every voucher without errors). Everything
    is checked again; nothing is ever approved or posted."""
    actor = require_actor(actor)
    prepared = _prepare(conn, client_id, file_bytes)
    wanted = [r.strip() for r in (ref_ids or []) if r and r.strip()] or None
    present = {p.parsed.ref_id for p in prepared}

    created: list[CreatedVoucher] = []
    skipped: list[SkippedVoucher] = [SkippedVoucher(r, "not in the file") for r in (wanted or []) if r not in present]
    for item in prepared:
        ref = item.parsed.ref_id
        if wanted is not None and ref not in wanted:
            skipped.append(SkippedVoucher(ref, "not selected"))
        elif not item.ok:
            skipped.append(SkippedVoucher(ref, "has errors: " + "; ".join(i.message for i in item.issues)))
        else:
            result = vouchers.create_draft(conn, item.draft, actor=actor)
            if result.errors:
                skipped.append(SkippedVoucher(ref, "has errors: " + "; ".join(e.message for e in result.errors)))
            else:
                created.append(CreatedVoucher(ref, result.voucher_id, item.allocations))
    return CommitResult(created, skipped)
