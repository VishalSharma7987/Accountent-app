"""Runs the Phase 7 pack (docs/test-packs/phase7-*) against the REAL services with a FAKE language model.

One run builds two clients inside the caller's transaction (rolled back by the caller):
  A  "Pack Traders": GST registration, ledgers, mappings, AI switch ON (synthetic). 12 sample documents + a bank statement text go through
     the real chain  text -> gateway (masking, audit) -> schema -> engine checks -> draft builder -> approval queue -> accountant's scripted
     edits -> accept -> approve -> post, then a bank CSV with narration suggestions, a Tally import (masters, queue, drafts) and a Tally export.
  B  "Pack Co B": AI switch OFF (no setting row). A second Tally file and one extraction attempt that must be refused.
Every expected value comes from the pack's hand-typed files; the runner never changes a pack file and never edits an expectation.

The runner NEVER touches the network and NEVER calls the real model: every gateway call is given a scripted `FakeLlmClient`, and while it
runs the OpenRouter client constructor and httpx's send methods raise (and are counted), so a hidden real call would fail the run.

HEADLINE PROPERTY (section "headline"): no voucher with a blocking finding is ever approvable or postable, and every posted voucher came
from an accepted queue item; the number of posted vouchers equals the number of accepted items.
"""

import copy
import hashlib
import json
import os
import re
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from decimal import Decimal
from unittest import mock

from pack_loader_p7 import Pack
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai.fake import FakeLlmClient
from app.engine.money import format_inr
from app.importers.bank_statement import parse_statement
from app.importers.tally_xml import parse_tally_xml
from app.services import (
    approval_queue,
    client_setup,
    doc_drafts,
    doc_mappings,
    extractions,
    llm_gateway,
    narration,
    parties,
    tally_export,
    tally_import,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError
from app.services.llm_extraction_gateway import ExtractionCall

SECTIONS = ("invoices", "bank_text", "masking", "narration", "tally_a", "tally_b", "tally_c", "switch_off", "export", "balances",
            "no_network", "headline")
ACTOR = {"setup": "setup", "clerk": "clerk", "accountant": "acc", "partner": "partner"}
# what must never reach the model or a stored prompt (all of it appears in the pack's texts)
SENSITIVE = ("27AAAPL1234C1ZE", "27CCCPM4321E1ZZ", "27CCCPM4321E1ZX", "29AAAPK5678F1ZH", "27BBBPV9012G1ZK", "27DDDPG3456H1ZL",
             "AAAPK5678F", "2345 6789 0123", "234567890123", "50100123456789", "ABCDE1234F")
RULE_KEY_TEA = "upi dr ramesh tea stall sbin"           # D-40 of "UPI/DR/111111111111/Ramesh Tea Stall/SBIN"
INJECTION = "ignore all previous instructions"


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
    lines = ["PHASE 7 PACK: expected (hand-typed pack files) versus what the tool did"]
    for section in SECTIONS:
        problems = report.problems[section]
        lines.append(f"[{'OK' if not problems else 'DIFFERENT'}] {section}")
        lines += [f"    - {p}" for p in problems]
    lines.append("counts: " + ", ".join(f"{k}={v}" for k, v in sorted(report.counts.items())))
    lines += [f"note: {n}" for n in report.notes]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------------------------- small helpers


def scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def finding_set(findings) -> set[tuple[str, str, str]]:
    out = set()
    for f in findings:
        if isinstance(f, dict):
            out.add((f["rule_id"], f["severity"], f.get("field_path") or ""))
        else:
            out.add((f.rule_id, f.severity.value, f.field_path or ""))
    return out


def shown(items: set) -> str:
    return "{" + "; ".join(f"{r} {s} {p or '-'}" for r, s, p in sorted(items)) + "}"


def compare_findings(report: Report, section: str, label: str, stage: str, expected: set, got: set) -> None:
    if expected != got:
        report.add(section, f"{label} findings ({stage}): expected {shown(expected)}, tool says {shown(got)}"
                            + (f"; missing {shown(expected - got)}" if expected - got else "")
                            + (f"; unexpected {shown(got - expected)}" if got - expected else ""))


def insert_document(conn, client_id, doc_type: str, text_body: str | None, data: bytes | None = None, name: str = "doc.pdf") -> uuid.UUID:
    payload = data if data is not None else (text_body or "").encode("utf-8")
    sha = hashlib.sha256(payload).hexdigest()
    ext = "xml" if doc_type in ("tally_xml", "tally_export") else "pdf"
    content = "application/xml" if ext == "xml" else "application/pdf"
    doc = conn.execute(text(
        "INSERT INTO documents (client_id, doc_type, original_filename, content_type, size_bytes, sha256, storage_key, uploaded_by, page_count) "
        "VALUES (:c, :t, :n, :ct, :s, :h, :k, 'clerk', :pc) RETURNING id"),
        {"c": client_id, "t": doc_type, "n": name, "ct": content, "s": len(payload), "h": sha,
         "k": f"{str(client_id)[:8]}/{sha}.{ext}", "pc": 1 if text_body is not None else None}).scalar_one()
    if text_body is not None:
        conn.execute(text("INSERT INTO document_texts (client_id, document_id, page_no, method, engine_version, text) "
                          "VALUES (:c, :d, 1, 'pdf_text', 'p7-pack', :t)"), {"c": client_id, "d": doc, "t": text_body})
    return doc


class FakeGateway:
    """Package D's gateway protocol on top of package C's REAL gateway (masking, switch, audit rows) with a scripted fake client."""

    def __init__(self, fake: FakeLlmClient):
        self.fake = fake

    def call(self, conn, *, client_id, document_id, request, prompt_version, actor):
        r = llm_gateway.call(conn, client_id=client_id, purpose=request.purpose, system=request.system, user=request.user,
                             prompt_version=prompt_version, actor=actor, document_id=document_id, llm_client=self.fake,
                             model="fake/model", max_tokens=request.max_tokens)
        if r.status == "ok" and r.data is not None:
            return ExtractionCall("ok", r.call_id, json.dumps(r.data, default=str), r.message)
        return ExtractionCall("blocked" if r.status == "blocked" else "error", r.call_id, None, r.message)


class Boom(FakeLlmClient):
    """A model that must not be called (a rule answered, or the switch is off)."""

    def __init__(self):
        super().__init__([])

    def complete(self, request):
        raise AssertionError("the model was called where the pack says it must not be")


# ------------------------------------------------------------------------------------------------------------------- the worlds


@dataclass
class World:
    client_id: object
    ids: dict
    docs: dict = field(default_factory=dict)        # pack doc id -> documents.id
    items: dict = field(default_factory=dict)       # pack item id -> approval_queue_items.id


def build_world_a(conn, pack: Pack) -> World:
    c = pack.config["client"]
    created = client_setup.create_client(
        conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]), fy_start=c["fy_start"],
        actor=ACTOR["setup"], proprietor_name=c["proprietor"])
    cid, ids = created.client_id, dict(created.ledger_ids)
    reg_id = uuid.uuid4()
    conn.execute(text("INSERT INTO gst_registrations (id, client_id, gstin, state_code, registration_type, effective_from) "
                      "VALUES (:r, :c, :g, :s, 'regular', :d)"),
                 {"r": reg_id, "c": cid, "g": c["gstin"], "s": c["gstin"][:2], "d": c["gst_effective_from"]})
    for led in pack.config["ledgers"]:
        ids[led["name"]] = client_setup.add_ledger(conn, cid, led["name"], led["group"], actor=ACTOR["setup"])
        if led.get("role"):
            conn.execute(text("INSERT INTO gst_ledger_roles (registration_id, client_id, role, ledger_id) VALUES (:r, :c, :role, :l)"),
                         {"r": reg_id, "c": cid, "role": led["role"], "l": ids[led["name"]]})
    for p in pack.config["parties"]:
        parties.set_party(conn, cid, ids[p["ledger"]], gstin=p["gstin"], state_code=p["state_code"], bill_wise=False, actor=ACTOR["setup"])
    for m in pack.config["party_mappings"]:
        doc_mappings.put_party_mapping(conn, cid, match_kind="gstin", match_key=m["gstin"], party_ledger_id=ids[m["ledger"]],
                                       actor=ACTOR["accountant"])
    for m in pack.config["line_mappings"]:
        doc_mappings.put_line_mapping(conn, cid, match_kind="hsn_sac", match_key=m["hsn"], ledger_id=ids[m["ledger"]], actor=ACTOR["accountant"])
    conn.execute(text("INSERT INTO client_ai_settings (client_id, llm_enabled, enabled_by, enabled_at, note, updated_by) "
                      "VALUES (:c, true, 'owner', now(), :n, 'owner')"), {"c": cid, "n": c["ai_note"]})
    return World(cid, ids)


