"""Step 7.0 foundation checks that need no database: migration 0018 text, the rule catalogue, the queue state path, the hooks
and the registered routers."""

import re
from decimal import Decimal
from pathlib import Path

from app import config
from app.engine import doc_types as t
from app.main import ROUTERS

ROOT = Path(__file__).resolve().parents[2].parent
MIGRATION = ROOT / "database" / "migrations" / "0018_documents_ai.sql"
PLAN = ROOT / "docs" / "PHASE7_PLAN.md"
NEW_TABLES = [
    "client_ai_settings", "documents", "document_texts", "document_vouchers", "llm_calls", "extractions", "party_mappings",
    "line_mappings", "narration_rules", "narration_suggestions", "tally_imports", "tally_master_map", "tally_exports",
    "approval_queue_items",
]


def test_every_phase7_table_enables_row_level_security_and_has_no_policy():
    text = MIGRATION.read_text(encoding="utf-8")
    created = re.findall(r"CREATE TABLE (\w+) \(", text)
    assert sorted(created) == sorted(NEW_TABLES)
    for table in created:
        assert re.search(rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;", text), table
    assert "CREATE POLICY" not in text.upper()


def test_the_migration_closes_function_privileges_and_is_schema_agnostic():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA" in text
    assert not re.search(r"\b(public|ledgermind_test)\s*\.", text, re.IGNORECASE)


def test_the_migration_has_no_money_column_so_amounts_cannot_bypass_the_voucher_service():
    text = MIGRATION.read_text(encoding="utf-8")
    assert not re.search(r"^\s+\w+\s+(numeric\(18|float|double|real[ ,])", text, re.MULTILINE | re.IGNORECASE)


def test_D52_the_audit_table_has_the_secret_tripwire_and_the_masking_evidence_check():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "llm_calls_no_secret" in text and "sk-or-" in text
    assert "llm_calls_masked_before_sending" in text


def test_D_rule_catalogue_is_complete_unique_and_described_in_the_plan():
    assert all(re.fullmatch(r"D-\d{2}", rule_id) and text.strip() for rule_id, text in t.RULES.items())
    assert len(t.RULES) == 52
    plan = PLAN.read_text(encoding="utf-8")
    missing = [r for r in t.RULES if r not in plan]
    assert missing == []


def test_D60_queue_path_matches_the_database_guard():
    assert t.can_move(t.QueueStatus.PENDING, t.QueueStatus.IN_REVIEW)
    assert t.can_move(t.QueueStatus.IN_REVIEW, t.QueueStatus.PENDING)
    assert t.can_move(t.QueueStatus.PENDING, t.QueueStatus.ACCEPTED)
    assert not t.can_move(t.QueueStatus.ACCEPTED, t.QueueStatus.PENDING)
    assert not t.can_move(t.QueueStatus.REJECTED, t.QueueStatus.ACCEPTED)
    assert t.QUEUE_TRANSITIONS[t.QueueStatus.ACCEPTED] == () and t.QUEUE_TRANSITIONS[t.QueueStatus.REJECTED] == ()


def test_D60_only_error_and_review_findings_block_acceptance():
    findings = [
        t.DocFinding("D-10", t.Severity.ERROR, "x"), t.DocFinding("D-20", t.Severity.REVIEW, "y"),
        t.DocFinding("D-05", t.Severity.WARNING, "z"), t.DocFinding("D-25", t.Severity.INFO, "i"),
    ]
    assert t.count_findings(findings) == (2, 1)
    assert findings[0].as_dict() == {"rule_id": "D-10", "severity": "error", "message": "x", "field_path": None,
                                     "printed": None, "computed": None}


def test_D06_external_values_are_text_and_the_tolerance_is_a_decimal():
    f = t.Field("1,00,000.50")
    assert isinstance(f.value, str) and f.confidence is None and f.source is None
    assert t.ROUND_TOLERANCE == Decimal("1.00")
    assert t.DRAFTABLE_VOUCHER_TYPE[t.DocType.PURCHASE_INVOICE] == "purchase"
    assert t.DocType.BANK_STATEMENT not in t.DRAFTABLE_VOUCHER_TYPE


def test_the_phase7_routers_are_registered_and_the_hooks_import():
    from app.api import (
        ai_settings,
        approval_queue,
        doc_mappings,
        documents,
        extractions,
        narration,
        tally,
    )
    from app.services import ai_hooks

    for module in (documents, tally, ai_settings, extractions, doc_mappings, approval_queue, narration):
        assert module.router in ROUTERS
    assert callable(ai_hooks.add_queue_item) and callable(ai_hooks.guard_voucher_change)


def test_D51_D52_nothing_ai_related_is_configured_by_default(monkeypatch):
    for name in ("DOCUMENT_STORE_DIR", "OPENROUTER_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert config.document_store_dir() is None
    assert config.openrouter_api_key() is None
    assert config.llm_model() is None
    assert config.ai_min_confidence() == "0.85"
    monkeypatch.setenv("LLM_MODEL", "  some/model  ")
    assert config.llm_model() == "some/model"


def test_the_fake_llm_client_scripts_answers_records_requests_and_never_touches_the_network():
    import pytest

    from app.ai.fake import FakeLlmClient
    from app.ai.llm import LlmError, LlmRequest

    request = LlmRequest(purpose="invoice_extraction", system="s", user="Invoice <GSTIN_1>", model="m/x")
    fake = FakeLlmClient(['{"a": 1}', LlmError("timeout")])
    assert fake.complete(request).text == '{"a": 1}'
    with pytest.raises(LlmError):
        fake.complete(request)
    with pytest.raises(AssertionError):
        fake.complete(request)
    assert [r.user for r in fake.requests] == ["Invoice <GSTIN_1>"] * 3
    assert FakeLlmClient(lambda r: r.user.upper()).complete(request).text == "INVOICE <GSTIN_1>"
