"""validate_party with the GST extension: gst_registration_type and the G-01 .. G-04 hand-over from P-01."""

from datetime import date

from engine_helpers import GROUPS, LEDGERS, ids

from app.engine.gst_types import StateCode
from app.engine.parties import validate_party

RAHUL = LEDGERS["rahul"]
GSTIN = "27AAPFU0939F1ZV"
CODES = [StateCode("27", "Maharashtra", "state", date(2017, 7, 1), None, "t", "pending")]


def check(**kw):
    return validate_party(RAHUL, GROUPS, **kw)


def test_G01_party_types_needing_a_gstin_are_regular_composition_sez_uin_holder():
    for kind in ("regular", "composition", "sez", "uin_holder"):
        assert check(gstin=GSTIN, gst_registration_type=kind) == [], kind
        assert ids(check(gst_registration_type=kind)) == [("G-01", None)], kind


def test_G01_unregistered_party_must_not_carry_a_gstin():
    assert check(gst_registration_type="unregistered") == []
    assert ids(check(gstin=GSTIN, gst_registration_type="unregistered")) == [("G-01", None)]


def test_G05_overseas_and_government_need_no_gstin_and_unknown_type_is_rejected():
    assert check(gst_registration_type="overseas") == []
    assert check(gst_registration_type="government") == []
    assert check(gst_registration_type=None) == []
    errors = check(gst_registration_type="casual")
    assert ids(errors) == [("G-05", None)] and "casual" in errors[0].message


def test_G02_party_gstin_check_digit_only_when_state_codes_are_given():
    bad = "27AAPFU0939F1ZW"
    assert check(gstin=bad) == []  # format-only P-01 behaviour is unchanged without the GST tables
    errors = check(gstin=bad, gst_state_codes=CODES, on_date=date(2026, 4, 1))
    assert ids(errors) == [("G-02", None)]


def test_G01_replaces_P01_when_state_codes_are_given():
    assert ids(check(gstin="BAD")) == [("P-01", None)]
    assert ids(check(gstin="BAD", gst_state_codes=CODES, on_date=date(2026, 4, 1))) == [("G-01", None)]


def test_G03_unknown_state_in_party_gstin():
    body = "38ABCDE1234F1Z"
    from app.engine.gstin import gstin_check_char

    errors = check(gstin=body + gstin_check_char(body), gst_state_codes=CODES, on_date=date(2026, 4, 1))
    assert ids(errors) == [("G-03", None)]


def test_G04_replaces_P03_P04_mismatch_when_state_codes_are_given():
    kw = {"gstin": GSTIN, "pan": "AAPFU0939G", "state_code": "29"}
    assert sorted(r for r, _ in ids(check(**kw))) == ["P-03", "P-04"]
    got = check(gst_state_codes=CODES, on_date=date(2026, 4, 1), **kw)
    assert ids(got) == [("G-04", None), ("G-04", None)]


def test_G04_matching_pan_and_state_pass_with_state_codes():
    assert check(gstin=GSTIN, pan="AAPFU0939F", state_code="27", gst_state_codes=CODES, on_date=date(2026, 4, 1)) == []
