import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from pack_loader import KNOWN_GROUPS, PackError, load_pack

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / "docs" / "test-packs" / "_template"


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    """A fresh, valid copy of the template that a test can break."""
    target = tmp_path / "pack"
    shutil.copytree(TEMPLATE, target)
    return target


def edit(folder: Path, name: str, old: str, new: str) -> None:
    path = folder / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"test setup: {old!r} not found in {name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def problems(folder: Path) -> list[str]:
    with pytest.raises(PackError) as info:
        load_pack(folder)
    return [str(i) for i in info.value.issues]


def assert_one_problem(folder: Path, *fragments: str) -> None:
    found = problems(folder)
    assert len(found) == 1, found
    for fragment in fragments:
        assert fragment in found[0], found[0]


# ------------------------------------------------------------------ the template itself


def test_template_pack_loads_with_literal_expected_values():
    pack = load_pack(TEMPLATE)
    assert pack.client.name == "Template Client"
    assert len(pack.ledgers) == 6
    assert len(pack.vouchers) == 6
    assert {v.ref_id for v in pack.vouchers} == {"V01", "V02", "V03"}
    assert len(pack.invalid_vouchers) == 10
    assert pack.expected_tb_total == (Decimal("60000.00"), Decimal("60000.00"))
    cash = next(b for b in pack.expected_balances if b.ledger_name == "Cash")
    assert (cash.closing_dr, cash.closing_cr) == (Decimal("5000.00"), Decimal("0.00"))


def test_known_groups_match_the_groups_table_in_claude_md():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    section = text.split("### Account groups", 1)[1].split("### Voucher types", 1)[0]
    rows = re.findall(r"^\| ([^|]+?) \| [^|]+ \| [^|]+ \| [^|]+ \|$", section, re.MULTILINE)
    names = {r for r in rows if r not in ("Group", "---")}
    assert names == set(KNOWN_GROUPS)


# ------------------------------------------------------------------ required files


def test_missing_folder():
    assert "does not exist" in problems(Path("no/such/folder"))[0]


@pytest.mark.parametrize(
    "name",
    ["client.yaml", "ledgers.csv", "vouchers.csv", "invalid_vouchers.csv",
     "expected_ledger_balances.csv", "expected_trial_balance.csv", "SIGNOFF.md"],
)
def test_every_required_file_is_checked(pack_dir, name):
    (pack_dir / name).unlink()
    found = problems(pack_dir)
    assert any(f"{name}: file is missing" in p for p in found), found


# ------------------------------------------------------------------ client.yaml


def test_client_bad_entity_type(pack_dir):
    edit(pack_dir, "client.yaml", "proprietorship", "sole trader")
    assert_one_problem(pack_dir, "client.yaml", "entity_type", "sole trader")


def test_client_fy_start_must_be_1_april(pack_dir):
    edit(pack_dir, "client.yaml", "fy_start: 2026-04-01", "fy_start: 2026-01-01")
    assert_one_problem(pack_dir, "fy_start", "1 April")


def test_client_pack_end_date_outside_the_year(pack_dir):
    edit(pack_dir, "client.yaml", "pack_end_date: 2026-04-30", "pack_end_date: 2027-04-30")
    assert_one_problem(pack_dir, "pack_end_date", "financial year")


def test_client_missing_key(pack_dir):
    edit(pack_dir, "client.yaml", "gst_type: regular", "")
    assert_one_problem(pack_dir, "'gst_type' is missing")


# ------------------------------------------------------------------ ledgers.csv


def test_ledgers_unknown_group(pack_dir):
    edit(pack_dir, "ledgers.csv", "Indirect Expenses", "Misc Expenses")
    found = problems(pack_dir)
    assert any("ledgers.csv row 7" in p and "unknown group 'Misc Expenses'" in p for p in found), found


def test_ledgers_duplicate_name_ignoring_case(pack_dir):
    edit(pack_dir, "ledgers.csv", "Rent,", "cash,")
    found = problems(pack_dir)
    assert any("ledgers.csv row 7" in p and "duplicate ledger 'cash'" in p for p in found), found


def test_ledgers_opening_balances_must_balance(pack_dir):
    edit(pack_dir, "ledgers.csv", "Cash,Cash-in-hand,10000.00", "Cash,Cash-in-hand,11000.00")
    found = problems(pack_dir)
    assert any(
        "opening balances do not balance" in p and "Dr 51000.00" in p and "Cr 50000.00" in p
        for p in found
    ), found


