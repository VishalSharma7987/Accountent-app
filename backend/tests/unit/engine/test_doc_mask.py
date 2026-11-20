"""D-50: masking of PAN, Aadhaar, bank account numbers, GSTIN (and key text) before any model call. Pure function, literal expectations."""

import pytest

from app.engine.doc_mask import (
    MaskingError,
    assert_clean,
    find_leftovers,
    mask,
    restore,
    restore_data,
)


def test_D50_pan_is_masked_and_counted():
    r = mask("PAN ABCDE1234F of supplier")
    assert r.text == "PAN [PAN_1] of supplier"
    assert r.report == {"PAN": 1}


def test_D50_lowercase_pan_is_masked():
    assert mask("pan abcde1234f").text == "pan [PAN_1]"


@pytest.mark.parametrize("text", ["ABCDE12345", "ABCD1234F", "ABCDE123F", "1234ABCDEF", "ABCDE-1234-F"])
def test_D50_pan_near_misses_are_left_alone(text):
    assert mask(text).text == text


def test_D50_gstin_is_one_token_and_does_not_leave_a_pan_token():
    r = mask("GSTIN 27ABCDE1234F1Z5 ok")
    assert r.text == "GSTIN [GSTIN_1] ok"
    assert r.report == {"GSTIN": 1}


def test_D50_gstin_and_the_same_holders_pan_get_separate_tokens():
    r = mask("27ABCDE1234F1Z5 / ABCDE1234F")
    assert r.text == "[GSTIN_1] / [PAN_1]"


def test_D50_adjacent_text_and_punctuation():
    r = mask("PAN:ABCDE1234F,GSTIN:27ABCDE1234F1Z5.")
    assert r.text == "PAN:[PAN_1],GSTIN:[GSTIN_1]."


@pytest.mark.parametrize("text", ["2345 6789 0123", "2345-6789-0123", "234567890123"])
def test_D50_aadhaar_in_each_format(text):
    r = mask("Aadhaar " + text + " end")
    assert r.text == "Aadhaar [AADHAAR_1] end"
    assert r.report == {"AADHAAR": 1}


def test_D50_aadhaar_in_devanagari_digits():
    assert mask("आधार २३४५ ६७८९ ०१२३").text == "आधार [AADHAAR_1]"


def test_D50_twelve_digits_starting_with_one_is_not_an_aadhaar_but_still_masked_as_account():
    r = mask("Ref 123456789012")
    assert r.text == "Ref [ACCOUNT_1]"
    assert r.report == {"ACCOUNT": 1}


def test_D50_bank_account_digit_runs():
    assert mask("A 50100123456789 B").text == "A [ACCOUNT_1] B"
    assert mask("1234567890123456789").text == "[ACCOUNT_1]"        # 19 digits
    assert mask("123456789").text == "[ACCOUNT_1]"                    # 9 digits
    assert mask("12345678").text == "12345678"                        # 8 digits: not an account number


def test_D50_sixteen_digit_card_style_grouping_is_masked():
    assert mask("1234 5678 9012 3456").text == "[ACCOUNT_1]"


@pytest.mark.parametrize("text, expected", [
    ("A/c No. 123-4567-89", "A/c No. [ACCOUNT_1]"),
    ("Account number: 12345678", "Account number: [ACCOUNT_1]"),
    ("ACCT 654321", "ACCT [ACCOUNT_1]"),
    ("a/c 12 3456 7890", "a/c [ACCOUNT_1]"),
])
def test_D50_account_number_after_a_keyword_is_masked_even_when_short_or_oddly_grouped(text, expected):
    assert mask(text).text == expected


def test_D50_keyword_with_too_few_digits_is_left_alone():
    assert mask("A/c No. 12345").text == "A/c No. 12345"


def test_D50_invoice_number_of_eight_digits_and_dates_and_normal_amounts_are_untouched():
    text = "Invoice No 20260401 dated 2026-04-01 total 1,00,000.00 and 12,34,56,789.50 qty 10 rate 0.123456789"
    assert mask(text).text == text


def test_D50_large_amount_with_decimals_is_not_taken_for_an_account_number():
    assert mask("Total 123456789.50").text == "Total 123456789.50"


def test_D50_account_number_before_a_full_stop_is_still_masked():
    assert mask("pay to 123456789012.").text == "pay to [ACCOUNT_1]."


