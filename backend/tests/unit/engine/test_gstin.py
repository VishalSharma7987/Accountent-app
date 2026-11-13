"""GSTIN rules G-01 .. G-04. Synthetic GSTINs and their check characters are typed literally from
docs/PHASE3_LEGAL_VALUES.md section 2 (hand-checked with the mod-36 algorithm)."""

from datetime import date

from app.engine.gst_types import StateCode
from app.engine.gstin import extract_pan, gstin_check_char, state_pan_errors, validate_gstin

D = date(2026, 4, 1)


def sc(code, name="State", kind="state", frm=date(2017, 7, 1), to=None, status="secondary_verified"):
    return StateCode(code, name, kind, frm, to, "test", status)


CODES = [
    sc("07", "Delhi"), sc("24", "Gujarat"), sc("27", "Maharashtra"), sc("29", "Karnataka"), sc("33", "Tamil Nadu"),
    sc("28", "Andhra Pradesh (old)", to=date(2020, 3, 31)), sc("96", "Foreign Country", "other_territory"),
    sc("97", "Other Territory", "other_territory"), sc("99", "Centre Jurisdiction", "centre_jurisdiction"),
]
VALID = ["27AAPFU0939F1ZV", "27ABCDE1234F1Z0", "29ABCDE1234F1ZW", "07AAAAA0000A1Z4", "33AAAAA0000A1Z9",
         "24ABCPA1234B1ZT"]
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def ids(errors):
    return [(e.rule_id, e.line_no) for e in errors]


def test_G02_check_character_of_known_gstins():
    assert [gstin_check_char(g[:14]) for g in VALID] == ["V", "0", "W", "4", "9", "T"]


def test_G02_valid_gstins_pass():
    for g in VALID:
        assert validate_gstin(g, CODES, D) == [], g


def test_G02_wrong_check_character_rejected_and_names_expected_one():
    errors = validate_gstin("27AAPFU0939F1ZW", CODES, D)
    assert ids(errors) == [("G-02", None)]
    assert "V" in errors[0].message


def test_G02_every_wrong_check_character_is_rejected():
    for c in ALPHABET:
        if c != "0":
            assert ids(validate_gstin("27ABCDE1234F1Z" + c, CODES, D)) == [("G-02", None)], c


def test_G02_one_wrong_character_in_any_body_position_is_caught():
    base = "27AAPFU0939F1ZV"
    digit_positions = (0, 1, 7, 8, 9, 10)
    for i in range(13):  # index 13 is the fixed 'Z' (G-01)
        original = base[i]
        if i in digit_positions:
            replacement = "5" if original != "5" else "6"
        else:
            replacement = "B" if original != "B" else "C"
        broken = base[:i] + replacement + base[i + 1:]
        got = {r for r, _ in ids(validate_gstin(broken, CODES, D))}
        assert got, (i, broken)  # never accepted as valid
        assert got <= {"G-02", "G-03"}, (i, broken, got)


def test_G01_wrong_length_and_pattern_rejected():
    assert ids(validate_gstin("27AAPFU0939F1Z", CODES, D)) == [("G-01", None)]
    assert ids(validate_gstin("", CODES, D)) == [("G-01", None)]
    assert ids(validate_gstin("AAAAAAAAAAAAAAA", CODES, D)) == [("G-01", None)]
    assert ids(validate_gstin("27AAPFU0939F1AV", CODES, D)) == [("G-01", None)]  # 14th must be Z
    assert ids(validate_gstin("27aapfu0939f1zv", CODES, D)) == [("G-01", None)]  # capitals only (normalise first)
    assert "15 characters" in validate_gstin("27AAPFU0939F1Z", CODES, D)[0].message


def test_G01_entity_number_zero_rejected():
    assert ids(validate_gstin("27AAPFU0939F0ZV", CODES, D)) == [("G-01", None)]


def test_G03_unknown_state_code_rejected():
    body = "38ABCDE1234F1Z"  # 38 is not in this table; check character is right, so only G-03 fires
    assert ids(validate_gstin(body + gstin_check_char(body), CODES, D)) == [("G-03", None)]


def test_G03_state_code_not_in_force_on_date_rejected():
    body = "28ABCDE1234F1Z"
    g = body + gstin_check_char(body)
    assert validate_gstin(g, CODES, date(2020, 3, 31)) == []
    assert ids(validate_gstin(g, CODES, date(2020, 4, 1))) == [("G-03", None)]


def test_G03_codes_96_97_99_are_not_registration_states():
    for code in ("96", "97", "99"):
        body = code + "ABCDE1234F1Z"
        errors = validate_gstin(body + gstin_check_char(body), CODES, D)
        assert ids(errors) == [("G-03", None)], code
        assert "not a registration state" in errors[0].message


def test_G02_and_G03_both_reported():
    assert ids(validate_gstin("38ABCDE1234F1ZA", CODES, D)) == [("G-02", None), ("G-03", None)]


def test_G04_pan_is_characters_3_to_12():
    assert extract_pan("27AAPFU0939F1ZV") == "AAPFU0939F"


def test_G04_pan_must_match_when_both_known():
    errors = state_pan_errors("27AAPFU0939F1ZV", state_code="27", pan="AAPFU0939G")
    assert ids(errors) == [("G-04", None)]
    assert "AAPFU0939F" in errors[0].message


def test_G04_state_code_must_equal_first_two_digits():
    errors = state_pan_errors("27AAPFU0939F1ZV", state_code="29", pan="AAPFU0939F")
    assert ids(errors) == [("G-04", None)]
    assert "29" in errors[0].message and "27" in errors[0].message


def test_G04_unknown_pan_or_state_is_not_checked():
    assert state_pan_errors("27AAPFU0939F1ZV", state_code=None, pan=None) == []
    assert state_pan_errors("27AAPFU0939F1ZV", state_code="27", pan=None) == []
