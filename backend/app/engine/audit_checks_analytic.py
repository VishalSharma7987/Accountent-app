"""Analytical and related-party checks A-15, A-18. Pure functions over plain facts (engine/audit_types.py); no DB, web or AI imports. Filled by package D.

Each entry of CHECKS maps a check id to a function (facts, params, rules) -> CheckResult; package A aggregates the three CHECKS dicts."""

CHECKS: dict = {}
