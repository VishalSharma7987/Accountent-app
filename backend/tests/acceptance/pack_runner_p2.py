"""Phase 2 acceptance runner: drives the REAL services (not the API) with the Phase 2 pack and compares every result
with the accountants' hand-worked expected files.

It never modifies a pack file and never bends the tool to fit them: every difference is collected per section as one
plain line (expected vs tool) for the owner and the accountants to decide. Pure helpers (diff_keyed, outstanding_rows,
ageing_rows, ...) need no database and are unit-tested in test_pack_runner_p2_helpers.py.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from chart_fixture import EXPECTED_GROUPS
from pack_loader_p2 import PackP2, PartyRec, VoucherRec, parse_amount, parse_date
from pack_runner import _group_name_of_ledger
from sqlalchemy import Connection, text

from app.engine.bills import OpeningBillIn
from app.engine.models import Allocation, VoucherDraft, VoucherLine
from app.engine.money import format_inr
from app.services import (
    bank,
    bills,
    cashbook,
    client_setup,
    msme,
    parties,
    reconciliation,
    reports,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError

ACTOR = "pack-runner-p2"
GROUP_CODE_BY_NAME = {name: code for code, name, *_ in EXPECTED_GROUPS}

SECTIONS = (
    "setup", "vouchers", "reversals", "wrong_vouchers", "wrong_parties", "trial_balance",
    "outstanding_receivable", "outstanding_payable", "ageing", "cash_book", "msme_due",
    "bank_import", "matches", "brs", "bank_only_drafts",
)


@dataclass
class RunReport:
    pack: str
    problems: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SECTIONS})
    warnings: list[str] = field(default_factory=list)  # reported, do not fail (message wording, keywords)
    notes: list[str] = field(default_factory=list)  # information for the owner (representation, helper ledgers)
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


def money(value: Decimal | str) -> str:
    return f"{Decimal(value):.2f}"


def split_refs(book_refs: str) -> frozenset[str]:
    """'V24+V25+V26' -> {'V24','V25','V26'}; '' (bank only) -> empty set."""
    return frozenset(x.strip() for x in book_refs.split("+") if x.strip())


def diff_keyed(expected: dict, actual: dict, fields: tuple[str, ...], label=str) -> list[str]:
    """Compare two {key: {field: text}} tables. One line per missing row, extra row and differing field."""
    out = []
    for key, want_row in expected.items():
        if key not in actual:
            out.append(f"{label(key)}: expected but the tool has no such row")
            continue
        for name in fields:
            want, got = want_row.get(name, ""), actual[key].get(name, "")
            if want != got:
                out.append(f"{label(key)}: {name} expected {want or '(blank)'}, tool says {got or '(blank)'}")
    for key in actual:
        if key not in expected:
            out.append(f"{label(key)}: the tool has this row but the pack does not")
    return out


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def outstanding_rows(report, natural_side: str) -> dict[tuple, dict]:
    """The tool's outstanding report as rows shaped like expected_outstanding_*.csv.

    Amounts in the report are in its direction (receivable Dr+, payable Cr+); the pack writes positive amounts with a
    `side`, so a negative figure becomes the opposite side."""
    opposite = "Cr" if natural_side == "Dr" else "Dr"

    def shown(value: Decimal) -> tuple[str, str]:
        return money(abs(value)), (natural_side if value >= 0 else opposite)

    rows: dict[tuple, dict] = {}
    for party in report.parties:
        for item in party.items:
            row_type = "on_account" if item.kind == "on_account" else "bill"
            outstanding, side = shown(item.outstanding)
            rows[(row_type, party.party_name, item.bill_ref or "")] = {
                "kind": item.kind, "side": side, "bill_date": _iso(item.bill_date), "due_date": _iso(item.due_date),
                "original": shown(item.original)[0], "outstanding": outstanding,
                "days_past_due": str(item.days_past_due), "bucket": item.bucket,
            }
        total, side = shown(party.total)
        rows[("party_total", party.party_name, "")] = {"side": side, "outstanding": total}
    total, side = shown(report.total)
    rows[("grand_total", "", "")] = {"side": side, "outstanding": total}
    return rows


def expected_outstanding(csv_rows: list[dict]) -> dict[tuple, dict]:
    out = {}
    for r in csv_rows:
        out[(r["row_type"], r["party"], r["bill_ref"])] = {
            k: r[k] for k in ("kind", "side", "bill_date", "due_date", "original", "outstanding", "days_past_due", "bucket")
        }
    return out


OUTSTANDING_FIELDS = ("kind", "side", "bill_date", "due_date", "original", "outstanding", "days_past_due", "bucket")


def reconcile_not_due_days(expected: dict, actual: dict) -> list[str]:
    """The pack counts days past due as report date minus due date (negative = still to run); the tool reports 0 while
    an item is not yet due (API contract). Where that is the ONLY difference, the tool's 0 is accepted and reported as a
    note instead of a failure. Mutates both tables so diff_keyed no longer sees it. Returns the note lines."""
    notes = []
    for key, want in expected.items():
        got = actual.get(key)
        if (got and want.get("bucket") == "not_due" and got.get("bucket") == "not_due"
                and got.get("days_past_due") == "0" and int(want["days_past_due"] or 0) < 0):
            notes.append(f"{key[1]} {key[2]}: pack shows {want['days_past_due']} days (still to run), tool shows 0")
            want["days_past_due"] = got["days_past_due"] = "0"
    return notes


def ageing_rows(report) -> dict[tuple, dict]:
    cols = ("not_due", "0-30", "31-60", "61-90", "90+")
    rows = {}
    for p in report.parties:
        rows[(report.kind, "party", p.party_name)] = {**{c: money(p.buckets[c]) for c in cols}, "total": money(p.total)}
    rows[(report.kind, "total", "")] = {**{c: money(report.buckets[c]) for c in cols}, "total": money(report.total)}
    return rows


AGEING_FIELDS = ("not_due", "0-30", "31-60", "61-90", "90+", "total")


def expected_ageing(csv_rows: list[dict]) -> dict[tuple, dict]:
    return {(r["kind"], r["row_type"], r["party"]): {c: r[c] for c in AGEING_FIELDS} for r in csv_rows}


def signed(balance) -> str:
    """A Balance (amount + Dr/Cr/None) as a signed 2-decimal text, Dr positive."""
    return money(-balance.amount if balance.side == "Cr" else balance.amount)


def cash_book_rows(book) -> dict[tuple, dict]:
    rows = {("opening", book.from_date.isoformat()): {"receipts": "0.00", "payments": "0.00", "closing_dr": signed(book.opening)}}
    for d in book.days:
        rows[("day", d.date.isoformat())] = {
            "receipts": money(d.receipts), "payments": money(d.payments), "closing_dr": signed(d.closing)}
    rows[("total", "")] = {"receipts": money(book.total_receipts), "payments": money(book.total_payments),
                           "closing_dr": signed(book.closing)}
    return rows


def expected_cash_book(csv_rows: list[dict]) -> dict[tuple, dict]:
    return {(r["row_type"], r["date"]): {k: r[k] for k in ("receipts", "payments", "closing_dr")} for r in csv_rows}


MSME_FIELDS = ("bill_date", "legal_days", "legal_due_date", "days_overdue", "outstanding")


def msme_rows(report) -> dict[tuple, dict]:
    rows = {("item", f.party_name, f.bill_ref or ""): {
        "bill_date": _iso(f.bill_date), "legal_days": str(f.legal_days), "legal_due_date": _iso(f.legal_due_date),
        "days_overdue": str(f.days_overdue), "outstanding": money(f.outstanding)} for f in report.items}
    rows[("total", "", "")] = {"outstanding": money(report.total_outstanding)}
    return rows


def expected_msme(csv_rows: list[dict]) -> dict[tuple, dict]:
    return {(r["row_type"], r["party"], r["bill_ref"]): {f: r[f] for f in MSME_FIELDS} for r in csv_rows}


def brs_rows(result) -> dict[tuple, dict]:
    """The tool's BRS shaped like expected_brs.csv; key (line_type, date, reference), field amount."""
    rows: dict[tuple, dict] = {("balance_per_books", _iso(result.as_on), ""): {"amount": money(result.balance_per_books)}}
    for line_type, items in (
        ("issued_not_presented", result.issued_not_presented), ("deposited_not_cleared", result.deposited_not_cleared),
        ("bank_only_credit", result.bank_only_credits), ("bank_only_debit", result.bank_only_debits),
    ):
        for i in items:
            rows[(line_type, _iso(i.date), i.reference or "")] = {"amount": money(i.amount)}
        total = sum((i.amount for i in items), Decimal("0.00"))
        total_type = {"bank_only_credit": "total_bank_only_credits", "bank_only_debit": "total_bank_only_debits"}.get(
            line_type, "total_" + line_type)
        rows[(total_type, "", "")] = {"amount": money(total)}
    rows[("computed_bank_balance", _iso(result.as_on), "")] = {"amount": money(result.computed_bank_balance)}
    rows[("balance_per_bank", _iso(result.as_on), "")] = {"amount": money(result.balance_per_bank)}
    rows[("difference", "", "")] = {"amount": money(result.difference)}
    return rows