def test_D50_repeated_value_gets_one_token_and_different_values_get_different_tokens():
    r = mask("ABCDE1234F and ABCDE1234F and PQRST6789K")
    assert r.text == "[PAN_1] and [PAN_1] and [PAN_2]"
    assert r.report == {"PAN": 3}   # occurrences


def test_D50_restore_round_trip_is_exact_for_a_mixed_text():
    original = ("Bill 100200300400 from 27ABCDE1234F1Z5 (PAN ABCDE1234F), Aadhaar 2345 6789 0123, "
                "A/c No. 50100123456789, repeat 27ABCDE1234F1Z5.")
    r = mask(original)
    assert r.text == ("Bill [ACCOUNT_1] from [GSTIN_1] (PAN [PAN_1]), Aadhaar [AADHAAR_1], A/c No. [ACCOUNT_2], repeat [GSTIN_1].")
    assert restore(r.text, r.mapping) == original


def test_D50_a_twelve_digit_invoice_number_is_masked_and_restored_without_loss():
    r = mask("Invoice 912345678901")
    assert r.text == "Invoice [AADHAAR_1]"
    assert restore("Invoice [AADHAAR_1]", r.mapping) == "Invoice 912345678901"


def test_D50_text_that_already_looks_like_a_token_cannot_be_confused_with_ours():
    original = "see [PAN_1] and ABCDE1234F"
    r = mask(original)
    assert r.text == "see [PAN_1] and [PAN_2]"
    assert restore(r.text, r.mapping) == original


def test_D50_restore_leaves_unknown_tokens_alone():
    assert restore("[PAN_9] x", {"[PAN_1]": "ABCDE1234F"}) == "[PAN_9] x"


def test_D50_restore_data_restores_strings_inside_nested_json():
    r = mask("ABCDE1234F 27ABCDE1234F1Z5")
    data = {"a": ["[PAN_1]", {"b": "gstin [GSTIN_1]"}], "n": 5, "x": None}
    assert restore_data(data, r.mapping) == {"a": ["ABCDE1234F", {"b": "gstin 27ABCDE1234F1Z5"}], "n": 5, "x": None}


def test_D52_an_openrouter_key_in_the_text_is_masked_as_a_secret():
    r = mask("key sk-or-v1-abc123def456 here")
    assert r.text == "key [SECRET_1] here"
    assert r.report == {"SECRET": 1}


def test_D50_empty_text_and_text_without_sensitive_data():
    assert mask("").text == ""
    r = mask("Plain narration, rent for May")
    assert r.text == "Plain narration, rent for May"
    assert r.report == {}


def test_D50_the_result_never_shows_the_original_values_in_its_repr():
    r = mask("PAN ABCDE1234F")
    assert "ABCDE1234F" not in repr(r)


def test_D50_assert_clean_accepts_masked_text_and_ordinary_numbers():
    r = mask("PAN ABCDE1234F, A/c 50100123456789, total 123456789.50, bill 20260401")
    assert_clean(r.text)
    assert find_leftovers(r.text) == {}


@pytest.mark.parametrize("text, kind", [
    ("PAN ABCDE1234F", "PAN"),
    ("GSTIN 27ABCDE1234F1Z5", "GSTIN"),
    ("Aadhaar 234567890123", "AADHAAR_OR_ACCOUNT"),
    ("Aadhaar 2345 6789 0123", "AADHAAR_OR_ACCOUNT"),
    ("A/c 50100123456789", "AADHAAR_OR_ACCOUNT"),
    ("A/c No. 123456", "AADHAAR_OR_ACCOUNT"),
    ("key sk-or-v1-abcdef", "SECRET"),
])
def test_D50_assert_clean_refuses_unmasked_text(text, kind):
    assert kind in find_leftovers(text)
    with pytest.raises(MaskingError) as info:
        assert_clean(text)
    assert kind in info.value.kinds
    assert "ABCDE1234F" not in str(info.value) and "234567890123" not in str(info.value)   # message holds counts, never values


def test_D50_assert_clean_does_not_trip_over_our_own_tokens():
    assert_clean("[PAN_1] [GSTIN_12] [AADHAAR_3] [ACCOUNT_4] [SECRET_1]")
