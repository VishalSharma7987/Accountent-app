"""Runs the Phase 8 pack (docs/test-packs/phase8-*) against the REAL audit services (runs, report, working papers, sampling, Form 3CD data, AI summary).

One run builds ONE synthetic client inside the caller's transaction (rolled back by the caller): the books are written the way the pack's input files
say (vouchers, lines, bills, documents, TDS items and challans, GST filed figures, stock, lock events, holidays, a related-party flag), with exactly one
injected error per audit check. The audit then runs twice (FY 2026-27 up to 31-10-2026 with all 18 checks, FY 2025-26 with eight checks). Every
expected value comes from the pack's hand-typed files; the runner never edits a pack file and never edits an expectation.

HEADLINE PROPERTY (section "headline"): every injected error appears in the audit report as a finding with non-empty evidence, nothing else is
reported (no clean control is flagged), and the books are unchanged after everything the audit did (row counts and a hash of vouchers and lines).

The runner NEVER touches the network and NEVER calls the real model: the AI summary is given a scripted `FakeLlmClient`, and while it runs the
OpenRouter client constructor and httpx's send methods raise (and are counted).
"""

import hashlib
import io
import json
import os
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest import mock

from openpyxl import load_workbook
from pack_loader_p8 import Pack
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.fake import FakeLlmClient
from app.services import (
    ai_settings,
    audit_form,
    audit_holidays,
    audit_papers,
    audit_related,
    audit_report,
    audit_runs,
    audit_summary,
    client_setup,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError

SECTIONS = ("findings", "summary", "controls", "report", "sampling", "paper", "ai_summary", "form", "books_unchanged", "no_network", "headline")
IST = timezone(timedelta(hours=5, minutes=30))
CENTS = Decimal("0.01")
BOOK_TABLES = ("vouchers", "voucher_lines", "ledgers", "opening_balances", "bill_allocations", "tds_voucher_items", "tds_challans",
               "tds_challan_allocations", "gst_filed_returns", "stock_movements", "stock_opening", "documents", "document_vouchers",
               "voucher_number_sequences", "periods", "financial_years", "parties", "tds_deductees")


class NetworkCalled(AssertionError):
    pass


@dataclass
class Report:
    problems: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SECTIONS})
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, section: str, message: str) -> None:
        self.problems[section].append(message)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def format_report(report: Report) -> str:
    lines = ["PHASE 8 PACK: expected (hand-typed pack files) versus what the tool did"]
    for section in SECTIONS:
        problems = report.problems[section]
        lines.append(f"[{'OK' if not problems else 'DIFFERENT'}] {section}")
        lines += [f"    - {p}" for p in problems]
    lines.append("counts: " + ", ".join(f"{k}={v}" for k, v in sorted(report.counts.items())))
    lines += [f"note: {n}" for n in report.notes]
    return "\n".join(lines)


def scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def money(value) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(CENTS)


@dataclass
class World:
    client_id: object
    fy26: object
    fy25: object
    ledgers: dict[str, object]
    vouchers: dict[str, object] = field(default_factory=dict)       # pack ref -> vouchers.id
    ref_of: dict[str, str] = field(default_factory=dict)            # str(voucher id) -> pack ref
    ledger_name: dict[str, str] = field(default_factory=dict)       # str(ledger id) -> name
    registration: object = None


# ------------------------------------------------------------------------------------------------------------------- building the books


def build_world(conn, pack: Pack) -> World:
    c = pack.config["client"]
    actor = pack.config["actors"]["setup"]
    created = client_setup.create_client(conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]),
                                         fy_start=c["fy_start"], actor=actor, proprietor_name=c["proprietor"])
    cid, ids = created.client_id, dict(created.ledger_ids)
    fy25 = uuid.uuid4()
    prev = c["previous_fy_start"]
    conn.execute(text("INSERT INTO financial_years (id, client_id, start_date, end_date) VALUES (:i, :c, :s, :e)"),
                 {"i": fy25, "c": cid, "s": prev, "e": date(prev.year + 1, 3, 31)})
    for led in pack.ledgers:
        ids[led["name"]] = client_setup.add_ledger(conn, cid, led["name"], led["group"], actor=actor)
    world = World(cid, created.financial_year_id, fy25, ids, ledger_name={str(v): k for k, v in ids.items()})

    reg = uuid.uuid4()
    world.registration = reg
    conn.execute(text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                      "VALUES (:r, :c, :g, :s, 'regular', :d)"), {"r": reg, "c": cid, "g": c["gstin"], "s": c["gstin"][:2], "d": c["gst_effective_from"]})
    for led in pack.ledgers:
        if led["gst_role"]:
            conn.execute(text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                         {"r": reg, "c": cid, "role": led["gst_role"], "l": ids[led["name"]]})
    for p in pack.parties:
        conn.execute(text(
            "INSERT INTO parties (ledger_id, client_id, bill_wise, msme_category, udyam_no, udyam_registration_date, msme_activity) "
            "VALUES (:l, :c, :bw, :cat, :u, :ud, :act)"),
            {"l": ids[p["ledger"]], "c": cid, "bw": p["bill_wise"] == "yes", "cat": p["msme_category"], "u": p["udyam_no"],
             "ud": date.fromisoformat(p["udyam_registration_date"]), "act": p["msme_activity"]})
    for ledger, debit, credit in pack.openings:
        conn.execute(text("INSERT INTO opening_balances (client_id, ledger_id, financial_year_id, debit, credit) VALUES (:c, :l, :fy, :d, :cr)"),
                     {"c": cid, "l": ids[ledger], "fy": world.fy26, "d": debit, "cr": credit})
    for d in pack.tds_deductees:
        conn.execute(text("INSERT INTO tds_deductees (ledger_id, client_id, pan, pan_status, deductee_type, default_nature_key) "
                          "VALUES (:l, :c, :pan, 'valid', :t, :n)"),
                     {"l": ids[d["ledger"]], "c": cid, "pan": d["pan"], "t": d["deductee_type"], "n": d["default_nature"]})
    post_vouchers(conn, pack, world)
    add_counters(conn, pack, world)
    add_documents(conn, pack, world)
    add_challans(conn, pack, world)
    add_gst_returns(conn, pack, world)
    add_stock(conn, pack, world)
    add_lock_events(conn, pack, world)
    for h in pack.holidays:
        audit_holidays.add_holiday(conn, cid, date.fromisoformat(h["date"]), h["name"], h["kind"], None, actor=pack.config["actors"]["setup"])
    for r in pack.related:
        audit_related.flag_ledger(conn, cid, ids[r["ledger"]], r["relationship"], None, pack.config["actors"]["setup"])
    return world


