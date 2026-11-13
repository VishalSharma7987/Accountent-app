"""Registration, item master and ledger-role rules G-05 .. G-08 (pure engine)."""

from datetime import date

from engine_helpers import GROUPS

from app.engine.gst_masters import (
    REQUIRED_ROLES,
    missing_roles,
    periods_overlap,
    registration_covers,
    validate_item,
    validate_ledger_roles,
    validate_registration,
)
from app.engine.gst_types import GstRegistration, StateCode
from app.engine.models import Ledger

D = date(2026, 4, 1)
CODES = [StateCode("27", "Maharashtra", "state", date(2017, 7, 1), None, "t", "pending")]
GSTIN = "27AAPFU0939F1ZV"
UQC = ["NOS", "KGS"]


def ids(errors):
    return [(e.rule_id, e.line_no) for e in errors]


def reg(client="regular", **kw):
    args = {"gstin": GSTIN, "registration_type": "regular", "return_frequency": "monthly", "composition_category": None,
                "effective_from": D, "effective_to": None, "client_gst_type": client, "client_pan": None, "state_codes": CODES,
                "others": ()}
    args.update(kw)
    return validate_registration(**args)


def test_G05_regular_client_regular_registration_passes():
    assert reg() == []


def test_G05_unregistered_client_cannot_have_a_registration():
    errors = reg(client="unregistered")
    assert ids(errors) == [("G-05", None)]
    assert "unregistered" in errors[0].message


def test_G05_composition_client_needs_composition_registration():
    assert ids(reg(client="composition", registration_type="regular")) == [("G-05", None)]
    assert reg(client="composition", registration_type="composition", composition_category="trader") == []


def test_G05_regular_client_cannot_hold_composition_registration():
    assert ids(reg(registration_type="composition", composition_category="trader")) == [("G-05", None)]


def test_G05_composition_needs_a_category_and_regular_must_not_have_one():
    assert ids(reg(client="composition", registration_type="composition")) == [("G-05", None)]
    assert ids(reg(composition_category="trader")) == [("G-05", None)]
    assert ids(reg(client="composition", registration_type="composition", composition_category="banker")) == [
        ("G-05", None)]


def test_G05_qrmp_only_for_regular():
    assert reg(return_frequency="qrmp") == []
    assert ids(reg(client="composition", registration_type="composition", composition_category="trader",
                   return_frequency="qrmp")) == [("G-05", None)]
    assert ids(reg(return_frequency="weekly")) == [("G-05", None)]


def test_G05_unknown_registration_type_rejected():
    assert ("G-05", None) in ids(reg(registration_type="casual"))


def test_G01_G02_apply_to_registration_gstin():
    assert ids(reg(gstin="BAD")) == [("G-01", None)]
    assert ids(reg(gstin="27AAPFU0939F1ZW")) == [("G-02", None)]


def test_G04_registration_pan_must_match_client_pan():
    assert reg(client_pan="AAPFU0939F") == []
    assert ids(reg(client_pan="AAPFU0939G")) == [("G-04", None)]


def test_G06_overlapping_period_of_same_gstin_rejected():
    other = ("id-1", date(2025, 4, 1), date(2026, 6, 30))
    errors = reg(others=(other,))
    assert ids(errors) == [("G-06", None)]
    assert "01-04-2025" in errors[0].message and "30-06-2026" in errors[0].message


def test_G06_adjacent_periods_do_not_overlap():
    assert reg(others=(("id-1", date(2025, 4, 1), date(2026, 3, 31)),)) == []


def test_G06_open_ended_other_registration_overlaps_everything_after_its_start():
    assert ids(reg(others=(("id-1", date(2026, 1, 1), None),), effective_to=date(2026, 12, 31))) == [("G-06", None)]


def test_G06_effective_to_before_from_rejected():
    assert ids(reg(effective_to=date(2026, 3, 31))) == [("G-06", None)]


def test_G06_periods_overlap_function():
    assert periods_overlap(date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 31), None)
    assert not periods_overlap(date(2026, 1, 1), date(2026, 1, 30), date(2026, 1, 31), None)
    assert periods_overlap(date(2026, 1, 1), None, date(2030, 1, 1), None)


def registration(**kw):
    args = {"id": "r1", "gstin": GSTIN, "state_code": "27", "registration_type": "regular", "return_frequency": "monthly",
                "composition_category": None, "effective_from": date(2026, 4, 1), "effective_to": date(2027, 3, 31)}
    args.update(kw)
    return GstRegistration(**args)


