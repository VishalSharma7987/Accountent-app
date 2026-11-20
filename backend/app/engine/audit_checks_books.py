"""Books checks A-01..A-06, A-12, A-13, A-14. Pure functions over plain facts (engine/audit_types.py); no DB, web or AI imports. Filled by package B.

Each entry of CHECKS maps a check id to a function (facts, params, rules) -> CheckResult; package A aggregates the three CHECKS dicts."""

CHECKS: dict = {}