def test_ledgers_amount_with_comma_or_one_decimal_is_rejected(pack_dir):
    edit(pack_dir, "ledgers.csv", "HDFC Bank,Bank Accounts,40000.00,0.00", 'HDFC Bank,Bank Accounts,"40,000.00",0.0')
    found = problems(pack_dir)
    assert any("ledgers.csv row 3" in p and "2 decimals" in p for p in found), found


# ------------------------------------------------------------------ vouchers.csv


def test_voucher_unknown_ledger_names_the_row(pack_dir):
    edit(pack_dir, "vouchers.csv", "V03,2026-04-15,payment,Rent,", "V03,2026-04-15,payment,Rentt,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 6" in p and "unknown ledger 'Rentt'" in p for p in found), found


def test_voucher_ledger_name_is_case_sensitive(pack_dir):
    edit(pack_dir, "vouchers.csv", "V03,2026-04-15,payment,Cash,", "V03,2026-04-15,payment,cash,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 7" in p and "unknown ledger 'cash'" in p for p in found), found


@pytest.mark.parametrize("bad_date", ["2026-02-30", "15/04/2026", "2026-4-15"])
def test_voucher_bad_date(pack_dir, bad_date):
    edit(pack_dir, "vouchers.csv", "V03,2026-04-15,payment,Rent,", f"V03,{bad_date},payment,Rent,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 6" in p and "real date as YYYY-MM-DD" in p for p in found), found


def test_voucher_date_outside_pack_period(pack_dir):
    edit(pack_dir, "vouchers.csv", "V03,2026-04-15,payment,Rent,", "V03,2026-05-15,payment,Rent,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 6" in p and "outside the pack period" in p for p in found), found


def test_valid_voucher_file_must_not_contain_an_unbalanced_voucher(pack_dir):
    edit(pack_dir, "vouchers.csv", "Cash,0.00,5000.00", "Cash,0.00,4000.00")
    found = problems(pack_dir)
    assert any("voucher V03 is not balanced" in p for p in found), found


def test_voucher_unknown_type(pack_dir):
    edit(pack_dir, "vouchers.csv", "V03,2026-04-15,payment,Rent,", "V03,2026-04-15,expense,Rent,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 6" in p and "voucher_type" in p for p in found), found


def test_voucher_line_with_both_debit_and_credit_is_a_pack_error(pack_dir):
    edit(pack_dir, "vouchers.csv", "Rent,5000.00,0.00", "Rent,5000.00,100.00")
    found = problems(pack_dir)
    assert any("vouchers.csv row 6" in p and "exactly one of debit / credit" in p for p in found), found


def test_voucher_lines_of_one_ref_must_share_date(pack_dir):
    edit(pack_dir, "vouchers.csv", "V03,2026-04-15,payment,Cash,", "V03,2026-04-16,payment,Cash,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 7" in p and "date differs" in p for p in found), found


def test_wrong_header_is_reported(pack_dir):
    edit(pack_dir, "vouchers.csv", "narration,reference_no", "remarks,reference_no")
    found = problems(pack_dir)
    assert any("vouchers.csv row 1" in p and "header must be exactly" in p for p in found), found


# ------------------------------------------------------------------ invalid_vouchers.csv


def test_invalid_vouchers_may_have_bad_amounts_unknown_ledgers_and_no_narration(pack_dir):
    with (pack_dir / "invalid_vouchers.csv").open("a", encoding="utf-8") as handle:
        handle.write("X08,2026-04-20,journal,No Such Ledger,-5.00,0.00,,,,V-05,exist\n")
        handle.write("X08,2026-04-20,journal,Rent,0.00,abc,,,,V-05,exist\n")
    pack = load_pack(pack_dir)
    assert len(pack.invalid_vouchers) == 12


def test_invalid_vouchers_need_a_real_rule_id(pack_dir):
    edit(pack_dir, "invalid_vouchers.csv", "V-09,narration", "V-99,narration")
    found = problems(pack_dir)
    assert any("invalid_vouchers.csv row 4" in p and "V-01 .. V-14" in p for p in found), found


def test_invalid_vouchers_need_an_expected_message_word(pack_dir):
    edit(pack_dir, "invalid_vouchers.csv", "V-03,decimal", "V-03,")
    found = problems(pack_dir)
    assert any("expected_message_contains is empty" in p for p in found), found


def test_invalid_voucher_lines_must_agree_on_expectation(pack_dir):
    edit(pack_dir, "invalid_vouchers.csv", "4000.00,Rent debit is more than cash credit,,,V-04,equal",
         "4000.00,Rent debit is more than cash credit,,,V-02,equal")
    found = problems(pack_dir)
    assert any("voucher X01" in p and "same expected_rule_id" in p for p in found), found


# ------------------------------------------------------------------ expected files