def build_world_b(conn, pack: Pack) -> World:
    c = pack.config["client_b"]
    created = client_setup.create_client(
        conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]), fy_start=c["fy_start"],
        actor=ACTOR["setup"], proprietor_name=c["proprietor"])
    ids = dict(created.ledger_ids)
    for led in c["ledgers"]:
        ids[led["name"]] = client_setup.add_ledger(conn, created.client_id, led["name"], led["group"], actor=ACTOR["setup"])
    return World(created.client_id, ids)


# ------------------------------------------------------------------------------------------------------------------- queue item helpers


def item_state(conn, item_id) -> dict:
    r = conn.execute(text("SELECT status, blocking_count, warning_count, draft_voucher_id, findings FROM approval_queue_items WHERE id = :i"),
                     {"i": item_id}).one()
    return {"status": r.status, "blocking": r.blocking_count, "warnings": r.warning_count, "draft": r.draft_voucher_id,
            "findings": finding_set(r.findings or [])}


def voucher_lines(conn, voucher_id) -> dict[str, tuple[Decimal, Decimal]]:
    rows = conn.execute(text("SELECT l.name, coalesce(sum(vl.debit), 0), coalesce(sum(vl.credit), 0) FROM voucher_lines vl "
                             "JOIN ledgers l ON l.id = vl.ledger_id WHERE vl.voucher_id = :v GROUP BY l.name"), {"v": voucher_id})
    return {r[0]: (r[1], r[2]) for r in rows}


def attack_approve(conn, report: Report, label: str, voucher_id) -> None:
    """A queued draft that is not accepted: the service refuses to approve it (friendly message) AND the database refuses it."""
    try:
        vouchers.approve(conn, voucher_id, actor=ACTOR["partner"])
    except ServiceError as exc:
        if exc.code != "queue_not_accepted":
            report.add("headline", f"{label}: approve before accept was refused with '{exc.code}', expected 'queue_not_accepted'")
    else:
        report.add("headline", f"{label}: a draft that is not accepted was APPROVED by the service")
    try:
        with conn.begin_nested():
            conn.execute(text("UPDATE vouchers SET status = 'approved', approved_by = 'x', approved_at = now() WHERE id = :v"), {"v": voucher_id})
    except DBAPIError:
        pass
    else:
        report.add("headline", f"{label}: the DATABASE let a draft that is not accepted become approved")
    report.bump("approve_refused_before_accept")