def post_vouchers(conn, pack: Pack, world: World) -> None:
    cid = world.client_id
    items = {i["voucher"]: i for i in pack.tds_items}
    partner = pack.config["actors"]["partner"]
    for v in sorted(pack.vouchers, key=lambda x: (x.on, x.ref)):
        fy = world.fy26 if v.fy == "F26" else world.fy25
        vid = uuid.uuid4()
        world.vouchers[v.ref], world.ref_of[str(vid)] = vid, v.ref
        conn.execute(text(
            "INSERT INTO vouchers (id, client_id, financial_year_id, voucher_type, voucher_date, narration, reference_no, party_ledger_id, created_by) "
            "VALUES (:i, :c, :fy, :t, :d, :n, :r, :p, 'clerk')"),
            {"i": vid, "c": cid, "fy": fy, "t": v.voucher_type, "d": v.on, "n": v.narration, "r": v.reference_no or None,
             "p": world.ledgers[v.party] if v.party else None})
        conn.execute(text("INSERT INTO voucher_lines (client_id, voucher_id, line_no, ledger_id, debit, credit) VALUES (:c, :v, :n, :l, :d, :cr)"),
                     [{"c": cid, "v": vid, "n": n, "l": world.ledgers[ln[0]], "d": ln[1], "cr": ln[2]} for n, ln in enumerate(v.lines, start=1)])
        for n, ln in enumerate(v.lines, start=1):
            if ln[3]:
                conn.execute(text(
                    "INSERT INTO bill_allocations (client_id, voucher_id, line_no, party_ledger_id, kind, bill_ref, due_date, debit, credit) "
                    "VALUES (:c, :v, :n, :p, :k, :r, :due, :d, :cr)"),
                    {"c": cid, "v": vid, "n": n, "p": world.ledgers[ln[0]], "k": ln[3], "r": ln[4], "due": ln[5], "d": ln[1], "cr": ln[2]})
        if v.ref in items:
            it = items[v.ref]
            base, tax = Decimal(it["base"]), Decimal(it["tax_deducted"])
            conn.execute(text(
                "INSERT INTO tds_voucher_items (client_id, voucher_id, item_no, kind, deductee_ledger_id, nature_key, act, section_ref, financial_year_id, "
                "event_date, payment_date, payment_amount, cumulative_before, cumulative_after, taxable_base, rate_applied, rate_reason, tds_amount, "
                "tds_line_no, engine_version) VALUES (:c, :v, 1, 'tds', :l, :nat, 'it_act_2025', '393(1) Sl.6(i)', :fy, :d, :d, :b, 0, :b, :b, :rate, "
                "'normal', :tax, :ln, 'p8-pack')"),
                {"c": cid, "v": vid, "l": world.ledgers[it["deductee"]], "nat": it["nature"], "fy": fy, "d": v.on, "b": base,
                 "rate": Decimal(it["rate_applied"]), "tax": tax, "ln": int(it["tds_line_no"])})
        conn.execute(text("UPDATE vouchers SET status = 'approved', approved_by = :a, approved_at = now() WHERE id = :v"), {"v": vid, "a": partner})
        posted = v.posted_at or datetime.combine(v.on, time(12, 0), tzinfo=IST)
        conn.execute(text("UPDATE vouchers SET status = 'posted', voucher_number = :n, posted_by = :a, posted_at = :t WHERE id = :v"),
                     {"v": vid, "n": v.number, "a": partner, "t": posted})
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))   # fire the deferred balance and allocation checks now


def add_counters(conn, pack: Pack, world: World) -> None:
    """voucher_number_sequences: the counter of every type and year equals its highest posted number (the database only lets it grow by one)."""
    highest: dict[tuple, int] = {}
    for v in pack.vouchers:
        key = (v.fy, v.voucher_type)
        highest[key] = max(highest.get(key, 0), int(v.number.rsplit("/", 1)[1]))
    for (fy, vtype), n in highest.items():
        _counter(conn, world, fy, vtype, n)