def expected_brs(csv_rows: list[dict]) -> dict[tuple, dict]:
    return {(r["line_type"], r["item_date"], r["reference"]): {"amount": r["amount"]} for r in csv_rows}


def _show(refs) -> str:
    return "+".join(sorted(refs)) or "nothing (bank only)"


def explain_errors(errors) -> str:
    return "; ".join(f"{e.rule_id}: {e.message}" for e in errors)


def judge_wrong(label: str, expected_rule: str, word: str | None, got: list) -> tuple[str | None, str | None]:
    """(problem, warning) for a refusal. `got` = rule errors with .rule_id/.message. A wrong rule id or extra rule ids
    are problems; a message that lacks the advisory word is only a warning."""
    ids = {e.rule_id for e in got}
    if expected_rule not in ids:
        return f"{label}: expected rule {expected_rule}, the tool reported {explain_errors(got)}", None
    if ids != {expected_rule}:
        return (f"{label}: wrong in more than one way; expected only {expected_rule}, the tool reported "
                f"{explain_errors(got)}"), None
    if word and not any(word.lower() in e.message.lower() for e in got):
        return None, f"{label}: the {expected_rule} message does not contain '{word}': {explain_errors(got)}"
    return None, None


# ===================================================================================================== the run


def _amount(value: Decimal) -> str | None:
    return None if value == 0 else f"{value:.2f}"