def run_script(conn, report: Report, section: str, pack: Pack, world: World, item: str, results: dict) -> None:
    """The accountant's scripted actions on one queue item (accountant_script.csv)."""
    cid, item_id = world.client_id, world.items[item]
    res = results.setdefault(item, {"first_accept": "na", "number": ""})
    seen_accept = False
    for step in pack.script.get(item, []):
        a, args = step.action, step.args
        state = item_state(conn, item_id)
        if a in ("accept", "accept_clean", "reject") and state["draft"] is not None and state["status"] in ("pending", "in_review"):
            attack_approve(conn, report, f"{item} step {step.step}", state["draft"])
        try:
            if a == "accept":
                acks = [{"rule_id": p.split("|")[0], "field_path": p.split("|")[1]} for p in args[0][0].split(";") if p]
                approval_queue.accept(conn, cid, item_id, acknowledge=acks, actor=ACTOR["accountant"])
                if not seen_accept:
                    res["first_accept"] = "ok"
            elif a == "accept_clean":
                out = approval_queue.accept_clean(conn, cid, [item_id], actor=ACTOR["accountant"])
                if out["accepted"] != [str(item_id)]:
                    report.add(section, f"{item}: accept_clean refused: {out['refused']}")
                if not seen_accept:
                    res["first_accept"] = "ok" if out["accepted"] else "refused"
            elif a == "accept_refused":
                try:
                    approval_queue.accept(conn, cid, item_id, actor=ACTOR["accountant"])
                except ServiceError as exc:
                    if exc.code != args[0][0]:
                        report.add(section, f"{item}: accept was refused with '{exc.code}', expected '{args[0][0]}'")
                else:
                    report.add(section, f"{item}: accept SUCCEEDED but the pack expects it to be refused ({args[0][0]})")
                if not seen_accept:
                    res["first_accept"] = "refused"
            elif a == "edit":
                approval_queue.edit_fields(conn, cid, item_id, edits=[(r[0], r[1]) for r in args], actor=ACTOR["accountant"])
            elif a == "add_line":
                line = json.loads((pack.root / args[0][0]).read_text(encoding="utf-8"))
                current = copy.deepcopy(approval_queue.get_detail(conn, cid, item_id)["current"])
                current["lines"].append(line)
                approval_queue.edit_fields(conn, cid, item_id, payload=current, actor=ACTOR["accountant"])
            elif a == "party_mapping":
                doc_mappings.put_party_mapping(conn, cid, match_kind=args[0][0], match_key=args[0][1], party_ledger_id=world.ids[args[0][2]],
                                               actor=ACTOR["accountant"])
            elif a == "reject":
                approval_queue.reject(conn, cid, item_id, reason=args[0][0], actor=ACTOR["accountant"])
            elif a == "approve_post":
                draft = state["draft"]
                if state["status"] != "accepted" or draft is None:
                    report.add(section, f"{item}: approve/post asked for an item that is {state['status']}")
                else:
                    vouchers.approve(conn, draft, actor=ACTOR["partner"])
                    res["number"] = vouchers.post(conn, draft, actor=ACTOR["partner"])
            elif a == "leave":
                pass
        except ServiceError as exc:
            report.add(section, f"{item} step {step.step} ({a}): the tool refused with '{exc.code}': {exc.message}")
        if a in ("accept", "accept_clean", "accept_refused"):
            seen_accept = True


def check_item(conn, report: Report, section: str, pack: Pack, world: World, item: str, initial: dict, results: dict) -> None:
    """Final state of one queue item against expected_decisions.csv / expected_findings.csv / expected_postings.csv."""
    dec = pack.decisions[item]
    st = item_state(conn, world.items[item])
    res = results.get(item, {"first_accept": "na", "number": ""})
    voucher_status = "none"
    if st["draft"] is not None:
        voucher_status = scalar(conn, "SELECT status FROM vouchers WHERE id = :v", v=st["draft"])
    checks = [
        ("draft created at first", "yes" if initial["draft"] is not None else "no", "yes" if dec.draft_initially else "no"),
        ("first accept attempt", res["first_accept"], dec.first_accept),
        ("queue status", st["status"], dec.final_queue_status),
        ("voucher status", voucher_status, dec.final_voucher_status),
        ("blocking findings at first", initial["blocking"], dec.blocking_initial),
        ("warnings at first", initial["warnings"], dec.warnings_initial),
        ("blocking findings at the end", st["blocking"], dec.blocking_final),
        ("warnings at the end", st["warnings"], dec.warnings_final),
    ]
    if dec.voucher_number:
        checks.append(("voucher number", res["number"], dec.voucher_number))
    for what, got, want in checks:
        if got != want:
            report.add(section, f"{item}: {what}: expected {want}, tool says {got}")
    compare_findings(report, section, item, "initial", pack.findings.get((item, "initial"), set()), initial["findings"])
    compare_findings(report, section, item, "final", pack.findings.get((item, "final"), set()), st["findings"])
    if dec.final_voucher_status == "posted" and st["draft"] is not None:
        want = {ledger: (dr, cr) for ledger, dr, cr in pack.postings[item]}
        got = voucher_lines(conn, st["draft"])
        for ledger in sorted(set(want) | set(got)):
            w, g = want.get(ledger, (Decimal(0), Decimal(0))), got.get(ledger, (Decimal(0), Decimal(0)))
            if w != g:
                report.add(section, f"{item}: posted lines {ledger}: expected Dr {format_inr(w[0])} Cr {format_inr(w[1])}, "
                                    f"tool says Dr {format_inr(g[0])} Cr {format_inr(g[1])}")
    report.bump("items_checked")


# ------------------------------------------------------------------------------------------------------------------- invoices (client A)


def run_documents(conn, report: Report, pack: Pack, w: World, fakes: list, initials: dict, results: dict) -> None:
    """Phase 1: every document that arrives first is read by the fake model, checked and drafted (nothing is posted yet)."""
    for doc in [d for d in pack.docs if d.arrives == "first"]:
        extract_and_build(conn, report, pack, w, doc, fakes, initials)


def extract_and_build(conn, report: Report, pack: Pack, w: World, doc, fakes: list, initials: dict) -> None:
    cid = w.client_id
    doc_db = insert_document(conn, cid, doc.doc_type, doc.text, name=f"{doc.doc_id}.pdf")
    w.docs[doc.doc_id] = doc_db
    answers = pack.answers[doc.doc_id]
    fake = FakeLlmClient([json.dumps(a) for a in answers])
    fakes.append(fake)
    gateway = FakeGateway(fake)
    out = None
    for attempt in range(len(answers)):
        out = extractions.run_llm_extraction(conn, client_id=cid, document_id=doc_db, actor=ACTOR["clerk"], gateway=gateway)
        if attempt == 0 and len(answers) > 1:
            if out.status != "invalid":
                report.add("invoices", f"{doc.doc_id}: first scripted answer should be refused as invalid (D-04), tool says '{out.status}'")
            compare_findings(report, "invoices", doc.doc_id, "attempt1", pack.findings.get((doc.doc_id, "attempt1"), set()),
                             finding_set(out.findings))
            if conn.execute(text("SELECT count(*) FROM approval_queue_items WHERE document_id = :d"), {"d": doc_db}).scalar_one() != 0:
                report.add("invoices", f"{doc.doc_id}: an invalid extraction must not create a queue item")
    if out.status != "ok":
        report.add("invoices" if doc.doc_type != "bank_statement" else "bank_text", f"{doc.doc_id}: extraction status '{out.status}': {out.message}")
        return
    if doc.doc_type == "bank_statement":
        compare_findings(report, "bank_text", doc.doc_id, "initial", pack.findings.get((doc.doc_id, "initial"), set()), finding_set(out.findings))
        if conn.execute(text("SELECT count(*) FROM approval_queue_items WHERE document_id = :d"), {"d": doc_db}).scalar_one() != 0:
            report.add("bank_text", f"{doc.doc_id}: a bank statement text must never create a queue item or a voucher")
        return
    built = doc_drafts.build_for_document(conn, cid, doc_db, out.extraction_id, actor=ACTOR["clerk"])
    w.items[doc.doc_id] = built.queue_item_id
    st = item_state(conn, built.queue_item_id)
    initials[doc.doc_id] = st