def _counter(conn, world: World, fy: str, vtype: str, n: int) -> None:
    params = {"c": world.client_id, "fy": world.fy26 if fy == "F26" else world.fy25, "t": vtype}
    conn.execute(text("INSERT INTO voucher_number_sequences (client_id, financial_year_id, voucher_type, last_number) VALUES (:c, :fy, :t, 1)"), params)
    for i in range(2, n + 1):
        conn.execute(text("UPDATE voucher_number_sequences SET last_number = :i WHERE client_id = :c AND financial_year_id = :fy AND voucher_type = :t"),
                     {**params, "i": i})


def add_documents(conn, pack: Pack, world: World) -> None:
    rows, links = [], []
    for v in pack.vouchers:
        if not v.document:
            continue
        sha = hashlib.sha256(f"phase8-pack-document-{v.ref}".encode()).hexdigest()
        doc = uuid.uuid4()
        kind = "purchase_invoice" if v.voucher_type == "purchase" else "expense_bill"
        rows.append({"i": doc, "c": world.client_id, "t": kind, "n": f"{v.ref}.pdf", "s": 1000, "h": sha, "k": f"p8/{sha}.pdf"})
        links.append({"c": world.client_id, "d": doc, "v": world.vouchers[v.ref]})
    conn.execute(text("INSERT INTO documents (id, client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by) "
                      "VALUES (:i, :c, :t, :n, 'application/pdf', :s, :h, :k, 'clerk')"), rows)
    conn.execute(text("INSERT INTO document_vouchers (client_id, document_id, voucher_id, linked_by) VALUES (:c, :d, :v, 'clerk')"), links)


def add_challans(conn, pack: Pack, world: World) -> None:
    cid = world.client_id
    made: dict[str, object] = {}
    for r in pack.tds_challans:
        if r["challan"] not in made:
            made[r["challan"]] = conn.execute(text(
                "INSERT INTO tds_challans (client_id, kind, financial_year_id, quarter, bsr_code, deposit_date, challan_serial_no, tax_amount, total_amount, "
                "created_by) VALUES (:c, 'tds', :fy, :q, :b, :d, :s, :t, :t, 'clerk') RETURNING id"),
                {"c": cid, "fy": world.fy26, "q": int(r["quarter"]), "b": r["bsr_code"], "d": date.fromisoformat(r["deposit_date"]), "s": r["serial_no"],
                 "t": Decimal(r["tax_amount"])}).scalar_one()
        item = scalar(conn, "SELECT id FROM tds_voucher_items WHERE voucher_id = :v AND item_no = 1", v=world.vouchers[r["item_voucher"]])
        conn.execute(text("INSERT INTO tds_challan_allocations (client_id, challan_id, item_id, amount, created_by) VALUES (:c, :ch, :i, :a, 'clerk')"),
                     {"c": cid, "ch": made[r["challan"]], "i": item, "a": Decimal(r["allocated"])})


def add_gst_returns(conn, pack: Pack, world: World) -> None:
    for r in pack.gst_filed:
        data = {"totals": {"taxable_value": r["gstr1_taxable_value"], "igst": r["gstr1_igst"], "cgst": r["gstr1_cgst"], "sgst": r["gstr1_sgst"],
                           "cess": r["gstr1_cess"]}}
        conn.execute(text("INSERT INTO gst_filed_returns (client_id, gst_registration_id, return_type, period_start, data, entered_by) "
                          "VALUES (:c, :g, 'gstr1', :p, CAST(:d AS jsonb), 'clerk')"),
                     {"c": world.client_id, "g": world.registration, "p": date.fromisoformat(r["return_period"]), "d": json.dumps(data)})


def add_stock(conn, pack: Pack, world: World) -> None:
    cid, fy = world.client_id, world.fy26
    godowns: dict[str, object] = {}
    items: dict[str, object] = {}
    for r in pack.stock_items:
        if r["godown"] not in godowns:
            godowns[r["godown"]] = conn.execute(text("INSERT INTO godowns (client_id, name) VALUES (:c, :n) RETURNING id"),
                                                {"c": cid, "n": r["godown"]}).scalar_one()
        item = conn.execute(text("INSERT INTO gst_items (client_id, name, item_kind, hsn_sac, uqc) VALUES (:c, :n, 'goods', :h, 'NOS') RETURNING id"),
                            {"c": cid, "n": r["item"], "h": r["hsn"]}).scalar_one()
        items[r["item"]] = item
        conn.execute(text("INSERT INTO stock_items (item_id, client_id, sku, default_godown_id) VALUES (:i, :c, :s, :g)"),
                     {"i": item, "c": cid, "s": r["item"], "g": godowns[r["godown"]]})
        conn.execute(text("INSERT INTO stock_opening (client_id, financial_year_id, item_id, godown_id, quantity, value, entered_by) "
                          "VALUES (:c, :fy, :i, :g, :q, :v, 'clerk')"),
                     {"c": cid, "fy": fy, "i": item, "g": godowns[r["godown"]], "q": Decimal(r["opening_qty"]), "v": Decimal(r["opening_value"])})
    conn.execute(text("INSERT INTO inventory_settings (client_id, financial_year_id, valuation_method, negative_stock_mode, set_by) "
                      "VALUES (:c, :fy, 'fifo', 'block', 'clerk')"), {"c": cid, "fy": fy})
    for j in pack.stock_journals:
        jid = uuid.uuid4()
        on = date.fromisoformat(j["date"])
        conn.execute(text("INSERT INTO stock_journals (id, client_id, financial_year_id, journal_type, journal_date, narration, reason_code, reason_note, "
                          "created_by) VALUES (:i, :c, :fy, 'write_off', :d, :n, :rc, :rn, 'clerk')"),
                     {"i": jid, "c": cid, "fy": fy, "d": on, "n": j["reason_note"], "rc": j["reason_code"], "rn": j["reason_note"]})
        conn.execute(text("INSERT INTO stock_journal_lines (journal_id, client_id, line_no, item_id, from_godown_id, quantity) "
                          "VALUES (:j, :c, 1, :i, :g, :q)"), {"j": jid, "c": cid, "i": items[j["item"]], "g": godowns[j["godown"]], "q": Decimal(j["quantity"])})
        conn.execute(text("UPDATE stock_journals SET status = 'approved', approved_by = 'partner', approved_at = now() WHERE id = :j"), {"j": jid})
        conn.execute(text("UPDATE stock_journals SET status = 'posted', journal_number = :n, posted_by = 'partner', posted_at = now() WHERE id = :j"),
                     {"j": jid, "n": j["number"]})
        conn.execute(text("INSERT INTO stock_movements (client_id, financial_year_id, item_id, godown_id, movement_date, kind, direction, quantity, "
                          "journal_id, journal_line_no, created_by) VALUES (:c, :fy, :i, :g, :d, 'write_off', 'out', :q, :j, 1, 'partner')"),
                     {"c": cid, "fy": fy, "i": items[j["item"]], "g": godowns[j["godown"]], "d": on, "q": Decimal(j["quantity"]), "j": jid})


