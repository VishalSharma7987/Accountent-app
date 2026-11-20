"""Reads the Phase 7 pack docs/test-packs/phase7-* (documents, fake language model, bank narrations, Tally files) as typed plain rows.

Format rules follow the Phase 1-6 loaders (2-decimal plain amounts) plus: the scripted model answers are JSON, every text file is UTF-8, and
nothing here imports the accounting engine, a service, the database or a language-model client. No file of the pack is ever written.
The pack contains SYNTHETIC data only: a loader check refuses text that looks like an OpenRouter key.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml
from pack_loader_p2 import PackFormatError, parse_amount

MARKER = "phase7.yaml"  # the file that tells the Phase 1-6 runners to leave this folder alone
SEVERITIES = ("error", "review", "warning", "info")
STAGES = ("attempt1", "initial", "final")
ACTIONS = ("accept", "accept_refused", "accept_clean", "edit", "add_line", "party_mapping", "reject", "approve_post", "leave")
_KEY = re.compile(r"sk-or-", re.IGNORECASE)


@dataclass(frozen=True)
class DocRec:
    doc_id: str
    file: str
    doc_type: str
    arrives: str            # "first" | "last"
    text: str               # the page text (one page per document)


@dataclass(frozen=True)
class Step:
    step: int
    action: str
    args: tuple[tuple[str, str, str], ...]   # one (arg1, arg2, arg3) per row of the step (edit rows are batched)


@dataclass(frozen=True)
class Decision:
    item: str
    draft_initially: bool
    first_accept: str        # ok | refused | na
    final_queue_status: str
    final_voucher_status: str
    voucher_number: str
    blocking_initial: int
    warnings_initial: int
    blocking_final: int
    warnings_final: int


@dataclass(frozen=True)
class NarrationStep:
    step: int
    line_no: int
    status: str
    source: str
    ledger: str
    model_called: int
    decision: str
    rule_count_after: int | None
    detail: str
    model: dict | None


@dataclass
class Pack:
    root: Path
    config: dict
    docs: list[DocRec]
    answers: dict[str, list]
    script: dict[str, list[Step]]
    findings: dict[tuple[str, str], set[tuple[str, str, str]]]
    decisions: dict[str, Decision]
    postings: dict[str, list[tuple[str, Decimal, Decimal]]]
    balances: dict[str, list[tuple[str, Decimal, Decimal]]]          # client "A" / "B" -> (ledger, debit, credit)
    balance_totals: dict[str, tuple[Decimal, Decimal]]
    masking: dict[str, dict[str, int]]
    narration: list[NarrationStep]
    narration_rules: list[tuple[str, str, str, int]]
    tally: dict[tuple[str, str], str]
    tally_files: dict[str, bytes] = field(default_factory=dict)
    bank_csv: bytes = b""
    bank_text_doc: str = "P7-B1"


def read_rows(root: Path, name: str) -> list[dict[str, str]]:
    path = root / name
    if not path.is_file():
        raise PackFormatError(f"{name}: file is missing")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)
                if any((v or "").strip() for v in row.values())]


def _int(text: str, where: str) -> int:
    if not re.fullmatch(r"\d+", text.strip()):
        raise PackFormatError(f"{where}: '{text}' must be a whole number")
    return int(text)


def _yes_no(text: str, where: str) -> bool:
    if text not in ("yes", "no"):
        raise PackFormatError(f"{where}: '{text}' must be yes or no")
    return text == "yes"


def load_pack_p7(root: Path) -> Pack:
    root = Path(root)
    if not (root / MARKER).is_file():
        raise PackFormatError(f"{root.name}: not a Phase 7 pack ({MARKER} is missing)")
    config = yaml.safe_load((root / MARKER).read_text(encoding="utf-8"))

    docs = []
    for r in read_rows(root, "documents.csv"):
        path = root / r["file"]
        if not path.is_file():
            raise PackFormatError(f"documents.csv: {r['file']} is missing")
        if r["arrives"] not in ("first", "last"):
            raise PackFormatError(f"documents.csv: arrives '{r['arrives']}' must be first or last")
        docs.append(DocRec(r["doc_id"], r["file"], r["doc_type"], r["arrives"], path.read_text(encoding="utf-8")))
    answers = json.loads((root / "fixtures" / "llm_answers.json").read_text(encoding="utf-8"))
    for doc in docs:
        if doc.doc_id not in answers or not answers[doc.doc_id]:
            raise PackFormatError(f"fixtures/llm_answers.json: no scripted answer for {doc.doc_id}")

    script: dict[str, list[Step]] = {}
    rows = read_rows(root, "accountant_script.csv")
    for r in rows:
        if r["action"] not in ACTIONS:
            raise PackFormatError(f"accountant_script.csv: unknown action '{r['action']}'")
    for item in dict.fromkeys(r["doc_id"] for r in rows):
        steps: list[Step] = []
        for no in dict.fromkeys(_int(r["step"], "accountant_script.csv step") for r in rows if r["doc_id"] == item):
            part = [r for r in rows if r["doc_id"] == item and int(r["step"]) == no]
            actions = {r["action"] for r in part}
            if len(actions) != 1:
                raise PackFormatError(f"accountant_script.csv: {item} step {no} mixes actions {sorted(actions)}")
            steps.append(Step(no, part[0]["action"], tuple((r["arg1"], r["arg2"], r["arg3"]) for r in part)))
        script[item] = steps

    findings: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for r in read_rows(root, "expected_findings.csv"):
        if r["stage"] not in STAGES or r["severity"] not in SEVERITIES:
            raise PackFormatError(f"expected_findings.csv: bad stage or severity in {r}")
        findings.setdefault((r["doc_id"], r["stage"]), set()).add((r["rule_id"], r["severity"], r["field_path"]))

    decisions: dict[str, Decision] = {}
    for r in read_rows(root, "expected_decisions.csv"):
        decisions[r["item"]] = Decision(
            r["item"], _yes_no(r["draft_initially"], "draft_initially"), r["first_accept"], r["final_queue_status"],
            r["final_voucher_status"], r["voucher_number"], _int(r["blocking_initial"], "blocking_initial"),
            _int(r["warnings_initial"], "warnings_initial"), _int(r["blocking_final"], "blocking_final"),
            _int(r["warnings_final"], "warnings_final"))

    postings: dict[str, list[tuple[str, Decimal, Decimal]]] = {}
    for r in read_rows(root, "expected_postings.csv"):
        postings.setdefault(r["item"], []).append(
            (r["ledger"], parse_amount(r["debit"], "expected_postings.csv "), parse_amount(r["credit"], "expected_postings.csv ")))

    balances: dict[str, list[tuple[str, Decimal, Decimal]]] = {"A": [], "B": []}
    totals: dict[str, tuple[Decimal, Decimal]] = {}
    for r in read_rows(root, "expected_ledger_balances.csv"):
        if r["client"] not in balances:
            raise PackFormatError(f"expected_ledger_balances.csv: client '{r['client']}' must be A or B")
        row = (r["ledger"], parse_amount(r["debit"], "expected_ledger_balances.csv "), parse_amount(r["credit"], "expected_ledger_balances.csv "))
        if r["ledger"] == "TOTAL":
            totals[r["client"]] = (row[1], row[2])
        else:
            balances[r["client"]].append(row)

    masking = {r["doc_id"]: {k: _int(r[k], f"expected_masking.csv {k}") for k in ("calls", "gstin", "pan", "aadhaar", "account")}
               for r in read_rows(root, "expected_masking.csv")}

    narr_answers = {a["step"]: a["model"] for a in json.loads((root / "fixtures" / "narration_answers.json").read_text(encoding="utf-8"))}
    narration = []
    for r in read_rows(root, "expected_narration.csv"):
        no = _int(r["step"], "expected_narration.csv step")
        narration.append(NarrationStep(
            no, _int(r["line_no"], "line_no"), r["status"], r["source"], r["ledger"], _int(r["model_called"], "model_called"),
            r["decision"], int(r["rule_count_after"]) if r["rule_count_after"] else None, r["detail"], narr_answers.get(no)))
    rules = [(r["direction"], r["narration_key"], r["ledger"], _int(r["approved_count"], "approved_count"))
             for r in read_rows(root, "narration_rules.csv")]

    tally = {(r["section"], r["key"]): r["value"] for r in read_rows(root, "expected_tally.csv")}
    tally_files = {p.name: p.read_bytes() for p in sorted((root / "tally").glob("*.xml"))}

    pack = Pack(root, config, docs, answers, script, findings, decisions, postings, balances, totals, masking, narration, rules, tally,
                tally_files, (root / config["bank"]["file"]).read_bytes())
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".txt", ".csv", ".json", ".xml", ".yaml", ".md") and _KEY.search(path.read_text(encoding="utf-8")):
            raise PackFormatError(f"{path.name}: looks like an API key; a pack holds synthetic data only")
    return pack