def _draft(client_id, v: VoucherRec, ledger_id) -> VoucherDraft:
    return VoucherDraft(
        client_id, v.voucher_type, v.date, v.narration, v.reference_no,
        ledger_id(v.party_ledger) if v.party_ledger else None,
        tuple(VoucherLine(
            ledger_id(l.ledger_name), _amount(l.debit), _amount(l.credit),
            tuple(Allocation(a.kind, a.amount, a.bill_ref, a.due_date) for a in l.allocations),
        ) for l in v.lines),
    )


def _set_party(conn, client_id, ledger_id, p: PartyRec, bill_wise: bool) -> None:
    parties.set_party(
        conn, client_id, ledger_id, gstin=p.gstin, pan=p.pan, state_code=p.state_code, credit_days=p.credit_days,
        msme_category=p.msme_category, udyam_no=p.udyam_no, msme_written_agreement=p.msme_written_agreement,
        bill_wise=bill_wise, actor=ACTOR,
    )


def run_pack_p2(conn: Connection, pack: PackP2) -> RunReport:
    report = RunReport(pack.folder.name)
    c = pack.client
    as_on: date = c["pack_end_date"]

    created = client_setup.create_client(
        conn, ClientProfile(c["name"], c["entity_type"], c["business_type"], c["gst_type"]),
        fy_start=c["fy_start"], actor=ACTOR, proprietor_name=c.get("proprietor_name"),
        partners=list(c.get("partners") or []) or None,
    )
    cid, fy = created.client_id, created.financial_year_id

    # ---- ledgers: the tool's standard ledgers first, the pack's own through add_ledger
    template = {name.lower(): (name, lid) for name, lid in created.ledger_ids.items()}
    ids: dict[str, object] = {}
    tool_name: dict[str, str] = {}
    for row in pack.ledgers:
        key = row["ledger_name"].lower()
        if key in template:
            name, lid = template[key]
            actual_group = _group_name_of_ledger(conn, lid)
            if actual_group != row["group_name"]:
                report.add("setup", f"ledger {row['ledger_name']}: pack puts it under '{row['group_name']}', "
                                    f"the tool's standard ledger is under '{actual_group}'")
            if name != row["ledger_name"]:
                report.add("setup", f"ledger {row['ledger_name']}: the tool's standard ledger is spelt '{name}'")
            ids[row["ledger_name"]], tool_name[row["ledger_name"]] = lid, name
        else:
            ids[row["ledger_name"]] = client_setup.add_ledger(
                conn, cid, row["ledger_name"], GROUP_CODE_BY_NAME[row["group_name"]], actor=ACTOR)
            tool_name[row["ledger_name"]] = row["ledger_name"]

    def ledger_id(name: str) -> object:
        return ids.get(name, f"no ledger named '{name}'")

    for row in pack.ledgers:
        if row["opening_dr"] > 0 or row["opening_cr"] > 0:
            try:
                client_setup.set_opening_balance(
                    conn, cid, fy, ids[row["ledger_name"]], _amount(row["opening_dr"]), _amount(row["opening_cr"]),
                    actor=ACTOR)
            except ServiceError as refusal:
                report.add("setup", f"opening balance of {row['ledger_name']} refused: {refusal.message}")
    check = client_setup.opening_balance_difference(conn, cid, fy)
    if not check.is_balanced:
        report.add("setup", f"opening balances differ: Dr {format_inr(check.total_debit)} vs Cr {format_inr(check.total_credit)}")

    # ---- parties: bill_wise=false, opening bills, then bill_wise=true (decisions_parts/A.md, step 2.1)
    bills_by_party: dict[str, list[dict]] = defaultdict(list)
    for b in pack.opening_bills:
        bills_by_party[b["ledger_name"]].append(b)
    for p in pack.parties:
        try:
            _set_party(conn, cid, ids[p.ledger_name], p, bill_wise=False)
            if bills_by_party.get(p.ledger_name):
                bills.set_opening_bills(conn, cid, fy, ids[p.ledger_name], [
                    OpeningBillIn(b["bill_ref"], parse_date(b["bill_date"]), f"{parse_amount(b['amount']):.2f}",
                                  b["side"], parse_date(b["due_date"]) if b["due_date"] else None)
                    for b in bills_by_party[p.ledger_name]], actor=ACTOR)
            if p.bill_wise:
                _set_party(conn, cid, ids[p.ledger_name], p, bill_wise=True)
        except VoucherRuleError as refusal:
            report.add("setup", f"party {p.ledger_name} refused: {explain_errors(refusal.errors)}")
        except ServiceError as refusal:
            report.add("setup", f"party {p.ledger_name} refused: {refusal.message}")

    bank_name = pack.bank_format["bank_ledger"]
    bank_id = ids[bank_name]
    try:
        bank_items = [{"kind": i["kind"], "reference": i["reference"], "item_date": parse_date(i["item_date"]),
                       "amount": f"{parse_amount(i['amount']):.2f}"} for i in pack.bank_opening_items]
        reconciliation.set_bank_opening_items(conn, cid, fy, bank_id, bank_items, actor=ACTOR)
    except ServiceError as refusal:
        report.add("setup", f"bank opening items refused: {refusal.message}")

    # ---- correct vouchers (date order), then reversals
    posted: dict[str, object] = {}
    for v in pack.vouchers:
        try:
            result = vouchers.create_draft(conn, _draft(cid, v, ledger_id), actor=ACTOR)
            if result.errors:
                report.add("vouchers", f"correct voucher {v.ref_id} was refused: {explain_errors(result.errors)}")
                continue
            vouchers.approve(conn, result.voucher_id, actor=ACTOR)
            vouchers.post(conn, result.voucher_id, actor=ACTOR)
        except VoucherRuleError as refusal:
            report.add("vouchers", f"correct voucher {v.ref_id} could not be posted: {explain_errors(refusal.errors)}")
            continue
        except ServiceError as refusal:
            report.add("vouchers", f"correct voucher {v.ref_id} could not be posted: {refusal.message}")
            continue
        posted[v.ref_id] = result.voucher_id
        report.counts["vouchers_posted"] += 1
    if report.counts["vouchers_posted"] != len(pack.vouchers):
        report.add("vouchers", f"{len(pack.vouchers)} vouchers in the pack, {report.counts['vouchers_posted']} posted")

    for r in pack.reversals:
        if r["ref_id"] not in posted:
            report.add("reversals", f"reversal of {r['ref_id']} skipped: the voucher was not posted")
            continue
        try:
            vouchers.reverse(conn, posted[r["ref_id"]], parse_date(r["reversal_date"]), r["reason"], actor=ACTOR)
            report.counts["reversed"] += 1
        except ServiceError as refusal:
            report.add("reversals", f"reversal of {r['ref_id']} refused: {refusal.message}")

    # ---- wrong vouchers: each must be refused with ONLY its rule. Never posted (a wrongly accepted one stops at approve).
    for v in pack.wrong_vouchers:
        label = f"wrong voucher {v.ref_id}"
        errors: list = []
        try:
            result = vouchers.create_draft(conn, _draft(cid, v, ledger_id), actor=ACTOR)
            if result.errors:
                errors = result.errors
            else:
                try:
                    vouchers.approve(conn, result.voucher_id, actor=ACTOR)
                except VoucherRuleError as refusal:
                    errors = refusal.errors
                if not errors:
                    report.add("wrong_vouchers", f"{label} (expected {v.expected_rule_id}) was ACCEPTED (saved and approved)")
                    continue
        except ServiceError as refusal:
            report.add("wrong_vouchers", f"{label}: the tool raised '{refusal.message}' instead of a rule error")
            continue
        problem, warning = judge_wrong(label, v.expected_rule_id, v.expected_message_contains, errors)
        if problem:
            report.add("wrong_vouchers", problem)
        else:
            report.counts["wrong_vouchers_refused"] += 1
        if warning:
            report.warnings.append(warning)

    for p in pack.wrong_parties:
        label = f"wrong party {p.ref_id} ({p.ledger_name})"
        try:
            _set_party(conn, cid, ids[p.ledger_name], p, p.bill_wise)
        except VoucherRuleError as refusal:
            problem, warning = judge_wrong(label, p.expected_rule_id, p.expected_message_contains, refusal.errors)
            if problem:
                report.add("wrong_parties", problem)
            else:
                report.counts["wrong_parties_refused"] += 1
            if warning:
                report.warnings.append(warning)
        except ServiceError as refusal:
            report.add("wrong_parties", f"{label}: the tool raised '{refusal.message}' instead of a rule error")
        else:
            report.add("wrong_parties", f"{label} (expected {p.expected_rule_id}) was ACCEPTED")

    _compare_books(conn, pack, cid, ids, tool_name, as_on, report)
    _bank_part(conn, pack, cid, fy, ids, bank_id, posted, as_on, report)
    return report


