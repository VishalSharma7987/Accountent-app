"""Bank reconciliation matching (rules R-03, R-04). Pure Python: no database, web or AI.

Two kinds of items are matched:
  BankLine  one line of the bank statement. direction "deposit" = money in (statement credit),
            "payment" = money out (statement debit).
  BookItem  one voucher line on the bank ledger, or an opening item. Dr to the bank ledger = "deposit",
            Cr = "payment".
Items of opposite directions are never paired. Amounts are positive Decimals.

auto_match proposes matches by deterministic rules, in this order, each on what is still unmatched:
  1  exact amount, same direction, date within the window, and the bank line's reference / cheque no / UTR is
     found in the voucher's reference_no or narration (case-insensitive; a number must equal a whole digit run,
     leading zeros ignored; other references must be at least 4 letters/digits long);
     matched only when the pairing is unambiguous both ways.
  2  exact amount, same direction, date within the window, exactly ONE candidate on each side.
  3  one bank line against a UNIQUE subset of 2..6 book items (or one book item against a unique subset of bank
     lines) of the same direction, within the window, whose amounts add up exactly.
Anything with several equally good candidates is never matched; it comes back as a suggestion with a reason.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.models import ValidationError
from app.engine.money import format_inr

DEPOSIT = "deposit"
PAYMENT = "payment"
MAX_SUBSET = 6
MAX_POOL = 20  # candidates considered for a subset search; more than this is left to the accountant
MIN_NUMBER_DIGITS = 3
MIN_TEXT_REFERENCE = 4


@dataclass(frozen=True)
class BankLine:
    id: object
    date: date
    amount: Decimal  # positive
    direction: str  # deposit | payment
    reference: str | None = None
    description: str = ""


@dataclass(frozen=True)
class BookItem:
    id: object
    date: date
    amount: Decimal  # positive
    direction: str  # deposit (Dr) | payment (Cr)
    reference_no: str | None = None
    narration: str = ""
    kind: str = "voucher_line"  # voucher_line | opening_item
    voucher_number: str | None = None


@dataclass(frozen=True)
class MatchGroup:
    bank_ids: tuple
    book_ids: tuple
    rule: int  # 1, 2 or 3


@dataclass(frozen=True)
class Suggestion:
    bank_line_ids: tuple
    book_item_ids: tuple
    reason: str


@dataclass(frozen=True)
class AutoMatchResult:
    groups: list[MatchGroup]
    suggestions: list[Suggestion]


# ======================================================================================== reference matching


def _alnum(value: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (value or "").lower())


def reference_in(reference: str | None, *texts: str | None) -> bool:
    """True when the bank reference is contained in one of the texts (see the module docstring)."""
    key = _alnum(reference)
    if not key:
        return False
    if key.isdigit():
        number = key.lstrip("0")
        if len(number) < MIN_NUMBER_DIGITS:
            return False
        return any(run.lstrip("0") == number for t in texts for run in re.findall(r"\d+", t or ""))
    if len(key) < MIN_TEXT_REFERENCE:
        return False
    return any(key in _alnum(t) for t in texts)


# =========================================================================================== candidate graph


def _order(items: Iterable) -> list:
    return sorted(items, key=lambda x: (x.date, str(x.id)))


def _near(a: date, b: date, window: int) -> bool:
    return abs((a - b).days) <= window


def _same_kind(b: BankLine, k: BookItem, window: int) -> bool:
    return b.direction == k.direction and b.amount == k.amount and _near(b.date, k.date, window)


def _pair_unique(
    banks: list[BankLine], books: list[BookItem], candidate
) -> list[tuple[BankLine, BookItem]]:
    """Pairs where the bank line has exactly one candidate and that item has exactly one bank candidate."""
    by_bank = {b.id: [k for k in books if candidate(b, k)] for b in banks}
    by_book: dict[object, int] = {}
    for found in by_bank.values():
        for k in found:
            by_book[k.id] = by_book.get(k.id, 0) + 1
    return [(b, by_bank[b.id][0]) for b in banks if len(by_bank[b.id]) == 1 and by_book[by_bank[b.id][0].id] == 1]


def _subsets(target: Decimal, pool: list, limit: int = 2) -> list[tuple]:
    """Up to `limit` subsets of 2..MAX_SUBSET pool items (pool sorted by amount, descending) adding up to target."""
    found: list[tuple] = []

    def walk(start: int, chosen: list, total: Decimal) -> None:
        if len(found) >= limit:
            return
        if total == target and len(chosen) >= 2:
            found.append(tuple(chosen))
            return
        if len(chosen) == MAX_SUBSET:
            return
        for n in range(start, len(pool)):
            amount = pool[n].amount
            if total + amount > target:
                continue
            walk(n + 1, [*chosen, pool[n]], total + amount)

    walk(0, [], Decimal("0.00"))
    return found


def _components(banks: list[BankLine], books: list[BookItem], window: int) -> list[tuple[list, list]]:
    """Clusters of unmatched items linked by 'same direction, same amount, within the window'."""
    parent: dict[tuple, tuple] = {}

    def find(x: tuple) -> tuple:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for b in banks:
        for k in books:
            if _same_kind(b, k, window):
                parent[find(("bank", b.id))] = find(("book", k.id))
    bank_by_id = {b.id: b for b in banks}
    book_by_id = {k.id: k for k in books}
    clusters: dict[tuple, tuple[list, list]] = {}
    for side, ident in list(parent):
        root = find((side, ident))
        entry = clusters.setdefault(root, ([], []))
        (entry[0] if side == "bank" else entry[1]).append(bank_by_id[ident] if side == "bank" else book_by_id[ident])
    return [(_order(x), _order(y)) for x, y in clusters.values()]


# ===================================================================================================== auto_match


def auto_match(
    bank_lines: Sequence[BankLine], book_items: Sequence[BookItem], date_window_days: int = 7
) -> AutoMatchResult:
    banks = _order(bank_lines)
    books = _order(book_items)
    window = date_window_days
    groups: list[MatchGroup] = []
    held_back: list[Suggestion] = []  # rule-3 ambiguities, kept only while their items stay unmatched

    def take(bank_ids: Iterable, book_ids: Iterable, rule: int) -> None:
        nonlocal banks, books
        b_ids, k_ids = tuple(bank_ids), tuple(book_ids)
        groups.append(MatchGroup(b_ids, k_ids, rule))
        banks = [b for b in banks if b.id not in b_ids]
        books = [k for k in books if k.id not in k_ids]

    # rule 1: reference found in the voucher
    def with_reference(b: BankLine, k: BookItem) -> bool:
        return _same_kind(b, k, window) and reference_in(b.reference, k.reference_no, k.narration)

    for b, k in _pair_unique([x for x in banks if x.reference], books, with_reference):
        take([b.id], [k.id], 1)

    # rule 2: one candidate on each side
    for b, k in _pair_unique(banks, books, lambda b, k: _same_kind(b, k, window)):
        take([b.id], [k.id], 2)

    # rule 3a: one bank line = unique subset of book items;  3b: one book item = unique subset of bank lines
    _subset_rule(banks, books, window, take, held_back, bank_side=True)
    _subset_rule(banks, books, window, take, held_back, bank_side=False)

    suggestions = []
    for bs, ks in _components(banks, books, window):
        if bs and ks:
            suggestions.append(Suggestion(
                tuple(x.id for x in bs), tuple(x.id for x in ks),
                f"{len(bs)} bank line(s) and {len(ks)} voucher line(s) have the same amount, direction and date "
                "range, so the tool cannot tell which belong together. Match them by hand.",
            ))
    open_banks = {b.id for b in banks}
    open_books = {k.id for k in books}
    for s in held_back:
        if set(s.bank_line_ids) <= open_banks and set(s.book_item_ids) <= open_books:
            suggestions.append(s)
    return AutoMatchResult(groups, suggestions)


def _subset_rule(banks, books, window, take, held_back, *, bank_side: bool) -> None:
    """Rule 3. bank_side=True: each bank line against subsets of book items; False: each book item against bank lines.

    Proposals that share an item with another proposal are dropped (they compete); a target with several possible
    subsets is dropped too. Both come back as suggestions."""
    current_banks = list(banks)
    current_books = list(books)
    targets = current_banks if bank_side else current_books
    others = current_books if bank_side else current_banks
    proposals: list[tuple[object, tuple]] = []
    for target in targets:
        pool = [
            o for o in others
            if o.direction == target.direction and o.amount < target.amount and _near(o.date, target.date, window)
        ]
        if len(pool) < 2:
            continue
        if len(pool) > MAX_POOL:
            _hold(held_back, target, pool, bank_side,
                  f"{len(pool)} items are close in date; too many to combine automatically. Match them by hand.")
            continue
        pool.sort(key=lambda x: (-x.amount, str(x.id)))
        found = _subsets(target.amount, pool)
        if len(found) == 1:
            proposals.append((target, found[0]))
        elif len(found) > 1:
            union = {x.id: x for s in found for x in s}
            _hold(held_back, target, list(union.values()), bank_side,
                  "More than one combination of items adds up to this amount, so the tool cannot choose. "
                  "Match them by hand.")
    use_count: dict[object, int] = {}
    for _, subset in proposals:
        for x in subset:
            use_count[x.id] = use_count.get(x.id, 0) + 1
    for target, subset in proposals:
        if any(use_count[x.id] > 1 for x in subset):
            _hold(held_back, target, list(subset), bank_side,
                  "Another line competes for the same items, so the tool cannot choose. Match them by hand.")
            continue
        ids = [x.id for x in subset]
        take([target.id] if bank_side else ids, ids if bank_side else [target.id], 3)


def _hold(held_back: list[Suggestion], target, pool: list, bank_side: bool, reason: str) -> None:
    ids = tuple(x.id for x in _order(pool))
    held_back.append(Suggestion((target.id,), ids, reason) if bank_side else Suggestion(ids, (target.id,), reason))


# ================================================================================================ validate_match


def signed_total(items: Iterable[BankLine | BookItem]) -> Decimal:
    """Deposits positive, payments negative."""
    return sum((x.amount if x.direction == DEPOSIT else -x.amount for x in items), Decimal("0.00"))


def _net(value: Decimal) -> str:
    if value == 0:
        return "nil"
    return f"{format_inr(abs(value))} {'deposit' if value > 0 else 'payment'}"


def validate_match(bank_items: Sequence[BankLine], book_items: Sequence[BookItem]) -> list[ValidationError]:
    """R-03 (a match needs items, each at most once) and R-04 (book total = bank total, exactly)."""
    errors: list[ValidationError] = []
    if not bank_items and not book_items:
        return [ValidationError("R-03", "Choose at least one bank line or voucher line to match.")]
    for label, items in (("bank line", bank_items), ("voucher line", book_items)):
        ids = [x.id for x in items]
        if len(set(ids)) != len(ids):
            errors.append(ValidationError("R-03", f"The same {label} is selected more than once."))
    if errors:
        return errors
    books, bank = signed_total(book_items), signed_total(bank_items)
    if books != bank:
        errors.append(ValidationError(
            "R-04",
            f"The match does not tie: books {_net(books)} and bank {_net(bank)} are not equal "
            f"(difference {format_inr(abs(books - bank))}).",
        ))
    return errors