def test_G06_invoice_date_must_fall_inside_registration_period():
    r = registration()
    assert registration_covers(r, date(2026, 4, 1)) and registration_covers(r, date(2027, 3, 31))
    assert not registration_covers(r, date(2026, 3, 31)) and not registration_covers(r, date(2027, 4, 1))
    assert not registration_covers(registration(is_active=False), date(2026, 5, 1))
    assert registration_covers(registration(effective_to=None), date(2040, 1, 1))


# ---- items G-07 ------------------------------------------------------------------------------------------


def test_G07_goods_hsn_of_4_6_or_8_digits_accepted():
    for code in ("8517", "851712", "85171200"):
        assert validate_item("goods", code, "NOS", UQC) == [], code


def test_G07_hsn_of_wrong_length_or_letters_rejected():
    for code in ("851", "85171", "8517123", "851712001", "85A7", ""):
        assert ids(validate_item("goods", code, "NOS", UQC)) == [("G-07", None)], code


def test_G07_sac_must_be_6_digits_starting_99():
    assert validate_item("service", "998314", None, UQC) == []
    for code in ("8314", "99831", "9983140", "898314"):
        assert ids(validate_item("service", code, None, UQC)) == [("G-07", None)], code


def test_G07_goods_need_uqc_from_the_table():
    assert ids(validate_item("goods", "8517", None, UQC)) == [("G-07", None)]
    errors = validate_item("goods", "8517", "XYZ", UQC)
    assert ids(errors) == [("G-07", None)] and "XYZ" in errors[0].message


def test_G07_service_uqc_optional_but_must_be_valid_if_given():
    assert validate_item("service", "998314", "NOS", UQC) == []
    assert ids(validate_item("service", "998314", "XYZ", UQC)) == [("G-07", None)]


def test_G07_unknown_kind_rejected():
    assert ids(validate_item("thing", "8517", "NOS", UQC)) == [("G-07", None)]


# ---- ledger roles G-08 -----------------------------------------------------------------------------------

CL = "client-1"


def led(i, group, client=CL, active=True):
    return Ledger(i, f"L-{i}", group, active, client)


def test_G08_correct_groups_pass():
    roles = {
        "output_cgst": led("a", "duties_taxes"), "input_igst": led("b", "duties_taxes"),
        "rcm_sgst": led("c", "duties_taxes"), "round_off": led("d", "indirect_expenses"),
        "itc_reversal": led("e", "indirect_expenses"),
    }
    assert validate_ledger_roles(roles, GROUPS, CL) == []
    assert validate_ledger_roles({"round_off": led("d", "indirect_incomes")}, GROUPS, CL) == []


def test_G08_tax_ledger_outside_duties_and_taxes_rejected():
    errors = validate_ledger_roles({"output_cgst": led("a", "indirect_expenses")}, GROUPS, CL)
    assert ids(errors) == [("G-08", None)]
    assert "Duties & Taxes" in errors[0].message and "L-a" in errors[0].message


def test_G08_round_off_and_reversal_group_rules():
    assert ids(validate_ledger_roles({"round_off": led("d", "duties_taxes")}, GROUPS, CL)) == [("G-08", None)]
    assert ids(validate_ledger_roles({"itc_reversal": led("e", "indirect_incomes")}, GROUPS, CL)) == [("G-08", None)]


def test_G08_missing_foreign_or_inactive_ledger_rejected():
    assert ids(validate_ledger_roles({"output_cgst": None}, GROUPS, CL)) == [("G-08", None)]
    foreign = {"output_cgst": led("a", "duties_taxes", client="other")}
    assert ids(validate_ledger_roles(foreign, GROUPS, CL)) == [("G-08", None)]
    inactive = {"output_cgst": led("a", "duties_taxes", active=False)}
    assert ids(validate_ledger_roles(inactive, GROUPS, CL)) == [("G-08", None)]


def test_G08_unknown_role_name_rejected():
    assert ids(validate_ledger_roles({"output_vat": led("a", "duties_taxes")}, GROUPS, CL)) == [("G-08", None)]


def test_G08_roles_an_invoice_needs_must_be_mapped():
    assert REQUIRED_ROLES["regular"] == (
        "output_cgst", "output_sgst", "output_igst", "input_cgst", "input_sgst", "input_igst")
    assert REQUIRED_ROLES["composition"] == ("composition_tax_expense", "composition_tax_payable")
    assert missing_roles("regular", {"output_cgst": "x", "input_cgst": "y"}) == [
        "output_sgst", "output_igst", "input_sgst", "input_igst"]
    assert missing_roles("composition", {"composition_tax_expense": "x", "composition_tax_payable": "y"}) == []
