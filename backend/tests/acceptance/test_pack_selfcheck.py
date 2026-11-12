"""balance_warnings: warning-only recomputation of closing balances from a pack's own files."""

import hashlib
import shutil
from pathlib import Path

import pytest
from pack_loader import balance_warnings, load_pack

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / "docs" / "test-packs" / "_template"


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(TEMPLATE, target)
    return target


def edit(folder: Path, name: str, old: str, new: str) -> None:
    path = folder / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def fingerprints(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


def test_template_has_no_warnings():
    assert balance_warnings(load_pack(TEMPLATE)) == []


def break_cash_and_capital(folder: Path) -> None:
    """Cash 5000.00 Dr -> 4000.00 Dr and Capital 50000.00 Cr -> 49000.00 Cr, in step in both expected files
    so the expected Trial Balance still balances (59000.00 = 59000.00) and the pack still loads."""
    for name in ("expected_ledger_balances.csv", "expected_trial_balance.csv"):
        edit(folder, name, "Cash,5000.00,0.00", "Cash,4000.00,0.00")
        edit(folder, name, "Owner Capital A/c,0.00,50000.00", "Owner Capital A/c,0.00,49000.00")
    edit(folder, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,59000.00,59000.00")


def test_a_wrong_expected_balance_is_reported_for_that_ledger_only(pack_dir):
    # hand check: Cash = 10000.00 opening - 5000.00 rent paid = 5000.00 Dr; Capital stays 50000.00 Cr
    break_cash_and_capital(pack_dir)
    assert balance_warnings(load_pack(pack_dir)) == [
        ("expected_ledger_balances.csv: 'Cash' is Dr 4000.00 there, but ledgers.csv + vouchers.csv give "
        "Dr 5000.00 (difference 1000.00)"),
        ("expected_ledger_balances.csv: 'Owner Capital A/c' is Cr 49000.00 there, but ledgers.csv + "
        "vouchers.csv give Cr 50000.00 (difference 1000.00)"),
    ]


def test_wrong_side_is_reported_with_both_sides(pack_dir):
    # hand check: Rahul = 10000.00 sale - 6000.00 receipt = 4000.00 Dr. Pack says 4000.00 Cr; to keep the
    # expected TB balanced the pack also moves Sales from 10000.00 Cr to 2000.00 Cr (Dr 56000 = Cr 50000 + 2000 + 4000).
    for name in ("expected_ledger_balances.csv", "expected_trial_balance.csv"):
        edit(pack_dir, name, "Rahul Enterprises,4000.00,0.00", "Rahul Enterprises,0.00,4000.00")
    edit(pack_dir, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,56000.00,56000.00")
    for name in ("expected_ledger_balances.csv", "expected_trial_balance.csv"):
        edit(pack_dir, name, "Sales,0.00,10000.00", "Sales,0.00,2000.00")
    assert balance_warnings(load_pack(pack_dir)) == [
        ("expected_ledger_balances.csv: 'Rahul Enterprises' is Cr 4000.00 there, but ledgers.csv + "
        "vouchers.csv give Dr 4000.00 (difference 8000.00)"),
        ("expected_ledger_balances.csv: 'Sales' is Cr 2000.00 there, but ledgers.csv + vouchers.csv give "
        "Cr 10000.00 (difference 8000.00)"),
    ]


def test_invalid_vouchers_are_ignored(pack_dir):
    with (pack_dir / "invalid_vouchers.csv").open("a", encoding="utf-8") as handle:
        handle.write("X09,2026-04-20,receipt,Cash,9999.00,0.00,Should never count,,,V-04,equal\n")
        handle.write("X09,2026-04-20,receipt,Rent,0.00,1.00,Should never count,,,V-04,equal\n")
    assert balance_warnings(load_pack(pack_dir)) == []


def test_a_voucher_missing_from_vouchers_csv_shows_up(pack_dir):
    # drop V03 (rent 5000.00 paid in cash): Cash would stay 10000.00 Dr and Rent would be nil
    lines = (pack_dir / "vouchers.csv").read_text(encoding="utf-8").splitlines(keepends=True)
    (pack_dir / "vouchers.csv").write_text("".join(x for x in lines if not x.startswith("V03")), encoding="utf-8")
    assert balance_warnings(load_pack(pack_dir)) == [
        ("expected_ledger_balances.csv: 'Cash' is Dr 5000.00 there, but ledgers.csv + vouchers.csv give "
        "Dr 10000.00 (difference 5000.00)"),
        ("expected_ledger_balances.csv: 'Rent' is Dr 5000.00 there, but ledgers.csv + vouchers.csv give "
        "nil (difference 5000.00)"),
    ]


def test_the_self_check_never_modifies_any_pack_file(pack_dir):
    break_cash_and_capital(pack_dir)
    before = fingerprints(pack_dir)
    assert len(balance_warnings(load_pack(pack_dir))) == 2
    assert fingerprints(pack_dir) == before


def test_a_reversed_voucher_and_its_mirror_cancel_out_in_the_self_check(pack_dir):
    # V03 (rent 5000.00 paid in cash) is reversed: Cash stays 10000.00 and Rent stays nil
    (pack_dir / "reversals.csv").write_text("ref_id,reversal_date,reason\nV03,2026-04-20,Booked in error\n", encoding="utf-8")
    for name in ("expected_ledger_balances.csv", "expected_trial_balance.csv"):
        edit(pack_dir, name, "Cash,5000.00,0.00", "Cash,10000.00,0.00")
        edit(pack_dir, name, "Rent,5000.00,0.00", "Rent,0.00,0.00")
    edit(pack_dir, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,60000.00,60000.00")
    assert balance_warnings(load_pack(pack_dir)) == []