def add_lock_events(conn, pack: Pack, world: World) -> None:
    """The lock and the later unlock of July 2026 as the books' own log shows them (audit_log rows with their original time stamps)."""
    for e in pack.lock_events:
        period = scalar(conn, "SELECT id FROM periods WHERE client_id = :c AND period_start = :s", c=world.client_id, s=date.fromisoformat(e["period_start"]))
        new = {"status": "locked" if e["action"] == "lock" else "open"}
        if e["reason"]:
            new["reason"] = e["reason"]
        conn.execute(text("INSERT INTO audit_log (client_id, actor, action, entity, entity_id, new_data, created_at) "
                          "VALUES (:c, :a, :act, 'period', :p, CAST(:n AS jsonb), :t)"),
                     {"c": world.client_id, "a": e["actor"], "act": e["action"], "p": period, "n": json.dumps(new), "t": datetime.fromisoformat(e["at"])})


# ------------------------------------------------------------------------------------------------------------------- the books' fingerprint


def books_digest(conn, client_id) -> dict:
    """Row counts of every books table of the client and a hash of every voucher and line: equal before and after means the audit changed nothing."""
    counts = {}
    for table in BOOK_TABLES:
        counts[table] = scalar(conn, f"SELECT count(*) FROM {table} WHERE client_id = :c", c=client_id)
    digest = hashlib.sha256()
    for row in conn.execute(text(
            "SELECT v.id::text, v.status, v.voucher_number, v.voucher_date::text, coalesce(v.reference_no, ''), coalesce(v.party_ledger_id::text, ''), "
            "coalesce(v.posted_at::text, ''), l.line_no, l.ledger_id::text, l.debit::text, l.credit::text FROM vouchers v "
            "JOIN voucher_lines l ON l.voucher_id = v.id WHERE v.client_id = :c ORDER BY v.id, l.line_no"), {"c": client_id}):
        digest.update("|".join(str(x) for x in row).encode() + b"\n")
    counts["hash"] = digest.hexdigest()
    return counts


# ------------------------------------------------------------------------------------------------------------------- comparing findings


def strings_in(value) -> set[str]:
    out: set[str] = set()
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            out |= strings_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= strings_in(v)
    return out


def dig(value, path: str):
    for part in path.split("."):
        if isinstance(value, list):
            value = value[int(part)] if part.isdigit() and int(part) < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def actual_findings(report_data: dict) -> list[dict]:
    return [f for c in report_data["checks"] for f in c["findings"]]


