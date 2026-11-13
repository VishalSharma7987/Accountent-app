"""Books <-> GSTR-2B reconciliation (G-42..G-44). Pure Python: no DB, web or AI imports.

Deterministic and conservative: a pair is made only when the keys are exactly equal after the documented normalisation;
two candidates for one key are reported as `ambiguous` and never resolved by guessing. Tolerance is configuration, not law.
Document types use the 2B vocabulary on both sides (a Debit Note voucher of the books is the supplier's credit note).
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")
HEADS = ("taxable_value", "igst", "cgst", "sgst", "cess")
CLASSES = ("matched", "value_mismatch", "gstin_mismatch", "period_mismatch", "only_in_books", "only_in_2b", "ambiguous")
_STRIP = re.compile(r"[\s/\-.\\]")


@dataclass(frozen=True)
class BookDoc:
    voucher_id: object
    voucher_number: str | None
    supplier_gstin: str | None
    doc_no: str
    doc_date: date
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    doc_type: str = "invoice"
    itc_status: str | None = None


@dataclass(frozen=True)
class Doc2B:
    document_id: object
    supplier_gstin: str | None
    doc_no: str
    doc_date: date
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    doc_type: str = "invoice"
    itc_available: str = "yes"
    ims_status: str = "none"


@dataclass(frozen=True)
class Link:
    link_id: object
    document_id: object
    voucher_id: object
    link_kind: str  # manual | accepted_difference
    note: str


@dataclass(frozen=True)
class Difference:
    field: str
    books: Decimal
    doc_2b: Decimal
    difference: Decimal  # doc_2b - books


@dataclass(frozen=True)
class ReconRow:
    cls: str
    book: BookDoc | None
    doc: Doc2B | None
    differences: tuple[Difference, ...] = ()
    note: str = ""
    link_id: object = None
    candidates: tuple[object, ...] = ()


@dataclass(frozen=True)
class ReconResult:
    rows: tuple[ReconRow, ...]
    summary: dict[str, int]
    totals: dict[str, dict[str, Decimal]]


@dataclass(frozen=True)
class ItcEffect:
    voucher_id: object
    supplier_tax_paid: str  # in_2b | not_in_2b
    pending_reason: str | None  # not_in_2b | ims_pending | ims_rejected | None
    note: str


def normalise_doc_no(value: str) -> str:
    """Upper-case, remove spaces and the characters / - . and backslash, then leading zeros ("000" becomes "0")."""
    cleaned = _STRIP.sub("", value).upper()
    stripped = cleaned.lstrip("0")
    return stripped if stripped else ("0" if cleaned else "")


def _key(gstin: str | None, doc_no: str, doc_date: date, doc_type: str) -> tuple:
    return (gstin, normalise_doc_no(doc_no), doc_date, doc_type)


def _differences(book: BookDoc, doc: Doc2B, tolerance: Decimal) -> tuple[Difference, ...]:
    found = []
    for head in HEADS:
        b, d = getattr(book, head), getattr(doc, head)
        if abs(d - b) > tolerance:
            found.append(Difference(head, b, d, d - b))
    return tuple(found)


def _risk_note(doc: Doc2B) -> str:
    parts = []
    if doc.itc_available == "no":
        parts.append("ITC is shown as not available in the 2B")
    elif doc.itc_available == "temporary":
        parts.append("ITC is shown as temporarily not available in the 2B")
    if doc.ims_status == "rejected":
        parts.append("IMS action: rejected (risk: credit may be lost)")
    elif doc.ims_status == "pending":
        parts.append("IMS action: pending")
    return "; ".join(parts)


def _pair(book: BookDoc, doc: Doc2B, tolerance: Decimal, link: Link | None) -> ReconRow:
    diffs = _differences(book, doc, tolerance)
    note = _risk_note(doc)
    if link is not None and link.link_kind == "accepted_difference":
        extra = "Difference accepted by the accountant: " + link.note
        return ReconRow("matched", book, doc, diffs, "; ".join(p for p in (extra, note) if p), link.link_id)
    cls = "value_mismatch" if diffs else "matched"
    if link is not None:
        note = "; ".join(p for p in ("Linked manually: " + link.note, note) if p)
    return ReconRow(cls, book, doc, diffs, note, None if link is None else link.link_id)


def _sign(doc_type: str) -> int:
    return -1 if doc_type == "credit_note" else 1


def _totals(rows: list[ReconRow]) -> dict[str, dict[str, Decimal]]:
    books = {h: ZERO for h in HEADS}
    docs = {h: ZERO for h in HEADS}
    for row in rows:
        row_doc = None if row.cls == "period_mismatch" else row.doc  # that document is in another period's 2B
        for target, item in ((books, row.book), (docs, row_doc)):
            if item is not None:
                for h in HEADS:
                    target[h] += _sign(item.doc_type) * getattr(item, h)
    return {"books": books, "doc_2b": docs, "difference": {h: docs[h] - books[h] for h in HEADS}}


def reconcile(
    books: list[BookDoc], docs: list[Doc2B], other_docs: list[Doc2B] | tuple = (), links: list[Link] | tuple = (),
    tolerance: Decimal = ZERO,
) -> ReconResult:
    rows: list[ReconRow] = []
    free_books = {b.voucher_id: b for b in books}
    free_docs = {d.document_id: d for d in docs}

    # 1. decisions the accountant stored (one to one)
    for link in links:
        book, doc = free_books.get(link.voucher_id), free_docs.get(link.document_id)
        if book is not None and doc is not None:
            rows.append(_pair(book, doc, tolerance, link))
            del free_books[link.voucher_id], free_docs[link.document_id]

    # 2. exact key (supplier GSTIN, normalised number, date, document type)
    by_book, by_doc = defaultdict(list), defaultdict(list)
    for b in free_books.values():
        by_book[_key(b.supplier_gstin, b.doc_no, b.doc_date, b.doc_type)].append(b)
    for d in free_docs.values():
        by_doc[_key(d.supplier_gstin, d.doc_no, d.doc_date, d.doc_type)].append(d)
    for key in sorted(set(by_book) & set(by_doc), key=str):
        bs, ds = by_book[key], by_doc[key]
        if len(bs) == 1 and len(ds) == 1:
            rows.append(_pair(bs[0], ds[0], tolerance, None))
        else:
            names = [f"voucher {b.voucher_id}" for b in bs] + [f"2B document {d.document_id}" for d in ds]
            rows.append(ReconRow("ambiguous", bs[0], ds[0], (), "More than one candidate, not resolved: " + ", ".join(names),
                                 None, tuple(b.voucher_id for b in bs) + tuple(d.document_id for d in ds)))
        for b in bs:
            del free_books[b.voucher_id]
        for d in ds:
            del free_docs[d.document_id]

    # 3. supplier GSTIN differs, everything else equal (number, date, type, taxable value)
    loose_b, loose_d = defaultdict(list), defaultdict(list)
    for b in free_books.values():
        loose_b[(normalise_doc_no(b.doc_no), b.doc_date, b.doc_type, b.taxable_value)].append(b)
    for d in free_docs.values():
        loose_d[(normalise_doc_no(d.doc_no), d.doc_date, d.doc_type, d.taxable_value)].append(d)
    for key in sorted(set(loose_b) & set(loose_d), key=str):
        bs, ds = loose_b[key], loose_d[key]
        if len(bs) == 1 and len(ds) == 1:
            b, d = bs[0], ds[0]
            note = f"Supplier GSTIN in books {b.supplier_gstin} differs from 2B {d.supplier_gstin}"
            rows.append(ReconRow("gstin_mismatch", b, d, _differences(b, d, tolerance), note))
            del free_books[b.voucher_id], free_docs[d.document_id]

    # 4. what is left: the document may sit in another period's 2B, else only on one side
    others = defaultdict(list)
    for d in other_docs:
        others[_key(d.supplier_gstin, d.doc_no, d.doc_date, d.doc_type)].append(d)
    for b in list(free_books.values()):
        found = others.get(_key(b.supplier_gstin, b.doc_no, b.doc_date, b.doc_type), [])
        if len(found) == 1:
            rows.append(ReconRow("period_mismatch", b, found[0], _differences(b, found[0], tolerance),
                                 "The document is in the GSTR-2B of another period"))
        else:
            rows.append(ReconRow("only_in_books", b, None, (), "Not found in the GSTR-2B"))
        del free_books[b.voucher_id]
    for d in free_docs.values():
        rows.append(ReconRow("only_in_2b", None, d, (), "Not found in the books"))

    order = {c: i for i, c in enumerate(CLASSES)}

    def sort_key(r: ReconRow):
        item = r.book or r.doc
        return (order[r.cls], normalise_doc_no(item.doc_no), str(item.supplier_gstin),
                str(r.book.voucher_id if r.book else r.doc.document_id))

    rows.sort(key=sort_key)
    summary = {c: 0 for c in CLASSES}
    for r in rows:
        summary[r.cls] += 1
    return ReconResult(tuple(rows), summary, _totals(rows))


def apply_effects(result: ReconResult) -> list[ItcEffect]:
    """What the reconciliation says about each book voucher's ITC evidence. Never `eligible`: that needs G-31 evidence.

    matched -> supplier tax paid `in_2b` (IMS rejected / pending keep the line pending); only in books -> pending `not_in_2b`.
    Value mismatch, GSTIN mismatch, period mismatch and ambiguous rows change nothing: the accountant decides first.
    """
    effects = []
    for row in result.rows:
        if row.cls == "only_in_books":
            effects.append(ItcEffect(row.book.voucher_id, "not_in_2b", "not_in_2b", "Not found in the GSTR-2B"))
        elif row.cls == "matched" and row.book is not None and row.doc is not None:
            reason = {"rejected": "ims_rejected", "pending": "ims_pending"}.get(row.doc.ims_status)
            effects.append(ItcEffect(row.book.voucher_id, "in_2b", reason, row.note))
    return effects
