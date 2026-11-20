"""Tax audit form data (Phase 8, package F): which form applies to a financial year and which clause data the books can give.

Pure Python: no DB, web or AI imports. Decimal only; the only arithmetic is exact addition of amounts the findings already carry.

* The form is chosen by the FINANCIAL YEAR END date against the effective dates of the seeded definitions (`audit_form_defs`): the law is data.
* A clause is derived ONLY when the seed lists it as `books` / `partly_books` AND this module knows which checks feed it AND every one of those
  checks ran in the run. Anything else is reported (`skipped`) and stays for manual entry: nothing is guessed, nothing is defaulted to zero
  for a check that did not run.
* Form 26 has no seeded clauses (its numbering was not read from the official form): every Form 26 clause is manual until the owner confirms
  a clause seed. The derivation map below is keyed by FORM 3CD clause numbers only.
* A derived entry is a count / total of findings: a figure for the accountant to check, never a conclusion about the tax audit.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class FormDef:
    form_key: str
    title: str
    law: str
    section_ref: str
    effective_from: date
    effective_to: date | None
    verification_status: str


@dataclass(frozen=True)
class ClauseDef:
    form_key: str
    clause_no: str
    title: str
    derivability: str            # books | partly_books | manual
    data_source: str | None
    verification_status: str


@dataclass(frozen=True)
class FindingRow:
    """What derivation needs of one stored finding."""

    id: str
    check_id: str
    amount: Decimal | None
    disallowance_amount: Decimal | None
    rule_status: str | None = None


@dataclass(frozen=True)
class DerivedEntry:
    clause_no: str
    field_key: str
    value: object                # str (count or 2-decimal amount, or a status) or list[str] (finding ids)


@dataclass(frozen=True)
class SkippedClause:
    clause_no: str
    reason: str


@dataclass(frozen=True)
class DeriveResult:
    entries: tuple[DerivedEntry, ...] = ()
    skipped: tuple[SkippedClause, ...] = ()


def select_form(defs: Sequence[FormDef], fy_end: date) -> FormDef | None:
    """The form in force on the financial year's last day (latest effective_from wins); None when no definition covers it."""
    live = [d for d in defs if d.effective_from <= fy_end and (d.effective_to is None or fy_end <= d.effective_to)]
    return max(live, key=lambda d: d.effective_from) if live else None


# Form 3CD clause -> (kind of figure, feeding checks, field prefix). An accounting mapping of existing checks to the clause, not law.
FORM_3CD_SOURCES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "21": ("cash_payments", ("A-05",), "cash_payment"),
    "22": ("count_amount", ("A-07",), "msme_interest_overdue"),
    "23": ("count_amount", ("A-18",), "related_party"),
    "26": ("count_amount", ("A-07",), "msme_unpaid"),
    "27": ("count_amount", ("A-08",), "gst_tieout_difference"),
    "31": ("count_amount", ("A-06",), "cash_receipts"),
    "34": ("count_amount", ("A-09", "A-10", "A-11"), "tds"),
}
_STATUS_ORDER = ("pending", "secondary_verified", "verified")   # weakest first


def _amount(value: Decimal | None) -> Decimal:
    return ZERO if value is None else value


def _text(value: Decimal) -> str:
    return f"{value:.2f}"


def _weakest(statuses: Iterable[str | None]) -> str | None:
    found = {s for s in statuses if s}
    for status in _STATUS_ORDER:
        if status in found:
            return status
    return None


def derive(clauses: Sequence[ClauseDef], findings: Sequence[FindingRow], run_check_ids: Iterable[str],
           failed_check_ids: Iterable[str] = (), only: Iterable[str] | None = None) -> DeriveResult:
    """Clause data of Form 3CD from the findings of one run. `run_check_ids` are the checks the run executed, `failed_check_ids` those of
    them that failed inside the run. `only` limits to the listed clause numbers. Every clause not derived is returned in `skipped` with why."""
    ran = set(run_check_ids) - set(failed_check_ids)
    wanted = None if only is None else set(only)
    entries: list[DerivedEntry] = []
    skipped: list[SkippedClause] = []
    for clause in clauses:
        if wanted is not None and clause.clause_no not in wanted:
            continue
        if clause.derivability == "manual":
            skipped.append(SkippedClause(clause.clause_no, "Entered by hand: this clause is not derivable from the books."))
            continue
        source = FORM_3CD_SOURCES.get(clause.clause_no) if clause.form_key == "form_3cd" else None
        if source is None:
            skipped.append(SkippedClause(clause.clause_no, "No derivation is defined for this clause here: enter it by hand "
                                                           "(its figures come from workings outside the audit checks)."))
            continue
        kind, check_ids, prefix = source
        missing = [c for c in check_ids if c not in ran]
        if missing:
            skipped.append(SkippedClause(clause.clause_no, f"The run did not complete check {', '.join(missing)}, so nothing is derived "
                                                           "(run the check, or enter the clause by hand)."))
            continue
        rows = [f for f in findings if f.check_id in check_ids]
        no = clause.clause_no
        if kind == "cash_payments":
            entries += [
                DerivedEntry(no, f"{prefix}_exception_count", str(len(rows))),
                DerivedEntry(no, f"{prefix}_total_amount", _text(sum((_amount(f.amount) for f in rows), ZERO))),
                DerivedEntry(no, f"{prefix}_disallowable_amount", _text(sum((_amount(f.disallowance_amount) for f in rows), ZERO))),
            ]
        else:
            entries += [
                DerivedEntry(no, f"{prefix}_count", str(len(rows))),
                DerivedEntry(no, f"{prefix}_amount", _text(sum((_amount(f.amount) for f in rows), ZERO))),
            ]
        status = _weakest(f.rule_status for f in rows)
        if status:
            entries.append(DerivedEntry(no, "legal_rule_status", status))
        entries.append(DerivedEntry(no, "source_finding_ids", sorted(f.id for f in rows)))
    return DeriveResult(tuple(entries), tuple(skipped))


def derivable_here(clause: ClauseDef) -> bool:
    """Whether `derive` can fill this clause (so the screen can say 'enter by hand' up front)."""
    return clause.derivability != "manual" and clause.form_key == "form_3cd" and clause.clause_no in FORM_3CD_SOURCES
