"""Tie-out: Books vs GSTR-1 working vs GSTR-3B working vs filed figures (Phase 3, package E, G-53). Pure Python.

Differences are shown, never forced. The causes (unposted drafts, manual journals on tax ledgers, documents of another
period, pending credit, rounding) are collected by the service and listed next to the figures.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.engine.gstr1 import ZERO

HEADS = ("taxable_value", "igst", "cgst", "sgst", "cess")
TAX_HEADS = ("igst", "cgst", "sgst", "cess")
CAUSE_KINDS = ("draft_voucher", "manual_journal_on_tax_ledger", "other_period_document", "pending_itc", "rounding")


@dataclass(frozen=True)
class Cause:
    kind: str
    reference: str
    amount: Decimal
    head: str | None = None


@dataclass
class TieOut:
    rows: list[dict]
    itc: dict
    causes: list[Cause]
    ties: bool
    warnings: list[str] = field(default_factory=list)


def _diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def filed_gstr1_totals(data: dict | None) -> dict[str, Decimal] | None:
    """Filed GSTR-1 figures per head from the accountant's entry (`data.totals`), or None when none were entered."""
    totals = (data or {}).get("totals")
    if not totals:
        return None
    return {h: Decimal(str(totals[h])) if totals.get(h) not in (None, "") else None for h in HEADS}


def filed_gstr3b_totals(data: dict | None) -> dict[str, Decimal] | None:
    """Filed GSTR-3B outward figures per head: the sum of 3.1 (a), (b), (c) and (e) that the accountant entered."""
    t31 = ((data or {}).get("t3_1")) or None
    if not t31:
        return None
    out: dict[str, Decimal | None] = {}
    for h in HEADS:
        vals = [Decimal(str(t31[k][h])) for k in ("a_outward_taxable", "b_zero_rated", "c_nil_exempt", "e_non_gst")
                if t31.get(k) and t31[k].get(h) not in (None, "")]
        out[h] = sum(vals, ZERO) if vals else None
    return out


def build_tieout(
    books_output: dict[str, Decimal],
    gstr1_totals: dict[str, Decimal],
    gstr3b_outward: dict[str, Decimal],
    filed_gstr1: dict[str, Decimal | None] | None,
    filed_gstr3b: dict[str, Decimal | None] | None,
    books_input: dict[str, Decimal],
    itc_register_eligible: dict[str, Decimal],
    gstr3b_4a: dict[str, Decimal],
    itc_pending: dict[str, Decimal],
    causes: list[Cause],
) -> TieOut:
    rows = []
    ties = True
    for h in HEADS:
        b, g1, g3 = books_output[h], gstr1_totals[h], gstr3b_outward[h]
        f1 = None if filed_gstr1 is None else filed_gstr1.get(h)
        f3 = None if filed_gstr3b is None else filed_gstr3b.get(h)
        row = {
            "head": h, "books_output": b, "gstr1_working": g1, "gstr3b_working": g3,
            "filed_gstr1": f1, "filed_gstr3b": f3,
            "d_books_gstr1": b - g1, "d_gstr1_gstr3b": g1 - g3,
            "d_books_filed": _diff(b, f1),
            "d_filed_gstr1_gstr3b": _diff(f1, f3),
        }
        for k in ("d_books_gstr1", "d_gstr1_gstr3b", "d_books_filed", "d_filed_gstr1_gstr3b"):
            if row[k]:
                ties = False
        rows.append(row)

    itc = {}
    for h in TAX_HEADS:
        d_reg = itc_register_eligible[h] - gstr3b_4a[h]
        d_books = books_input[h] - itc_register_eligible[h] - itc_pending[h]
        itc[h] = {
            "books_input": books_input[h], "itc_register_eligible": itc_register_eligible[h],
            "gstr3b_4a": gstr3b_4a[h], "itc_register_pending": itc_pending[h],
            "d_register_gstr3b": d_reg, "d_books_register_pending": d_books,
        }
        if d_reg or d_books:
            ties = False
    ordered = sorted(causes, key=lambda c: (CAUSE_KINDS.index(c.kind), c.reference))
    return TieOut(rows=rows, itc=itc, causes=ordered, ties=ties)
