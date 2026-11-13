"""TDS masters rules T-10, T-11, T-12 (master side), T-14 and the TAN check T-30 (pure engine). Literal expectations."""

from datetime import date
from decimal import Decimal

from engine_helpers import GROUPS

from app.engine.models import Ledger
from app.engine.tds_masters import (
    available_amount,
    validate_certificate,
    validate_deductee,
    validate_ledger_roles,
    validate_tan,
)

C = "client-1"


def ids(errors):
    return [e.rule_id for e in errors]


def dd(pan, status, dtype):
    return validate_deductee(pan, status, dtype)


# ---- T-10 PAN format and status --------------------------------------------------------------------------------


def test_T10_valid_pan_with_valid_status_passes():
    assert dd("ABCPE1234F", "valid", "individual") == ([], [])


def test_T10_valid_status_without_pan_rejected():
    errors, _ = dd(None, "valid", "individual")
    assert ids(errors) == ["T-10"]
    assert "needs a PAN" in errors[0].message


def test_T10_invalid_status_without_pan_rejected():
    assert ids(dd(None, "invalid", "company")[0]) == ["T-10"]


def test_T10_missing_status_with_pan_rejected():
    errors, _ = dd("ABCPE1234F", "missing", "individual")
    assert ids(errors) == ["T-10"]
    assert "must not carry a PAN" in errors[0].message


def test_T10_applied_for_with_pan_rejected():
    assert ids(dd("ABCPE1234F", "applied_for", "individual")[0]) == ["T-10"]


def test_T10_missing_and_applied_for_without_pan_pass():
    assert dd(None, "missing", "company") == ([], [])
    assert dd(None, "applied_for", "huf") == ([], [])


def test_T10_bad_pan_format_rejected():
    for bad in ("ABCPE12345", "ABCP1234FF", "abcpe1234f", "ABCPE1234", "ABCPE1234F1"):
        errors, _ = dd(bad, "valid", "individual")
        assert ids(errors) == ["T-10"], bad
        assert "AAAAA9999A" in errors[0].message


def test_T10_unknown_status_and_unknown_type_rejected():
    assert ids(dd(None, "pending", "company")[0]) == ["T-10"]
    assert ids(dd(None, "missing", "partnership")[0]) == ["T-09"]


# ---- T-11 fourth letter vs deductee type (warning, never an error) ---------------------------------------------


def test_T11_fourth_letter_fits_type_no_warning():
    for pan, dtype in (("ABCPE1234F", "individual"), ("ABCHE1234F", "huf"), ("ABCCE1234F", "company"),
                       ("ABCFE1234F", "firm"), ("ABCFE1234F", "llp"), ("ABCAE1234F", "aop_boi"),
                       ("ABCBE1234F", "aop_boi"), ("ABCTE1234F", "trust"), ("ABCLE1234F", "local_authority")):
        assert dd(pan, "valid", dtype) == ([], []), pan


def test_T11_mismatch_is_a_warning_not_an_error():
    errors, warnings = dd("ABCCE1234F", "valid", "individual")
    assert errors == []
    assert ids(warnings) == ["T-11"]
    assert "4th letter 'C'" in warnings[0].message and "individual" in warnings[0].message


def test_T11_type_other_never_warns_and_unknown_letter_warns_for_named_types():
    assert dd("ABCZE1234F", "valid", "other") == ([], [])
    assert ids(dd("ABCZE1234F", "valid", "company")[1]) == ["T-11"]


def test_T11_invalid_status_pan_is_still_checked_for_letter():
    assert ids(dd("ABCCE1234F", "invalid", "individual")[1]) == ["T-11"]


# ---- T-30 TAN ---------------------------------------------------------------------------------------------------


def test_T30_tan_format():
    assert validate_tan("MUMS12345A") == []
    for bad in ("MUMS1234A", "MUM12345AA", "mums12345a", "MUMS12345", ""):
        assert ids(validate_tan(bad)) == ["T-30"], bad


# ---- T-12 certificate (master side) -----------------------------------------------------------------------------


def cert(**kw):
    args = {"certificate_no": "LDC/1", "rate": Decimal(1), "max_amount": Decimal("500000.00"),
            "valid_from": date(2026, 4, 1), "valid_to": date(2027, 3, 31)}
    args.update(kw)
    return validate_certificate(**args)


def test_T12_good_certificate_and_nil_certificate_pass():
    assert cert() == []
    assert cert(rate=Decimal(0)) == []