def _compare_books(conn, pack: PackP2, cid, ids, tool_name, as_on: date, report: RunReport) -> None:
    exp = pack.expected

    # trial balance
    tb = reports.trial_balance(conn, cid, as_on)
    actual = {r.ledger_name: (r.debit, r.credit, r.group_path[-1]) for s in tb.sections for r in s.rows}
    listed = set()
    want_total = None
    for r in exp["expected_trial_balance"]:
        if r["group_name"] == "TOTAL":
            want_total = (Decimal(r["dr"]), Decimal(r["cr"]))
            continue
        name = tool_name.get(r["ledger_name"], r["ledger_name"])
        listed.add(name)
        if name not in actual:
            report.add("trial_balance", f"{r['ledger_name']}: not found in the tool's Trial Balance")
            continue
        dr, cr, group = actual[name]
        if (money(dr), money(cr)) != (r["dr"], r["cr"]):
            report.add("trial_balance", f"{r['ledger_name']}: expected Dr {r['dr']} / Cr {r['cr']}, tool says Dr {money(dr)} / Cr {money(cr)}")
        if group != r["group_name"]:
            report.add("trial_balance", f"{r['ledger_name']}: expected under '{r['group_name']}', the tool has it under '{group}'")
    for name, (dr, cr, _) in actual.items():
        if name not in listed and (dr or cr):
            report.add("trial_balance", f"{name}: not in the pack but the tool shows Dr {money(dr)} / Cr {money(cr)}")
    if want_total and (money(tb.total_debit), money(tb.total_credit)) != (money(want_total[0]), money(want_total[1])):
        report.add("trial_balance", f"totals: expected Dr {money(want_total[0])} / Cr {money(want_total[1])}, "
                                    f"tool says Dr {money(tb.total_debit)} / Cr {money(tb.total_credit)}")
    if not tb.is_balanced:
        report.add("trial_balance", f"the tool's Trial Balance does not balance: difference {format_inr(tb.difference.amount)} {tb.difference.side}")

    # outstanding + ageing
    for kind, natural, section, name in (
        ("receivable", "Dr", "outstanding_receivable", "expected_outstanding_receivable"),
        ("payable", "Cr", "outstanding_payable", "expected_outstanding_payable"),
    ):
        tool = bills.outstanding_report(conn, cid, kind, as_on)
        want, got = expected_outstanding(exp[name]), outstanding_rows(tool, natural)
        report.notes += [f"days past due, {kind}: " + n for n in reconcile_not_due_days(want, got)]
        for line in diff_keyed(want, got, OUTSTANDING_FIELDS, label=lambda k: f"{k[0]} {k[1]} {k[2]}".strip()):
            report.add(section, line)
        if not tool.ties:
            report.add(section, f"{kind}: the open items do not tie to the party ledger balances")
        want_a = {k: v for k, v in expected_ageing(exp["expected_ageing"]).items() if k[0] == kind}
        for line in diff_keyed(want_a, ageing_rows(tool), AGEING_FIELDS, label=lambda k: f"{k[0]} {k[1]} {k[2]}".strip()):
            report.add("ageing", line)

    # cash book (day totals)
    book = cashbook.cash_book(conn, cid, ids["Cash"], pack.client["fy_start"], as_on)
    for line in diff_keyed(expected_cash_book(exp["expected_cash_book"]), cash_book_rows(book),
                           ("receipts", "payments", "closing_dr"), label=lambda k: f"cash book {k[0]} {k[1]}".strip()):
        report.add("cash_book", line)

    # MSME
    rep = msme.msme_report(conn, cid, as_on)
    if rep.rule_status != "pending":
        report.add("msme_due", f"rule status expected 'pending', tool says '{rep.rule_status}'")
    for line in diff_keyed(expected_msme(exp["expected_msme_due"]), msme_rows(rep), MSME_FIELDS,
                           label=lambda k: f"msme {k[0]} {k[1]} {k[2]}".strip()):
        report.add("msme_due", line)


