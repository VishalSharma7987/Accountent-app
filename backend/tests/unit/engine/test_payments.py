"""D-01: possible duplicate payment (same party ledger, same total, within 7 days)."""

from datetime import date
from decimal import Decimal

from app.engine.duplicates import ExistingVoucher
from app.engine.models import VoucherDraft, VoucherLine
from app.engine.payments import DUPLICATE_PAYMENT_DAYS, duplicate_payment_errors

D = Decimal


def draft(on=date(2026, 4, 10), amount="10000", party="sharma", vtype="payment", override=None, client="c1"):
    return VoucherDraft(
        client, vtype, on, "Paid supplier", None, party,
        (VoucherLine("sharma", amount, None), VoucherLine("cash", None, amount)), override,
    )


def ex(on=date(2026, 4, 4), total="10000.00", party="sharma", status="posted", number="PAY/2026-27/0001",
       vtype="payment", reverses=None, vid="old", client="c1"):
    return ExistingVoucher(vid, client, vtype, party, None, D(total), status, number, on, reverses)


def test_D01_constant_is_seven_days():
    assert DUPLICATE_PAYMENT_DAYS == 7


def test_D01_same_party_amount_six_days_apart_is_blocked():
    errors = duplicate_payment_errors(draft(), [ex(on=date(2026, 4, 4))])
    assert [e.rule_id for e in errors] == ["D-01"]
    assert "10,000.00" in errors[0].message and "PAY/2026-27/0001" in errors[0].message
    assert "04-04-2026" in errors[0].message


def test_D01_exactly_seven_days_apart_is_blocked():
    assert duplicate_payment_errors(draft(), [ex(on=date(2026, 4, 3))])


def test_D01_eight_days_apart_is_allowed():
    assert duplicate_payment_errors(draft(), [ex(on=date(2026, 4, 2))]) == []


def test_D01_later_payment_within_window_is_blocked():
    assert duplicate_payment_errors(draft(), [ex(on=date(2026, 4, 16))])


def test_D01_different_amount_is_allowed():
    assert duplicate_payment_errors(draft(), [ex(total="10000.01")]) == []


def test_D01_different_party_is_allowed():
    assert duplicate_payment_errors(draft(), [ex(party="rahul")]) == []


def test_D01_reversed_original_is_not_counted():
    assert duplicate_payment_errors(draft(), [ex(status="reversed")]) == []


def test_D01_reversal_voucher_and_non_payments_are_not_candidates():
    assert duplicate_payment_errors(draft(), [ex(reverses="x")]) == []
    assert duplicate_payment_errors(draft(), [ex(vtype="receipt")]) == []


def test_D01_override_reason_lets_it_through():
    assert duplicate_payment_errors(draft(override="Second instalment, agreed"), [ex()]) == []
    assert duplicate_payment_errors(draft(override="   "), [ex()])  # a blank reason does not count


def test_D01_voucher_being_edited_does_not_clash_with_itself():
    assert duplicate_payment_errors(draft(), [ex(vid="me")], draft_id="me") == []


def test_D01_only_payments_with_a_party_are_checked():
    assert duplicate_payment_errors(draft(vtype="receipt"), [ex()]) == []
    assert duplicate_payment_errors(draft(party=None), [ex(party=None)]) == []