def test_T12_blank_number_rejected():
    assert ids(cert(certificate_no="  ")) == ["T-12"]


def test_T12_rate_out_of_range_or_too_many_decimals():
    assert ids(cert(rate=Decimal(-1))) == ["T-12"]
    assert ids(cert(rate=Decimal("100.5"))) == ["T-12"]
    assert ids(cert(rate=Decimal("1.00001"))) == ["T-12"]
    assert cert(rate=Decimal("0.5555")) == []


def test_T12_max_amount_must_be_positive_two_decimals():
    assert ids(cert(max_amount=Decimal(0))) == ["T-12"]
    assert ids(cert(max_amount=Decimal("100.005"))) == ["T-12"]


def test_T12_validity_to_before_from_rejected():
    errors = cert(valid_from=date(2026, 4, 1), valid_to=date(2026, 3, 31))
    assert ids(errors) == ["T-12"]
    assert "01-04-2026" in errors[0].message and "31-03-2026" in errors[0].message


def test_T12_available_amount_never_negative():
    assert available_amount(Decimal("500000.00"), Decimal("200000.00")) == Decimal("300000.00")
    assert available_amount(Decimal("100.00"), Decimal("150.00")) == Decimal("0.00")


# ---- T-14 ledger roles -------------------------------------------------------------------------------------------


def L(name, group, active=True, client=C):
    return Ledger(name, name, group, active, client)


def roles(entries, ledgers, natures=None):
    return validate_ledger_roles(entries, ledgers, GROUPS, C, natures or {"contractor": "tds", "tcs_scrap": "tcs"})


def test_T14_right_groups_pass():
    entries = [("tds_payable", None, "tp"), ("tds_payable", "contractor", "tp194c"),
               ("tcs_payable", None, "tcsp"), ("tds_receivable", None, "tr"), ("tcs_receivable", None, "tcr"),
               ("interest_expense", None, "ie"), ("late_fee_expense", None, "ie")]
    ledgers = {"tp": L("tp", "duties_taxes"), "tp194c": L("tp194c", "duties_taxes"), "tcsp": L("tcsp", "duties_taxes"),
               "tr": L("tr", "loans_advances_asset"), "tcr": L("tcr", "current_assets"),
               "ie": L("ie", "indirect_expenses")}
    assert roles(entries, ledgers) == []


def test_T14_payable_under_wrong_group_rejected():
    errors = roles([("tds_payable", None, "x")], {"x": L("x", "indirect_expenses")})
    assert ids(errors) == ["T-14"]
    assert "Duties & Taxes" in errors[0].message


def test_T14_receivable_and_expense_wrong_group_rejected():
    errors = roles([("tds_receivable", None, "a"), ("interest_expense", None, "b")],
                   {"a": L("a", "duties_taxes"), "b": L("b", "duties_taxes")})
    assert ids(errors) == ["T-14", "T-14"]


def test_T14_missing_other_client_or_inactive_ledger_rejected():
    errors = roles([("tds_payable", None, "gone"), ("tds_payable", "contractor", "o"), ("tcs_payable", None, "i")],
                   {"o": L("o", "duties_taxes", client="client-2"), "i": L("i", "duties_taxes", active=False)})
    assert ids(errors) == ["T-14", "T-14", "T-14"]
    assert "inactive" in errors[2].message


def test_T14_unknown_role_unknown_nature_and_kind_mismatch_rejected():
    ledgers = {"t": L("t", "duties_taxes")}
    assert ids(roles([("tds_basket", None, "t")], ledgers)) == ["T-14"]
    assert ids(roles([("tds_payable", "nosuch", "t")], ledgers)) == ["T-14"]
    assert ids(roles([("tds_payable", "tcs_scrap", "t")], ledgers)) == ["T-14"]   # TCS nature on a TDS role
    assert ids(roles([("tcs_payable", "contractor", "t")], ledgers)) == ["T-14"]  # TDS nature on a TCS role


def test_T14_nature_on_a_role_without_nature_rejected_and_duplicates_rejected():
    ledgers = {"t": L("t", "duties_taxes"), "e": L("e", "indirect_expenses")}
    assert ids(roles([("interest_expense", "contractor", "e")], ledgers)) == ["T-14"]
    dup = roles([("tds_payable", None, "t"), ("tds_payable", None, "t")], ledgers)
    assert ids(dup) == ["T-14"] and "twice" in dup[0].message
