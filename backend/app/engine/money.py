"""Exact money: parsing, rounding and Indian-style formatting. Decimal only, never float."""

import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext

TWO_PLACES = Decimal("0.01")
MAX_AMOUNT = Decimal("99999999999999.99")  # 14 whole digits: what the database column holds

_PLAIN_NUMBER = re.compile(r"^\d+(\.\d+)?$")
_NEGATIVE_NUMBER = re.compile(r"^-\d+(\.\d+)?$")


class MoneyError(ValueError):
    """An amount that cannot be accepted. `code` is one of:
    float, negative, decimals, invalid, too_large."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _shown(value: object) -> str:
    """How the offending amount is quoted back to the user."""
    return str(value).strip() if isinstance(value, (str, int, Decimal, float)) and not isinstance(value, bool) else repr(value)


def parse_amount(value: object) -> Decimal:
    """Turn an amount as entered into a Decimal with exactly 2 decimal places.

    Accepts plain text ("1000", "10.5"), int and Decimal. Rejects floats, bools, negatives, more than 2 decimal
    places, NaN/infinity, anything with commas, signs, exponents or letters, and amounts above 14 whole digits.
    """
    if value is None:
        raise MoneyError("invalid", "amount is missing")
    if isinstance(value, bool):
        raise MoneyError("invalid", f"amount {value!r} is not a valid number")
    if isinstance(value, float):
        raise MoneyError(
            "float", f"amount {value} is given as a floating-point number; amounts must be text or Decimal"
        )

    if isinstance(value, str):
        text = value.strip()
        if _NEGATIVE_NUMBER.match(text):
            raise MoneyError("negative", f"amount {text} is negative")
        if not _PLAIN_NUMBER.match(text):
            raise MoneyError("invalid", f"amount {value!r} is not a valid number")
        number = Decimal(text)
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        raise MoneyError("invalid", f"amount {value!r} is not a valid number")

    if not number.is_finite():
        raise MoneyError("invalid", f"amount {value!r} is not a valid number")
    if number < 0:
        raise MoneyError("negative", f"amount {_shown(value)} is negative")

    with localcontext() as ctx:
        ctx.prec = 60
        if number.quantize(TWO_PLACES, rounding=ROUND_DOWN) != number:
            raise MoneyError("decimals", f"amount {_shown(value)} has more than 2 decimal places")
        result = number.quantize(TWO_PLACES)
    if result > MAX_AMOUNT:
        raise MoneyError("too_large", f"amount {_shown(value)} is too large (maximum {format_inr(MAX_AMOUNT)})")
    return result


def no_negative_zero(value: Decimal) -> Decimal:
    """A zero amount is never negative: Decimal('-0.00') (from -1 * 0.00 or rounding -0.004) becomes Decimal('0.00')."""
    return value.copy_abs() if value.is_zero() else value


def round_half_up(value: Decimal, places: int = 2) -> Decimal:
    """Round to `places` decimals, halves away from zero (the legal rounding for tax amounts). Zero is never negative."""
    with localcontext() as ctx:
        ctx.prec = 60
        return no_negative_zero(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def format_inr(value: Decimal) -> str:
    """Indian digit grouping with 2 decimals: 1,00,000.00 (halves round up)."""
    rounded = round_half_up(value, 2)
    sign = "-" if rounded < 0 else ""
    whole, _, fraction = f"{abs(rounded):f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}{','.join(groups + [tail])}.{fraction}"