def run_invoices_phase2(conn, report: Report, pack: Pack, w: World, results: dict) -> None:
    for doc in [d for d in pack.docs if d.arrives == "first" and d.doc_type != "bank_statement"]:
        if doc.doc_id in w.items:
            run_script(conn, report, "invoices", pack, w, doc.doc_id, results)


# ------------------------------------------------------------------------------------------------------------------- masking evidence


def check_masking(conn, report: Report, pack: Pack, w: World, fakes: list) -> None:
    rows = conn.execute(text("SELECT document_id, purpose, status, masking_applied, masking_report, prompt_masked, response_raw "
                             "FROM llm_calls WHERE client_id = :c AND document_id IS NOT NULL"), {"c": w.client_id}).all()
    by_doc: dict[str, list] = {}
    inverse = {v: k for k, v in w.docs.items()}
    for r in rows:
        by_doc.setdefault(inverse.get(r.document_id, "?"), []).append(r)
    kinds = {"gstin": "GSTIN", "pan": "PAN", "aadhaar": "AADHAAR", "account": "ACCOUNT"}
    for doc_id, want in pack.masking.items():
        calls = [r for r in by_doc.get(doc_id, []) if r.status != "blocked"]
        if len(calls) != want["calls"]:
            report.add("masking", f"{doc_id}: expected {want['calls']} model call(s) stored, tool says {len(calls)}")
        for r in calls:
            counts = (r.masking_report or {}).get("counts", {})
            for key, kind in kinds.items():
                if counts.get(kind, 0) != want[key]:
                    report.add("masking", f"{doc_id}: masked {kind} expected {want[key]}, llm_calls.masking_report says {counts.get(kind, 0)}")
            if not r.masking_applied:
                report.add("masking", f"{doc_id}: a call was stored without masking_applied")
            if (r.masking_report or {}).get("data_class") != "synthetic":
                report.add("masking", f"{doc_id}: the data class of the client is not recorded as synthetic on the call")
    for r in rows:
        for secret in SENSITIVE:
            if secret in (r.prompt_masked or "") or secret in (r.response_raw or ""):
                report.add("masking", f"llm_calls holds the unmasked value '{secret[:4]}...' for a call on {inverse.get(r.document_id, '?')}")
        if "sk-or-" in (r.prompt_masked or "") + (r.response_raw or ""):
            report.add("masking", "llm_calls holds key-like text")
    seen_system_injection = False
    for fake in fakes:
        for req in fake.requests:
            for secret in SENSITIVE:
                if secret in req.user or secret in req.system:
                    report.add("masking", f"the fake model RECEIVED the unmasked value '{secret[:4]}...'")
            if INJECTION in req.system.lower():
                seen_system_injection = True
    if seen_system_injection:
        report.add("masking", "text from a document reached the SYSTEM prompt (it must only ever be data in the user message)")
    # the injected sentence of P7-03 reached the model only as DATA, between the document markers
    fake3 = next((f for f in fakes if f.requests and INJECTION in f.requests[0].user.lower()), None)
    if fake3 is None:
        report.add("masking", "P7-03: the hidden instruction text did not reach the (fake) model as document data")
    else:
        user = fake3.requests[0].user
        if not (user.index("<<<DOCUMENT_START>>>") < user.lower().index(INJECTION) < user.index("<<<DOCUMENT_END>>>")):
            report.add("masking", "P7-03: the hidden instruction text is not inside the document data block")
    # tokens are restored locally: the stored answer holds tokens, the stored extraction holds the real GSTIN
    r2 = [r for r in by_doc.get("P7-02", []) if r.status == "ok"]
    if r2 and "[GSTIN_1]" not in (r2[0].response_raw or ""):
        report.add("masking", "P7-02: the stored raw answer should hold the masking token [GSTIN_1]")
    got = conn.execute(text("SELECT payload -> 'supplier_gstin' ->> 'value' FROM extractions WHERE client_id = :c AND document_id = :d"),
                       {"c": w.client_id, "d": w.docs["P7-02"]}).scalar()
    if got != "29AAAPK5678F1ZH":
        report.add("masking", f"P7-02: the token was not restored locally; stored supplier GSTIN is {got}")


# ------------------------------------------------------------------------------------------------------------------- bank narrations