def compare_findings(report: Report, pack: Pack, world: World, run_name: str, report_data: dict) -> set[str]:
    """Match the report's findings with expected_findings.csv one to one; returns the ids of the expected findings that matched with evidence."""
    expected = [f for f in pack.findings if f.run == run_name]
    got: dict[tuple, dict] = {}
    for f in actual_findings(report_data):
        key = (run_name, f["check_id"], None if f["finding_date"] is None else date.fromisoformat(str(f["finding_date"])[:10]), money(f["amount"]),
               f["subject_ref"])
        if key in got:
            report.add("findings", f"{run_name}: two findings share {key}")
        got[key] = f
    exp_keys = {f.key for f in expected}
    for key in sorted(set(got) - exp_keys, key=str):
        report.add("findings", f"{run_name}: UNEXPECTED finding (not in expected_findings.csv): {key[1]} {key[2]} {key[3]} '{key[4]}': {got[key]['message']}")
    matched: set[str] = set()
    for e in expected:
        f = got.get(e.key)
        if f is None:
            report.add("findings", f"{run_name}: MISSING {e.id} ({e.kind}): {e.check_id} {e.finding_date} {e.amount} '{e.subject_ref}'")
            continue
        problems = []
        if f["severity"] != e.severity:
            problems.append(f"severity {f['severity']} (expected {e.severity})")
        if money(f.get("disallowance_amount")) != e.disallowance:
            problems.append(f"disallowance {money(f.get('disallowance_amount'))} (expected {e.disallowance})")
        if (f.get("rule_status") or "") != e.rule_status:
            problems.append(f"rule status '{f.get('rule_status')}' (expected '{e.rule_status}')")
        evidence = f.get("evidence") or {}
        if not evidence:
            problems.append("EVIDENCE IS EMPTY")
        strings = strings_in(evidence)
        vouchers = {ref for sid, ref in world.ref_of.items() if sid in strings}
        if vouchers != set(e.evidence_vouchers):
            problems.append(f"evidence vouchers {sorted(vouchers)} (expected {sorted(e.evidence_vouchers)})")
        ledgers = {name for sid, name in world.ledger_name.items() if sid in strings}
        if ledgers != set(e.evidence_ledgers):
            problems.append(f"evidence ledgers {sorted(ledgers)} (expected {sorted(e.evidence_ledgers)})")
        for path, want in e.evidence_values:
            have = dig(evidence, path)
            if have is None or str(have) != want:
                problems.append(f"evidence {path} = {have!r} (expected {want!r})")
        if e.check_id == "A-14" and "days_after_period_end" in evidence:
            problems.append("evidence shows a late-posting reason that must not apply")
        if e.check_id == "A-13" and e.evidence_values and dict(e.evidence_values).get("reason") == "Sunday" and "holiday_name" in evidence:
            problems.append("a plain Sunday must not carry a holiday name")
        if problems:
            report.add("findings", f"{run_name} {e.id} ({e.check_id} '{e.subject_ref}'): " + "; ".join(problems))
        elif evidence:
            matched.add(e.id)
    return matched


def compare_summary(report: Report, pack: Pack, run_name: str, run: dict, report_data: dict) -> None:
    if run["status"] != "completed":
        report.add("summary", f"{run_name}: the run status is {run['status']} (expected completed)")
    by_check = (run.get("summary") or {}).get("by_check", {})
    shown = {c["check_id"]: c for c in report_data["checks"]}
    for (name, check), (n_findings, population) in sorted(pack.summary.items()):
        if name != run_name:
            continue
        entry = by_check.get(check)
        if entry is None:
            report.add("summary", f"{run_name} {check}: no entry in the run summary")
            continue
        if entry.get("error"):
            report.add("summary", f"{run_name} {check}: the check failed inside the run: {entry['error']}")
            continue
        if (entry["findings"], entry["population"]) != (n_findings, population):
            report.add("summary", f"{run_name} {check}: findings/population {entry['findings']}/{entry['population']} (expected {n_findings}/{population})")
        if (len(shown[check]["findings"]), shown[check]["population"]) != (n_findings, population):
            report.add("summary", f"{run_name} {check}: the report shows {len(shown[check]['findings'])} findings and population {shown[check]['population']}")
    expected_checks = {c for (n, c) in pack.summary if n == run_name}
    if set(run["check_ids"]) != expected_checks:
        report.add("summary", f"{run_name}: run covers {sorted(run['check_ids'])} (expected {sorted(expected_checks)})")


def check_controls(report: Report, pack: Pack, world: World, report_data: dict) -> None:
    by_check: dict[str, list[dict]] = {}
    for f in actual_findings(report_data):
        by_check.setdefault(f["check_id"], []).append(f)
    for c in pack.controls:
        blob = " ".join(json.dumps(f.get("evidence"), default=str) + " " + str(f["subject_ref"]) for f in by_check.get(c.check_id, []))
        if c.kind == "voucher":
            target = str(world.vouchers[c.target])
        elif c.kind == "ledger":
            target = str(world.ledgers[c.target])
        else:
            target = c.target
        if target in blob:
            report.add("controls", f"{c.id} ({c.check_id}, {c.kind} {c.target}) was FLAGGED but is a clean control: {c.why}")
    report.bump("controls_checked", len(pack.controls))


def check_report(report: Report, pack: Pack, report_data: dict, run_id, conn, client_id) -> None:
    h = pack.config["headline"]
    totals = report_data["totals"]
    if totals["findings"] != h["findings_fy26"]:
        report.add("report", f"total findings {totals['findings']} (expected {h['findings_fy26']})")
    if totals["by_severity"] != h["by_severity"]:
        report.add("report", f"findings by severity {totals['by_severity']} (expected {h['by_severity']})")
    if totals["disallowance_amount"] != h["disallowance_total"]:
        report.add("report", f"disallowance total {totals['disallowance_amount']} (expected {h['disallowance_total']})")
    pending = sorted(r["rule_key"] for r in report_data["rules_pending"])
    if pending != sorted(h["pending_rule_keys"]):
        report.add("report", f"rules shown as pending {pending} (expected {sorted(h['pending_rule_keys'])})")
    if not all("limit pending verification" in r["line"] for r in report_data["rules_pending"]):
        report.add("report", "a pending rule line does not say 'limit pending verification'")
    for f in actual_findings(report_data):
        if f["check_id"] in ("A-05", "A-06") and "limit pending verification" not in f["message"]:
            report.add("report", f"{f['check_id']} message does not say 'limit pending verification': {f['message']}")
    sheets = load_workbook(io.BytesIO(audit_report.report_xlsx(report_data))).sheetnames
    if len(sheets) != h["report_sheets"] or sheets[0] != "Summary":
        report.add("report", f"Excel report has {len(sheets)} sheets {sheets[:3]}... (expected {h['report_sheets']} starting with Summary)")
    rows = audit_runs.list_findings(conn, client_id, run_id, check_id="A-05")
    if len(rows) != 1 or not rows[0]["evidence"]:
        report.add("report", "list_findings(check A-05) did not return the one finding with its evidence")
    report.bump("report_sheets", len(sheets))


