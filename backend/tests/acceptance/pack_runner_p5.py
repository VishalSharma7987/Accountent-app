"""Phase 5 (Inventory) acceptance runner: drives the REAL services (not the API) with the Phase 5 pack and compares every result
with the hand-worked expected files.

It never modifies a pack file and never bends the tool to fit them: every difference is collected per section as one plain line
(expected vs tool) for the owner to decide. The valuation method of a year is frozen once it has movements, so the same month is
run for three clients that differ only in their method (FIFO, weighted average periodic, weighted average moving). Each client
gets: ledgers, GST registration, godowns, stock items, policy, opening stock, 10 invoice vouchers with stock (purchases, sales,
a debit note and a credit note that are physical returns), 2 stock journals (a damage write-off, a transfer), NRV per item, the
stock register, the item ledgers (cost of every movement), the closing stock at lower of cost and NRV, and the refusals of the
wrong cases (S-01, S-02, S-10, S-12), after which nothing may have been posted by them.
"""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from pack_loader_p5 import METHODS, JournalRec5, PackP5, VoucherRec5
from pack_runner_p2 import diff_keyed
from pack_runner_p3 import _post, _refusal_text, _setup_ledgers
from sqlalchemy import Connection, text

from app.db import repositories_inventory_movements as mov_repo
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.inventory_journals import JournalLineInput
from app.engine.inventory_masters import OpeningInput
from app.engine.inventory_voucher import StockLineIn
from app.engine.models import VoucherDraft
from app.services import (
    client_setup,
    gst_items,
    gst_registrations,
    inventory_journals,
    inventory_masters,
    inventory_nrv,
    inventory_reports,
    vouchers,
)
from app.services.client_setup import ClientProfile
from app.services.errors import ServiceError, VoucherRuleError
from app.services.inventory_nrv import NrvInput

ACTOR = "pack-runner-p5"
PER_METHOD = ("setup", "vouchers", "register", "movement_cost", "by_godown", "closing_stock", "wrong_cases")
SECTIONS = tuple(f"{m}/{s}" for m in METHODS for s in PER_METHOD)


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


def refusal_key(refusal: Exception) -> str:
    """The rule id of a refusal: the first rule error of a voucher / journal, or the rule id inside a service error's details
    (S-01 comes as `negative_stock`), else the service error code."""
    if isinstance(refusal, VoucherRuleError):
        return refusal.errors[0].rule_id if refusal.errors else refusal.code
    details = getattr(refusal, "details", None)
    if isinstance(details, list) and details and isinstance(details[0], dict) and details[0].get("rule_id"):
        return str(details[0]["rule_id"])
    return getattr(refusal, "code", type(refusal).__name__)


def count_movements(conn: Connection, cid) -> int:
    return conn.execute(text("SELECT count(*) FROM stock_movements WHERE client_id = :c"), {"c": cid}).scalar_one()


@contextmanager
def guard(report: RunReport, section: str):
    """A service that raises instead of answering is a difference too: it is reported, the run goes on."""
    try:
        yield
    except (VoucherRuleError, ServiceError) as refusal:
        report.add(section, f"the tool refused instead of answering: {_refusal_text(refusal)}")
    except Exception as crash:  # noqa: BLE001 - any failure of the tool is a finding, not a crash of the report
        report.add(section, f"the tool failed with {type(crash).__name__}: {crash}")


