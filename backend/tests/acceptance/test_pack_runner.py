"""Step 1.10: every test pack against the real services. A pack passes only when the tool matches the accountants'
expected answers to the paisa and rejects every wrong voucher with the promised rule.

On a difference the failure message is the report for the accountants (ledger, expected, tool). The runner never
changes a pack file: when the tool and the pack disagree the accountants decide which is right.
"""

import shutil
import warnings
from pathlib import Path

import pytest
from pack_loader import load_pack
from pack_runner import format_report, run_pack

pytestmark = pytest.mark.integration

PACKS_DIR = Path(__file__).resolve().parents[3] / "docs" / "test-packs"
# the template included: it must pass too. Phase 2 packs (they have allocations.csv) run in test_pack_runner_p2.py, Phase 3 packs (gst_registrations.csv) in test_pack_runner_p3.py
PACKS = sorted(
    p for p in PACKS_DIR.iterdir()
    if p.is_dir() and not (p / "allocations.csv").exists() and not (p / "gst_registrations.csv").exists()
)


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.name)
def test_pack_matches_the_expected_answers_to_the_paisa(svc_conn, pack_dir):
    pack = load_pack(pack_dir)
    report = run_pack(svc_conn, pack)
    for warning in report.warnings:
        warnings.warn(f"{pack_dir.name}: pack self-check: {warning}", stacklevel=1)  # warning only
    assert report.problems == [], "\n" + format_report(report)
    assert report.posted == len({v.ref_id for v in pack.vouchers})
    assert report.reversed == len(pack.reversals)
    assert report.wrong_checked == len({v.ref_id for v in pack.invalid_vouchers})


# ------------------------------------------------------------------ the runner is not vacuous


@pytest.fixture
def template_copy(tmp_path):
    target = tmp_path / "pack"
    shutil.copytree(PACKS_DIR / "_template", target)
    return target


def edit(folder: Path, name: str, old: str, new: str) -> None:
    path = folder / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_a_wrong_expected_balance_is_reported_ledger_by_ledger_and_never_corrected(svc_conn, template_copy):
    # Cash really closes at 5,000.00 Dr (10,000 opening - 5,000 rent). The "accountants" wrote 4,000 and moved
    # 1,000 off the Capital so that their own Trial Balance still adds up.
    for name in ("expected_ledger_balances.csv", "expected_trial_balance.csv"):
        edit(template_copy, name, "Cash,5000.00,0.00", "Cash,4000.00,0.00")
        edit(template_copy, name, "Owner Capital A/c,0.00,50000.00", "Owner Capital A/c,0.00,49000.00")
    edit(template_copy, "expected_trial_balance.csv", "TOTAL,,60000.00,60000.00", "TOTAL,,59000.00,59000.00")
    before = (template_copy / "expected_ledger_balances.csv").read_bytes()

    report = run_pack(svc_conn, load_pack(template_copy))

    assert report.problems == [
        "Cash: expected Dr 4,000.00, tool says Dr 5,000.00 (difference 1,000.00)",
        "Owner Capital A/c: expected Cr 49,000.00, tool says Cr 50,000.00 (difference 1,000.00)",
        "Trial Balance line Cash: expected Dr 4,000.00, tool says Dr 5,000.00 (difference 1,000.00)",
        "Trial Balance line Owner Capital A/c: expected Cr 49,000.00, tool says Cr 50,000.00 (difference 1,000.00)",
        "Trial Balance totals: expected Dr 59,000.00 / Cr 59,000.00, tool says Dr 60,000.00 / Cr 60,000.00",
    ]
    assert len(report.warnings) == 2  # the pack's own self-check noticed the same two ledgers
    assert (template_copy / "expected_ledger_balances.csv").read_bytes() == before  # never modified


def test_a_wrong_voucher_that_the_tool_rejects_for_another_reason_is_reported(svc_conn, template_copy):
    for _ in range(2):  # both lines of X01 (really unbalanced: V-04) carry the promise
        edit(template_copy, "invalid_vouchers.csv", ",,V-04,equal", ",,V-09,equal")
    report = run_pack(svc_conn, load_pack(template_copy))
    assert len(report.problems) == 1
    assert report.problems[0].startswith("wrong voucher X01: expected rule V-09, the tool reported V-04: Debit 5,000.00 and Credit 4,000.00 are not equal")


def test_a_wrong_voucher_that_the_tool_accepts_is_reported_as_accepted(svc_conn, template_copy):
    # X01 made correct (credit 5000.00): the tool accepts it, so the pack's promise of V-04 is broken
    edit(template_copy, "invalid_vouchers.csv", "Cash,0.00,4000.00,Rent debit is more than cash credit",
         "Cash,0.00,5000.00,Rent debit is more than cash credit")
    report = run_pack(svc_conn, load_pack(template_copy))
    assert any(p == "wrong voucher X01 (expected V-04) was ACCEPTED and saved as a draft" for p in report.problems), report.problems
