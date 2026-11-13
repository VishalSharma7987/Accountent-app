"""26AS / AIS <-> books reconciliation (T-42, T-43). Pure Python: no DB, web or AI imports.

Deterministic and conservative: a pair is made only when the keys are exactly equal; an unmapped or ambiguous section, or a
PAN the books do not know, is REPORTED and never guessed; nothing is written. Tolerance is configuration, not law.

Side "deductor" (the statement lists tax our client deducted; books = posted deduction items):
  key = deductee PAN + nature, where the printed section is mapped to a nature through the section table (old OR new code,
  whichever the file prints; the code identifies the nature, so the date window of the table row is not used). A printed
  section that maps to no nature is `unmapped`; one that maps to several natures (e.g. 393(1)) is `ambiguous`: both are
  reported, never matched, and can be linked by hand.
Side "deductee" (the statement lists tax deducted from our client; books = posted vouchers that debited a TDS receivable
  ledger): the books hold neither the deductor's TAN nor the section, so the key is only the transaction month and the amount.
  Pairing is one to one, closest amount first, then nearest date, then smallest id (stable); `section_mapping_status` is
  `not_applicable`.

Classes (compared on tax deducted of the statement vs the tax of the books):
  matched          same key, same month, amount within tolerance
  amount_mismatch  same key, same month, amount differs by more than the tolerance
  date_mismatch    same key, amount within tolerance, different month
  only_in_books    nothing in the statement for this book entry
  only_in_26as     nothing in the books for this statement row (`reason` says why when it is a mapping / PAN problem)
A link made by hand (manual / accepted_difference) fixes the pair whatever the figures; the difference is still reported.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")
CLASSES = ("matched", "amount_mismatch", "only_in_books", "only_in_26as", "date_mismatch")
SIDES = ("deductee", "deductor")


@dataclass(frozen=True)
class Row26:
    row_id: object
    row_no: int
    deductor_tan: str | None
    deductor_name: str | None
    deductee_pan: str | None
    section_ref: str | None
    transaction_date: date | None
    amount_paid: Decimal
    tax_deducted: Decimal
    tax_deposited: Decimal


@dataclass(frozen=True)
class BookEntry:
    book_id: object  # item id (deductor side) or voucher id (deductee side)
    pan: str | None  # deductee PAN from the deductee master (deductor side)
    nature_key: str | None
    deductee_name: str | None
    section_ref: str | None  # as stored on the item (snapshot)
    event_date: date
    payment_amount: Decimal
    tds_amount: Decimal
    voucher_id: object | None = None
    voucher_number: str | None = None


@dataclass(frozen=True)
class SectionMap:
    """One row of the section table: a printed section string (either Act) and the nature it stands for."""

    nature_key: str
    section_ref: str


@dataclass(frozen=True)
class RecLink:
    link_id: object
    row_id: object
    book_id: object
    link_kind: str  # manual | accepted_difference
    note: str


@dataclass(frozen=True)
class ReconRow:
    cls: str
    row: Row26 | None
    book: BookEntry | None
    difference: Decimal | None  # tax deducted in the statement minus tax in the books
    paid_difference: Decimal | None  # amount paid in the statement minus payment amount in the books
    section_mapping_status: str  # mapped | unmapped | ambiguous | not_applicable
    reason: str | None = None
    link_id: object | None = None
    link_kind: str | None = None
    link_stale: bool = False


@dataclass
class ReconResult:
    rows: list[ReconRow] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def normalise_section(text: str | None) -> str:
    """'Section 194C', '194-C', '194J(a)', '194JA' -> '194C', '194C', '194JA', '194JA'. Letters upper-case; spaces, hyphens,
    brackets and the word SECTION dropped, so a statement that prints 194JA finds the table row 194J(a)."""
    value = re.sub(r"(?i)^\s*section\s*", "", text or "")
    return re.sub(r"[\s\-()]", "", value).upper()


def map_section(printed: str | None, sections: list[SectionMap]) -> tuple[str, str | None]:
    """-> (status, nature_key): mapped / unmapped / ambiguous; never a guess."""
    wanted = normalise_section(printed)
    natures = sorted({s.nature_key for s in sections if normalise_section(s.section_ref) == wanted}) if wanted else []
    if not natures:
        return "unmapped", None
    if len(natures) > 1:
        return "ambiguous", None
    return "mapped", natures[0]


def _month(d: date | None) -> tuple[int, int] | None:
    return (d.year, d.month) if d else None


def reconcile(side: str, rows: list[Row26], books: list[BookEntry], sections: list[SectionMap], known_pans: set[str],
              links: list[RecLink], tolerance: Decimal) -> ReconResult:
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}")
    out: list[ReconRow] = []

    def paid_gap(r: Row26, b: BookEntry) -> Decimal | None:  # the deductee-side books carry no payment amount
        return r.amount_paid - b.payment_amount if side == "deductor" else None

    by_book = {b.book_id: b for b in books}
    used_rows: set = set()
    used_books: set = set()

    # ---- hand-made links first: they fix the pair whatever the figures
    for link in links:
        row = next((r for r in rows if r.row_id == link.row_id), None)
        book = by_book.get(link.book_id)
        if row is None:
            continue
        if book is None:  # the book entry is gone (voucher reversed); the row is treated as unlinked and flagged
            continue
        used_rows.add(row.row_id)
        used_books.add(book.book_id)
        status, _ = map_section(row.section_ref, sections) if side == "deductor" else ("not_applicable", None)
        out.append(ReconRow(
            "matched", row, book, row.tax_deducted - book.tds_amount, paid_gap(row, book), status,
            link_id=link.link_id, link_kind=link.link_kind,
        ))
    stale = {link.row_id for link in links if link.book_id not in by_book}

    # ---- classify the remaining statement rows
    keyed: dict[object, tuple] = {}
    rest_rows: list[tuple[Row26, str, str | None]] = []  # row, mapping status, reason for being unmatchable
    for row in rows:
        if row.row_id in used_rows:
            continue
        if side == "deductor":
            status, nature = map_section(row.section_ref, sections)
            if status != "mapped":
                reason = "unmapped_section" if status == "unmapped" else "ambiguous_section"
                rest_rows.append((row, status, reason))
            elif not row.deductee_pan or row.deductee_pan not in known_pans:
                rest_rows.append((row, status, "unknown_pan"))
            else:
                keyed[row.row_id] = (row.deductee_pan, nature)
                rest_rows.append((row, status, None))
        else:
            keyed[row.row_id] = None
            rest_rows.append((row, "not_applicable", None))

    def book_key(b: BookEntry):
        if side == "deductor":
            return (b.pan, b.nature_key) if b.pan and b.nature_key else ("no-key", b.book_id)
        return None

    free = [b for b in books if b.book_id not in used_books]
    candidates = [(row, status) for row, status, reason in rest_rows if reason is None]
    paired: dict[object, tuple[str, BookEntry]] = {}

    def pair(predicate, cls: str) -> None:
        """One to one, closest amount first, then nearest date, then smallest id; deterministic."""
        options = []
        for row, _ in candidates:
            if row.row_id in paired:
                continue
            for b in free:
                if b.book_id in used_books or book_key(b) != keyed[row.row_id] or not predicate(row, b):
                    continue
                gap = (row.transaction_date - b.event_date).days if row.transaction_date else 0
                options.append((abs(row.tax_deducted - b.tds_amount), abs(gap), str(b.book_id), row.row_no, row, b))
        for _, _, _, _, row, b in sorted(options, key=lambda o: o[:4]):
            if row.row_id in paired or b.book_id in used_books:
                continue
            paired[row.row_id] = (cls, b)
            used_books.add(b.book_id)

    def within(row: Row26, b: BookEntry) -> bool:
        return abs(row.tax_deducted - b.tds_amount) <= tolerance

    def same_month(row: Row26, b: BookEntry) -> bool:
        return _month(row.transaction_date) == _month(b.event_date)

    pair(lambda r, b: same_month(r, b) and within(r, b), "matched")
    pair(lambda r, b: same_month(r, b), "amount_mismatch")
    pair(lambda r, b: within(r, b), "date_mismatch")

    for row, status, reason in rest_rows:
        if row.row_id in paired:
            cls, b = paired[row.row_id]
            out.append(ReconRow(cls, row, b, row.tax_deducted - b.tds_amount, paid_gap(row, b), status))
        else:
            out.append(ReconRow("only_in_26as", row, None, None, None, status, reason=reason or "not_in_books",
                                link_stale=row.row_id in stale))
    for b in books:
        if b.book_id not in used_books:
            reason = "pan_missing" if side == "deductor" and not b.pan else ("no_nature" if side == "deductor" and not b.nature_key else None)
            out.append(ReconRow("only_in_books", None, b, None, None, "not_applicable", reason=reason or "not_in_statement"))

    order = {c: i for i, c in enumerate(CLASSES)}
    out.sort(key=lambda r: (order[r.cls], r.row.row_no if r.row else 10**9, str(r.book.book_id) if r.book else ""))
    summary = {c: 0 for c in CLASSES}
    for r in out:
        summary[r.cls] += 1
    return ReconResult(out, summary)