class World:
    """What one method's client needs while its movements are posted."""

    def __init__(self, conn: Connection, pack: PackP5, method: str, report: RunReport):
        self.conn, self.pack, self.method, self.report = conn, pack, method, report
        c = pack.client
        created = client_setup.create_client(
            conn, ClientProfile(f"{c['name']} ({method})", c["entity_type"], c["business_type"], c["gst_type"]),
            fy_start=c["fy_start"], actor=ACTOR, proprietor_name=c.get("proprietor_name"))
        self.cid, self.fy = created.client_id, created.financial_year_id
        zero = Decimal("0.00")
        self.ids = _setup_ledgers(conn, report, self.cid, self.fy, created,
                                  [{**r, "opening_dr": zero, "opening_cr": zero} for r in pack.ledgers])
        self.reg_id = None
        self.godown: dict[str, object] = {}
        self.item: dict[str, object] = {}
        self.item_facts = {r["item_name"]: r for r in pack.items}
        self.number: dict[str, str] = {}  # ref -> voucher / journal number
        self.date_of: dict[str, date] = {}
        self.vrec: dict[str, VoucherRec5] = {}
        self.ref_of_number: dict[str, str] = {}

    def sec(self, name: str) -> str:
        return f"{self.method}/{name}"

    # ---------------------------------------------------------------------------------------------- setup
    def setup(self) -> None:
        pack, conn, cid, c = self.pack, self.conn, self.cid, self.pack.client
        with guard(self.report, self.sec("setup")):
            self.reg_id = gst_registrations.create_registration(
                conn, cid, gstin=c["registration_gstin"], registration_type="regular", effective_from=c["fy_start"], actor=ACTOR)
            gst_registrations.set_ledger_roles(conn, cid, self.reg_id, {r["role"]: self.ids[r["ledger_name"]] for r in pack.roles},
                                               actor=ACTOR)
            for name in pack.godowns:
                self.godown[name] = inventory_masters.create_godown(conn, cid, name=name, actor=ACTOR)
            for it in pack.items:
                item_id = gst_items.create_item(
                    conn, cid, name=it["item_name"], item_kind="goods", hsn_sac=it["hsn_sac"], uqc=it["uqc"],
                    sales_ledger_id=self.ids[it["sales_ledger"]], purchase_ledger_id=self.ids[it["purchase_ledger"]], actor=ACTOR)
                inventory_masters.put_stock_item(conn, cid, item_id, sku=it["sku"],
                                                 default_godown_id=self.godown[it["default_godown"]], actor=ACTOR)
                self.item[it["item_name"]] = item_id
            inventory_masters.put_policy(conn, cid, self.fy, valuation_method=self.method,
                                         negative_stock_mode=c["negative_stock_mode"], actor=ACTOR)
            total = inventory_masters.replace_opening(
                conn, cid, self.fy,
                [OpeningInput(self.item[r["item_name"]], self.godown[r["godown_name"]], r["quantity"], r["value"]) for r in pack.opening],
                actor=ACTOR)
            want_total = sum((r["value"] for r in pack.opening), Decimal("0.00"))
            if Decimal(str(total)) != want_total:
                self.report.add(self.sec("setup"), f"opening stock total expected {want_total:.2f}, tool says {Decimal(str(total)):.2f}")

    # ---------------------------------------------------------------------------------------------- drafts
    def original_movement(self, original_ref: str, item_name: str):
        """The sale / purchase movement of the original voucher (what a physical return names)."""
        rows = mov_repo.returnable(self.conn, self.cid, self.item[item_name], None)
        wanted = self.number[original_ref]
        found = [r for r in rows if r["voucher_number"] == wanted]
        return str(found[0]["movement_id"]) if found else None

    def draft(self, v_type: str, on: date, narration: str, reference_no, party: str, gstin: str, original_ref, note_reason,
              lines: list[tuple[str, Decimal, Decimal, str | None, str]]) -> VoucherDraft:
        """`lines` = (item name, quantity, rate, godown name or None, ledger name)."""
        items, stock = [], []
        for n, (name, qty, rate, godown, ledger) in enumerate(lines, start=1):
            facts = self.item_facts[name]
            items.append(ItemLineIn(name, facts["hsn_sac"], qty, rate, Decimal("0.00"), str(self.ids[ledger]), str(self.item[name]), facts["uqc"]))
            if v_type in ("credit_note", "debit_note"):
                stock.append(StockLineIn(n, str(self.godown[godown]) if godown else None, self.original_movement(original_ref, name)))
            elif godown:
                stock.append(StockLineIn(n, str(self.godown[godown])))
        original_no = original_date = None
        if original_ref:
            original = self.vrec[original_ref]
            original_no = original.reference_no or self.number[original_ref]
            original_date = original.date
        inv = InvoiceIn(str(self.reg_id), "tax_invoice", "b2b", self.pack.client["place_of_supply"], on, tuple(items), gstin,
                        original_invoice_no=original_no, original_invoice_date=original_date, note_reason=note_reason)
        return VoucherDraft(self.cid, v_type, on, narration, reference_no, self.ids[party], (), gst=inv, stock=tuple(stock))

    def post_voucher(self, v: VoucherRec5) -> None:
        draft = self.draft(v.voucher_type, v.date, v.narration, v.reference_no, v.party_ledger, v.counterparty_gstin, v.original_ref,
                           v.note_reason, [(i.item_name, i.quantity, i.unit_rate, i.godown_name, i.item_ledger) for i in v.items])
        vid, problem = _post(self.conn, draft)
        if problem:
            self.report.add(self.sec("vouchers"), f"correct voucher {v.ref_id} was refused: {problem}")
            return
        self.number[v.ref_id] = vouchers.get_voucher(self.conn, vid).voucher_number
        self.vrec[v.ref_id] = v
        self.report.counts["vouchers_posted"] += 1

    def journal_lines(self, j) -> list[JournalLineInput]:
        return [JournalLineInput(self.item[j.item_name], self.godown[j.from_godown_name],
                                 self.godown[j.to_godown_name] if j.to_godown_name else None, j.quantity)]

    def post_journal(self, j: JournalRec5) -> None:
        try:
            view = inventory_journals.create_journal(
                self.conn, self.cid, journal_type=j.journal_type, journal_date=j.date, narration=j.narration, reason_code=j.reason_code,
                reason_note=j.reason_note, lines=self.journal_lines(j), actor=ACTOR)
            inventory_journals.approve_journal(self.conn, self.cid, view.row.id, actor=ACTOR)
            done = inventory_journals.post_journal(self.conn, self.cid, view.row.id, actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            self.report.add(self.sec("vouchers"), f"correct journal {j.ref_id} was refused: {_refusal_text(refusal)}")
            return
        self.number[j.ref_id] = done.row.journal_number
        self.report.counts["journals_posted"] += 1

    # ---------------------------------------------------------------------------------------------- run
    def run(self) -> None:
        pack, report = self.pack, self.report
        self.setup()
        if self.reg_id is None or not self.item:
            report.add(self.sec("setup"), "the client could not be set up: nothing else can run")
            return
        timeline = sorted([(v.date, 0, v) for v in pack.vouchers] + [(j.date, 1, j) for j in pack.journals], key=lambda x: (x[0], x[1]))
        for _, _, entry in timeline:
            with guard(report, self.sec("vouchers")):
                self.post_voucher(entry) if isinstance(entry, VoucherRec5) else self.post_journal(entry)
        self.ref_of_number = {n: r for r, n in self.number.items()}
        want = {(r["ref_id"],): {"number": r["voucher_number"]} for r in pack.expected["expected_vouchers"]}
        got = {(ref,): {"number": n} for ref, n in self.number.items()}
        for line in diff_keyed(want, got, ("number",), label=lambda k: f"document {k[0]}"):
            report.add(self.sec("vouchers"), line)
        with guard(report, self.sec("register")):
            self.check_register()
        with guard(report, self.sec("movement_cost")):
            self.check_movement_cost()
        with guard(report, self.sec("by_godown")):
            self.check_by_godown()
        with guard(report, self.sec("closing_stock")):
            self.check_closing_stock()
        with guard(report, self.sec("wrong_cases")):
            self.check_wrong_cases()

    # ---------------------------------------------------------------------------------------------- checks
    def expected(self, name: str) -> list[dict]:
        return [r for r in self.pack.expected[name] if "method" not in r or r["method"] == self.method]

    def check_register(self) -> None:
        sec, c = self.sec("register"), self.pack.client
        result = inventory_reports.stock_register(self.conn, self.cid, self.fy, from_date=c["report_from"], to_date=c["report_to"])
        if result["policy"]["valuation_method"] != self.method:
            self.report.add(sec, f"policy: expected {self.method}, tool says {result['policy']['valuation_method']}")
        cols = ("opening_qty", "opening_value", "inward_qty", "inward_value", "outward_qty", "outward_value", "closing_qty", "closing_value")
        want = {(r["item_name"],): {k: r[k] for k in cols} for r in self.expected("expected_register")}
        got = {(r["name"],): {k: r[k] for k in cols} for r in result["rows"]}
        for line in diff_keyed(want, got, cols, label=lambda k: f"{self.method} register {k[0]}"):
            self.report.add(sec, line)
        totals_cols = ("opening_value", "inward_value", "outward_value", "closing_value")
        want_t = {(r["method"],): {k: r[k] for k in totals_cols}
                  for r in self.pack.expected["expected_register_totals"] if r["method"] == self.method}
        got_t = {(self.method,): {k: result["totals"][k] for k in totals_cols}}
        for line in diff_keyed(want_t, got_t, totals_cols, label=lambda k: f"{k[0]} register totals"):
            self.report.add(sec, line)
        for e in result["errors"]:
            self.report.add(sec, f"the register reports an error {e['rule_id']}: {e['message']}")
        self.report.notes += [f"{self.method} register warning {w['rule_id']}: {w['message']}" for w in result["warnings"]]

    def check_movement_cost(self) -> None:
        sec, c = self.sec("movement_cost"), self.pack.client
        got: dict[tuple, dict] = {}
        for name, item_id in self.item.items():
            ledger = inventory_reports.item_ledger(self.conn, self.cid, item_id, self.fy, from_date=c["report_from"], to_date=c["report_to"])
            for r in ledger["rows"]:
                inward = Decimal(r["in_qty"]) > 0
                number = r["document_number"]
                ref = self.ref_of_number.get(number, str(number))
                got[(ref, name, r["kind"])] = {"quantity": r["in_qty"] if inward else r["out_qty"],
                                               "value": r["in_value"] if inward else r["out_value"]}
            for e in ledger["errors"]:
                self.report.add(sec, f"item ledger of {name} reports an error {e['rule_id']}: {e['message']}")
        want = {(r["ref_id"], r["item_name"], r["kind"]): {"quantity": r["quantity"], "value": r["value"]} for r in self.expected("expected_movement_cost")}
        for line in diff_keyed(want, got, ("quantity", "value"), label=lambda k: f"{self.method} movement {k[0]} {k[1]} {k[2]}"):
            self.report.add(sec, line)

    def check_by_godown(self) -> None:
        sec, c = self.sec("by_godown"), self.pack.client
        result = inventory_reports.stock_register(self.conn, self.cid, self.fy, from_date=c["report_from"], to_date=c["report_to"])
        got = {(r["name"], g["godown_name"]): {"closing_qty": g["closing_qty"]}
               for r in result["rows"] for g in r["by_godown"] if Decimal(g["closing_qty"]) != 0}
        want = {(r["item_name"], r["godown_name"]): {"closing_qty": r["closing_qty"]} for r in self.pack.expected["expected_by_godown"]}
        for line in diff_keyed(want, got, ("closing_qty",), label=lambda k: f"{self.method} {k[0]} in {k[1]}"):
            self.report.add(sec, line)
        # the godown view of the register: quantities only, no values (valuation is per item)
        shop = inventory_reports.stock_register(self.conn, self.cid, self.fy, from_date=c["report_from"], to_date=c["report_to"],
                                                godown_id=self.godown["Shop"])
        if any(r["closing_value"] is not None for r in shop["rows"]):
            self.report.add(sec, "the register of one godown shows values; valuation is per item, so they must be blank")

    def check_closing_stock(self) -> None:
        sec, c = self.sec("closing_stock"), self.pack.client
        inventory_nrv.put_nrv(
            self.conn, self.cid, self.fy, c["nrv_as_on"],
            [NrvInput(self.item[r["item_name"]], r["nrv_per_unit"], r["basis_note"]) for r in self.pack.nrv], actor=ACTOR)
        result = inventory_reports.closing_stock(self.conn, self.cid, self.fy, as_on=c["nrv_as_on"])
        cols = ("closing_qty", "cost_value", "nrv_per_unit", "nrv_value", "write_down", "carrying_value")
        want = {(r["item_name"],): {k: r[k] for k in cols} for r in self.expected("expected_closing_stock")}
        got = {(r["name"],): {k: ("" if r[k] is None else r[k]) for k in cols} for r in result["rows"]}
        for line in diff_keyed(want, got, cols, label=lambda k: f"{self.method} closing stock {k[0]}"):
            self.report.add(sec, line)
        names = {r["item_id"]: r["name"] for r in result["rows"]}
        for row in (r for r in self.pack.expected["expected_closing_totals"] if r["method"] == self.method):
            for k in ("cost_value", "write_down", "carrying_value"):
                if result["totals"][k] != row[k]:
                    self.report.add(sec, f"{self.method} closing totals {k}: expected {row[k]}, tool says {result['totals'][k]}")
            without = sorted(names.get(i, i) for i in result["items_without_nrv"])
            if without != sorted(x for x in row["items_without_nrv"].split("|") if x):
                self.report.add(sec, f"{self.method} items without NRV: expected {row['items_without_nrv']}, tool says {'|'.join(without)}")
        s15 = [w for w in result["warnings"] if w["rule_id"] == "S-15"]
        if len(s15) != 1:
            self.report.add(sec, f"{self.method}: expected exactly one S-15 warning (the item without NRV), the tool gave {len(s15)}")
        for e in result["errors"]:
            self.report.add(sec, f"closing stock reports an error {e['rule_id']}: {e['message']}")
        if result["policy"]["valuation_method"] != self.method:
            self.report.add(sec, f"closing stock states method {result['policy']['valuation_method']}, expected {self.method}")

    def check_wrong_cases(self) -> None:
        sec = self.sec("wrong_cases")
        for w in self.pack.wrong_cases:
            before = count_movements(self.conn, self.cid)
            label = f"{self.method} wrong case {w['case_id']} ({w['description']})"
            key = self.try_wrong(w)
            if key != w["expected_rule"]:
                self.report.add(sec, f"{label}: expected refusal {w['expected_rule']}, the tool said {key}")
            else:
                self.report.counts["wrong_cases_refused"] += 1
            if count_movements(self.conn, self.cid) != before:
                self.report.add(sec, f"{label}: stock movements were written although the case is wrong")

    def try_wrong(self, w: dict) -> str:
        """The rule id the tool refuses with ('accepted' when it did not refuse)."""
        try:
            qty = Decimal(w["quantity"])
        except InvalidOperation:
            return "bad pack row"
        on = date.fromisoformat(w["date"])
        pack = self.pack
        if w["kind"] in ("transfer", "write_off"):
            j = JournalRec5(w["case_id"], w["kind"], on, w["description"], w["reason_code"] or None,
                            "Wrong-case check" if w["reason_code"] else None, w["item_name"], w["godown_name"],
                            w["to_godown_name"] or None, qty)
            try:
                view = inventory_journals.create_journal(
                    self.conn, self.cid, journal_type=j.journal_type, journal_date=j.date, narration=j.narration,
                    reason_code=j.reason_code, reason_note=j.reason_note, lines=self.journal_lines(j), actor=ACTOR)
                inventory_journals.approve_journal(self.conn, self.cid, view.row.id, actor=ACTOR)
                inventory_journals.post_journal(self.conn, self.cid, view.row.id, actor=ACTOR)
            except (VoucherRuleError, ServiceError) as refusal:
                return refusal_key(refusal)
            return "accepted"
        v_type = w["kind"]
        party, ledger, rate = (("Rahul Enterprises", "Sales", Decimal("20.00")) if v_type == "sales"
                               else ("Rahul Enterprises", "Sales Returns", Decimal("22.00")))
        original = w["original_ref"] or None
        draft = self.draft(v_type, on, w["description"], None, party, pack.vouchers[0].counterparty_gstin, original,
                           "sales_return" if original else None, [(w["item_name"], qty, rate, w["godown_name"] or None, ledger)])
        try:
            result = vouchers.create_draft(self.conn, draft, actor=ACTOR)
            if result.errors:
                return result.errors[0].rule_id
            vouchers.approve(self.conn, result.voucher_id, actor=ACTOR)
            vouchers.post(self.conn, result.voucher_id, actor=ACTOR)
        except (VoucherRuleError, ServiceError) as refusal:
            return refusal_key(refusal)
        return "accepted"


# ===================================================================================================== the run


def run_pack_p5(conn: Connection, pack: PackP5) -> RunReport:
    report = RunReport(pack.folder.name)
    report.notes.append(
        "Known limit (package B, not exercised): the goods of a reversed sale come back as a NEW FIFO layer, so reversing the original "
        "purchase afterwards is still refused (S-17), a false block.")
    for method in METHODS:
        World(conn, pack, method, report).run()
    return report
