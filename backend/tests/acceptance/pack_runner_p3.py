"""Phase 3 (GST) acceptance runner: drives the REAL services (not the API) with the Phase 3 pack and compares every
result with the hand-worked expected files of the accountants.

It never modifies a pack file and never bends the tool to fit them: every difference is collected per section as one
plain line (expected vs tool) for the owner and the accountants to decide. One run builds the whole world (client,
ledgers, GST registration, items, invoice-mode vouchers, payments, GSTR-2B imports, ITC evidence, returns, 180-day
check, composition client, wrong cases) inside the caller's transaction.
"""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from chart_fixture import EXPECTED_GROUPS
from pack_loader_p3 import InvoiceRec, PackP3
from pack_runner import _group_name_of_ledger
from pack_runner_p2 import diff_keyed, explain_errors, judge_wrong, money
from sqlalchemy import Connection

from app.engine.gst_invoice import typed_tax_errors
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import Allocation, VoucherDraft, VoucherLine
from app.services import (
    client_setup,
    gst_invoices,
    gst_itc,
    gst_items,
    gst_recon,
    gst_registrations,
    gst_returns,
    parties,
    reports,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

ACTOR = "pack-runner-p3"
GROUP_CODE_BY_NAME = {name: code for code, name, *_ in EXPECTED_GROUPS}
HEADS4 = ("igst", "cgst", "sgst", "cess")
HEADS5 = ("taxable_value",) + HEADS4

SECTIONS = (
    "setup", "vouchers", "invoice_items", "ledger_balances", "reconciliation", "apply_2b", "itc_register", "register_tie",
    "gstr1", "gstr1_documents", "gstr3b", "tie_out", "exposure_180", "reversals", "composition", "rule_status", "wrong_cases",
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


def rate4(value) -> str:
    return f"{Decimal(str(value)):.4f}"


def qty3(value) -> str:
    return f"{Decimal(str(value)):.3f}"


def amt(value) -> str:
    """Money as plain 2-decimal text; None stays blank."""
    return "" if value is None or value == "" else f"{Decimal(str(value)):.2f}"


def iso(value) -> str:
    return "" if value is None else str(value)


def csv_cells(row: dict, columns: tuple[str, ...]) -> dict[str, str]:
    """Expected cells of a pack row: a blank cell means 'not part of this row' and is never compared."""
    return {c: row[c] for c in columns if row.get(c, "") != ""}


def narrow(want: dict, got: dict) -> dict:
    """The tool's rows reduced to the fields the pack states for the same key; a tool row the pack does not list stays whole."""
    return {key: ({f: row.get(f, "") for f in want[key]} if key in want else row) for key, row in got.items()}


def all_fields(want: dict) -> tuple[str, ...]:
    return tuple(sorted({f for row in want.values() for f in row}))


def gstr1_rows(tables: dict) -> dict[tuple, dict]:
    """The tool's GSTR-1 working flattened like expected_gstr1.csv."""
    rows: dict[tuple, dict] = {}

    def item(table: str, key: str, inv_value, it: dict) -> None:
        rows[(table, key)] = {"invoice_value": amt(inv_value), **{h: amt(it[h]) for h in HEADS5}}

    for party in tables["b2b"]:
        for inv in party["invoices"]:
            for it in inv["items"]:
                key = f"{party['party_gstin']}|{inv['invoice_no']}|{inv['invoice_date']}|{inv['place_of_supply']}|{rate4(it['rate'])}"
                item("b2b", key, inv["invoice_value"], it)
    for block in tables["b2cl"]:
        for inv in block["invoices"]:
            for it in inv["items"]:
                item("b2cl", f"{block['place_of_supply']}|{inv['invoice_no']}|{inv['invoice_date']}|{rate4(it['rate'])}",
                     inv["invoice_value"], it)
    for r in tables["b2cs"]:
        rows[("b2cs", f"{r['place_of_supply']}|{rate4(r['rate'])}")] = {h: amt(r[h]) for h in HEADS5}
    for party in tables["cdnr"]:
        for note in party["notes"]:
            for it in note["items"]:
                key = (f"{party['party_gstin']}|{note['note_no']}|{note['note_date']}|{note['original_invoice_no']}|"
                       f"{note['original_invoice_date']}|{note['reason']}|{rate4(it['rate'])}")
                item("cdnr", key, note["note_value"], it)
    for bucket, kinds in tables["nil_exempt_non_gst"].items():
        for kind, value in kinds.items():
            if Decimal(str(value)) != 0:
                rows[("nil_exempt", f"{bucket}|{kind}")] = {"taxable_value": amt(value)}
    for r in tables["hsn_summary"]:
        rows[("hsn", f"{r['hsn_sac']}|{r['uqc'] or ''}|{rate4(r['rate'])}")] = {
            "quantity": qty3(r["quantity"]), "total_value": amt(r["total_value"]), **{h: amt(r[h]) for h in HEADS5}}
    rows[("totals", "all")] = {h: amt(tables["totals"][h]) for h in HEADS5}
    return rows


def expected_gstr1(csv_rows: list[dict]) -> dict[tuple, dict]:
    cols = ("quantity", "total_value", "invoice_value") + HEADS5
    return {(r["table"], r["row_key"]): csv_cells(r, cols) for r in csv_rows}


def gstr3b_rows(tables: dict) -> dict[tuple, dict]:
    """The tool's GSTR-3B working flattened like expected_gstr3b.csv."""
    rows: dict[tuple, dict] = {}
    for name, b in tables["t3_1"].items():
        rows[("t3_1", name)] = {h: amt(b[h]) for h in HEADS5}
    for kind, lst in tables["t3_2"].items():
        for r in lst:
            rows[("t3_2", f"{kind}|{r['place_of_supply']}")] = {"taxable_value": amt(r["taxable_value"]), "igst": amt(r["igst"])}
    t4 = tables["t4"]
    for part in ("a", "b"):
        for name, b in t4[part].items():
            rows[("t4", f"{part}_{name}")] = {h: amt(b[h]) for h in HEADS4}
    for name in ("c_net", "d_ineligible"):
        rows[("t4", name)] = {h: amt(t4[name][h]) for h in HEADS4}
    for name, b in tables["t5"].items():
        rows[("t5", name)] = {"taxable_value": amt(b["taxable_value"])}
    for name in ("tax_payable", "rcm_payable_in_cash", "itc_available"):
        rows[("t6_1", name)] = {h: amt(tables["t6_1"][name][h]) for h in HEADS4}
    return rows


def expected_gstr3b(csv_rows: list[dict]) -> dict[tuple, dict]:
    return {(r["table"], r["row_key"]): csv_cells(r, HEADS5) for r in csv_rows}


# ===================================================================================================== the run


@contextmanager
def guard(report: RunReport, section: str):
    """A service that raises instead of answering is a difference too: it is reported, the run goes on."""
    try:
        yield
    except (VoucherRuleError, ServiceError) as refusal:
        report.add(section, f"the tool refused instead of answering: {_refusal_text(refusal)}")
    except Exception as crash:  # noqa: BLE001 - any failure of the tool is a finding, not a crash of the report
        report.add(section, f"the tool failed with {type(crash).__name__}: {crash}")


def _refusal_text(refusal: Exception) -> str:
    return explain_errors(refusal.errors) if isinstance(refusal, VoucherRuleError) else refusal.message  # type: ignore[attr-defined]


def _invoice_draft(cid, reg_id, v: InvoiceRec, ids: dict, item_ids: dict) -> VoucherDraft:
    items = tuple(
        ItemLineIn(
            i.item_name, i.hsn_sac, i.quantity, i.unit_rate, i.discount, str(ids[i.item_ledger]),
            item_id=str(item_ids[i.item_name]) if i.item_name in item_ids else None, uqc=i.uqc,
            rcm_category_key=i.rcm_category, itc_category_key=i.itc_category)
        for i in v.items)
    inv = InvoiceIn(
        str(reg_id), v.document_kind, v.supply_category, v.place_of_supply, v.invoice_date, items,
        original_invoice_no=v.original_invoice_no, original_invoice_date=v.original_invoice_date,
        note_reason=v.note_reason)
    return VoucherDraft(cid, v.voucher_type, v.date, v.narration, v.reference_no, ids[v.party_ledger], (), gst=inv)


def _post(conn, draft: VoucherDraft):
    """(voucher_id, None) when posted, else (None, the refusal as text)."""
    try:
        result = vouchers.create_draft(conn, draft, actor=ACTOR)
        if result.errors:
            return None, explain_errors(result.errors)
        vouchers.approve(conn, result.voucher_id, actor=ACTOR)
        vouchers.post(conn, result.voucher_id, actor=ACTOR)
        return result.voucher_id, None
    except (VoucherRuleError, ServiceError) as refusal:
        return None, _refusal_text(refusal)


def _setup_ledgers(conn, report: RunReport, cid, fy, created, rows: list[dict]) -> dict[str, object]:
    template = {name.lower(): lid for name, lid in created.ledger_ids.items()}
    ids: dict[str, object] = {}
    for row in rows:
        key = row["ledger_name"].lower()
        if key in template:
            lid = template[key]
            actual_group = _group_name_of_ledger(conn, lid)
            if actual_group != row["group_name"]:
                report.add("setup", f"ledger {row['ledger_name']}: pack puts it under '{row['group_name']}', "
                                    f"the tool's standard ledger is under '{actual_group}'")
            ids[row["ledger_name"]] = lid
        else:
            ids[row["ledger_name"]] = client_setup.add_ledger(
                conn, cid, row["ledger_name"], GROUP_CODE_BY_NAME[row["group_name"]], actor=ACTOR)
    for row in rows:
        if row["opening_dr"] > 0 or row["opening_cr"] > 0:
            try:
                client_setup.set_opening_balance(
                    conn, cid, fy, ids[row["ledger_name"]], None if row["opening_dr"] == 0 else f"{row['opening_dr']:.2f}",
                    None if row["opening_cr"] == 0 else f"{row['opening_cr']:.2f}", actor=ACTOR)
            except ServiceError as refusal:
                report.add("setup", f"opening balance of {row['ledger_name']} refused: {refusal.message}")
    return ids


def run_pack_p3(conn: Connection, pack: PackP3) -> RunReport:
    report = RunReport(pack.folder.name)
    c = pack.client
    exp = pack.expected
    created = client_setup.create_client(
        conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]),
        fy_start=c["fy_start"], actor=ACTOR, proprietor_name=c.get("proprietor_name"))
    cid, fy = created.client_id, created.financial_year_id
    ids = _setup_ledgers(conn, report, cid, fy, created, pack.ledgers)
    if not client_setup.opening_balance_difference(conn, cid, fy).is_balanced:
        report.add("setup", "opening balances do not balance")

    for p in pack.parties:
        try:
            parties.set_party(
                conn, cid, ids[p["ledger_name"]], gstin=p["gstin"] or None, state_code=p["state_code"] or None,
                gst_registration_type=p["gst_registration_type"] or None, bill_wise=p["bill_wise"], actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            report.add("setup", f"party {p['ledger_name']} refused: {_refusal_text(refusal)}")

    reg_ids: dict[str, object] = {}
    for r in pack.registrations:
        try:
            reg_ids[r["gstin"]] = gst_registrations.create_registration(
                conn, cid, gstin=r["gstin"], registration_type=r["registration_type"], effective_from=r["effective_from"],
                return_frequency=r["return_frequency"] or "monthly", composition_category=r["composition_category"] or None,
                trade_name=r["trade_name"] or None, actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            report.add("setup", f"registration {r['gstin']} refused: {_refusal_text(refusal)}")
    reg_id = reg_ids.get(c["registration_gstin"])
    if reg_id is None:
        report.add("setup", "the main registration was not created: nothing else can run")
        return report
    try:
        gst_registrations.set_ledger_roles(conn, cid, reg_id, {r["role"]: ids[r["ledger_name"]] for r in pack.roles}, actor=ACTOR)
    except (VoucherRuleError, ServiceError) as refusal:
        report.add("setup", f"ledger roles refused: {_refusal_text(refusal)}")

    item_ids: dict[str, object] = {}
    for it in pack.items:
        try:
            item_ids[it["name"]] = gst_items.create_item(
                conn, cid, name=it["name"], item_kind=it["item_kind"], hsn_sac=it["hsn_sac"], uqc=it["uqc"] or None,
                sales_ledger_id=ids[it["sales_ledger"]] if it["sales_ledger"] else None,
                purchase_ledger_id=ids[it["purchase_ledger"]] if it["purchase_ledger"] else None, actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            report.add("setup", f"item {it['name']} refused: {_refusal_text(refusal)}")

    # ---- invoice-mode vouchers (date order) and the tool's item rows; then the payments
    posted: dict[str, object] = {}
    number: dict[str, str] = {}
    tool_invoice: dict[str, dict] = {}
    for v in pack.invoices:
        vid, problem = _post(conn, _invoice_draft(cid, reg_id, v, ids, item_ids))
        if problem:
            report.add("vouchers", f"correct voucher {v.ref_id} was refused: {problem}")
            continue
        posted[v.ref_id] = vid
        number[v.ref_id] = vouchers.get_voucher(conn, vid).voucher_number
        tool_invoice[v.ref_id] = gst_invoices.load(conn, cid, vid) or {}
        report.counts["vouchers_posted"] += 1
    for ref, rows in pack.payments:
        head = rows[0]
        total = sum((r["amount"] for r in rows), Decimal("0.00"))
        draft = VoucherDraft(
            cid, "payment", date.fromisoformat(head["date"]), head["narration"], None, ids[head["party_ledger"]],
            (VoucherLine(ids[head["party_ledger"]], f"{total:.2f}", None,
                         tuple(Allocation("against_ref", f"{r['amount']:.2f}", r["bill_ref"]) for r in rows)),
             VoucherLine(ids[head["bank_ledger"]], None, f"{total:.2f}")))
        _, problem = _post(conn, draft)
        if problem:
            report.add("vouchers", f"payment {ref} was refused: {problem}")
        else:
            report.counts["payments_posted"] += 1
    if report.counts["vouchers_posted"] != len(pack.invoices):
        report.add("vouchers", f"{len(pack.invoices)} invoices in the pack, {report.counts['vouchers_posted']} posted")

    inv_fields = ("voucher_number", "party_amount", "has_rcm")
    want_inv = {(r["ref_id"],): {f: r[f] for f in inv_fields} for r in exp["expected_invoices"]}
    got_inv = {(ref,): {"voucher_number": number[ref], "party_amount": amt(tool_invoice[ref].get("invoice_value")),
                        "has_rcm": str(bool(tool_invoice[ref].get("has_rcm"))).lower()} for ref in tool_invoice}
    for line in diff_keyed(want_inv, got_inv, inv_fields, label=lambda k: f"invoice {k[0]}"):
        report.add("invoice_items", line)
    item_fields = ("treatment", "gst_rate", "taxable_value", "cgst", "sgst", "igst", "cess")
    want_items = {(r["ref_id"], r["item_no"]): {f: (rate4(r[f]) if f == "gst_rate" else r[f]) for f in item_fields}
                  for r in exp["expected_invoice_items"]}
    got_items = {(ref, str(i["item_line_no"])): {f: (rate4(i[f]) if f == "gst_rate" else i[f]) for f in item_fields}
                 for ref, inv in tool_invoice.items() for i in inv.get("items", [])}
    for line in diff_keyed(want_items, got_items, item_fields, label=lambda k: f"item {k[0]}/{k[1]}"):
        report.add("invoice_items", line)

    _ledger_balances(conn, cid, c["pack_end_date"], exp, report)

    # ---- ITC evidence -> GSTR-2B import and reconciliation -> apply to the register -> claims
    ref_of_voucher = {str(v): r for r, v in posted.items()}

    def entries() -> dict[str, dict]:
        out = {}
        for e in gst_itc.list_register(conn, cid, registration_id=reg_id)["entries"]:
            out[ref_of_voucher.get(str(e["voucher_id"]), str(e["voucher_id"]))] = e
        return out

    entry_of = entries()
    for ev in pack.evidence:
        e = entry_of.get(ev["ref_id"])
        if e is None:
            report.add("itc_register", f"{ev['ref_id']}: no ITC register entry was made when the voucher was posted")
            continue
        try:
            gst_itc.update_evidence(conn, cid, e["id"], tax_document_held=ev["tax_document_held"],
                                    goods_services_received=ev["goods_services_received"],
                                    received_date=ev["received_date"], actor=ACTOR)
        except ServiceError as refusal:
            report.add("itc_register", f"{ev['ref_id']}: evidence refused: {refusal.message}")

    period = c["return_period"].strftime("%Y-%m")
    for name, content in pack.gstr2b.items():
        file_period = f"{name[-9:-5]}-{name[-11:-9]}"  # gstr2b_042026.json -> 2026-04
        try:
            gst_recon.import_file(conn, cid, reg_id, "gstr2b", file_period, name, content, ACTOR)
        except ServiceError as refusal:
            report.add("reconciliation", f"{name}: the tool refused the file: {refusal.message} {refusal.details or ''}")
    with guard(report, "reconciliation"):
        _reconciliation(conn, cid, reg_id, period, exp, report, ref_of_voucher)
    with guard(report, "apply_2b"):
        _apply_2b(conn, cid, reg_id, period, exp, report, entries)

    entry_of = entries()
    for cl in pack.claims:
        e = entry_of.get(cl["ref_id"])
        if e is None:
            continue
        try:
            gst_itc.set_claimed_period(conn, cid, e["id"], cl["claimed_in_period"], actor=ACTOR)
        except ServiceError as refusal:
            report.add("itc_register", f"{cl['ref_id']}: the claim was refused: {refusal.message}")
    entry_of = entries()
    itc_fields = ("source", "status", "pending_reason", "blocked_category_key", "supplier_tax_paid", "claimed_in_period",
                  "claim_deadline", "cgst", "sgst", "igst", "cess")
    want_itc = {(r["ref_id"],): {f: r[f] for f in itc_fields if f != "claim_deadline" or r[f] != ""}
                for r in exp["expected_itc"]}  # blank claim_deadline = not stated; other blanks mean "none"
    got_itc = {(ref,): {f: (amt(e[f]) if f in HEADS4 else iso(e[f])) for f in itc_fields} for ref, e in entry_of.items()}
    for line in diff_keyed(want_itc, narrow(want_itc, got_itc), itc_fields, label=lambda k: f"ITC {k[0]}"):
        report.add("itc_register", line)

    # ---- returns, tie-out
    month = c["return_period"]
    rule_got: dict[str, str] = {}
    with guard(report, "gstr1"):
        g1 = gst_returns.gstr1_working(conn, cid, reg_id, "month", month)
        rule_got["gstr1"] = g1["rule_status"]["worst"]
        want1 = expected_gstr1(exp["expected_gstr1"])
        for line in diff_keyed(want1, narrow(want1, gstr1_rows(g1["tables"])), all_fields(want1),
                               label=lambda k: f"GSTR-1 {k[0]} {k[1]}"):
            report.add("gstr1", line)
        for w in g1["tables"]["unclassified"]:
            report.add("gstr1", f"{w['voucher_number']} is not in any GSTR-1 table (unclassified)")
        report.notes += [f"GSTR-1 warning: {w}" for w in g1["warnings"]]
        doc_fields = ("from_no", "to_no", "total", "cancelled", "net_issued")
        want_docs = {(r["nature"],): {k: r[k] for k in doc_fields} for r in exp["expected_gstr1_documents"]}
        got_docs = {(d["nature"],): {k: str(d[k]) for k in doc_fields} for d in g1["tables"]["documents_issued"]}
        for line in diff_keyed(want_docs, got_docs, doc_fields, label=lambda k: f"documents issued {k[0]}"):
            report.add("gstr1_documents", line)
    with guard(report, "gstr3b"):
        g3 = gst_returns.gstr3b_working(conn, cid, reg_id, "month", month)
        rule_got["gstr3b"] = g3["rule_status"]["worst"]
        want3 = expected_gstr3b(exp["expected_gstr3b"])
        for line in diff_keyed(want3, narrow(want3, gstr3b_rows(g3["tables"])), all_fields(want3),
                               label=lambda k: f"GSTR-3B {k[0]} {k[1]}"):
            report.add("gstr3b", line)
        report.notes += [f"GSTR-3B warning: {w}" for w in g3["warnings"]]
    with guard(report, "tie_out"):
        _tie_out(gst_returns.tie_out(conn, cid, reg_id, "month", month), exp, report)

    # ---- 180 days, reversal drafts, register tie, rule status
    with guard(report, "exposure_180"):
        _exposure_and_reversals(conn, cid, reg_id, c["exposure_as_on"], exp, report, posted, ids, rule_got)
    want_rs = {(r["working"],): {"worst": r["worst"]} for r in exp["expected_rule_status"]}
    got_rs = {(k,): {"worst": v} for k, v in rule_got.items()}
    for line in diff_keyed(want_rs, got_rs, ("worst",), label=lambda k: f"rule status {k[0]}"):
        report.add("rule_status", line)
    with guard(report, "register_tie"):
        tie = gst_itc.register_tie(conn, cid, reg_id, c["exposure_as_on"])
        want_t = {(r["head"],): {"input_ledger": r["input_ledger"], "itc_register": r["itc_register"]} for r in exp["expected_register_tie"]}
        got_t = {(h,): {"input_ledger": amt(tie["input_ledgers"][h]["amount"]), "itc_register": amt(tie["itc_register"][h]["amount"])}
                 for h in HEADS4}
        for line in diff_keyed(want_t, got_t, ("input_ledger", "itc_register"), label=lambda k: f"register tie {k[0]}"):
            report.add("register_tie", line)
        if not tie["ties"]:
            report.add("register_tie", f"the tool says the Input ledgers do not tie to the register: {tie['difference']}")

    comp_ctx: dict = {}
    with guard(report, "composition"):
        comp_ctx = _composition(conn, pack, exp, report)
    with guard(report, "wrong_cases"):
        _wrong_cases(conn, pack, cid, reg_id, ids, entry_of, comp_ctx, report)
    return report


def _ledger_balances(conn, cid, as_on, exp, report: RunReport) -> None:
    tb = reports.trial_balance(conn, cid, as_on)
    actual = {r.ledger_name: (r.debit, r.credit) for s in tb.sections for r in s.rows}
    for r in exp["expected_ledger_balances"]:
        name = r["ledger_name"]
        if name not in actual:
            if Decimal(r["amount"]) != 0:
                report.add("ledger_balances", f"{name}: not found in the tool's Trial Balance")
            continue
        dr, cr = actual[name]
        side, net = ("Dr", dr - cr) if dr >= cr else ("Cr", cr - dr)
        if net == 0:
            side = r["side"]
        if (side, money(net)) != (r["side"], r["amount"]):
            report.add("ledger_balances", f"{name}: expected {r['side']} {r['amount']}, tool says {side} {money(net)}")


def _reconciliation(conn, cid, reg_id, period: str, exp, report: RunReport, ref_of_voucher: dict) -> None:
    try:
        recon = gst_recon.reconcile(conn, cid, reg_id, period)
    except ServiceError as refusal:
        report.add("reconciliation", f"the tool could not reconcile {period}: {refusal.message}")
        return
    fields = ("books_ref", "taxable_diff", "igst_diff", "cgst_diff", "sgst_diff")
    got = {}
    for row in recon.result.rows:
        key_item = row.book or row.doc
        both = row.book is not None and row.doc is not None
        diffs = {d.field: d.difference for d in row.differences}
        got[(row.cls, key_item.supplier_gstin, key_item.doc_no)] = {
            "books_ref": ref_of_voucher.get(str(row.book.voucher_id), "") if row.book else "",
            **{f"{h}_diff": (amt(diffs.get(src, Decimal("0.00"))) if both else "")
               for h, src in (("taxable", "taxable_value"), ("igst", "igst"), ("cgst", "cgst"), ("sgst", "sgst"))},
        }
    want = {(r["class"], r["supplier_gstin"], r["doc_no"]): {f: r[f] for f in fields} for r in exp["expected_reconciliation"]}
    for line in diff_keyed(want, got, fields, label=lambda k: f"2B {k[0]} {k[2]}"):
        report.add("reconciliation", line)
    for side, row in recon.result.totals.items():
        w = next((r for r in exp["expected_reconciliation_totals"] if r["side"] == side), None)
        if w is None:
            report.add("reconciliation", f"totals {side}: not in the pack")
            continue
        for f in HEADS5:
            if amt(row[f]) != w[f]:
                report.add("reconciliation", f"totals {side} {f}: expected {w[f]}, tool says {amt(row[f])}")


def _apply_2b(conn, cid, reg_id, period: str, exp, report: RunReport, entries) -> None:
    ref_of_entry = {str(e["id"]): ref for ref, e in entries().items()}
    result = gst_recon.apply(conn, cid, reg_id, period, ACTOR)
    if not result["applied"]:
        report.add("apply_2b", "the tool did not apply the reconciliation to the ITC register")
        return
    got = {(ref_of_entry.get(str(u["itc_entry_id"]), str(u["itc_entry_id"])),): {"from_status": u["from_status"], "to_status": u["to_status"]}
           for u in result["updated"]}
    want = {(r["ref_id"],): {"from_status": r["from_status"], "to_status": r["to_status"]} for r in exp["expected_apply2b"]}
    for line in diff_keyed(want, got, ("from_status", "to_status"), label=lambda k: f"apply 2B {k[0]}"):
        report.add("apply_2b", line)


def _tie_out(envelope: dict, exp, report: RunReport) -> None:
    tie = envelope["tables"]
    fields = ("books", "gstr1", "gstr3b", "register_eligible", "register_pending", "d_books_gstr1", "d_gstr1_gstr3b", "d_register_gstr3b")
    got: dict[tuple, dict] = {}
    for r in tie["rows"]:
        got[("output", r["head"])] = {
            "books": amt(r["books_output"]), "gstr1": amt(r["gstr1_working"]), "gstr3b": amt(r["gstr3b_working"]),
            "d_books_gstr1": amt(r["d_books_gstr1"]), "d_gstr1_gstr3b": amt(r["d_gstr1_gstr3b"])}
    for head, r in tie["itc"].items():
        got[("itc", head)] = {
            "books": amt(r["books_input"]), "gstr3b": amt(r["gstr3b_4a"]), "register_eligible": amt(r["itc_register_eligible"]),
            "register_pending": amt(r["itc_register_pending"]), "d_register_gstr3b": amt(r["d_register_gstr3b"])}
    got[("ties", "all")] = {"books": str(bool(tie["ties"])).lower()}
    want = {(r["section"], r["head"]): csv_cells(r, fields) for r in exp["expected_tieout"]}
    for line in diff_keyed(want, narrow(want, got), fields, label=lambda k: f"tie-out {k[0]} {k[1]}"):
        report.add("tie_out", line)
    for cause in tie.get("causes", []):
        report.notes.append(f"tie-out cause listed by the tool: {cause}")


def _exposure_and_reversals(conn, cid, reg_id, as_on, exp, report: RunReport, posted, ids, rule_got) -> None:
    ref_of_voucher = {str(v): r for r, v in posted.items()}
    ref_of_entry = {str(e["id"]): ref_of_voucher.get(str(e["voucher_id"]), "?")
                    for e in gst_itc.list_register(conn, cid, registration_id=reg_id)["entries"]}
    x = gst_itc.exposure_180(conn, cid, reg_id, as_on)
    rule_got["exposure_180"] = x["rule_status"]
    got: dict[tuple, dict] = {}
    for listname in ("items", "approaching"):
        for i in x[listname]:
            got[(listname, ref_of_entry.get(str(i["itc_entry_id"]), "?"))] = {
                "days": str(i["days"]), "due_on_day": iso(i["due_on_day"]), "outstanding": amt(i["outstanding"]),
                "fraction": f"{Decimal(str(i['unpaid_share']['fraction'])):.4f}", **{h: amt(i[h]) for h in HEADS4}}
    got[("total", "all")] = {h: amt(x["total"][h]) for h in HEADS4}
    fields = ("days", "due_on_day", "outstanding", "fraction") + HEADS4
    want = {(r["list"], r["ref_id"]): csv_cells(r, fields) for r in exp["expected_exposure"]}
    for line in diff_keyed(want, narrow(want, got), fields, label=lambda k: f"180 days {k[0]} {k[1]}"):
        report.add("exposure_180", line)

    try:
        made = gst_itc.create_reversals(conn, cid, reg_id, as_on, None, actor=ACTOR)
    except ServiceError as refusal:
        report.add("reversals", f"the tool refused to draft the reversals: {refusal.message}")
        return
    gotr = {}
    for m in made:
        v = vouchers.get_voucher(conn, m["voucher_id"])
        by_ledger = {ln.ledger_id: (ln.debit, ln.credit) for ln in v.lines}
        ref = ref_of_entry.get(str(m["itc_entry_id"]), "?")
        gotr[(ref,)] = {
            **{h: amt(m[h]) for h in HEADS4},
            "journal_dr_itc_reversal": amt(by_ledger.get(ids["ITC Reversal"], (0, 0))[0]),
            "journal_cr_input_cgst": amt(by_ledger.get(ids["Input CGST"], (0, 0))[1]),
            "journal_cr_input_sgst": amt(by_ledger.get(ids["Input SGST"], (0, 0))[1])}
        if v.status != "draft":
            report.add("reversals", f"{ref}: the reversal voucher should be a draft, it is {v.status}")
    fields = HEADS4 + ("journal_dr_itc_reversal", "journal_cr_input_cgst", "journal_cr_input_sgst")
    wantr = {(r["ref_id"],): {f: r[f] for f in fields} for r in exp["expected_reversals"]}
    for line in diff_keyed(wantr, gotr, fields, label=lambda k: f"reversal {k[0]}"):
        report.add("reversals", line)


def _composition(conn, pack: PackP3, exp, report: RunReport) -> dict:
    """The second client of the pack (composition dealer). Returns what the wrong cases need (ids)."""
    cp = pack.composition
    created = client_setup.create_client(
        conn, ClientProfile(cp["name"], cp["entity_type"], cp["business_type"], cp["gst_type"]),
        fy_start=cp["fy_start"], actor=ACTOR, proprietor_name=cp.get("proprietor_name"))
    cid = created.client_id
    ids = dict(created.ledger_ids)
    for ledger in cp["ledgers"]:
        ids[ledger["name"]] = client_setup.add_ledger(conn, cid, ledger["name"], GROUP_CODE_BY_NAME[ledger["group"]], actor=ACTOR)
    ctx = {"cid": cid, "ids": ids, "reg": None}
    try:
        parties.set_party(conn, cid, ids["Walk-in Retail"], state_code="27", gst_registration_type="unregistered",
                          bill_wise=False, actor=ACTOR)
        r = cp["registration"]
        reg = gst_registrations.create_registration(
            conn, cid, gstin=r["gstin"], registration_type=r["registration_type"],
            composition_category=r["composition_category"], effective_from=r["effective_from"], actor=ACTOR)
        ctx["reg"] = reg
        gst_registrations.set_ledger_roles(conn, cid, reg, {k: ids[v] for k, v in cp["roles"].items()}, actor=ACTOR)
    except (VoucherRuleError, ServiceError) as refusal:
        report.add("composition", f"the composition client could not be set up: {_refusal_text(refusal)}")
        return ctx
    for v in cp["vouchers"]:
        item = ItemLineIn(v["item_description"], v["hsn_sac"], Decimal(v["quantity"]), Decimal(v["unit_rate"]), Decimal("0.00"),
                          str(ids["Sales"]), uqc=v["uqc"])
        inv = InvoiceIn(str(reg), "bill_of_supply", "b2c", "27", v["date"], (item,))
        _, problem = _post(conn, VoucherDraft(cid, "sales", v["date"], v["narration"], None, ids[v["party"]], (), gst=inv))
        if problem:
            report.add("composition", f"composition voucher {v['ref_id']} was refused: {problem}")
    try:
        w = gst_returns.composition_working(conn, cid, reg, cp["quarter_start"])
    except ServiceError as refusal:
        report.add("composition", f"the tool could not work the composition quarter: {refusal.message}")
        return ctx
    got = {
        "category": w["category"], "rate_status": w["rate_status"], "turnover_basis": w["turnover_basis"],
        "quarter_turnover": amt(w["quarter_turnover"]), "ytd_turnover": amt(w["ytd_turnover"]), "limit": amt(w["limit"]),
        "limit_crossed": str(bool(w["limit_crossed"])).lower(), "tax_cgst": amt(w["tax"]["cgst"]),
        "tax_sgst": amt(w["tax"]["sgst"]), "tax_total": amt(w["tax"]["total"]),
        "invoices_with_tax": str(len(w["invoices_with_tax"])),
    }
    for row in exp["expected_composition"]:
        if got.get(row["field"]) != row["value"]:
            report.add("composition", f"{row['field']}: expected {row['value']}, tool says {got.get(row['field'])}")
    return ctx


def _wrong_cases(conn, pack: PackP3, cid, reg_id, ids, entry_of: dict, comp_ctx: dict, report: RunReport) -> None:
    for w in pack.wrong_cases:
        label = f"wrong case {w['case_id']} ({w['description']})"
        nested = conn.begin_nested()
        try:
            outcome = _run_wrong_case(conn, w, cid, reg_id, ids, entry_of, comp_ctx)
        finally:
            nested.rollback()
        if outcome is None:
            report.add("wrong_cases", f"{label} (expected {w['expected_rule_id']}) was ACCEPTED")
            continue
        kind, value = outcome
        if kind == "code":
            if value != w["expected_rule_id"]:
                report.add("wrong_cases", f"{label}: expected {w['expected_rule_id']}, the tool raised '{value}'")
            else:
                report.counts["wrong_cases_refused"] += 1
            continue
        problem, warning = judge_wrong(label, w["expected_rule_id"], w["expected_message_contains"] or None, value)
        if problem:
            report.add("wrong_cases", problem)
        else:
            report.counts["wrong_cases_refused"] += 1
        if warning:
            report.warnings.append(warning)


def _draft_errors(conn, draft: VoucherDraft):
    result = vouchers.create_draft(conn, draft, actor=ACTOR)
    return ("rules", result.errors) if result.errors else None


def _run_wrong_case(conn, w: dict, cid, reg_id, ids, entry_of: dict, comp_ctx: dict):
    """None when the tool ACCEPTED the wrong input, else ('rules', [errors]) or ('code', service error code)."""
    kind = w["kind"]
    on = date(2026, 4, 28)
    try:
        if kind == "registration":
            gst_registrations.create_registration(conn, cid, gstin=w["field_1"], registration_type="regular",
                                                  effective_from=date(2026, 4, 1), actor=ACTOR)
        elif kind == "party":
            parties.set_party(conn, cid, ids["Patel Agencies"], gstin=w["field_1"], state_code=w["field_2"],
                              gst_registration_type=w["field_3"], bill_wise=False, actor=ACTOR)
        elif kind == "typed_lines":
            # G-14 is enforced where a request body becomes a draft (app/api/gst_invoice_input.py, via this engine function);
            # the voucher service itself replaces typed lines without a word, so the rule is asked directly.
            errors = typed_tax_errors(True, [[w["field_2"].lower().replace("output ", "")]])
            return ("rules", errors) if errors else None
        elif kind == "unknown_hsn":
            item = ItemLineIn("Unknown goods", w["field_1"], Decimal(1), Decimal("1000.00"), Decimal("0.00"), str(ids["Sales"]), uqc="NOS")
            inv = InvoiceIn(str(reg_id), "tax_invoice", "b2b", "27", on, (item,))
            return _draft_errors(conn, VoucherDraft(cid, "sales", on, "Unknown HSN", None, ids["Rahul Enterprises"], (), gst=inv))
        elif kind == "claim_blocked":
            gst_itc.set_claimed_period(conn, cid, entry_of[w["field_1"]]["id"], date(2026, 4, 1), actor=ACTOR)
        elif kind == "composition_tax_invoice":
            if comp_ctx.get("reg") is None:
                return "code", "the composition client was not set up"
            cids = comp_ctx["ids"]
            item = ItemLineIn("Sugar", "1701", Decimal(10), Decimal("45.00"), Decimal("0.00"), str(cids["Sales"]), uqc="KGS")
            inv = InvoiceIn(str(comp_ctx["reg"]), w["field_2"], "b2c", "27", date(2026, 6, 1), (item,))
            return _draft_errors(conn, VoucherDraft(comp_ctx["cid"], "sales", date(2026, 6, 1), "Tax invoice by composition dealer",
                                                    None, cids["Walk-in Retail"], (), gst=inv))
        elif kind == "reversal_twice":
            gst_itc.create_reversals(conn, cid, reg_id, date(2026, 10, 1), None, actor=ACTOR)
        else:
            return "code", f"unknown case kind {kind}"
    except VoucherRuleError as refusal:
        return "rules", refusal.errors
    except ServiceError as refusal:
        return "code", refusal.code
    return None