def test_expected_balance_for_unknown_ledger(pack_dir):
    edit(pack_dir, "expected_ledger_balances.csv", "Rent,5000.00", "Rentt,5000.00")
    found = problems(pack_dir)
    assert any("expected_ledger_balances.csv row 7" in p and "unknown ledger 'Rentt'" in p for p in found)


def test_expected_balances_must_list_every_ledger(pack_dir):
    edit(pack_dir, "expected_ledger_balances.csv", "Rent,5000.00,0.00\n", "")
    found = problems(pack_dir)
    assert any("every ledger must be listed" in p and "Rent" in p for p in found), found


def test_expected_trial_balance_that_does_not_balance(pack_dir):
    edit(pack_dir, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,60000.00,59000.00")
    found = problems(pack_dir)
    assert any("not balanced" in p and "60000.00" in p and "59000.00" in p for p in found), found


def test_expected_trial_balance_total_must_equal_the_lines(pack_dir):
    edit(pack_dir, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,61000.00,61000.00")
    found = problems(pack_dir)
    assert any("does not equal the sum of the lines" in p for p in found), found


def test_expected_trial_balance_needs_a_total_row(pack_dir):
    edit(pack_dir, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00\n", "")
    found = problems(pack_dir)
    assert any("TOTAL row is missing" in p for p in found), found


def test_expected_trial_balance_must_agree_with_ledger_balances(pack_dir):
    edit(pack_dir, "expected_trial_balance.csv", "Cash,5000.00,0.00", "Cash,4000.00,0.00")
    found = problems(pack_dir)
    assert any("expected_trial_balance.csv row 2" in p and "expected_ledger_balances.csv" in p for p in found)


def test_expected_trial_balance_group_must_match_ledgers_csv(pack_dir):
    edit(pack_dir, "expected_trial_balance.csv", "Sales Accounts,Sales", "Direct Incomes,Sales")
    found = problems(pack_dir)
    assert any("does not match ledgers.csv" in p for p in found), found


# ------------------------------------------------------------------ reporting


def test_all_problems_are_reported_together_not_just_the_first(pack_dir):
    edit(pack_dir, "client.yaml", "proprietorship", "sole trader")
    edit(pack_dir, "vouchers.csv", "Rent,5000.00", "Rentt,5000.00")
    edit(pack_dir, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,60000.00,59000.00")
    assert len(problems(pack_dir)) >= 3


# ------------------------------------------------------------------ party_ledger column


def test_party_ledger_must_be_a_ledger_of_the_pack(pack_dir):
    edit(pack_dir, "vouchers.csv", "INV-001,Rahul Enterprises\nV01", "INV-001,Rahul Enterprisez\nV01")
    found = problems(pack_dir)
    assert any("vouchers.csv row 2" in p and "unknown party_ledger 'Rahul Enterprisez'" in p for p in found), found


def test_party_ledger_of_a_valid_voucher_must_be_one_of_its_lines(pack_dir):
    # V03 is a payment from Cash to Rent: naming Rahul Enterprises as its party breaks V-13
    for old, new in (("5000.00,0.00,April shop rent paid in cash,,", "5000.00,0.00,April shop rent paid in cash,,Rahul Enterprises"),
                     ("0.00,5000.00,April shop rent paid in cash,,", "0.00,5000.00,April shop rent paid in cash,,Rahul Enterprises")):
        edit(pack_dir, "vouchers.csv", old, new)
    found = problems(pack_dir)
    assert any("voucher V03: party_ledger 'Rahul Enterprises' is not one of the voucher's lines" in p for p in found), found


def test_party_ledger_must_be_the_same_on_every_line_of_a_voucher(pack_dir):
    edit(pack_dir, "vouchers.csv", "Sales,0.00,10000.00,Goods sold to Rahul Enterprises,INV-001,Rahul Enterprises",
         "Sales,0.00,10000.00,Goods sold to Rahul Enterprises,INV-001,")
    found = problems(pack_dir)
    assert any("vouchers.csv row 3" in p and "party_ledger differs" in p for p in found), found


def test_invalid_vouchers_may_name_any_party_ledger_even_one_that_does_not_exist(pack_dir):
    with (pack_dir / "invalid_vouchers.csv").open("a", encoding="utf-8") as handle:
        handle.write("X08,2026-04-20,sales,Cash,5.00,0.00,Unknown party,INV-9,Nobody At All,V-05,party\n")
        handle.write("X08,2026-04-20,sales,Sales,0.00,5.00,Unknown party,INV-9,Nobody At All,V-05,party\n")
    pack = load_pack(pack_dir)
    assert pack.invalid_vouchers[-1].party_ledger == "Nobody At All"


def test_old_pack_without_the_party_ledger_column_is_reported(pack_dir):
    edit(pack_dir, "vouchers.csv", "narration,reference_no,party_ledger", "narration,reference_no")
    found = problems(pack_dir)
    assert any("vouchers.csv row 1" in p and "header must be exactly" in p and "party_ledger" in p for p in found), found


# ------------------------------------------------------------------ client.yaml: proprietor_name / partners


def test_template_client_has_the_proprietor(pack_dir):
    pack = load_pack(pack_dir)
    assert (pack.client.proprietor_name, pack.client.partners) == ("Owner", ())


def test_proprietorship_needs_the_proprietor_name(pack_dir):
    edit(pack_dir, "client.yaml", "proprietor_name: Owner", "")
    assert_one_problem(pack_dir, "client.yaml", "'proprietor_name' is required for a proprietorship")


def test_partnership_needs_partners_and_a_list_of_names(pack_dir):
    edit(pack_dir, "client.yaml", "proprietorship ", "partnership    ")
    assert_one_problem(pack_dir, "'partners' is required for a partnership or LLP")
    with (pack_dir / "client.yaml").open("a", encoding="utf-8") as handle:
        handle.write("partners: [Anil Shah, Bina Shah]\n")
    pack = load_pack(pack_dir)
    assert pack.client.partners == ("Anil Shah", "Bina Shah")


@pytest.mark.parametrize("bad", ["partners: Anil Shah", "partners: [Anil Shah, 5]", "partners: [Anil Shah, anil shah]"])
def test_partners_must_be_different_names_in_a_list(pack_dir, bad):
    edit(pack_dir, "client.yaml", "proprietorship ", "partnership    ")
    with (pack_dir / "client.yaml").open("a", encoding="utf-8") as handle:
        handle.write(bad + "\n")
    found = problems(pack_dir)
    assert any("'partners'" in p for p in found), found


# ------------------------------------------------------------------ reversals.csv


def add_file(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def test_reversals_are_loaded(pack_dir):
    add_file(pack_dir, "reversals.csv", "ref_id,reversal_date,reason\nV03,2026-04-20,Booked in the wrong month\n")
    pack = load_pack(pack_dir)
    assert [(r.row, r.ref_id, r.reversal_date.isoformat(), r.reason) for r in pack.reversals] == [
        (2, "V03", "2026-04-20", "Booked in the wrong month")
    ]


def test_pack_without_optional_files_has_no_reversals_or_locked_periods(pack_dir):
    pack = load_pack(pack_dir)
    assert pack.reversals == () and pack.locked_periods == ()


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("V99,2026-04-20,why", "'V99' is not a voucher of vouchers.csv"),
        ("V03,2026-04-31,why", "real date as YYYY-MM-DD"),
        ("V03,2026-05-02,why", "outside the pack period"),
        ("V03,2026-04-20,", "reason is empty"),
    ],
)
def test_bad_reversal_rows_are_reported_with_the_row(pack_dir, row, message):
    add_file(pack_dir, "reversals.csv", f"ref_id,reversal_date,reason\n{row}\n")
    found = problems(pack_dir)
    assert any("reversals.csv row 2" in p and message in p for p in found), found


def test_a_voucher_cannot_be_reversed_twice(pack_dir):
    add_file(pack_dir, "reversals.csv", "ref_id,reversal_date,reason\nV03,2026-04-20,a\nV03,2026-04-21,b\n")
    found = problems(pack_dir)
    assert any("reversals.csv row 3" in p and "reversed twice" in p for p in found), found


# ------------------------------------------------------------------ locked_periods.csv


def test_locked_periods_are_loaded(pack_dir):
    add_file(pack_dir, "locked_periods.csv", "month\n2026-05\n2026-06\n")
    assert load_pack(pack_dir).locked_periods == ("2026-05", "2026-06")


@pytest.mark.parametrize(
    ("month", "message"),
    [("2026-13", "month must be YYYY-MM"), ("May 2026", "month must be YYYY-MM"), ("2025-03", "outside the financial year"),
     ("2027-04", "outside the financial year")],
)
def test_bad_locked_months_are_reported(pack_dir, month, message):
    add_file(pack_dir, "locked_periods.csv", f"month\n{month}\n")
    found = problems(pack_dir)
    assert any("locked_periods.csv row 2" in p and message in p for p in found), found


def test_a_month_cannot_be_listed_twice(pack_dir):
    add_file(pack_dir, "locked_periods.csv", "month\n2026-05\n2026-05\n")
    assert any("listed twice" in p for p in problems(pack_dir))