# ------------------------------------------------------------------------------------------------------------------- sampling


def check_sampling(report: Report, pack: Pack) -> None:
    items = [(ref, pack.voucher_by_ref[ref].total) for ref in pack.sampling_population]
    if len(items) != pack.summary[("FY26", "A-03")][1]:
        report.add("sampling", f"the sampling population has {len(items)} items but expected_summary.csv says A-03 has {pack.summary[('FY26', 'A-03')][1]}")
    for s in pack.sampling:
        kw: dict = {"seed": s.seed}
        if s.method == "value":
            kw.update(threshold=str(s.threshold), rest_size=s.rest_size)
        else:
            kw["size"] = s.size
        if s.start is not None:
            kw["start"] = s.start
        first = audit_papers.preview(items, s.method, **kw)
        second = audit_papers.preview(list(reversed(items)), s.method, **kw)     # the same population in another order: the same sample
        if first != list(s.expected):
            report.add("sampling", f"{s.id} ({s.method}, seed {s.seed}): tool drew {first}, hand-derived {list(s.expected)}")
        if second != first:
            report.add("sampling", f"{s.id}: the same seed and population gave a different sample when the population came in another order")
    report.bump("sampling_cases", len(pack.sampling))


# ------------------------------------------------------------------------------------------------------------------- working paper


def code_of(fn, *args, **kwargs) -> str:
    try:
        fn(*args, **kwargs)
    except ServiceError as exc:
        return exc.code
    return "no_error"


def check_paper(report: Report, pack: Pack, world: World, conn, run_id) -> None:
    cid = world.client_id
    reviewer = pack.config["actors"]["reviewer"]
    partner = pack.config["actors"]["partner"]
    pid = None
    items: list[dict] = []
    for st in pack.paper_flow:
        label = f"paper step {st.step} ({st.action})"
        expect = dict(p.split("=", 1) for p in st.expect.split("|")) if "=" in st.expect else {"_": st.expect}
        outcome = None
        try:
            if st.action == "create_paper":
                made = audit_papers.create_paper(conn, cid, run_id, st.arg, reviewer)
                pid = made["id"]
                items = audit_papers.get_paper(conn, cid, pid)["items"]
                outcome = {"status": made["status"], "exceptions": str(made["items"])}
            elif st.action == "review":
                outcome = code_of(audit_papers.send_to_review, conn, cid, pid, reviewer)
            elif st.action == "reopen":
                outcome = code_of(audit_papers.reopen, conn, cid, pid, reviewer)
            elif st.action == "sign_off":
                try:
                    done = audit_papers.sign_off(conn, cid, pid, st.arg, partner)
                    outcome = {"status": audit_papers.get_paper(conn, cid, pid)["status"]} if done.get("ok") else "not_ok"
                except ServiceError as exc:
                    outcome = exc.code
            elif st.action == "decide":
                amount, status, note = st.arg.split("|")
                item = next(i for i in items if Decimal(str(i["amount"])).quantize(CENTS) == Decimal(amount))
                outcome = code_of(audit_papers.decide_item, conn, cid, pid, item["id"], status, note, reviewer)
            elif st.action == "note":
                outcome = code_of(audit_papers.add_note, conn, cid, pid, st.arg, reviewer)
            elif st.action == "sample":
                method, seed, size = st.arg.split("|")
                try:
                    one = audit_papers.sample(conn, cid, pid, method, reviewer, seed=int(seed), size=int(size))
                    two = audit_papers.sample(conn, cid, pid, method, reviewer, seed=int(seed), size=int(size))
                    stored = audit_papers.get_paper(conn, cid, pid)["sample"]
                    same = one["ids"] == two["ids"] == stored["ids"] and stored["seed"] == int(seed) and len(one["ids"]) == int(size)
                    outcome = "repeatable" if same else "differs"
                except ServiceError as exc:
                    outcome = exc.code
            elif st.action in ("sql_update_item", "sql_update_paper", "sql_insert_note"):
                outcome = "rejected" if db_rejects(conn, st.action, pid, cid) else "ACCEPTED"
            elif st.action == "audit_log":
                row = conn.execute(text("SELECT old_data, new_data FROM audit_log WHERE client_id = :c AND entity = 'audit_working_paper' "
                                        "AND entity_id = :p AND action = :a ORDER BY id DESC LIMIT 1"), {"c": cid, "p": pid, "a": st.arg}).first()
                outcome = {"old": (row[0] or {}).get("status"), "new": (row[1] or {}).get("status")} if row else "no_log_row"
        except ServiceError as exc:
            outcome = exc.code
        if isinstance(outcome, dict):
            for k, want in expect.items():
                if str(outcome.get(k)) != want:
                    report.add("paper", f"{label}: {k} = {outcome.get(k)} (expected {want})")
        else:
            want = expect.get("_") or expect.get("code") or st.expect
            got = outcome
            if want != got and not (st.expect == "ok" and got == "no_error"):
                report.add("paper", f"{label}: outcome '{got}' (expected '{want}')")
    report.bump("paper_steps", len(pack.paper_flow))