def run_narration(conn, report: Report, pack: Pack, w: World, fakes: list) -> None:
    cid, bank = w.client_id, pack.config["bank"]
    parsed = parse_statement(pack.bank_csv, bank["mapping"], bank["opening_balance"], bank["closing_balance"])
    if parsed.problems or len(parsed.lines) != 6:
        report.add("narration", f"the bank CSV did not parse cleanly: {parsed.problems}")
        return
    stmt = conn.execute(
        text("INSERT INTO bank_statements (client_id, bank_ledger_id, file_name, file_sha256, period_from, period_to, opening_balance, "
             "closing_balance, imported_by) VALUES (:c, :b, 'statement_june_2026.csv', :h, '2026-06-01', '2026-06-30', :o, :cl, 'setup') RETURNING id"),
        {"c": cid, "b": w.ids[bank["ledger"]], "h": hashlib.sha256(pack.bank_csv).hexdigest(), "o": bank["opening_balance"],
         "cl": bank["closing_balance"]}).scalar_one()
    line_ids = {}
    for n, ln in enumerate(parsed.lines, start=1):
        line_ids[n] = conn.execute(
            text("INSERT INTO bank_statement_lines (client_id, statement_id, line_no, txn_date, description, debit, credit) "
                 "VALUES (:c, :s, :n, :d, :t, :db, :cr) RETURNING id"),
            {"c": cid, "s": stmt, "n": n, "d": ln.txn_date, "t": ln.description, "db": ln.debit, "cr": ln.credit}).scalar_one()
    for direction, key, ledger, count in pack.narration_rules:     # rules the accountant had learned earlier (makes line 3 ambiguous)
        conn.execute(text("INSERT INTO narration_rules (client_id, direction, narration_key, ledger_id, approved_count, created_by) "
                          "VALUES (:c, :d, :k, :l, :n, 'acc')"), {"c": cid, "d": direction, "k": key, "l": w.ids[ledger], "n": count})
    for st in pack.narration:
        label = f"narration step {st.step} (line {st.line_no})"
        spec = st.model
        if st.step == 6:   # the client's switch is turned OFF for the last line
            conn.execute(text("UPDATE client_ai_settings SET llm_enabled = false, enabled_by = NULL, enabled_at = NULL WHERE client_id = :c"), {"c": cid})
        if spec is None:
            fake = Boom()
        elif "pick" in spec:
            name, conf = spec["pick"], spec["confidence"]

            def respond(request, name=name, conf=conf):
                code = re.search(rf"^(L\d+): {re.escape(name)}$", request.user, re.MULTILINE).group(1)
                return json.dumps({"choice": code, "confidence": conf})

            fake = FakeLlmClient(respond)
        else:
            fake = FakeLlmClient([spec["raw"]])
        fakes.append(fake)
        try:
            res = narration.suggest(conn, cid, line_ids[st.line_no], actor=ACTOR["accountant"], llm_client=fake)
        except AssertionError as exc:
            report.add("narration", f"{label}: {exc}")
            continue
        called = len(fake.requests)
        if called != st.model_called:
            report.add("narration", f"{label}: model calls expected {st.model_called}, tool made {called}")
        if res.status != st.status:
            report.add("narration", f"{label}: status expected {st.status}, tool says {res.status} ({res.message})")
        if st.source or st.ledger:
            if res.suggestion is None:
                report.add("narration", f"{label}: expected a suggestion from the {st.source} for {st.ledger}, none was made")
            elif (res.suggestion.source, res.suggestion.ledger_name) != (st.source, st.ledger):
                report.add("narration", f"{label}: expected {st.source} / {st.ledger}, tool says {res.suggestion.source} / "
                                        f"{res.suggestion.ledger_name}")
        elif res.suggestion is not None:
            report.add("narration", f"{label}: no suggestion was expected, tool selected {res.suggestion.ledger_name}")
        if st.status == "ambiguous":
            got = "|".join(f"{c['ledger_name']}:{c['count']}" for c in res.ambiguous)
            if got != st.detail:
                report.add("narration", f"{label}: candidates expected {st.detail}, tool says {got}")
        elif st.status in ("none", "llm_blocked") and st.detail.lower() not in (res.message or "").lower():
            report.add("narration", f"{label}: message should mention '{st.detail}', tool says '{res.message}'")
        if st.step == 1 and called:
            sent = fake.requests[0].user
            if "Ramesh Tea Stall" not in sent or "150.00" in sent or str(w.ids["Tea Expense"]) in sent:
                report.add("narration", f"{label}: the prompt must hold the narration and ledger NAMES only (no amount, no id)")
        if st.step == 5 and called and "ABCDE1234F" in fake.requests[0].user:
            report.add("narration", f"{label}: the PAN in the narration reached the model")
        if res.suggestion is not None and st.decision == "accept":
            narration.accept_suggestion(conn, cid, res.suggestion.id, actor=ACTOR["accountant"])
        elif res.suggestion is not None and st.decision == "reject":
            narration.reject_suggestion(conn, cid, res.suggestion.id, actor=ACTOR["accountant"])
        if st.rule_count_after is not None:
            got = scalar(conn, "SELECT approved_count FROM narration_rules WHERE client_id = :c AND narration_key = :k", c=cid, k=RULE_KEY_TEA)
            if got != st.rule_count_after:
                report.add("narration", f"{label}: rule count expected {st.rule_count_after}, tool says {got}")
        if st.step == 5 and scalar(conn, "SELECT count(*) FROM narration_rules WHERE client_id = :c AND narration_key LIKE 'payment to mehta%'",
                                   c=cid) != 0:
            report.add("narration", f"{label}: a rejected model suggestion taught a rule")
    n_vouchers = scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = :c AND narration ILIKE '%tea stall%'", c=cid)
    if n_vouchers != 0:
        report.add("narration", "a narration suggestion created a voucher (D-44)")
    if scalar(conn, "SELECT count(*) FROM llm_calls WHERE client_id = :c AND purpose = 'narration_suggestion' AND status = 'ok'", c=cid) != \
            pack.config["headline"]["llm_calls_narration_ok"]:
        report.add("narration", "number of stored narration model calls differs from headline.llm_calls_narration_ok")


# ------------------------------------------------------------------------------------------------------------------- Tally


def kv(text_value: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in text_value.split(";") if p)


