"""Audit report assembly (Phase 8, package A): plain rows in, JSON report or Excel workbook out. No SQL, no writes, no rules of its own.

The report answers the auditor's questions per check: how many items were examined (population), what was found (with evidence), notes such as
"limit not available for dd-mm-yyyy", and which legal limits were pending verification when the run was made.
"""

import json
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook

from app.engine.audit_types import Finding
from app.engine.money import round_half_up


def json_safe(value: Any) -> Any:
    """Evidence and parameters as plain JSON: money and ids as text, dates ISO, tuples as lists."""
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else round_half_up(value)


def finding_row(f: Finding) -> dict[str, Any]:
    """The columns of an audit_findings row. A legal-limit status travels inside the evidence (`evidence.rule`)."""
    evidence = json_safe(f.evidence)
    if f.rule_status and "rule" not in evidence:
        evidence["rule"] = {"verification_status": f.rule_status}
    return {
        "check_id": f.check_id, "finding_key": f.finding_key, "severity": f.severity.value, "subject_kind": f.subject_kind,
        "subject_id": f.subject_id, "subject_ref": f.subject_ref, "finding_date": f.finding_date, "amount": _money(f.amount),
        "disallowance_amount": _money(f.disallowance_amount), "message": f.message, "evidence": evidence,
    }


def rule_status_of(evidence: Mapping[str, Any]) -> str | None:
    rule = evidence.get("rule")
    if isinstance(rule, Mapping):
        return rule.get("verification_status") or rule.get("status")
    return None


def _pending_line(rule: Mapping[str, Any]) -> str:
    return f"{rule['rule_key']} ({rule['law']}, {rule['section_ref']}): limit pending verification"


def assemble_report(run: Mapping[str, Any], findings: list[Mapping[str, Any]], catalogue: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    summary = run.get("summary") or {}
    by_check = summary.get("by_check", {})
    pending = [{"rule_key": r["rule_key"], "law": r["law"], "section_ref": r["section_ref"], "line": _pending_line(r)}
               for r in run.get("rules_used", []) if r.get("verification_status") == "pending"]
    checks = []
    severity_totals: dict[str, int] = {}
    disallowance = Decimal("0.00")
    for check_id in sorted(run["check_ids"]):
        info = by_check.get(check_id, {})
        rows = []
        for f in (x for x in findings if x["check_id"] == check_id):
            rows.append({**f, "rule_status": rule_status_of(f.get("evidence") or {})})
            severity_totals[f["severity"]] = severity_totals.get(f["severity"], 0) + 1
            if f.get("disallowance_amount") is not None:
                disallowance += Decimal(str(f["disallowance_amount"]))
        entry = {"check_id": check_id, "title": catalogue.get(check_id, {}).get("title", check_id),
                 "severity": catalogue.get(check_id, {}).get("severity"), "population": info.get("population", 0),
                 "findings": rows, "notes": list(info.get("notes", []))}
        if info.get("error"):
            entry["error"] = info["error"]
        checks.append(entry)
    return {
        "run": {k: run.get(k) for k in ("id", "financial_year_id", "from_date", "to_date", "check_ids", "status", "finding_count",
                                        "created_by", "created_at", "params", "engine_version")},
        "rules_pending": pending,
        "checks": checks,
        "totals": {"findings": sum(len(c["findings"]) for c in checks), "by_severity": severity_totals,
                   "disallowance_amount": f"{disallowance:.2f}"},
    }


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int)):
        return value
    safe = json_safe(value)
    return json.dumps(safe) if isinstance(safe, (list, dict)) else str(safe)


def report_xlsx(report: Mapping[str, Any]) -> bytes:
    """One Summary sheet (run, pending limits, per-check counts) and one sheet per check with the evidence keys as columns."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    run = report["run"]
    ws.append(["Audit run", str(run["id"])])
    ws.append(["Period", f"{run['from_date']} to {run['to_date']}"])
    ws.append(["Run by", run["created_by"]])
    ws.append(["Engine", run["engine_version"]])
    ws.append([])
    for p in report["rules_pending"]:
        ws.append([p["line"]])
    if report["rules_pending"]:
        ws.append([])
    ws.append(["Check", "Title", "Examined", "Findings", "Notes"])
    for c in report["checks"]:
        ws.append([c["check_id"], c["title"], c["population"], len(c["findings"]), "; ".join([*c["notes"], *([c["error"]] if c.get("error") else [])])])
    ws.append([])
    ws.append(["Total findings", report["totals"]["findings"]])
    ws.append(["Disallowance total", report["totals"]["disallowance_amount"]])
    for c in report["checks"]:
        sheet = wb.create_sheet(c["check_id"])
        keys = sorted({k for f in c["findings"] for k in (f.get("evidence") or {})})
        sheet.append(["Severity", "Amount", "Disallowance", "Date", "Subject", "Finding", "Rule status", "Message", *keys])
        for f in c["findings"]:
            ev = f.get("evidence") or {}
            sheet.append([f["severity"], _cell(f.get("amount")), _cell(f.get("disallowance_amount")), _cell(f.get("finding_date")),
                          f.get("subject_ref"), f.get("finding_key"), f.get("rule_status"), f["message"], *[_cell(ev.get(k)) for k in keys]])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
