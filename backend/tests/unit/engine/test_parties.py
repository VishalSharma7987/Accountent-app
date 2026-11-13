"""validate_party: rules P-01 .. P-07 and P-09 .. P-11. Expected rule ids and key words are typed literally."""

from datetime import date

from engine_helpers import GROUPS, LEDGERS, ids

from app.engine.parties import normalise_id, party_nature, validate_party

RAHUL = LEDGERS["rahul"]
SHARMA = LEDGERS["sharma"]
GSTIN = "27AABCU9603R1ZN"
PAN = "AABCU9603R"


def check(ledger=RAHUL, **kw):
    return validate_party(ledger, GROUPS, **kw)


def test_valid_party_with_everything_filled_passes():
    assert check(gstin=GSTIN, pan=PAN, state_code="27", credit_days=30, msme_category="micro",
                 udyam_no="UDYAM-MH-18-0012345", msme_activity="manufacturing",
                 udyam_registration_date=date(2021, 3, 1), msme_written_agreement=True, msme_agreed_days=30) == []


def test_valid_party_with_nothing_filled_passes():
    assert check() == []


def test_P01_gstin_wrong_length_rejected():
    errors = check(gstin="27AABCU9603R1Z")
    assert ids(errors) == [("P-01", None)]
    assert "15 characters" in errors[0].message


def test_P01_gstin_wrong_pattern_rejected():
    assert ids(check(gstin="AAAAAAAAAAAAAAA")) == [("P-01", None)]


def test_P01_gstin_without_Z_in_14th_place_rejected():
    assert ids(check(gstin="27AABCU9603R1AM")) == [("P-01", None)]


def test_P02_pan_wrong_pattern_rejected():
    errors = check(pan="AABCU96R03")
    assert ids(errors) == [("P-02", None)]
    assert "5 letters, 4 digits" in errors[0].message


def test_P03_pan_must_sit_inside_gstin():
    errors = check(gstin=GSTIN, pan="AABCU9603Q")
    assert ids(errors) == [("P-03", None)]
    assert "AABCU9603R" in errors[0].message


def test_P03_not_checked_when_only_one_of_them_given():
    assert check(gstin=GSTIN) == []
    assert check(pan=PAN) == []


def test_P04_state_code_must_be_two_digits():
    assert ids(check(state_code="7")) == [("P-04", None)]
    assert ids(check(state_code="AB")) == [("P-04", None)]


def test_P04_state_code_must_match_gstin():
    errors = check(gstin=GSTIN, state_code="29")
    assert ids(errors) == [("P-04", None)]
    assert "27" in errors[0].message


def test_P05_msme_category_needs_udyam_number():
    errors = check(msme_category="small", msme_activity="services")
    assert ids(errors) == [("P-05", None)]
    assert "Udyam" in errors[0].message


def test_P05_malformed_udyam_rejected_even_without_category():
    assert ids(check(udyam_no="UDYAM-MH-18-12345", udyam_registration_date=date(2021, 3, 1))) == [("P-05", None)]


def test_P05_unknown_category_rejected():
    assert ids(check(msme_category="tiny")) == [("P-05", None)]


def test_P05_category_none_without_udyam_is_fine():
    assert check(msme_category="none", udyam_no=None) == []


def test_P06_credit_days_negative_rejected():
    assert ids(check(credit_days=-1)) == [("P-06", None)]


def test_P06_credit_days_fraction_rejected():
    assert ids(check(credit_days="2.5")) == [("P-06", None)]
    assert ids(check(credit_days=2.5)) == [("P-06", None)]


def test_P06_credit_days_text_number_and_zero_accepted():
    assert check(credit_days="45") == []
    assert check(credit_days=0) == []


def test_P07_only_debtor_or_creditor_ledgers_can_be_parties():
    errors = check(LEDGERS["rent"])
    assert ids(errors) == [("P-07", None)]
    assert "Indirect Expenses" in errors[0].message


def test_P07_custom_subgroup_under_sundry_debtors_is_accepted():
    from app.engine.models import Group, Ledger

    groups = {**GROUPS, "dealers": Group("dealers", "Dealers", "asset", "balance_sheet", "sundry_debtors")}
    ledger = Ledger("d1", "Dealer One", "dealers", True, "client-1")
    assert validate_party(ledger, groups) == []
    assert party_nature(ledger, groups) == "debtor"


def test_party_nature_of_debtor_and_creditor():
    assert party_nature(RAHUL, GROUPS) == "debtor"
    assert party_nature(SHARMA, GROUPS) == "creditor"
    assert party_nature(LEDGERS["rent"], GROUPS) is None


def test_all_errors_are_reported_together():
    errors = check(gstin="BAD", pan="BAD", state_code="1", credit_days=-5, msme_category="micro")
    assert sorted(e.rule_id for e in errors) == ["P-01", "P-02", "P-04", "P-05", "P-06", "P-09"]


def test_normalise_id_trims_and_uppercases_blank_becomes_none():
    assert normalise_id("  aabcu9603r ") == "AABCU9603R"
    assert normalise_id("   ") is None
    assert normalise_id(None) is None


UDYAM = "UDYAM-MH-18-0012345"


def test_P09_micro_and_small_need_an_activity_medium_and_none_do_not():
    kw = {"udyam_no": UDYAM, "udyam_registration_date": date(2021, 3, 1)}
    for cat in ("micro", "small"):
        errors = check(msme_category=cat, **kw)
        assert ids(errors) == [("P-09", None)]
        assert "manufacturing, services or trading" in errors[0].message
        assert check(msme_category=cat, msme_activity="trading", **kw) == []
    assert check(msme_category="medium", **kw) == []
    assert check() == []


def test_P09_unknown_activity_rejected():
    assert ids(check(msme_activity="retail")) == [("P-09", None)]


def test_P10_udyam_number_needs_the_registration_date():
    errors = check(udyam_no=UDYAM)
    assert ids(errors) == [("P-10", None)]
    assert "registration date" in errors[0].message
    assert check(udyam_no=UDYAM, udyam_registration_date=date(2021, 3, 1)) == []


def test_P11_written_agreement_needs_agreed_days():
    errors = check(msme_written_agreement=True)
    assert ids(errors) == [("P-11", None)]
    assert "agreed credit days" in errors[0].message


def test_P11_agreed_days_without_agreement_rejected():
    assert ids(check(msme_agreed_days=30)) == [("P-11", None)]


def test_P11_agreed_days_must_be_1_to_45():
    for bad in (0, 46, 60, -5):
        errors = check(msme_written_agreement=True, msme_agreed_days=bad)
        assert ids(errors) == [("P-11", None)], bad
    assert "45" in errors[0].message
    for good in (1, 45):
        assert check(msme_written_agreement=True, msme_agreed_days=good) == []
