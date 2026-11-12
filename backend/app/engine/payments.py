"""D-01: possible duplicate payment = another Payment to the same party ledger, for the same total, within
DUPLICATE_PAYMENT_DAYS days (either side of the date). A convenience window, not law.

Same override as V-10: `duplicate_override_reason` on the draft lets it through. Reversed vouchers, reversal
vouchers, non-payments and the voucher being edited are ignored. Only drafts with a party ledger are checked
(without a party there is nothing to compare).
"""

from collections.abc import Sequence
from decimal import Decimal

from app.engine.duplicates import ExistingVoucher
from app.engine.models import ValidationError, VoucherDraft
from app.engine.money import MoneyError, format_inr, parse_amount

DUPLICATE_PAYMENT_DAYS = 7


def _total_debit(draft: VoucherDraft) -> Decimal | None:
    total = Decimal("0.00")
    for line in draft.lines:
        if line.debit is None or (isinstance(line.debit, str) and line.debit.strip() == ""):
            continue
        try:
            total += parse_amount(line.debit)
        except MoneyError:
            return None  # an unreadable amount is reported by V-03; it cannot be compared
    return total


def duplicate_payment_errors(
    draft: VoucherDraft,
    existing: Sequence[ExistingVoucher],
    *,
    draft_id: object | None = None,
    days: int = DUPLICATE_PAYMENT_DAYS,
) -> list[ValidationError]:
    if draft.voucher_type != "payment" or draft.party_ledger_id is None:
        return []
    if (draft.duplicate_override_reason or "").strip():
        return []
    total = _total_debit(draft)
    if total is None:
        return []
    for other in existing:
        if (
            other.id != draft_id
            and other.voucher_type == "payment"
            and other.status != "reversed"
            and other.reverses_voucher_id is None
            and other.client_id == draft.client_id
            and other.party_ledger_id == draft.party_ledger_id
            and other.total == total
            and abs((other.voucher_date - draft.voucher_date).days) <= days
        ):
            where = other.voucher_number if other.voucher_number else "a draft"
            return [ValidationError(
                "D-01",
                f"A payment of {format_inr(total)} to this party already exists: {where} dated "
                f"{other.voucher_date.strftime('%d-%m-%Y')} (within {days} days). This may be a duplicate payment. "
                "Save it anyway only with a reason.",
            )]
    return []
