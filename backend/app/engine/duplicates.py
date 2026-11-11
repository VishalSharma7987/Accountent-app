"""V-10: possible duplicate voucher = same client + type + party ledger + reference no + total.

Decisions (docs/DECISIONS.md): applies only when a reference no exists; the reference is compared trimmed and
ignoring case; reversed vouchers, reversal vouchers and the voucher being edited are ignored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engine.models import ValidationError, VoucherDraft
from app.engine.money import MoneyError, format_inr, parse_amount

TYPE_LABELS = {
    "contra": "Contra", "payment": "Payment", "receipt": "Receipt", "sales": "Sales", "purchase": "Purchase",
    "credit_note": "Credit Note", "debit_note": "Debit Note", "journal": "Journal",
}


@dataclass(frozen=True)
class ExistingVoucher:
    id: object
    client_id: object
    voucher_type: str
    party_ledger_id: object | None
    reference_no: str | None
    total: Decimal  # total debit of the voucher
    status: str  # draft | approved | posted | reversed
    voucher_number: str | None
    voucher_date: date
    reverses_voucher_id: object | None = None  # set on a reversal voucher


def _reference_key(reference_no: str | None) -> str:
    return (reference_no or "").strip().casefold()


def _draft_total(draft: VoucherDraft) -> Decimal | None:
    """Total debit of the draft, or None when an amount cannot be read (then it cannot be compared)."""
    total = Decimal("0.00")
    for line in draft.lines:
        raw = line.debit
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            continue
        try:
            total += parse_amount(raw)
        except MoneyError:
            return None
    return total


def find_possible_duplicate(
    draft: VoucherDraft,
    existing_vouchers: Sequence[ExistingVoucher],
    *,
    draft_id: object | None = None,
) -> ExistingVoucher | None:
    """The first existing voucher that looks like the same entry again, or None."""
    reference = _reference_key(draft.reference_no)
    if not reference:
        return None
    total = _draft_total(draft)
    if total is None:
        return None
    for other in existing_vouchers:
        if (
            other.id != draft_id
            and other.status != "reversed"
            and other.reverses_voucher_id is None
            and other.client_id == draft.client_id
            and other.voucher_type == draft.voucher_type
            and other.party_ledger_id == draft.party_ledger_id
            and _reference_key(other.reference_no) == reference
            and other.total == total
        ):
            return other
    return None


def duplicate_error(draft: VoucherDraft, match: ExistingVoucher) -> ValidationError:
    """The V-10 error for a draft that matches an existing voucher."""
    label = TYPE_LABELS.get(draft.voucher_type, draft.voucher_type)
    where = match.voucher_number if match.voucher_number else "a draft"
    return ValidationError(
        "V-10",
        f"A {label} voucher with Reference No '{(draft.reference_no or '').strip()}' and amount "
        f"{format_inr(match.total)} for this party already exists: {where} dated "
        f"{match.voucher_date.strftime('%d-%m-%Y')}. Save it anyway only with a reason.",
    )
