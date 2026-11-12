### Steps 2.1-2.3 (agent A): party master, bill-wise allocation + opening bills, outstanding + ageing
- Done: engine/parties.py (P-01..P-07), engine/bills.py (B-01..B-05, due dates, open bills, mirrored allocations, opening-bills check, ageing), services/parties.py (P-08), services/bills.py, db/repositories_bills.py, voucher hooks (draft/approve/post/reverse, B-07), API parties + bills, allocations on voucher lines.
- Tests: unit 22 (parties) + 57 (bills, ageing); integration 9 in tests/integration/test_bill_wise.py (services, voucher flow, reversal, DB trigger, API).
- Commit: see git log of branch p2-A.
- Decisions added: see docs/decisions_parts/A.md (9 rows). Contract edits: docs/PHASE2_API_CONTRACT.md (Parties, Bill-wise).