def _bank_part(conn, pack: PackP2, cid, fy, ids, bank_id, posted, as_on: date, report: RunReport) -> None:
    exp = pack.expected
    fmt = pack.bank_format
    try:
        format_id = bank.save_format(conn, cid, fmt["name"], fmt["mapping"], actor=ACTOR)
        content = (pack.folder / "bank_statement.csv").read_bytes()
        stmt = bank.import_statement(conn, cid, bank_id, format_id, "bank_statement.csv", content, actor=ACTOR)
    except ServiceError as refusal:
        report.add("bank_import", f"the statement import was refused: {refusal.message} {getattr(refusal, 'details', '') or ''}")
        return
    lines = bank.statement_lines(conn, stmt.statement_id)
    n_expected = len(exp["expected_matches"])
    if len(lines) != n_expected:
        report.add("bank_import", f"expected {n_expected} statement lines, the tool imported {len(lines)}")
    if stmt.opening_balance != Decimal(fmt["mapping"]["opening_balance"]):
        report.add("bank_import", f"opening balance expected {fmt['mapping']['opening_balance']}, tool says {money(stmt.opening_balance)}")
    want_close = next((r["amount"] for r in exp["expected_brs"] if r["line_type"] == "balance_per_bank"), None)
    if want_close and money(stmt.closing_balance) != want_close:
        report.add("bank_import", f"closing balance expected {want_close}, tool says {money(stmt.closing_balance)}")
    line_id = {ln.line_no: ln.id for ln in lines}

    # auto-match, then read the matches back as {bank line no -> book refs}
    summary = reconciliation.auto_match(conn, cid, bank_id, as_on, actor=ACTOR)
    report.counts["auto_matched_groups"] = summary.matched_groups
    voucher_ref = {vid: ref for ref, vid in posted.items()}
    rows = conn.execute(text(
        "SELECT mi.match_id, bl.line_no, vl.voucher_id, oi.reference FROM recon_match_items mi "
        "LEFT JOIN bank_statement_lines bl ON bl.id = mi.bank_line_id "
        "LEFT JOIN voucher_lines vl ON vl.id = mi.voucher_line_id "
        "LEFT JOIN bank_opening_items oi ON oi.id = mi.opening_item_id WHERE mi.client_id = :c"), {"c": cid}).all()
    groups: dict[object, tuple[set, set]] = defaultdict(lambda: (set(), set()))
    for r in rows:
        if r.line_no is not None:
            groups[r.match_id][0].add(r.line_no)
        elif r.voucher_id is not None:
            groups[r.match_id][1].add(voucher_ref.get(r.voucher_id, f"voucher {r.voucher_id}"))
        else:
            groups[r.match_id][1].add(f"OPENING:{r.reference}")
    actual_refs: dict[int, frozenset] = {no: frozenset() for no in line_id}
    for bank_nos, refs in groups.values():
        for no in bank_nos:
            actual_refs[no] = frozenset(refs)
    for r in exp["expected_matches"]:
        no = int(r["bank_line_no"])
        want, got = split_refs(r["book_refs"]), actual_refs.get(no, frozenset())
        if want != got:
            report.add("matches", f"statement line {no}: expected {_show(want)}, tool says {_show(got)}")

    # BRS
    result = reconciliation.brs(conn, cid, bank_id, as_on)
    for line in diff_keyed(expected_brs(exp["expected_brs"]), brs_rows(result), ("amount",),
                           label=lambda k: " ".join(x for x in k if x)):
        report.add("brs", line)
    if not result.ties or result.difference != 0:
        report.add("brs", f"the BRS does not tie: difference {money(result.difference)}")

    # bank-only drafts
    suggestions = {s.bank_line_id: s for s in reconciliation.bank_only_suggestions(conn, cid, bank_id, as_on)}
    items, wanted = [], {}
    for r in exp["expected_bank_only_drafts"]:
        no, counter = int(r["bank_line_no"]), r["counter_ledger"]
        if counter not in ids:
            code = GROUP_CODE_BY_NAME["Indirect Incomes" if r["voucher_type"] == "receipt" else "Indirect Expenses"]
            ids[counter] = client_setup.add_ledger(conn, cid, counter, code, actor=ACTOR)
            report.notes.append(f"the runner created the counter ledger '{counter}' (as an accountant would) for the bank-only draft")
        sug = suggestions.get(line_id.get(no))
        if sug is None:
            report.notes.append(f"statement line {no}: the tool made no suggestion; the runner chose '{counter}' from the pack")
        elif sug.counter_ledger_name is None:
            report.notes.append(f"statement line {no}: the tool suggests no counter ledger ({sug.reason}); the runner chose '{counter}'")
        elif sug.counter_ledger_name != counter:
            report.warnings.append(f"statement line {no}: the tool suggests '{sug.counter_ledger_name}', the pack says '{counter}'")
        items.append((line_id[no], ids[counter]))
        wanted[line_id[no]] = (no, r)
    result_d = reconciliation.draft_vouchers_for_bank_only(conn, cid, bank_id, items, actor=ACTOR)
    if result_d.errors:
        for _bank_line, errs in result_d.errors:
            report.add("bank_only_drafts", f"draft refused: {explain_errors(errs)}")
        return
    if len(result_d.created) != len(wanted):
        report.add("bank_only_drafts", f"expected {len(wanted)} drafts, the tool created {len(result_d.created)}")
    for bank_line, voucher_id in result_d.created:
        no, r = wanted[bank_line]
        head = conn.execute(text("SELECT voucher_type, voucher_date, status, voucher_number FROM vouchers WHERE id = :v"),
                            {"v": voucher_id}).one()
        lines_ = conn.execute(text(
            "SELECT l.name, vl.debit, vl.credit FROM voucher_lines vl JOIN ledgers l ON l.id = vl.ledger_id "
            "WHERE vl.voucher_id = :v ORDER BY vl.line_no"), {"v": voucher_id}).all()
        label = f"bank-only draft for statement line {no}"
        if head.status != "draft" or head.voucher_number is not None:
            report.add("bank_only_drafts", f"{label}: must be a draft with no number, tool has status {head.status} {head.voucher_number or ''}")
        if head.voucher_type != r["voucher_type"]:
            report.add("bank_only_drafts", f"{label}: type expected {r['voucher_type']}, tool says {head.voucher_type}")
        if head.voucher_date.isoformat() != r["txn_date"]:
            report.add("bank_only_drafts", f"{label}: date expected {r['txn_date']}, tool says {head.voucher_date.isoformat()}")
        counter_line = next((x for x in lines_ if x.name == r["counter_ledger"]), None)
        if counter_line is None:
            report.add("bank_only_drafts", f"{label}: no line on '{r['counter_ledger']}'")
        elif money(counter_line.debit or counter_line.credit) != r["amount"]:
            report.add("bank_only_drafts", f"{label}: amount expected {r['amount']}, tool says {money(counter_line.debit or counter_line.credit)}")
        report.counts["bank_only_drafts"] += 1
    posted_now = conn.execute(text("SELECT count(*) FROM vouchers WHERE client_id = :c AND status IN ('posted','reversed')"),
                              {"c": cid}).scalar_one()
    if posted_now != len(posted) + sum(1 for _ in pack.reversals):
        report.add("bank_only_drafts", f"posted/reversed voucher count changed to {posted_now}: drafts must never be posted")
    after = reconciliation.brs(conn, cid, bank_id, as_on)
    if after.difference != 0:
        report.add("bank_only_drafts", f"the BRS stopped tying after drafting: difference {money(after.difference)}")
