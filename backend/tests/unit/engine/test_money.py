from decimal import Decimal

import pytest

from app.engine.money import MoneyError, format_inr, parse_amount, round_half_up

# ---------------------------------------------------------------------------------------- parse_amount


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("1000", "1000.00"),
        ("10.5", "10.50"),
        ("10.50", "10.50"),
        ("0", "0.00"),
        ("0.01", "0.01"),
        (" 25.00 ", "25.00"),  # spaces around a pasted cell are not part of the number
        (12, "12.00"),
        (0, "0.00"),
        (Decimal("0.1"), "0.10"),
        (Decimal("1E+2"), "100.00"),
        ("99999999999999.99", "99999999999999.99"),  # largest amount the database column holds
    ],
)
def test_parse_amount_accepts_plain_amounts_and_always_returns_two_decimals(given, expected):
    result = parse_amount(given)
    assert isinstance(result, Decimal)
    assert str(result) == expected


@pytest.mark.parametrize(
    ("given", "code", "fragment"),
    [
        (10.5, "float", "floating-point"),
        (0.1, "float", "floating-point"),
        ("-5", "negative", "negative"),
        ("-0.01", "negative", "negative"),
        (-3, "negative", "negative"),
        (Decimal("-0.01"), "negative", "negative"),
        ("10.005", "decimals", "more than 2 decimal places"),
        (Decimal("10.005"), "decimals", "more than 2 decimal places"),
        ("0.001", "decimals", "more than 2 decimal places"),
        ("100.0001", "decimals", "more than 2 decimal places"),
        ("1,000.00", "invalid", "not a valid number"),
        ("1,00,000", "invalid", "not a valid number"),
        ("Rs 100", "invalid", "not a valid number"),
        ("abc", "invalid", "not a valid number"),
        ("", "invalid", "not a valid number"),
        ("+5", "invalid", "not a valid number"),
        ("1e3", "invalid", "not a valid number"),
        ("1_000", "invalid", "not a valid number"),
        ("1 000", "invalid", "not a valid number"),
        ("NaN", "invalid", "not a valid number"),
        ("Infinity", "invalid", "not a valid number"),
        (Decimal("NaN"), "invalid", "not a valid number"),
        (Decimal("Infinity"), "invalid", "not a valid number"),
        (None, "invalid", "missing"),
        (True, "invalid", "not a valid number"),
        ("100000000000000.00", "too_large", "too large"),
        (10**14, "too_large", "too large"),
    ],
)
def test_parse_amount_rejects_with_a_clear_reason(given, code, fragment):
    with pytest.raises(MoneyError) as info:
        parse_amount(given)
    assert info.value.code == code
    assert fragment in str(info.value)


def test_parse_amount_message_shows_what_was_typed():
    with pytest.raises(MoneyError) as info:
        parse_amount("10.005")
    assert str(info.value) == "amount 10.005 has more than 2 decimal places"


# -------------------------------------------------------------------------------------- round_half_up


@pytest.mark.parametrize(
    ("given", "places", "expected"),
    [
        ("2.675", 2, "2.68"),
        ("2.665", 2, "2.67"),
        ("2.664", 2, "2.66"),
        ("-2.675", 2, "-2.68"),  # half goes away from zero
        ("0.005", 2, "0.01"),
        ("0.004", 2, "0.00"),
        ("2.5", 0, "3"),
        ("3.5", 0, "4"),
        ("-2.5", 0, "-3"),
        ("1234.56785", 4, "1234.5679"),
        ("10", 2, "10.00"),
    ],
)
def test_round_half_up(given, places, expected):
    assert str(round_half_up(Decimal(given), places)) == expected


# ------------------------------------------------------------------------------------------ format_inr


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (Decimal(0), "0.00"),
        (Decimal(5), "5.00"),
        (Decimal("999.99"), "999.99"),
        (Decimal(1000), "1,000.00"),
        (Decimal(10000), "10,000.00"),
        (Decimal(100000), "1,00,000.00"),
        (Decimal("1234567.89"), "12,34,567.89"),
        (Decimal("123456789.5"), "12,34,56,789.50"),
        (Decimal(1000000000), "1,00,00,00,000.00"),
        (Decimal(-100000), "-1,00,000.00"),
        (Decimal("0.005"), "0.01"),
        (Decimal("99999999999999.99"), "9,99,99,99,99,99,999.99"),
    ],
)
def test_format_inr_groups_in_lakhs_and_crores(given, expected):
    assert format_inr(given) == expected


def test_no_negative_zero_money_values():
    from app.engine.money import no_negative_zero

    assert str(no_negative_zero(Decimal(-1) * Decimal("0.00"))) == "0.00"
    assert str(round_half_up(Decimal("-0.004"))) == "0.00"
    assert str(no_negative_zero(Decimal("-5.00"))) == "-5.00"
