"""V-10: possible duplicate = same client + type + party ledger + reference no + total."""

from datetime import date
from decimal import Decimal

import pytest
from engine_helpers import draft, line

from app.engine.duplicates import ExistingVoucher, duplicate_error, find_possible_duplicate


def existing(**overrides):
    base = {
        "id": "v-1",
        "client_id": "client-1",
        "voucher_type": "purchase",
        "party_ledger_id": "sharma",
        "reference_no": "SUP/889",
        "total": Decimal("50000.00"),
        "status": "posted",
        "voucher_number": "PUR/2026-27/0001",
        "voucher_date": date(2026, 4, 5),
        "reverses_voucher_id": None,
    }
    base.update(overrides)
    return ExistingVoucher(**base)


def new_purchase(**overrides):
    args = {
        "reference_no": "SUP/889",
        "party": "sharma",
    }
    args.update(overrides)
    return draft("purchase", [line("purchases", dr=overrides.get("amount", "50000")), line("sharma", cr=overrides.get("amount", "50000"))],
                 reference_no=args["reference_no"], party=args["party"], client=overrides.get("client", "client-1"))


def test_V10_same_client_type_party_reference_and_total_is_a_duplicate():
    match = find_possible_duplicate(new_purchase(), [existing()])
    assert match is not None and match.id == "v-1"


def test_V10_a_voucher_that_differs_in_any_one_field_is_not_a_duplicate():
    assert find_possible_duplicate(new_purchase(amount="50000.01"), [existing()]) is None  # total
    assert find_possible_duplicate(new_purchase(reference_no="SUP/890"), [existing()]) is None  # reference
    assert find_possible_duplicate(new_purchase(party="rahul"), [existing()]) is None  # party
    assert find_possible_duplicate(new_purchase(client="client-2"), [existing()]) is None  # client
    assert find_possible_duplicate(new_purchase(), [existing(voucher_type="debit_note")]) is None  # type
    assert find_possible_duplicate(new_purchase(), [existing(client_id="client-2")]) is None


@pytest.mark.parametrize("typed", ["sup/889", "  SUP/889  ", "Sup/889"])
def test_V10_reference_is_compared_trimmed_and_ignoring_case(typed):
    assert find_possible_duplicate(new_purchase(reference_no=typed), [existing()]) is not None


@pytest.mark.parametrize("reference", [None, "", "   "])
def test_V10_without_a_reference_nothing_is_flagged(reference):
    assert find_possible_duplicate(new_purchase(reference_no=reference), [existing(reference_no=reference)]) is None


def test_V10_reversed_vouchers_are_ignored_so_a_corrected_entry_can_be_made():
    assert find_possible_duplicate(new_purchase(), [existing(status="reversed")]) is None


def test_V10_reversal_vouchers_are_ignored():
    assert find_possible_duplicate(new_purchase(), [existing(reverses_voucher_id="v-0")]) is None


@pytest.mark.parametrize("status", ["draft", "approved", "posted"])
def test_V10_drafts_approved_and_posted_vouchers_all_count(status):
    assert find_possible_duplicate(new_purchase(), [existing(status=status)]) is not None


def test_V10_the_voucher_being_edited_does_not_clash_with_itself():
    assert find_possible_duplicate(new_purchase(), [existing()], draft_id="v-1") is None
    assert find_possible_duplicate(new_purchase(), [existing(), existing(id="v-2")], draft_id="v-1").id == "v-2"


def test_V10_first_match_in_the_given_order_is_returned():
    assert find_possible_duplicate(new_purchase(), [existing(id="v-9"), existing(id="v-3")]).id == "v-9"


def test_V10_total_is_the_sum_of_the_debit_side():
    d = draft(
        "purchase",
        [line("purchases", dr="30000"), line("freight", dr="20000"), line("sharma", cr="50000")],
        reference_no="SUP/889",
        party="sharma",
    )
    assert find_possible_duplicate(d, [existing()]) is not None


def test_V10_a_draft_with_unreadable_amounts_cannot_be_compared():
    d = draft("purchase", [line("purchases", dr="50000.005"), line("sharma", cr="50000")], reference_no="SUP/889", party="sharma")
    assert find_possible_duplicate(d, [existing()]) is None


def test_V10_two_vouchers_without_a_party_match_on_the_other_fields():
    a = draft("payment", [line("rent", dr="1000"), line("cash", cr="1000")], reference_no="CHQ-12")
    assert find_possible_duplicate(a, [existing(voucher_type="payment", party_ledger_id=None, reference_no="CHQ-12", total=Decimal("1000.00"))]) is not None


def test_V10_error_names_the_matching_voucher_in_plain_language():
    error = duplicate_error(new_purchase(), existing())
    assert (error.rule_id, error.line_no) == ("V-10", None)
    assert error.message == (
        "A Purchase voucher with Reference No 'SUP/889' and amount 50,000.00 for this party already exists: "
        "PUR/2026-27/0001 dated 05-04-2026. Save it anyway only with a reason."
    )


def test_V10_error_for_a_draft_match_says_draft():
    error = duplicate_error(new_purchase(amount="1250000"), existing(voucher_number=None, status="draft", total=Decimal("1250000.00")))
    assert error.message == (
        "A Purchase voucher with Reference No 'SUP/889' and amount 12,50,000.00 for this party already exists: "
        "a draft dated 05-04-2026. Save it anyway only with a reason."
    )
