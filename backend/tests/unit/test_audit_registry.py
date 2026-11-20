"""Phase 8 package A: the check registry, run parameters, summary and report assembly. Pure: no database. Expected values typed literally."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine import audit_checks_analytic, audit_checks_books, audit_checks_compliance
from app.engine import audit_registry as reg
from app.engine import audit_types as t
from app.services import audit_report

FROM, TO = date(2026, 4, 1), date(2027, 3, 31)


def _finding(check_id="A-12", key="A-12:v1", evidence=None, severity=t.Severity.INFO, **kw):
    return t.Finding(check_id, key, severity, "voucher", "SAL/2026-27/0001", "Round total 50,000.00",
                     {"voucher_ids": ["v1"]} if evidence is None else evidence, **kw)


def _facts():
    return reg.AuditFacts(ledgers={}, vouchers=())


def _params():
    return t.AuditParams(FROM, TO)


def test_A00_registry_merges_the_three_check_modules(monkeypatch):
    def f1(facts, params, rules):
        return t.CheckResult("A-12")

    monkeypatch.setattr(audit_checks_books, "CHECKS", {"A-12": f1})
    monkeypatch.setattr(audit_checks_compliance, "CHECKS", {"A-09": f1})
    monkeypatch.setattr(audit_checks_analytic, "CHECKS", {"A-15": f1})
    assert sorted(reg.all_checks()) == ["A-09", "A-12", "A-15"]
    assert reg.module_of("A-09") == "compliance"


def test_A00_registry_refuses_a_duplicate_or_unknown_check_id(monkeypatch):
    def f1(facts, params, rules):
        return t.CheckResult("A-12")

    monkeypatch.setattr(audit_checks_books, "CHECKS", {"A-12": f1})
    monkeypatch.setattr(audit_checks_analytic, "CHECKS", {"A-12": f1})
    with pytest.raises(ValueError, match="A-12 is registered twice"):
        reg.all_checks()
    monkeypatch.setattr(audit_checks_analytic, "CHECKS", {"A-99": f1})
    with pytest.raises(ValueError, match="A-99 is not in the catalogue"):
        reg.all_checks()


def test_A00_execute_runs_checks_in_id_order_and_isolates_a_failing_check():
    def good(facts, params, rules):
        return t.CheckResult("A-12", findings=(_finding(),), population=("v1", "v2"))

    def boom(facts, params, rules):
        raise RuntimeError("bad data")

    out = reg.execute(["A-13", "A-12", "A-01"], _facts(), _params(), (), checks={"A-12": good, "A-13": boom})
    assert [o.check_id for o in out] == ["A-01", "A-12", "A-13"]
    assert out[0].error == "check A-01 is not available in this build"
    assert out[1].error is None and len(out[1].result.findings) == 1
    assert out[2].result is None and out[2].error == "check A-13 failed: RuntimeError: bad data"


def test_A00_a_finding_without_evidence_makes_the_check_fail_not_the_run():
    def no_evidence(facts, params, rules):
        return t.CheckResult("A-12", findings=(_finding(evidence={}),))

    out = reg.execute(["A-12"], _facts(), _params(), (), checks={"A-12": no_evidence})
    assert out[0].result is None
    assert out[0].error == "check A-12 returned finding A-12:v1 without evidence"


def test_A00_a_finding_of_another_check_or_a_repeated_key_is_refused():
    def other(facts, params, rules):
        return t.CheckResult("A-12", findings=(_finding(check_id="A-13", key="A-13:v1"),))

    def twice(facts, params, rules):
        return t.CheckResult("A-12", findings=(_finding(), _finding()))

    out = reg.execute(["A-12"], _facts(), _params(), (), checks={"A-12": other})
    assert out[0].error == "check A-12 returned finding A-13:v1 that belongs to check A-13"
    out = reg.execute(["A-12"], _facts(), _params(), (), checks={"A-12": twice})
    assert out[0].error == "check A-12 returned finding key A-12:v1 twice"


def test_A00_summary_counts_findings_population_notes_and_errors():
    def good(facts, params, rules):
        return t.CheckResult("A-12", findings=(_finding(), _finding(key="A-12:v2")), population=("v1", "v2", "v3"),
                             notes=("no limit row for 14-08-2026",))

    def err(facts, params, rules):
        raise ValueError("x")

    def review(facts, params, rules):
        return t.CheckResult("A-15", findings=(_finding("A-15", "A-15:l1", severity=t.Severity.REVIEW),))

    out = reg.execute(["A-12", "A-13", "A-15"], _facts(), _params(), (), checks={"A-12": good, "A-13": err, "A-15": review})
    s = reg.build_summary(out)
    assert s["by_check"]["A-12"] == {"findings": 2, "population": 3, "notes": ["no limit row for 14-08-2026"],
                                     "population_ids": ["v1", "v2", "v3"]}
    assert s["by_check"]["A-13"] == {"findings": 0, "population": 0, "notes": [], "error": "check A-13 failed: ValueError: x"}
    assert s["by_severity"] == {"info": 2, "review": 1}
    assert reg.finding_total(out) == 3


def test_A00_params_default_to_the_whole_period_and_the_plan_defaults():
    p = reg.params_from_input(FROM, TO, None)
    assert (p.duplicate_window_days, p.round_unit, p.round_min_amount, p.late_posting_days) == (7, Decimal("1000.00"), Decimal("10000.00"), 30)
    assert (p.variance_min_amount, p.variance_band_percent) == (Decimal("100000.00"), Decimal("50.00"))
    assert p.doc_required_types == ("purchase", "payment", "debit_note")


def test_A00_params_accept_overrides_and_reject_anything_unclear():
    p = reg.params_from_input(FROM, TO, {"duplicate_window_days": 3, "round_unit": "500", "doc_required_types": ["purchase"],
                                         "variance_band_percent": "25.5"})
    assert (p.duplicate_window_days, p.round_unit, p.doc_required_types, p.variance_band_percent) == (
        3, Decimal("500.00"), ("purchase",), Decimal("25.50"))
    for bad in ({"round_unit": "10.005"}, {"duplicate_window_days": 0}, {"duplicate_window_days": "x"}, {"colour": 1},
                {"doc_required_types": ["lunch"]}, {"round_unit": "0"}):
        with pytest.raises(ValueError):
            reg.params_from_input(FROM, TO, bad)


def test_A00_params_are_stored_as_plain_json():
    d = reg.params_to_dict(reg.params_from_input(FROM, TO, {"round_unit": "2500"}))
    assert d["from_date"] == "2026-04-01" and d["to_date"] == "2027-03-31"
    assert d["round_unit"] == "2500.00" and d["doc_required_types"] == ["purchase", "payment", "debit_note"]
    assert d["duplicate_window_days"] == 7 and d["sample_seed"] is None


def test_A00_rule_rows_are_stored_with_their_status():
    r = t.LimitRule("cash_payment_daily_limit", "it_act_2025", "section X", Decimal("10000.00"), "above", Decimal("100.00"),
                    date(2026, 4, 1), None, "pending")
    assert reg.rule_to_dict(r) == {
        "rule_key": "cash_payment_daily_limit", "law": "it_act_2025", "section_ref": "section X", "amount": "10000.00",
        "breach_when": "above", "disallow_percent": "100.00", "effective_from": "2026-04-01", "effective_to": None,
        "verification_status": "pending"}


def test_A00_json_safe_turns_money_dates_and_ids_into_text():
    out = audit_report.json_safe({"a": Decimal("11000.5"), "d": date(2026, 8, 14), "t": (1, 2), "n": None})
    assert out == {"a": "11000.50", "d": "2026-08-14", "t": [1, 2], "n": None}


def test_A00_findings_keep_the_rule_status_inside_the_evidence():
    f = _finding("A-05", "A-05:p:2026-08-14", rule_status="pending")
    row = audit_report.finding_row(f)
    assert row["evidence"]["rule"] == {"verification_status": "pending"}
    assert row["evidence"]["voucher_ids"] == ["v1"]
    assert audit_report.rule_status_of({"rule": {"verification_status": "pending"}}) == "pending"
    assert audit_report.rule_status_of({"voucher_ids": ["v1"]}) is None


def _run_row():
    return {"id": "r1", "financial_year_id": "fy", "from_date": "2026-04-01", "to_date": "2027-03-31", "check_ids": ["A-05", "A-12"],
            "status": "completed", "finding_count": 2, "created_by": "tester", "created_at": "2026-11-20T10:00:00",
            "params": {}, "engine_version": "audit-1",
            "rules_used": [{"rule_key": "cash_payment_daily_limit", "law": "it_act_2025", "verification_status": "pending",
                            "section_ref": "section X", "amount": "10000.00"},
                           {"rule_key": "cash_receipt_limit", "law": "it_act_1961", "verification_status": "secondary_verified",
                            "section_ref": "section 269ST", "amount": "200000.00"}],
            "summary": {"by_check": {"A-05": {"findings": 1, "population": 4, "notes": ["limit not available for 01-04-2026"]},
                                     "A-12": {"findings": 1, "population": 9, "notes": []}},
                        "by_severity": {"error": 1, "info": 1}}}


def _findings():
    return [
        {"id": "f1", "check_id": "A-05", "severity": "error", "message": "Cash payments to Sharma Traders", "amount": "11000.00",
         "disallowance_amount": "11000.00", "evidence": {"voucher_ids": ["v1", "v2"], "rule": {"verification_status": "pending"}}},
        {"id": "f2", "check_id": "A-12", "severity": "info", "message": "Round total", "amount": "50000.00",
         "disallowance_amount": None, "evidence": {"voucher_ids": ["v9"]}},
    ]


CATALOGUE = {"A-05": {"title": "Cash payment above the daily limit", "severity": "error"},
             "A-12": {"title": "Round-amount entries", "severity": "info"}}


def test_A00_report_lists_each_check_with_population_findings_and_notes():
    rep = audit_report.assemble_report(_run_row(), _findings(), CATALOGUE)
    assert [c["check_id"] for c in rep["checks"]] == ["A-05", "A-12"]
    a05 = rep["checks"][0]
    assert (a05["title"], a05["population"], len(a05["findings"])) == ("Cash payment above the daily limit", 4, 1)
    assert a05["notes"] == ["limit not available for 01-04-2026"]
    assert a05["findings"][0]["rule_status"] == "pending"
    assert rep["checks"][1]["findings"][0]["rule_status"] is None


def test_A00_report_says_limit_pending_verification_and_totals_the_disallowance():
    rep = audit_report.assemble_report(_run_row(), _findings(), CATALOGUE)
    assert [r["rule_key"] for r in rep["rules_pending"]] == ["cash_payment_daily_limit"]
    assert rep["rules_pending"][0]["line"] == "cash_payment_daily_limit (it_act_2025, section X): limit pending verification"
    assert rep["totals"] == {"findings": 2, "by_severity": {"error": 1, "info": 1}, "disallowance_amount": "11000.00"}


def test_A00_report_shows_a_failed_check_instead_of_hiding_it():
    run = _run_row()
    run["summary"]["by_check"]["A-12"] = {"findings": 0, "population": 0, "notes": [], "error": "check A-12 failed: ValueError: x"}
    rep = audit_report.assemble_report(run, _findings()[:1], CATALOGUE)
    assert rep["checks"][1]["error"] == "check A-12 failed: ValueError: x"


def test_A00_excel_has_a_summary_sheet_then_one_sheet_per_check_with_evidence_columns():
    from io import BytesIO

    from openpyxl import load_workbook

    rep = audit_report.assemble_report(_run_row(), _findings(), CATALOGUE)
    wb = load_workbook(BytesIO(audit_report.report_xlsx(rep)))
    assert wb.sheetnames == ["Summary", "A-05", "A-12"]
    summary = [[c.value for c in row] for row in wb["Summary"].iter_rows()]
    assert any("limit pending verification" in str(c) for row in summary for c in row)
    rows = [[c.value for c in row] for row in wb["A-05"].iter_rows()]
    assert rows[0][:3] == ["Severity", "Amount", "Disallowance"]
    assert "voucher_ids" in rows[0] and rows[1][0] == "error" and rows[1][1] == "11000.00"


def test_A00_audit_services_never_write_to_a_books_table():
    import re

    from app.services.audit_hooks import READ_ONLY_TABLES

    root = Path(__file__).resolve().parents[2] / "app"
    files = [root / "services" / n for n in ("audit_runs.py", "audit_load_common.py", "audit_report.py")] + [root / "db" / "repositories_audit.py"]
    for f in files:
        src = f.read_text(encoding="utf-8")
        for table in READ_ONLY_TABLES:
            assert not re.search(rf"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+{table}\b", src, re.IGNORECASE), (f.name, table)


def test_A00_summary_stores_population_ids_amounts_and_total():
    from decimal import Decimal

    def chk(facts, params, rules):
        return t.CheckResult("A-12", population=("v1", "v2"), population_amount=Decimal("30000.00"),
                             population_amounts={"v1": Decimal("10000.00"), "v2": Decimal("20000.00")})

    s = reg.build_summary(reg.execute(["A-12"], _facts(), _params(), (), checks={"A-12": chk}))
    assert s["by_check"]["A-12"]["population_ids"] == ["v1", "v2"]
    assert s["by_check"]["A-12"]["population_amount"] == "30000.00"
    assert s["by_check"]["A-12"]["population_amounts"] == {"v1": "10000.00", "v2": "20000.00"}