def db_rejects(conn, action: str, pid, cid) -> bool:
    sql = {"sql_update_item": "UPDATE audit_paper_items SET reviewer_note = 'edited after sign-off' WHERE paper_id = :p",
           "sql_update_paper": "UPDATE audit_working_papers SET conclusion = 'edited after sign-off' WHERE id = :p",
           "sql_insert_note": "INSERT INTO audit_paper_notes (client_id, paper_id, note, created_by) VALUES (:c, :p, 'late note', 'x')"}[action]
    try:
        with conn.begin_nested():
            conn.execute(text(sql), {"p": pid, "c": cid})
    except DBAPIError:
        return True
    return False


# ------------------------------------------------------------------------------------------------------------------- AI summary


def check_ai(report: Report, pack: Pack, world: World, conn, run_id, fakes: list, answers: dict) -> None:
    cid = world.client_id
    owner = pack.config["actors"]["owner"]
    auditor = pack.config["actors"]["auditor"]
    fake = FakeLlmClient([json.dumps({"summary": answers[k]}) for k in ("A-05", "A-08")])
    fakes.append(fake)
    stored = lambda: scalar(conn, "SELECT count(*) FROM audit_ai_summaries WHERE client_id = :c", c=cid)
    gstin = pack.config["client"]["gstin"]
    for st in pack.ai:
        label = f"ai step {st.step} ({st.action})"
        expect = dict(p.split("=", 1) for p in st.expect.split("|")) if "=" in st.expect else {}
        got: dict = {}
        if st.action == "switch_off":
            res = audit_summary.summarise(conn, cid, run_id, actor=auditor, check_id=st.arg, llm_client=fake)
            got = {"status": res.status, "reason": res.reason, "model_requests": len(fake.requests), "summaries_stored": stored()}
        elif st.action == "switch_on":
            ai_settings.set_settings(conn, cid, llm_enabled=True, data_class="synthetic", note="synthetic pack data only", actor=owner)
        elif st.action == "summarise":
            res = audit_summary.summarise(conn, cid, run_id, actor=auditor, check_id=st.arg, llm_client=fake)
            got = {"status": res.status, "suggestion": "yes" if res.is_suggestion else "no", "summaries_stored": stored(), "model_requests": len(fake.requests)}
            if res.status != "ok":
                report.add("ai_summary", f"{label}: summary was {res.status} ({res.reason}): {res.problems}")
            if st.arg == "A-08":
                sent = fake.requests[-1].user if fake.requests else ""
                prompt = conn.execute(text("SELECT prompt_masked FROM llm_calls WHERE id = :i"), {"i": res.llm_call_id}).scalar() or ""
                got["gstin_in_prompt"] = "yes" if (gstin in sent or gstin in prompt) else "no"
            if res.status == "ok":
                row = conn.execute(text("SELECT is_suggestion, paper_id FROM audit_ai_summaries WHERE id = :i"), {"i": res.id}).one()
                if not row[0] or row[1] is not None:
                    report.add("ai_summary", f"{label}: the stored summary is not a plain suggestion")
        elif st.action == "paper_untouched":
            got = {"papers_created_by_summary": scalar(conn, "SELECT count(*) FROM audit_working_papers WHERE client_id = :c AND created_by = :a", c=cid, a=auditor)}
        for k, want in expect.items():
            if str(got.get(k)) != want:
                report.add("ai_summary", f"{label}: {k} = {got.get(k)} (expected {want})")
    report.bump("model_requests", len(fake.requests))


# ------------------------------------------------------------------------------------------------------------------- Form 3CD / Form 26


def check_form(report: Report, pack: Pack, world: World, conn, run25_id) -> None:
    cid = world.client_id
    tester = pack.config["actors"]["reviewer"]
    old = audit_form.form_for_year(conn, cid, world.fy25)
    if old["form_key"] != "form_3cd":
        report.add("form", f"FY 2025-26 uses form {old['form_key']} (expected form_3cd)")
    new = audit_form.form_for_year(conn, cid, world.fy26)
    if new["form_key"] != "form_26" or new["clauses"] != []:
        report.add("form", f"FY 2026-27 form {new['form_key']} with {len(new['clauses'])} clauses (expected form_26 with none: its clause list is not seeded)")
    made = audit_form.create_set(conn, cid, world.fy25, actor=tester)
    out = audit_form.derive(conn, cid, made["id"], run25_id, actor=tester)
    got = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(text(
        "SELECT clause_no, field_key, value, origin FROM audit_form_entries WHERE form_set_id = :s"), {"s": made["id"]})}
    for clause, field_key, value, origin in pack.form:
        if origin == "derived" and got.get((clause, field_key)) != (value, "derived"):
            report.add("form", f"clause {clause} {field_key}: {got.get((clause, field_key))} (expected {(value, 'derived')})")
    skipped = [s["clause_no"] for s in out["skipped"]]
    if skipped != ["18", "35", "40", "44"]:
        report.add("form", f"clauses left for hand entry {skipped} (expected ['18', '35', '40', '44'])")
    finding = scalar(conn, "SELECT id FROM audit_findings WHERE run_id = :r AND check_id = 'A-05'", r=run25_id)
    ids = got.get(("21", "source_finding_ids"))
    if ids is None or str(finding) not in str(ids[0]):
        report.add("form", "clause 21 does not name its source finding")
    for clause, field_key, value, origin in pack.form:
        if origin == "manual":
            audit_form.enter_manual(conn, cid, made["id"], clause, field_key, value, actor=tester)
    audit_form.finalise(conn, cid, made["id"], actor=tester)
    for label, call in (("enter", lambda: audit_form.enter_manual(conn, cid, made["id"], "18", "depreciation_note", "changed", actor=tester)),
                        ("derive", lambda: audit_form.derive(conn, cid, made["id"], run25_id, actor=tester)),
                        ("finalise", lambda: audit_form.finalise(conn, cid, made["id"], actor=tester))):
        if code_of(call) != "form_finalised":
            report.add("form", f"a finalised form set accepted: {label}")
    report.bump("form_entries", len(got))


