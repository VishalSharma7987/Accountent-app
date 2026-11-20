"""Reads the Phase 8 pack docs/test-packs/phase8-* (audit checks A-01 .. A-18 with injected errors) as typed plain rows.

Format rules follow the Phase 1-7 loaders (2-decimal plain amounts, UTF-8 CSV). Nothing here imports the accounting engine, a service, the
database or a language-model client. No file of the pack is ever written. The pack is SYNTHETIC: a loader check refuses text that looks like
an OpenRouter key. The marker file `phase8.yaml` is what tells the Phase 1-7 runners to leave the folder alone.
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import PackFormatError, parse_amount

MARKER = "phase8.yaml"
CHECK_IDS = tuple(f"A-{n:02d}" for n in range(1, 19))
SEVERITIES = ("error", "review", "warning", "info")
KINDS = ("injected", "variant", "incidental", "mirror")
RUNS = ("FY26", "FY25")
CONTROL_KINDS = ("voucher", "ledger", "text")
_KEY = re.compile(r"sk-or-", re.IGNORECASE)


@dataclass(frozen=True)
class Voucher:
    ref: str
    fy: str                     # F26 | F25
    voucher_type: str
    on: date
    number: str
    party: str
    reference_no: str
    document: bool
    posted_at: datetime | None
    narration: str
    lines: tuple[tuple[str, Decimal, Decimal, str, str, date | None], ...]   # ledger, debit, credit, alloc kind, alloc ref, alloc due

    @property
    def total(self) -> Decimal:
        return sum((ln[1] for ln in self.lines), Decimal("0.00"))


@dataclass(frozen=True)
class ExpectedFinding:
    id: str
    run: str
    kind: str
    check_id: str
    severity: str
    finding_date: date | None
    amount: Decimal | None
    disallowance: Decimal | None
    rule_status: str
    subject_ref: str
    evidence_vouchers: frozenset[str]
    evidence_ledgers: frozenset[str]
    evidence_values: tuple[tuple[str, str], ...]

    @property
    def key(self) -> tuple:
        return (self.run, self.check_id, self.finding_date, self.amount, self.subject_ref)


@dataclass(frozen=True)
class Control:
    id: str
    check_id: str
    kind: str
    target: str
    why: str


@dataclass(frozen=True)
class SampleCase:
    id: str
    method: str
    seed: int
    size: int | None
    threshold: Decimal | None
    rest_size: int | None
    start: int | None
    expected: tuple[str, ...]


@dataclass(frozen=True)
class FlowStep:
    step: int
    action: str
    arg: str
    expect: str


@dataclass
class Pack:
    root: Path
    config: dict
    ledgers: list[dict]
    parties: list[dict]
    openings: list[tuple[str, Decimal, Decimal]]
    vouchers: list[Voucher]
    tds_deductees: list[dict]
    tds_items: list[dict]
    tds_challans: list[dict]
    gst_filed: list[dict]
    stock_items: list[dict]
    stock_journals: list[dict]
    holidays: list[dict]
    related: list[dict]
    lock_events: list[dict]
    findings: list[ExpectedFinding]
    summary: dict[tuple[str, str], tuple[int, int]]       # (run, check) -> (findings, population)
    controls: list[Control]
    sampling_population: tuple[str, ...]
    sampling: list[SampleCase]
    paper_flow: list[FlowStep]
    form: list[tuple[str, str, str, str]]                 # clause, field, value, origin
    ai: list[FlowStep]
    voucher_by_ref: dict[str, Voucher] = field(default_factory=dict)


def read_rows(root: Path, name: str) -> list[dict[str, str]]:
    path = root / name
    if not path.is_file():
        raise PackFormatError(f"{name}: file is missing")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{k.strip(): (v or "").strip() if k != "reference_no" else (v or "") for k, v in row.items()} for row in csv.DictReader(handle)
                if any((v or "").strip() for v in row.values())]


def _date(text: str, where: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise PackFormatError(f"{where}: '{text}' is not a date (YYYY-MM-DD)") from None


def _amount(text: str, where: str) -> Decimal | None:
    return parse_amount(text, where) if text else None


def _int(text: str, where: str) -> int | None:
    if not text:
        return None
    if not re.fullmatch(r"-?\d+", text):
        raise PackFormatError(f"{where}: '{text}' must be a whole number")
    return int(text)


def _set(text: str) -> frozenset[str]:
    return frozenset(x.strip() for x in text.split(";") if x.strip())


def _pairs(text: str, where: str) -> tuple[tuple[str, str], ...]:
    out = []
    for part in (p for p in text.split("|") if p.strip()):
        if "=" not in part:
            raise PackFormatError(f"{where}: '{part}' must look like key=value")
        k, _, val = part.partition("=")
        out.append((k.strip(), val.strip()))
    return tuple(out)


def load_pack_p8(root: Path) -> Pack:
    root = Path(root)
    if not (root / MARKER).is_file():
        raise PackFormatError(f"{root.name}: not a Phase 8 pack ({MARKER} is missing)")
    config = yaml.safe_load((root / MARKER).read_text(encoding="utf-8"))

    lines: dict[str, list] = {}
    for r in read_rows(root, "lines.csv"):
        lines.setdefault(r["ref"], []).append((
            r["ledger"], parse_amount(r["debit"], "lines.csv "), parse_amount(r["credit"], "lines.csv "), r["alloc_kind"], r["alloc_ref"],
            _date(r["alloc_due"], "lines.csv alloc_due")))
    vouchers = []
    for r in read_rows(root, "vouchers.csv"):
        if r["ref"] not in lines:
            raise PackFormatError(f"vouchers.csv: {r['ref']} has no lines")
        posted = datetime.fromisoformat(r["posted_at"]) if r["posted_at"] else None
        vouchers.append(Voucher(r["ref"], r["fy"], r["type"], _date(r["date"], "vouchers.csv date"), r["number"], r["party"], r["reference_no"],
                                r["document"] == "yes", posted, r["narration"], tuple(lines[r["ref"]])))
    refs = [v.ref for v in vouchers]
    if len(set(refs)) != len(refs):
        raise PackFormatError("vouchers.csv: a voucher ref is used twice")
    for v in vouchers:
        if sum(ln[1] for ln in v.lines) != sum(ln[2] for ln in v.lines):
            raise PackFormatError(f"vouchers.csv / lines.csv: {v.ref} does not balance (debit and credit differ)")

    findings = []
    for r in read_rows(root, "expected_findings.csv"):
        if r["check_id"] not in CHECK_IDS or r["severity"] not in SEVERITIES or r["run"] not in RUNS or r["kind"] not in KINDS:
            raise PackFormatError(f"expected_findings.csv: bad check, severity, run or kind in {r['id']}")
        findings.append(ExpectedFinding(
            r["id"], r["run"], r["kind"], r["check_id"], r["severity"], _date(r["finding_date"], "expected_findings.csv finding_date"),
            _amount(r["amount"], "expected_findings.csv "), _amount(r["disallowance"], "expected_findings.csv "), r["rule_status"], r["subject_ref"],
            _set(r["evidence_vouchers"]), _set(r["evidence_ledgers"]), _pairs(r["evidence_values"], f"expected_findings.csv {r['id']}")))
    if len({f.key for f in findings}) != len(findings):
        raise PackFormatError("expected_findings.csv: two expected findings have the same run, check, date, amount and subject")
    if len({f.id for f in findings}) != len(findings):
        raise PackFormatError("expected_findings.csv: an id is used twice")
    known = {v.ref for v in vouchers}
    for f in findings:
        for ref in f.evidence_vouchers:
            if ref not in known:
                raise PackFormatError(f"expected_findings.csv: {f.id} names an unknown voucher {ref}")

    summary = {(r["run"], r["check_id"]): (_int(r["findings"], "findings"), _int(r["population"], "population"))
               for r in read_rows(root, "expected_summary.csv")}
    for run in RUNS:
        for key in [k for k in summary if k[0] == run]:
            expected = len([f for f in findings if f.run == run and f.check_id == key[1]])
            if summary[key][0] != expected:
                raise PackFormatError(f"expected_summary.csv: {key} says {summary[key][0]} findings, expected_findings.csv lists {expected}")

    controls = []
    for r in read_rows(root, "expected_controls.csv"):
        if r["kind"] not in CONTROL_KINDS or r["check_id"] not in CHECK_IDS:
            raise PackFormatError(f"expected_controls.csv: bad kind or check in {r['id']}")
        if r["kind"] == "voucher" and r["target"] not in known:
            raise PackFormatError(f"expected_controls.csv: {r['id']} names an unknown voucher {r['target']}")
        controls.append(Control(r["id"], r["check_id"], r["kind"], r["target"], r["why"]))

    sampling_rows = read_rows(root, "expected_sampling.csv")
    population = tuple(x for r in sampling_rows if r["method"] == "population" for x in r["expected"].split(";"))
    cases = [SampleCase(r["id"], r["method"], _int(r["seed"], "seed"), _int(r["size"], "size"), _amount(r["threshold"], "expected_sampling.csv "),
                        _int(r["rest_size"], "rest_size"), _int(r["start"], "start"), tuple(r["expected"].split(";")))
             for r in sampling_rows if r["method"] != "population"]
    for ref in population:
        if ref not in known:
            raise PackFormatError(f"expected_sampling.csv: population names an unknown voucher {ref}")

    def flow(name):
        return [FlowStep(_int(r["step"], f"{name} step"), r["action"], r["arg"], r["expect"]) for r in read_rows(root, name)]

    pack = Pack(root, config, read_rows(root, "ledgers.csv"), read_rows(root, "parties.csv"),
                [(r["ledger"], parse_amount(r["debit"], "openings.csv "), parse_amount(r["credit"], "openings.csv ")) for r in read_rows(root, "openings.csv")],
                vouchers, read_rows(root, "tds_deductees.csv"), read_rows(root, "tds_items.csv"), read_rows(root, "tds_challans.csv"),
                read_rows(root, "gst_filed.csv"), read_rows(root, "stock_items.csv"), read_rows(root, "stock_journals.csv"),
                read_rows(root, "holidays.csv"), read_rows(root, "related_parties.csv"), read_rows(root, "lock_events.csv"),
                findings, summary, controls, population, cases, flow("expected_paper_flow.csv"),
                [(r["clause_no"], r["field_key"], r["value"], r["origin"]) for r in read_rows(root, "expected_form3cd.csv")],
                flow("expected_ai.csv"), {v.ref: v for v in vouchers})
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".txt", ".csv", ".json", ".yaml", ".md") and _KEY.search(path.read_text(encoding="utf-8")):
            raise PackFormatError(f"{path.name}: looks like an API key; a pack holds synthetic data only")
    return pack