def run_tally(conn, report: Report, pack: Pack, w: World, section: str, key: str, xml_name: str, numbers: dict[str, str],
              decisions: dict[str, tuple[str, ...]], results: dict, initials: dict) -> None:
    """One Tally file: import report, master decisions, apply, queue, the accountant's scripted actions."""
    exp = {k: v for (s, k), v in pack.tally.items() if s == key}
    cid = w.client_id
    xml = pack.tally_files[xml_name]
    doc = insert_document(conn, cid, "tally_xml", None, data=xml, name=xml_name)
    imp = tally_import.import_xml(conn, cid, doc, xml, actor=ACTOR["clerk"])
    rep = imp.report
    if rep["counts"] != {k: int(v) for k, v in kv(exp["counts"]).items()}:
        report.add(section, f"report counts: expected {exp['counts']}, tool says {rep['counts']}")
    if rep["vouchers"]["by_type"] != {k: int(v) for k, v in kv(exp["by_type"]).items()}:
        report.add(section, f"voucher types: expected {exp['by_type']}, tool says {rep['vouchers']['by_type']}")
    if rep["vouchers"]["drafted_later"] != int(exp["drafted_later"]):
        report.add(section, f"vouchers to be drafted: expected {exp['drafted_later']}, tool says {rep['vouchers']['drafted_later']}")
    opening = {r["name"]: r["opening_balance_reported"] for r in rep["ledgers"] if r["opening_balance_reported"] is not None}
    if opening != kv(exp["opening_reported"]):
        report.add(section, f"opening balances reported: expected {exp['opening_reported']}, tool says {opening}")
    if rep["opening_balances_not_applied"] is not True and exp.get("opening_balances_not_applied") == "true":
        report.add(section, "D-33: opening balances must be reported as NOT applied")
    if key == "import_a":
        skipped = sorted(f"{s['number']}:{s['reason_rule']}" for s in rep["vouchers"]["skipped"])
        if skipped != sorted(exp["skipped"].split(";")):
            report.add(section, f"skipped vouchers: expected {exp['skipped']}, tool says {';'.join(skipped)}")
        if rep["bill_allocations_not_imported"] != int(exp["bill_allocations_not_imported"]):
            report.add(section, "bill allocations reported differ from the pack")
        try:
            tally_import.queue_vouchers(conn, cid, imp.import_id, xml, actor=ACTOR["clerk"])
        except ServiceError as exc:
            if exc.code != exp["early_queue_refused"]:
                report.add(section, f"queueing before the masters are decided: expected {exp['early_queue_refused']}, tool says {exc.code}")
        else:
            report.add(section, "vouchers were queued before the masters were decided (D-31)")
    n = tally_import.confirm_exact_matches(conn, cid, imp.import_id, actor=ACTOR["accountant"])
    if n != int(exp["confirmed_exact"]):
        report.add(section, f"exact matches confirmed: expected {exp['confirmed_exact']}, tool says {n}")
    masters = {m["source_name"]: m for m in tally_import.list_masters(conn, cid, kind="ledger")}
    for name, decision in decisions.items():
        tally_import.set_master_decision(conn, cid, masters[name]["id"], decision=decision[0], actor=ACTOR["accountant"])
    applied = tally_import.apply_masters(conn, cid, imp.import_id, xml, actor=ACTOR["accountant"])
    if "ledgers_created" in exp and applied["created"]["ledgers"] != int(exp["ledgers_created"]):
        report.add(section, f"ledgers created by apply: expected {exp['ledgers_created']}, tool says {applied['created']['ledgers']}")
    before = scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=cid)
    queued = tally_import.queue_vouchers(conn, cid, imp.import_id, xml, actor=ACTOR["clerk"])
    for what, got in (("queued", queued.queued), ("drafted", queued.drafted), ("needs_review", queued.needs_review)):
        if got != int(exp[what]):
            report.add(section, f"{what}: expected {exp[what]}, tool says {got}")
    if queued.drafted != scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = :c", c=cid) - before:
        report.add(section, "the number of drafts created differs from the number reported")
    if key == "import_a":
        again = tally_import.queue_vouchers(conn, cid, imp.import_id, xml, actor=ACTOR["clerk"])   # D-37: nothing is queued twice
        if again.queued != int(exp["second_run_queued"]):
            report.add(section, f"second run queued {again.queued}, expected {exp['second_run_queued']} (D-37)")
        got = sorted(s["reason_rule"] for s in again.skipped)
        if got != sorted(exp["second_run_skipped"].split(";")):
            report.add(section, f"second run skipped: expected {exp['second_run_skipped']}, tool says {';'.join(got)}")
    rows = conn.execute(text("SELECT id, edited_payload ->> 'number' AS number FROM approval_queue_items WHERE client_id = :c AND tally_import_id = :i"),
                        {"c": cid, "i": imp.import_id}).all()
    by_number = {r.number: r.id for r in rows}
    for item, number in numbers.items():
        if number not in by_number:
            report.add(section, f"{item}: no queue item for Tally voucher {number}")
            continue
        w.items[item] = by_number[number]
        initials[item] = item_state(conn, by_number[number])
    for item in numbers:
        if item in w.items:
            run_script(conn, report, section, pack, w, item, results)
            check_item(conn, report, section, pack, w, item, initials[item], results)


def run_tally_c(conn, report: Report, pack: Pack, w: World) -> None:
    exp = {k: v for (s, k), v in pack.tally.items() if s == "import_c"}
    xml = pack.tally_files["tally_c_rejected_dtd.xml"]
    doc = insert_document(conn, w.client_id, "tally_xml", None, data=xml, name="tally_c_rejected_dtd.xml")
    try:
        tally_import.import_xml(conn, w.client_id, doc, xml, actor=ACTOR["clerk"])
    except ServiceError as exc:
        if exc.code != exp["error_code"] or (exc.details or {}).get("rule_id") != exp["error_rule"]:
            report.add("tally_c", f"expected {exp['error_code']} / {exp['error_rule']}, tool says {exc.code} / {(exc.details or {}).get('rule_id')}")
    else:
        report.add("tally_c", "a file with a DTD and an entity was ACCEPTED (D-30)")
    if scalar(conn, "SELECT count(*) FROM tally_imports WHERE document_id = :d", d=doc) != 0:
        report.add("tally_c", "a refused file left an import behind")


