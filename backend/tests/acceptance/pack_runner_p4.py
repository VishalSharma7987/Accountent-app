"""Phase 4 (TDS / TCS) acceptance runner: drives the REAL services (not the API) with the Phase 4 pack and compares every result
with the hand-worked expected files of the accountants.

It never modifies a pack file and never bends the tool to fit them: every difference is collected per section as one plain line
(expected vs tool) for the owner and the accountants to decide. One run builds the whole world inside the caller's transaction:
client with two financial years (2025-26 under the Income-tax Act 1961, 2026-27 under the Act of 2025), deductee master,
certificates, 28 vouchers with TDS / TCS, challans and allocations, interest, quarterly workings, certificate data, a 26AS
statement with its reconciliation, and the refusals of the wrong cases. Phase 4.1 adds the addendum in the pack's p41 folder (a
second small client): TDS on a GST invoice, a threshold crossing with earlier payments at their own rates, a partial certificate
with both rates, and rent by an individual not liable to tax audit (ex-194-IB). The main client (a partnership) answers "No" for
both years, so its rent stays under ex-194-I.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pack_loader_p4 import PackP4, VoucherRec
from pack_loader_p41 import PackP41, VoucherRec41, load_pack_p41
from pack_runner_p2 import diff_keyed, explain_errors, judge_wrong, money
from pack_runner_p3 import _post, _refusal_text, _setup_ledgers, amt, guard, iso, narrow
from sqlalchemy import Connection, text

from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import VoucherDraft, VoucherLine
from app.engine.tds_types import TdsLineIn
from app.services import (
    client_setup,
    gst_registrations,
    reports,
    tds_challans,
    tds_deduction,
    tds_hooks,
    tds_masters,
    tds_recon,
    tds_returns,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

ACTOR = "pack-runner-p4"

SECTIONS = (
    "setup", "vouchers", "items", "ledger_balances", "challans", "register", "by_deductee", "position", "interest",
    "return_working", "certificates", "recon", "rule_status", "wrong_cases", "p41",
)


@dataclass
class RunReport:
    pack: str
    problems: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SECTIONS})
    warnings: list[str] = field(default_factory=list)  # reported, do not fail
    notes: list[str] = field(default_factory=list)  # information for the owner
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, section: str, message: str) -> None:
        self.problems[section].append(message)

    @property
    def total_problems(self) -> int:
        return sum(len(v) for v in self.problems.values())


def format_report(report: RunReport) -> str:
    lines = [f"Pack '{report.pack}': {report.total_problems} difference(s), {len(report.warnings)} warning(s)"]
    for section in SECTIONS:
        found = report.problems[section]
        lines.append(f"[{'FAIL' if found else 'ok  '}] {section}")
        lines += [f"        - {p}" for p in found]
    if report.warnings:
        lines.append("WARNINGS (not failures):")
        lines += [f"  * {w}" for w in report.warnings]
    if report.notes:
        lines.append("NOTES:")
        lines += [f"  * {n}" for n in report.notes]
    lines.append("COUNTS: " + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    return "\n".join(lines)


# ================================================================================================ pure helpers


def plain(value) -> str:
    """A rate or count as plain text without trailing zeros: '2.0000' and '2' are both '2'; blank stays blank."""
    if value is None or value == "":
        return ""
    return format(Decimal(str(value)).normalize(), "f")


def boolean(value) -> str:
    return "true" if value in (True, "true", "True") else "false"


def csv_fields(row: dict, columns: tuple[str, ...]) -> dict[str, str]:
    """Expected cells of a row for the given columns; a blank cell of an optional column is not compared (the caller says which)."""
    return {c: row[c] for c in columns}


def lines_for(v_type: str, party, counter, amount: str) -> tuple[VoucherLine, ...]:
    """Lines as an accountant types them: gross amounts, no tax line (the tool adds it)."""
    if v_type in ("purchase", "receipt"):
        return (VoucherLine(counter, amount, None), VoucherLine(party, None, amount))
    return (VoucherLine(party, amount, None), VoucherLine(counter, None, amount))  # payment, sales


def tds_draft(cid, v_type: str, on: date, narration: str, reference_no, party, counter, amount: Decimal, nature: str,
              credit: date | None, payment: date | None, cert_id=None, manual_tax: Decimal | None = None) -> VoucherDraft:
    item = TdsLineIn(party, nature, amount, credit, payment, cert_id, manual_tax)
    return VoucherDraft(cid, v_type, on, narration, reference_no, party, lines_for(v_type, party, counter, f"{amount:.2f}"), tds=(item,))


def _try_draft(conn: Connection, draft: VoucherDraft):
    """The rule errors of a refused draft ([] = it was accepted and saved)."""
    try:
        return vouchers.create_draft(conn, draft, actor=ACTOR).errors
    except VoucherRuleError as refusal:
        return refusal.errors


# ===================================================================================================== the run


def _second_year(conn: Connection, cid, start: date) -> uuid.UUID:
    """The second financial year with its 12 monthly periods (the tool has no 'add a year' service yet: plain rows like its own tests)."""
    fy = uuid.uuid4()
    end = date(start.year + 1, 3, 31)
    conn.execute(text("INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (:f, :c, :s, :e)"),
                 {"f": fy, "c": cid, "s": start, "e": end})
    conn.execute(
        text("INSERT INTO periods (client_id, financial_year_id, period_start, period_end) SELECT :c, :f, d::date, "
             "(d + interval '1 month' - interval '1 day')::date FROM generate_series(CAST(:s AS date), CAST(:e AS date) - interval '1 month', "
             "'1 month') d"),
        {"c": cid, "f": fy, "s": start, "e": end})
    return fy


def run_pack_p4(conn: Connection, pack: PackP4) -> RunReport:
    report = RunReport(pack.folder.name)
    c = pack.client
    exp = pack.expected
    created = client_setup.create_client(
        conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]),
        fy_start=c["fy_start"], actor=ACTOR, partners=c["partners"])
    cid = created.client_id
    fy_of_name = {"first": created.financial_year_id, "second": _second_year(conn, cid, c["second_fy_start"])}
    zero = Decimal("0.00")
    ids = _setup_ledgers(conn, report, cid, created.financial_year_id,
                         created, [{**r, "opening_dr": zero, "opening_cr": zero} for r in pack.ledgers])
    with guard(report, "setup"):
        tds_masters.set_tan(conn, cid, c["tan"], actor=ACTOR)
        tds_masters.set_fy_flag(conn, cid, fy_of_name["second"], True,
                                "Prior-year turnover above the limit (pack assumption; the limit itself is pending)", actor=ACTOR)
        tds_masters.set_ledger_roles(conn, cid, [(r["role"], r["nature_key"] or None, ids[r["ledger_name"]]) for r in pack.roles], actor=ACTOR)
        for fy in fy_of_name.values():  # T-19: a partnership is not an individual / HUF: rent stays under ex-194-I (entered, not guessed)
            tds_masters.set_deductor_profile(conn, cid, fy, False, "Partnership firm: not an individual / HUF", actor=ACTOR)
    for d in pack.deductees:
        try:
            tds_masters.set_deductee(conn, cid, ids[d["ledger_name"]], pan=d["pan"] or None, pan_status=d["pan_status"],
                                     deductee_type=d["deductee_type"], actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            report.add("setup", f"deductee {d['ledger_name']} refused: {_refusal_text(refusal)}")
    cert_ids: dict[str, object] = {}
    for k in pack.certificates:
        try:
            cert_ids[k["cert_ref"]] = tds_masters.add_certificate(
                conn, cid, ids[k["ledger_name"]], certificate_no=k["certificate_no"], nature_key=k["nature_key"], rate=k["rate"],
                max_amount=k["max_amount"], valid_from=k["valid_from"], valid_to=k["valid_to"], actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            report.add("setup", f"certificate {k['cert_ref']} refused: {_refusal_text(refusal)}")

    # ---- vouchers in date order: draft -> approve -> post, then what the tool stored
    posted: dict[str, object] = {}
    number: dict[str, str] = {}
    item_of: dict[str, dict] = {}
    for v in pack.vouchers:
        draft = tds_draft(cid, v.voucher_type, v.date, v.narration, v.reference_no, ids[v.party_ledger], ids[v.counter_ledger], v.amount,
                          v.nature_key, v.credit_date, v.payment_date, cert_ids.get(v.cert_ref) if v.cert_ref else None)
        vid, problem = _post(conn, draft)
        if problem:
            report.add("vouchers", f"correct voucher {v.ref_id} was refused: {problem}")
            continue
        posted[v.ref_id] = vid
        number[v.ref_id] = vouchers.get_voucher(conn, vid).voucher_number
        block = tds_hooks.load_tds(conn, cid, vid) or {"items": []}
        if len(block["items"]) == 1:
            item_of[v.ref_id] = block["items"][0]
        else:
            report.add("items", f"{v.ref_id}: the tool stored {len(block['items'])} deduction items, one expected")
        report.counts["vouchers_posted"] += 1
    ref_of_number = {n: r for r, n in number.items()}
    item_id: dict[str, object] = {}
    for ref, vid in posted.items():
        item_id[ref] = conn.execute(text("SELECT id FROM tds_voucher_items WHERE voucher_id = :v ORDER BY item_no LIMIT 1"), {"v": vid}).scalar_one_or_none()
    ref_of_item = {str(i): r for r, i in item_id.items() if i is not None}
    if report.counts["vouchers_posted"] != len(pack.vouchers):
        report.add("vouchers", f"{len(pack.vouchers)} vouchers in the pack, {report.counts['vouchers_posted']} posted")

    want_numbers = {(r["ref_id"],): {"voucher_number": r["voucher_number"]} for r in exp["expected_vouchers"]}
    got_numbers = {(ref,): {"voucher_number": n} for ref, n in number.items()}
    for line in diff_keyed(want_numbers, got_numbers, ("voucher_number",), label=lambda k: f"voucher {k[0]}"):
        report.add("vouchers", line)

    # ---- what the engine worked out per item (hand-calculated in WORKING.md)
    item_fields = ("act", "section_ref", "event_date", "payment_amount", "cumulative_before", "cumulative_after", "threshold_crossed",
                   "taxable_base", "rate_applied", "rate_reason", "tax_already_on_base", "tds_amount", "verification_status")
    want_items = {(r["ref_id"],): {f: r[f] for f in item_fields if r[f] != ""} for r in exp["expected_items"]}  # blank = not stated
    got_items = {(ref,): {**{f: str(i[f]) for f in item_fields}, "threshold_crossed": boolean(i["threshold_crossed"]),
                          "rate_applied": plain(i["rate_applied"])} for ref, i in item_of.items()}
    for line in diff_keyed(want_items, narrow(want_items, got_items), item_fields, label=lambda k: f"item of {k[0]}"):
        report.add("items", line)
    for ref, i in item_of.items():  # the generated tax line must be there for every deduction with tax
        if Decimal(i["tds_amount"]) > 0 and not i["tds_line_no"]:
            report.add("items", f"{ref}: tax {i['tds_amount']} was worked out but no tax line was added to the voucher")
    for ref, i in item_of.items():
        report.notes += [f"{ref} warning {w['rule_id']}: {w['message']}" for w in i["warnings"]]

    _ledger_balances(conn, cid, exp, report)

    # ---- challans with allocations, then the year views
    challan_of: dict[str, object] = {}
    for ch in pack.challans:
        try:
            challan_of[ch.ref_id] = tds_challans.create_challan(conn, cid, {
                "kind": ch.kind, "financial_year_id": fy_of_name[ch.fy], "quarter": ch.quarter, "bsr_code": ch.bsr_code,
                "deposit_date": ch.deposit_date, "challan_serial_no": ch.serial_no, "tax_amount": f"{ch.tax:.2f}",
                "interest_amount": f"{ch.interest:.2f}", "fee_amount": f"{ch.fee:.2f}",
                "allocations": [{"item_id": item_id[ref], "amount": f"{a:.2f}"} for ref, a in ch.allocations]}, actor=ACTOR)
            report.counts["challans"] += 1
        except (VoucherRuleError, ServiceError) as refusal:
            report.add("challans", f"challan {ch.ref_id} was refused: {_refusal_text(refusal)}")
    with guard(report, "challans"):
        ref_of_challan = {str(i): r for r, i in challan_of.items()}
        got = {}
        for row in tds_challans.list_challans(conn, cid):
            ref = ref_of_challan.get(str(row["id"]), str(row["id"]))
            got[(ref,)] = {"total_amount": amt(row["total_amount"]), "allocated": amt(row["allocated"]),
                           "unallocated": amt(row["unallocated"]), "status": row["status"]}
        want = {(r["ref_id"],): {k: v for k, v in r.items() if k != "ref_id"} for r in exp["expected_challans"]}
        for line in diff_keyed(want, got, ("total_amount", "allocated", "unallocated", "status"), label=lambda k: f"challan {k[0]}"):
            report.add("challans", line)

    rule_got: dict[str, str] = {}
    with guard(report, "register"):
        _register(conn, cid, fy_of_name, exp, report, ref_of_number, rule_got)
    with guard(report, "by_deductee"):
        _by_deductee(conn, cid, fy_of_name["second"], exp, report)
    with guard(report, "position"):
        _position(conn, cid, ids, exp, report)
    with guard(report, "interest"):
        _interest(conn, cid, fy_of_name, c["interest_as_on"], exp, report, ref_of_item, rule_got)
    with guard(report, "return_working"):
        _returns(conn, cid, fy_of_name, exp, report, rule_got)
    with guard(report, "certificates"):
        _certificates(conn, cid, ids, fy_of_name, exp, report, rule_got)
    with guard(report, "recon"):
        _recon(conn, cid, fy_of_name["second"], pack, exp, report, item_id, ref_of_number, rule_got)

    want_rs = {(r["working"],): {"worst": r["worst"]} for r in exp["expected_rule_status"]}
    got_rs = {(k,): {"worst": v} for k, v in rule_got.items()}
    for line in diff_keyed(want_rs, got_rs, ("worst",), label=lambda k: f"rule status of {k[0]}"):
        report.add("rule_status", line)

    with guard(report, "wrong_cases"):
        _wrong_cases(conn, cid, ids, fy_of_name, cert_ids, item_id, challan_of, posted, pack, report)
    with guard(report, "p41"):
        _run_p41(conn, report, load_pack_p41(pack.folder / "p41"))
    return report


# ============================================================================================ sections


def _ledger_balances(conn, cid, exp, report: RunReport) -> None:
    by_date: dict[date, list[dict]] = defaultdict(list)
    for r in exp["expected_ledger_balances"]:
        by_date[date.fromisoformat(r["as_on"])].append(r)
    for as_on, rows in by_date.items():
        with guard(report, "ledger_balances"):
            tb = reports.trial_balance(conn, cid, as_on)
            actual = {r.ledger_name: (r.debit, r.credit) for s in tb.sections for r in s.rows}
            for r in rows:
                name = r["ledger_name"]
                if name not in actual:
                    report.add("ledger_balances", f"{as_on}: {name}: not found in the tool's Trial Balance")
                    continue
                dr, cr = actual[name]
                side, net = ("Dr", dr - cr) if dr >= cr else ("Cr", cr - dr)
                if (side, money(net)) != (r["side"], r["amount"]):
                    report.add("ledger_balances", f"{as_on}: {name}: expected {r['side']} {r['amount']}, tool says {side} {money(net)}")


def _register(conn, cid, fy_of_name, exp, report, ref_of_number, rule_got) -> None:
    got = {}
    for fy in fy_of_name.values():
        res = tds_deduction.register(conn, cid, financial_year_id=fy, quarter=None, nature_key=None, deductee_ledger_id=None)
        for r in res["rows"]:
            got[(ref_of_number.get(r["voucher_number"], r["voucher_number"]),)] = {
                "tds_amount": r["tds_amount"], "deposited": r["deposited"], "balance": r["balance"], "deposited_on": r["deposited_on"] or ""}
    fields = ("tds_amount", "deposited", "balance", "deposited_on")
    want = {(r["ref_id"],): {f: r[f] for f in fields} for r in exp["expected_register"]}
    for line in diff_keyed(want, got, fields, label=lambda k: f"register row of {k[0]}"):
        report.add("register", line)
    rule_got["register_fy25_contractor"] = tds_deduction.register(
        conn, cid, financial_year_id=fy_of_name["first"], quarter=None, nature_key="contractor", deductee_ledger_id=None)["rule_status"]["worst"]
    rule_got["register_fy26_contractor"] = tds_deduction.register(
        conn, cid, financial_year_id=fy_of_name["second"], quarter=None, nature_key="contractor", deductee_ledger_id=None)["rule_status"]["worst"]
    rule_got["register_fy26_tcs_scrap"] = tds_deduction.register(
        conn, cid, financial_year_id=fy_of_name["second"], quarter=None, nature_key="tcs_scrap", deductee_ledger_id=None)["rule_status"]["worst"]


def _by_deductee(conn, cid, fy, exp, report) -> None:
    fields = ("cumulative_amount", "tax_deducted", "threshold_crossed_on", "threshold")
    got = {(r["deductee_name"], r["nature_key"]): {
        "cumulative_amount": r["cumulative_amount"], "tax_deducted": r["tax_deducted"],
        "threshold_crossed_on": r["threshold_crossed_on"] or "", "threshold": r["threshold"] or ""}
        for r in tds_deduction.by_deductee(conn, cid, fy)}
    want = {(r["deductee_name"], r["nature_key"]): {f: r[f] for f in fields} for r in exp["expected_by_deductee"]}
    for line in diff_keyed(want, got, fields, label=lambda k: f"{k[0]} / {k[1]}"):
        report.add("by_deductee", line)


def _position(conn, cid, ids, exp, report) -> None:
    fields = ("cumulative_amount", "tax_deducted", "single_threshold", "monthly_threshold", "annual_threshold", "headroom")
    for r in exp["expected_position"]:
        label = f"position of {r['deductee_name']} / {r['nature_key']} on {r['on']}"
        got = tds_deduction.threshold_position(conn, cid, ids[r["deductee_name"]], r["nature_key"], date.fromisoformat(r["on"]))
        if isinstance(got, list):
            report.add("position", f"{label}: the tool refused: {explain_errors(got)}")
            continue
        for f in fields:
            if (got.get(f) or "") != r[f]:
                report.add("position", f"{label}: {f} expected {r[f] or '(blank)'}, tool says {got.get(f) or '(blank)'}")


def _interest(conn, cid, fy_of_name, as_on, exp, report, ref_of_item, rule_got) -> None:
    fields = ("deducted_on", "due_date", "months_late_deduction", "interest_late_deduction", "deposited_on", "months_late_deposit",
              "interest_late_deposit")
    got = {}
    for key, fy in fy_of_name.items():
        res = tds_challans.interest(conn, cid, fy, as_on)
        if key == "second":
            rule_got["interest_fy26"] = res["rule_status"]["worst"]
        for r in res["rows"]:
            got[(ref_of_item.get(str(r["item_id"]), str(r["item_id"])),)] = {
                "deducted_on": iso(r["deducted_on"]), "due_date": iso(r["due_date"]), "months_late_deduction": str(r["months_late_deduction"]),
                "interest_late_deduction": amt(r["interest_late_deduction"]), "deposited_on": iso(r["deposited_on"]),
                "months_late_deposit": str(r["months_late_deposit"]), "interest_late_deposit": amt(r["interest_late_deposit"])}
    want = {(r["ref_id"],): {f: r[f] for f in fields} for r in exp["expected_interest"]}
    for line in diff_keyed(want, got, fields, label=lambda k: f"interest of {k[0]}"):
        report.add("interest", line)


def _returns(conn, cid, fy_of_name, exp, report, rule_got) -> None:
    workings = {
        "q1_fy2026-27_non_salary": ("second", 1, "non_salary_resident"), "q4_fy2025-26_non_salary": ("first", 4, "non_salary_resident"),
        "q1_fy2026-27_tcs": ("second", 1, "tcs"), "q4_fy2025-26_tcs": ("first", 4, "tcs"),
    }
    got_rows, got_totals = {}, {}
    for key, (fy, quarter, kind) in workings.items():
        w = tds_returns.return_working(conn, cid, fy_of_name[fy], quarter, kind)
        if key == "q1_fy2026-27_non_salary":
            rule_got["return_q1_non_salary"] = w["rule_status"]["worst"]
        if key == "q1_fy2026-27_tcs":
            rule_got["return_q1_tcs"] = w["rule_status"]["worst"]
        for n, r in enumerate(w["deductee_rows"], 1):
            got_rows[(key, str(n))] = {
                "deductee_name": r["deductee_name"], "event_date": iso(r["event_date"]), "section_ref": r["section_ref"],
                "amount_paid": amt(r["amount_paid"]), "taxable_base": amt(r["taxable_base"]), "tax_deducted": amt(r["tax_deducted"]),
                "tax_deposited": amt(r["tax_deposited"]), "rate": plain(r["rate"]), "rate_reason": r["rate_reason"],
                "error_row": boolean(r["error_row"])}
        t = w["totals"]
        got_totals[(key,)] = {
            "form_no": w["form_no"], "form_status": w["form_status"], "tan": w["tan"], "row_count": str(t["row_count"]),
            "amount_paid": amt(t["amount_paid"]), "tax_deducted": amt(t["tax_deducted"]), "tax_deposited": amt(t["tax_deposited"]),
            "short_deposit": amt(t["short_deposit"]), "challan_count": str(t["challan_count"]), "challan_tax": amt(t["challan_tax"]),
            "challan_interest": amt(t["challan_interest"]), "challan_total": amt(t["challan_total"]),
            "error_rule_ids": "|".join(sorted({e["rule_id"] for e in w["errors"]})),
            "warning_rule_ids": "|".join(sorted({e["rule_id"] for e in w["warnings"]}))}
    row_fields = ("deductee_name", "event_date", "section_ref", "amount_paid", "taxable_base", "tax_deducted", "tax_deposited", "rate",
                  "rate_reason", "error_row")
    want_rows = {(r["working"], r["row_no"]): {f: r[f] for f in row_fields} for r in exp["expected_return_rows"]}
    for line in diff_keyed(want_rows, got_rows, row_fields, label=lambda k: f"{k[0]} row {k[1]}"):
        report.add("return_working", line)
    tot_fields = ("form_no", "form_status", "tan", "row_count", "amount_paid", "tax_deducted", "tax_deposited", "short_deposit",
                  "challan_count", "challan_tax", "challan_interest", "challan_total", "error_rule_ids", "warning_rule_ids")
    want_totals = {(r["working"],): {f: r[f].replace(";", "|") for f in tot_fields} for r in exp["expected_return_totals"]}
    for line in diff_keyed(want_totals, got_totals, tot_fields, label=lambda k: f"{k[0]} totals"):
        report.add("return_working", line)


def _certificates(conn, cid, ids, fy_of_name, exp, report, rule_got) -> None:
    for r in exp["expected_certificates"]:
        label = f"certificate {r['case']} ({r['ledger_name']}, quarter {r['quarter']})"
        try:
            got = tds_returns.certificate_preview(conn, cid, ids[r["ledger_name"]], fy_of_name[r["fy"]], int(r["quarter"]), r["kind"])
        except VoucherRuleError as refusal:
            rules = {e.rule_id for e in refusal.errors}
            if r["refusal_rule"] != next(iter(rules), "") or len(rules) != 1:
                report.add("certificates", f"{label}: expected {r['refusal_rule'] or 'a certificate'}, the tool refused with {explain_errors(refusal.errors)}")
            continue
        if r["refusal_rule"]:
            report.add("certificates", f"{label}: expected the refusal {r['refusal_rule']}, the tool produced a certificate")
            continue
        facts = {"form_no": got["form_no"], "period": got["period"], "total_amount_paid": amt(got["total_amount_paid"]),
                 "total_deducted": amt(got["total_deducted"]), "total_deposited": amt(got["total_deposited"]),
                 "item_count": str(len(got["items"])), "challan_count": str(len(got["challans"]))}
        for f, value in facts.items():
            if value != r[f]:
                report.add("certificates", f"{label}: {f} expected {r[f]}, tool says {value}")
        if r["case"] == "C1":
            rule_got["certificate_alpha_q1"] = got["rule_status"]["worst"]
        if r["case"] == "C3":
            rule_got["certificate_mehta_q4_fy25"] = got["rule_status"]["worst"]


def _recon(conn, cid, fy, pack: PackP4, exp, report, item_id, ref_of_number, rule_got) -> None:
    result = tds_recon.import_file(conn, cid, fy, "form_26as", "deductor", "statement_26as_fy2026-27.csv", pack.statement, ACTOR)
    rows = {r["row_no"]: r["id"] for r in tds_recon.list_rows(conn, cid, result.import_id)}
    if result.row_count != len(rows):
        report.add("recon", f"the tool listed {len(rows)} rows after importing {result.row_count}")
    for link in pack.links:
        tds_recon.create_link(conn, cid, rows[link["row_no"]], item_id[link["voucher_ref"]], None, link["link_kind"], link["note"], ACTOR)
    rec = tds_recon.reconcile(conn, cid, fy, result.import_id)
    rule_got["recon_fy26"] = rec.rule_status["worst"]
    got = {}
    for r in rec.result.rows:
        key = f"row:{r.row.row_no}" if r.row is not None else f"book:{ref_of_number.get(r.book.voucher_number, r.book.voucher_number)}"
        got[(key,)] = {"class": r.cls, "difference": amt(r.difference), "reason": r.reason or "", "link_kind": r.link_kind or ""}
    fields = ("class", "difference", "reason", "link_kind")
    want = {(r["key"],): {f: r[f] for f in fields} for r in exp["expected_recon"]}
    for line in diff_keyed(want, got, fields, label=lambda k: f"reconciliation {k[0]}"):
        report.add("recon", line)
    want_sum = {(r["class"],): {"count": r["count"]} for r in exp["expected_recon_summary"]}
    got_sum = {(k,): {"count": str(v)} for k, v in rec.result.summary.items()}
    for line in diff_keyed(want_sum, got_sum, ("count",), label=lambda k: f"reconciliation summary {k[0]}"):
        report.add("recon", line)


def _wrong_cases(conn, cid, ids, fy_of_name, cert_ids, item_id, challan_of, posted, pack: PackP4, report: RunReport) -> None:
    for w in pack.wrong_cases:
        label = f"{w['case_id']} ({w['description']})"
        expected, word = w["expected_rule_id"], w["expected_message_contains"] or None
        kind = w["kind"]
        got: list = []
        try:
            if kind == "voucher":
                draft = tds_draft(
                    cid, w["voucher_type"], date.fromisoformat(w["date"]), "Wrong case", "WRONG/1" if w["voucher_type"] == "purchase" else None,
                    ids[w["party_ledger"]], ids[w["counter_ledger"]], Decimal(w["amount"]), w["nature_key"],
                    date.fromisoformat(w["credit_date"]) if w["credit_date"] else None,
                    date.fromisoformat(w["payment_date"]) if w["payment_date"] else None,
                    cert_ids.get(w["cert_ref"]) if w["cert_ref"] else None, Decimal(w["manual_tax"]) if w["manual_tax"] else None)
                got = _try_draft(conn, draft)
            elif kind == "deductee":
                tds_masters.set_deductee(conn, cid, ids[w["party_ledger"]], pan="ABCDE1", pan_status="valid", deductee_type="company", actor=ACTOR)
            elif kind == "reverse":
                vouchers.reverse(conn, posted[w["party_ledger"]], date.fromisoformat(w["date"]), "Wrong case", actor=ACTOR)
            elif kind == "challan":
                ref = w["party_ledger"]
                base = {"kind": "tds", "financial_year_id": fy_of_name["second"], "quarter": 2, "bsr_code": "0510308",
                        "deposit_date": date.fromisoformat(w["date"]), "challan_serial_no": "99001", "tax_amount": "300.00"}
                if ref == "CH1":
                    first = next(c for c in pack.challans if c.ref_id == "CH1")
                    base.update(quarter=first.quarter, bsr_code=first.bsr_code, deposit_date=first.deposit_date,
                                challan_serial_no=first.serial_no, tax_amount="100.00")
                elif ref == "BAD":
                    base.update(bsr_code="12345")
                else:
                    base["allocations"] = [{"item_id": item_id[ref], "amount": w["amount"]}]
                tds_challans.create_challan(conn, cid, base, actor=ACTOR)
        except VoucherRuleError as refusal:
            got = refusal.errors
        except ServiceError as refusal:
            if refusal.code != expected:
                report.add("wrong_cases", f"{label}: expected {expected}, the tool refused with {refusal.code}: {refusal.message}")
            elif word and word.lower() not in refusal.message.lower():
                report.warnings.append(f"{label}: the message does not contain '{word}': {refusal.message}")
                report.counts["wrong_cases_refused"] += 1
            else:
                report.counts["wrong_cases_refused"] += 1
            continue
        if not got:
            report.add("wrong_cases", f"{label}: the tool accepted it, expected {expected}")
            continue
        problem, warning = judge_wrong(label, expected, word, got)
        if problem:
            report.add("wrong_cases", problem)
        else:
            report.counts["wrong_cases_refused"] += 1
        if warning:
            report.warnings.append(warning)


# ============================================================================================ Phase 4.1 addendum


def _p41_draft(cid, v: VoucherRec41, ids, reg_id, supplier_gstin: str, cert_id=None, reference_no=None) -> VoucherDraft:
    """A TDS voucher; with `gst_invoice_value` a GST purchase invoice (one item, HSN 8415, supplier in the same state) carrying the TDS item."""
    if v.gst_invoice_value is None:
        return tds_draft(cid, v.voucher_type, v.date, v.narration, reference_no or v.reference_no, ids[v.party_ledger], ids[v.counter_ledger],
                         v.amount, v.nature_key, v.credit_date, v.payment_date, cert_id)
    item = ItemLineIn("Contract work", "8415", Decimal(1), v.gst_invoice_value, Decimal("0.00"), ids[v.counter_ledger], uqc="NOS")
    inv = InvoiceIn(str(reg_id), "tax_invoice", "b2b", "27", v.date, (item,), counterparty_gstin=supplier_gstin)
    tds = TdsLineIn(ids[v.party_ledger], v.nature_key, v.amount, v.credit_date, v.payment_date, cert_id)
    return VoucherDraft(cid, v.voucher_type, v.date, v.narration, reference_no or v.reference_no, ids[v.party_ledger], (), gst=inv, tds=(tds,))


def _run_p41(conn: Connection, report: RunReport, pack: PackP41) -> None:
    c, exp = pack.client, pack.expected
    created = client_setup.create_client(
        conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]),
        fy_start=c["fy_start"], actor=ACTOR, proprietor_name=c.get("proprietor_name"))
    cid = created.client_id
    fy_second = _second_year(conn, cid, c["second_fy_start"])
    zero = Decimal("0.00")
    ids = _setup_ledgers(conn, report, cid, created.financial_year_id, created, [{**r, "opening_dr": zero, "opening_cr": zero} for r in pack.ledgers])
    reg_id = gst_registrations.create_registration(conn, cid, gstin=c["gstin"], registration_type="regular",
                                                   effective_from=c["registration_effective_from"], actor=ACTOR)
    gst_registrations.set_ledger_roles(conn, cid, reg_id, {r["role"]: ids[r["ledger_name"]] for r in pack.gst_roles}, actor=ACTOR)
    tds_masters.set_tan(conn, cid, c["tan"], actor=ACTOR)
    tds_masters.set_ledger_roles(conn, cid, [(r["role"], r["nature_key"] or None, ids[r["ledger_name"]]) for r in pack.roles], actor=ACTOR)
    tds_masters.set_deductor_profile(conn, cid, fy_second, bool(c["individual_huf_not_tax_audited_2026_27"]),
                                     "Individual not liable to tax audit in the preceding year (pack assumption)", actor=ACTOR)
    for d in pack.deductees:
        tds_masters.set_deductee(conn, cid, ids[d["ledger_name"]], pan=d["pan"] or None, pan_status=d["pan_status"],
                                 deductee_type=d["deductee_type"], actor=ACTOR)
    cert_ids = {k["cert_ref"]: tds_masters.add_certificate(
        conn, cid, ids[k["ledger_name"]], certificate_no=k["certificate_no"], nature_key=k["nature_key"], rate=k["rate"],
        max_amount=k["max_amount"], valid_from=k["valid_from"], valid_to=k["valid_to"], actor=ACTOR) for k in pack.certificates}

    posted: dict[str, object] = {}
    number: dict[str, str] = {}
    item_of: dict[str, dict] = {}
    for v in pack.vouchers:
        if v.set_pan:  # the PAN is confirmed on the portal between two payments: the earlier ones keep the status they had
            deductee = next(d for d in pack.deductees if d["ledger_name"] == v.party_ledger)
            tds_masters.set_deductee(conn, cid, ids[v.party_ledger], pan=v.set_pan, pan_status="valid", deductee_type=deductee["deductee_type"], actor=ACTOR)
        vid, problem = _post(conn, _p41_draft(cid, v, ids, reg_id, c["invoice_supplier_gstin"], cert_ids.get(v.cert_ref) if v.cert_ref else None))
        if problem:
            report.add("p41", f"correct voucher {v.ref_id} was refused: {problem}")
            continue
        posted[v.ref_id] = vid
        number[v.ref_id] = vouchers.get_voucher(conn, vid).voucher_number
        item_of[v.ref_id] = (tds_hooks.load_tds(conn, cid, vid) or {"items": [{}]})["items"][0]
        report.counts["p41_vouchers_posted"] += 1

    fields = ("nature_key", "act", "section_ref", "event_date", "payment_amount", "cumulative_before", "cumulative_after",
              "threshold_crossed", "taxable_base", "rate_applied", "certificate_rate", "effective_rate", "rate_reason",
              "tax_already_on_base", "tds_amount", "verification_status")
    want = {(r["ref_id"],): {f: r[f] for f in fields} for r in exp["expected_items"]}
    got = {(ref,): {**{f: str(i.get(f) or "") for f in fields}, "threshold_crossed": boolean(i.get("threshold_crossed")),
                    "rate_applied": plain(i.get("rate_applied")), "certificate_rate": plain(i.get("certificate_rate")),
                    "effective_rate": plain(i.get("effective_rate"))} for ref, i in item_of.items()}
    for line in diff_keyed(want, got, fields, label=lambda k: f"p41 item of {k[0]}"):
        report.add("p41", line)

    # the register shows the same two rates
    ref_of_number = {n: r for r, n in number.items()}
    reg = tds_deduction.register(conn, cid, financial_year_id=fy_second, quarter=None, nature_key=None, deductee_ledger_id=None)
    rate_fields = ("certificate_rate", "effective_rate")
    got_reg = {(ref_of_number.get(r["voucher_number"], r["voucher_number"]),): {f: plain(r[f]) for f in rate_fields} for r in reg["rows"]}
    want_reg = {(r["ref_id"],): {f: r[f] for f in rate_fields} for r in exp["expected_items"]}
    for line in diff_keyed(want_reg, got_reg, rate_fields, label=lambda k: f"p41 register row of {k[0]}"):
        report.add("p41", line)

    # the voucher lines: GST lines unchanged, party credit reduced by the tax, the tax payable line added
    name_of = {lid: name for name, lid in ids.items()}
    got_lines = {}
    for ref in {r["ref_id"] for r in exp["expected_lines"]}:
        if ref in posted:
            for ln in vouchers.get_voucher(conn, posted[ref]).lines:
                got_lines[(ref, str(ln.line_no))] = {"ledger_name": name_of.get(ln.ledger_id, str(ln.ledger_id)), "debit": amt(ln.debit), "credit": amt(ln.credit)}
    line_fields = ("ledger_name", "debit", "credit")
    want_lines = {(r["ref_id"], r["line_no"]): {f: r[f] for f in line_fields} for r in exp["expected_lines"]}
    for line in diff_keyed(want_lines, got_lines, line_fields, label=lambda k: f"p41 voucher {k[0]} line {k[1]}"):
        report.add("p41", line)

    for w in pack.wrong_cases:
        label = f"p41 {w['case_id']} ({w['description']})"
        rec = VoucherRec41(w["case_id"], date.fromisoformat(w["date"]), w["voucher_type"], None, "Wrong case", w["party_ledger"],
                           w["counter_ledger"], Decimal(w["amount"]), w["nature_key"], None, date.fromisoformat(w["payment_date"]), None, None,
                           Decimal(w["gst_invoice_value"]) if w["gst_invoice_value"] else None)
        errors = _try_draft(conn, _p41_draft(cid, rec, ids, reg_id, c["invoice_supplier_gstin"],
                                             reference_no="WRONG/1" if w["voucher_type"] == "purchase" else None))
        if not errors:
            report.add("p41", f"{label}: the tool accepted it, expected {w['expected_rule_id']}")
            continue
        problem, warning = judge_wrong(label, w["expected_rule_id"], w["expected_message_contains"] or None, errors)
        if problem:
            report.add("p41", problem)
        else:
            report.counts["p41_wrong_cases_refused"] += 1
        if warning:
            report.warnings.append(warning)


__all__ = ["SECTIONS", "RunReport", "VoucherRec", "format_report", "run_pack_p4"]