# ------------------------------------------------------------------------------------------------------------------- the run


def run_pack_p8(conn, pack: Pack) -> Report:
    report = Report()
    network = {"calls": 0}

    def forbidden(*args, **kwargs):
        network["calls"] += 1
        raise NetworkCalled("the acceptance run must never touch the network or the real model")

    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, {"LLM_MODEL": "fake/model"}))
        stack.enter_context(mock.patch("httpx.Client.send", forbidden))
        stack.enter_context(mock.patch("httpx.AsyncClient.send", forbidden))
        stack.enter_context(mock.patch("app.ai.openrouter.OpenRouterClient.__init__", forbidden))

        world = build_world(conn, pack)
        cid = world.client_id
        report.bump("vouchers_fy26", scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = :c AND financial_year_id = :f AND status = 'posted'",
                                           c=cid, f=world.fy26))
        report.bump("vouchers_fy25", scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = :c AND financial_year_id = :f AND status = 'posted'",
                                           c=cid, f=world.fy25))
        before = books_digest(conn, cid)
        auditor = pack.config["actors"]["auditor"]
        r26, r25 = pack.config["run_fy26"], pack.config["run_fy25"]

        run1 = audit_runs.create_run(conn, cid, auditor, world.fy26, r26["from_date"], r26["to_date"], None, r26["params"])
        run25 = audit_runs.create_run(conn, cid, auditor, world.fy25, None, None, r25["checks"], None)
        rep1 = audit_runs.build_report(conn, cid, run1["id"])
        rep25 = audit_runs.build_report(conn, cid, run25["id"])
        row1, row25 = audit_runs.get_run(conn, cid, run1["id"]), audit_runs.get_run(conn, cid, run25["id"])

        matched = compare_findings(report, pack, world, "FY26", rep1) | compare_findings(report, pack, world, "FY25", rep25)
        compare_summary(report, pack, "FY26", row1, rep1)
        compare_summary(report, pack, "FY25", row25, rep25)
        check_controls(report, pack, world, rep1)
        check_report(report, pack, rep1, run1["id"], conn, cid)
        check_sampling(report, pack)
        check_paper(report, pack, world, conn, run1["id"])
        answers = json.loads((pack.root / "fixtures" / "ai_answers.json").read_text(encoding="utf-8"))
        fakes: list = []
        check_ai(report, pack, world, conn, run1["id"], fakes, answers)
        check_form(report, pack, world, conn, run25["id"])

        after = books_digest(conn, cid)
        if after != before:
            changed = [k for k in before if before[k] != after[k]]
            report.add("books_unchanged", f"the audit CHANGED the books: {changed}")
        report.counts["books_rows"] = sum(v for k, v in before.items() if k != "hash")
        if network["calls"]:
            report.add("no_network", f"{network['calls']} attempt(s) to reach the network or the real model")
        for f in fakes:
            if not isinstance(f, FakeLlmClient):
                report.add("no_network", "a model client other than the fake was used")
        report.counts["network_attempts"] = network["calls"]

        # ---- the headline property
        h = pack.config["headline"]
        injected = [f for f in pack.findings if f.run == "FY26" and f.kind == "injected"]
        injected_checks = {f.check_id for f in injected}
        if len(injected) != h["injected_checks"] or injected_checks != {f"A-{n:02d}" for n in range(1, 19)}:
            report.add("headline", f"the pack must inject exactly one error per check A-01..A-18 (found {len(injected)} injected rows)")
        for f in injected:
            if f.id not in matched:
                report.add("headline", f"injected error {f.id} ({f.check_id}: {f.subject_ref}) is not in the audit report with its evidence")
        if report.problems["findings"]:
            report.add("headline", "the report differs from the expected findings (see the findings section)")
        if report.problems["controls"]:
            report.add("headline", "a clean control was flagged")
        if report.problems["books_unchanged"]:
            report.add("headline", "the books changed during the audit")
        report.counts["findings_matched_with_evidence"] = len(matched)
        report.counts["injected_errors"] = len(injected)
        report.counts["findings_fy26"] = len(actual_findings(rep1))
        report.counts["findings_fy25"] = len(actual_findings(rep25))
        for key, want in (("vouchers_fy26", h["vouchers_fy26"]), ("vouchers_fy25", h["vouchers_fy25"]), ("model_requests", h["model_requests"])):
            if report.counts.get(key) != want:
                report.add("headline", f"{key} = {report.counts.get(key)} (expected {want})")
    return report


__all__ = ["SECTIONS", "Report", "format_report", "run_pack_p8"]