def check_export(conn, report: Report, pack: Pack, w: World, key: str, balances: list) -> None:
    exp = {k: v for (s, k), v in pack.tally.items() if s == key}
    stored: list = []

    def store(c, client_id, doc_type, filename, data, actor):
        stored.append(data)
        return insert_document(c, client_id, "tally_export", None, data=data, name=filename)

    out = tally_export.export(conn, w.client_id, kind="vouchers", store_document=store, actor=ACTOR["accountant"])
    back = parse_tally_xml(stored[0])
    if len(back.vouchers) != int(exp["voucher_count"]) or out.voucher_count != int(exp["voucher_count"]):
        report.add("export", f"{key}: vouchers exported: expected {exp['voucher_count']}, file has {len(back.vouchers)}, tool says {out.voucher_count}")
    if len({x.name for x in back.ledgers}) != int(exp["ledger_count"]):
        report.add("export", f"{key}: ledgers exported: expected {exp['ledger_count']}, file has {len({x.name for x in back.ledgers})}")
    got: dict[str, Decimal] = {}
    for v in back.vouchers:
        for e in v.entries:
            got[e.ledger_name] = got.get(e.ledger_name, Decimal(0)) - e.amount   # Tally: debit = negative amount
    want = {ledger: dr - cr for ledger, dr, cr in balances}
    if exp.get("debit_balances_equal_expected") == "true" and got != want:
        diff = {k: (want.get(k), got.get(k)) for k in sorted(set(want) | set(got)) if want.get(k) != got.get(k)}
        report.add("export", f"{key}: re-reading the exported file gives other ledger balances (ledger: expected, file): {diff}")
    report.bump("exported_vouchers", len(back.vouchers))


def check_balances(conn, report: Report, pack: Pack, w: World, client: str) -> list:
    rows = conn.execute(text("SELECT l.name, sum(vl.debit) - sum(vl.credit) FROM voucher_lines vl JOIN vouchers v ON v.id = vl.voucher_id "
                             "JOIN ledgers l ON l.id = vl.ledger_id WHERE v.client_id = :c AND v.status IN ('posted', 'reversed') GROUP BY l.name"),
                        {"c": w.client_id}).all()
    got = {r[0]: r[1] for r in rows}
    want = {ledger: dr - cr for ledger, dr, cr in pack.balances[client]}
    for ledger in sorted(set(want) | set(got)):
        if want.get(ledger, Decimal(0)) != got.get(ledger, Decimal(0)):
            g, x = got.get(ledger, Decimal(0)), want.get(ledger, Decimal(0))
            report.add("balances", f"client {client} {ledger}: expected {'Dr' if x >= 0 else 'Cr'} {format_inr(abs(x))}, "
                                   f"tool says {'Dr' if g >= 0 else 'Cr'} {format_inr(abs(g))}")
    total_dr = sum((v for v in got.values() if v > 0), Decimal(0))
    total_cr = -sum((v for v in got.values() if v < 0), Decimal(0))
    if (total_dr, total_cr) != pack.balance_totals[client]:
        report.add("balances", f"client {client} totals: expected Dr {format_inr(pack.balance_totals[client][0])} / Cr "
                               f"{format_inr(pack.balance_totals[client][1])}, tool says Dr {format_inr(total_dr)} / Cr {format_inr(total_cr)}")
    return [(ledger, d if d > 0 else Decimal(0), -d if d < 0 else Decimal(0)) for ledger, d in sorted(got.items())]


# ------------------------------------------------------------------------------------------------------------------- headline


def check_headline(conn, report: Report, pack: Pack, worlds: list[World], fakes: list) -> None:
    h = pack.config["headline"]
    cids = [w.client_id for w in worlds]
    q = "SELECT count(*) FROM approval_queue_items WHERE client_id = ANY(:c)"
    total = scalar(conn, q, c=cids)
    for label, status, want in (("accepted", "accepted", h["accepted"]), ("rejected", "rejected", h["rejected"]), ("pending", "pending", h["pending"])):
        got = scalar(conn, q + " AND status = :s", c=cids, s=status)
        if got != want:
            report.add("headline", f"queue items {label}: expected {want}, tool says {got}")
    if total != h["queue_items_total"]:
        report.add("headline", f"queue items in total: expected {h['queue_items_total']}, tool says {total}")
    posted = scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = ANY(:c) AND status = 'posted'", c=cids)
    accepted = scalar(conn, q + " AND status = 'accepted'", c=cids)
    if posted != h["vouchers_posted"]:
        report.add("headline", f"posted vouchers: expected {h['vouchers_posted']}, tool says {posted}")
    if posted != accepted:
        report.add("headline", f"posted vouchers ({posted}) differ from accepted queue items ({accepted})")
    # 1. every voucher that is no longer a draft came from an ACCEPTED item (and no voucher exists outside the queue)
    bad = conn.execute(text(
        "SELECT v.id, v.status FROM vouchers v WHERE v.client_id = ANY(:c) AND v.status <> 'draft' AND NOT EXISTS "
        "(SELECT 1 FROM approval_queue_items q WHERE q.draft_voucher_id = v.id AND q.status = 'accepted')"), {"c": cids}).all()
    for r in bad:
        report.add("headline", f"voucher {str(r.id)[:8]} is {r.status} but did not come from an accepted queue item")
    outside = scalar(conn, "SELECT count(*) FROM vouchers v WHERE v.client_id = ANY(:c) AND NOT EXISTS "
                           "(SELECT 1 FROM approval_queue_items q WHERE q.draft_voucher_id = v.id)", c=cids)
    if outside:
        report.add("headline", f"{outside} voucher(s) exist that did not come from the approval queue")
    # 2. no accepted item carries a blocking finding; an item with a blocking finding has no approvable voucher
    for r in conn.execute(text("SELECT id, blocking_count FROM approval_queue_items WHERE client_id = ANY(:c) AND status = 'accepted' "
                               "AND blocking_count > 0"), {"c": cids}):
        report.add("headline", f"accepted item {str(r.id)[:8]} still has {r.blocking_count} blocking finding(s)")
    for r in conn.execute(text("SELECT q.id, v.status FROM approval_queue_items q JOIN vouchers v ON v.id = q.draft_voucher_id "
                               "WHERE q.client_id = ANY(:c) AND q.blocking_count > 0 AND v.status <> 'draft'"), {"c": cids}):
        report.add("headline", f"item {str(r.id)[:8]} has a blocking finding but its voucher is {r.status}")
    # 3. every item that is still pending is refused by accept (the service re-checks everything)
    for w in worlds:
        for item, item_id in w.items.items():
            st = item_state(conn, item_id)
            if st["status"] == "pending":
                try:
                    approval_queue.accept(conn, w.client_id, item_id, actor=ACTOR["accountant"])
                except ServiceError as exc:
                    if exc.code != "queue_blocked":
                        report.add("headline", f"{item}: a pending item was refused with '{exc.code}', expected queue_blocked")
                else:
                    report.add("headline", f"{item}: a pending item with blocking findings was ACCEPTED")
                report.bump("pending_items_refused")
    for key, action, want in (("accepted_audited", "queue_item_accepted", h["accepted"]), ("rejected_audited", "queue_item_rejected", h["rejected"])):
        got = scalar(conn, "SELECT count(*) FROM audit_log WHERE client_id = ANY(:c) AND action = :a", c=cids, a=action)
        if got != want:
            report.add("headline", f"{key}: audit rows expected {want}, tool says {got}")
    if report.counts.get("approve_refused_before_accept", 0) != h["approve_refused_before_accept"]:
        report.add("headline", f"approve-before-accept attempts refused: expected {h['approve_refused_before_accept']}, "
                               f"{report.counts.get('approve_refused_before_accept', 0)} happened")
    for what, purpose, status, cid_set, want in (
            ("invoice extraction calls", "invoice_extraction", "ok", cids[:1], h["llm_calls_invoice_extraction_ok"]),
            ("narration calls", "narration_suggestion", "ok", cids[:1], h["llm_calls_narration_ok"])):
        got = scalar(conn, "SELECT count(*) FROM llm_calls WHERE client_id = ANY(:c) AND purpose = :p AND status = :s", c=cid_set, p=purpose, s=status)
        if got != want:
            report.add("headline", f"stored {what}: expected {want}, tool says {got}")
    seen = sum(len(f.requests) for f in fakes)
    if seen != h["model_requests_total"]:
        report.add("headline", f"requests the fake model saw: expected {h['model_requests_total']}, tool says {seen}")


# ------------------------------------------------------------------------------------------------------------------- the run


def run_pack_p7(conn, pack: Pack) -> Report:
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

        wa = build_world_a(conn, pack)
        wb = build_world_b(conn, pack)
        fakes: list = []
        initials: dict = {}
        results: dict = {}

        # ---- A: documents (phase 1: read + draft; phase 2: the accountant works; phase 3: the late duplicate)
        run_documents(conn, report, pack, wa, fakes, initials, results)
        run_invoices_phase2(conn, report, pack, wa, results)
        for doc in [d for d in pack.docs if d.arrives == "last"]:
            extract_and_build(conn, report, pack, wa, doc, fakes, initials)
            run_script(conn, report, "invoices", pack, wa, doc.doc_id, results)
        for doc in [d for d in pack.docs if d.doc_type != "bank_statement"]:
            if doc.doc_id in wa.items:
                check_item(conn, report, "invoices", pack, wa, doc.doc_id, initials[doc.doc_id], results)
        check_masking(conn, report, pack, wa, fakes)

        # ---- A: bank narrations, Tally file A
        run_narration(conn, report, pack, wa, fakes)
        run_tally(conn, report, pack, wa, "tally_a", "import_a", "tally_a_masters_vouchers.xml",
                  {"TA-1": "T-S-1", "TA-2": "P-1", "TA-3": "7", "TA-4": "J-1"},
                  {"Tally New Vendor": ("create",), "Rent Paid": ("create",)}, results, initials)
        run_tally_c(conn, report, pack, wa)

        # ---- B: Tally file B and the switch-off check
        run_tally(conn, report, pack, wb, "tally_b", "import_b", "tally_b_second_company.xml", {"TB-1": "R-9", "TB-2": "J-2"},
                  {"Mystery Ledger": ("skip",)}, results, initials)
        run_switch_off(conn, report, pack, wb)

        # ---- balances and the export round trip
        for client, w in (("A", wa), ("B", wb)):
            check_balances(conn, report, pack, w, client)
            check_export(conn, report, pack, w, f"export_{client.lower()}", pack.balances[client])

        check_headline(conn, report, pack, [wa, wb], fakes)
        if network["calls"]:
            report.add("no_network", f"{network['calls']} attempt(s) to reach the network or the real model")
        for f in fakes:
            if not isinstance(f, FakeLlmClient):
                report.add("no_network", "a model client other than the fake was used")
        report.counts["model_requests"] = sum(len(f.requests) for f in fakes)
        report.counts["network_attempts"] = network["calls"]
        report.counts["vouchers_posted"] = scalar(conn, "SELECT count(*) FROM vouchers WHERE client_id = ANY(:c) AND status = 'posted'",
                                                  c=[wa.client_id, wb.client_id])
    return report


def run_switch_off(conn, report: Report, pack: Pack, wb: World) -> None:
    """Client B has no AI setting row: the extraction is REFUSED (D-51), the fake model sees nothing, the refusal is recorded."""
    doc = next(d for d in pack.docs if d.doc_id == "P7-01")
    doc_db = insert_document(conn, wb.client_id, doc.doc_type, doc.text, name="switch_off.pdf")
    fake = Boom()
    out = extractions.run_llm_extraction(conn, client_id=wb.client_id, document_id=doc_db, actor=ACTOR["clerk"], gateway=FakeGateway(fake))
    if out.status != "blocked":
        report.add("switch_off", f"expected the extraction to be blocked (switch off), tool says '{out.status}'")
    if fake.requests:
        report.add("switch_off", "the model was called although the client's AI switch is off")
    row = conn.execute(text("SELECT status, prompt_masked, response_raw FROM llm_calls WHERE client_id = :c"), {"c": wb.client_id}).all()
    if len(row) != pack.config["headline"]["llm_calls_blocked_switch_off"] or [r.status for r in row] != ["blocked"]:
        report.add("switch_off", f"expected exactly one blocked llm_calls row, found {[r.status for r in row]}")
    elif row[0].prompt_masked is not None or row[0].response_raw is not None:
        report.add("switch_off", "a blocked call must hold no prompt and no answer")
    if scalar(conn, "SELECT count(*) FROM extractions WHERE client_id = :c", c=wb.client_id) != 0:
        report.add("switch_off", "a blocked call stored an extraction")

