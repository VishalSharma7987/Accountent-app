# Sign-off — ABC Traders, Phase 2 (April to June 2026)

Fill this in after you have checked the pack by hand. An unsigned pack is not a pass criterion.

| Item | Value |
| --- | --- |
| Pack folder | abc-traders-phase2-jun-2026 |
| Verified by (name, role) | |
| Date verified | YYYY-MM-DD |
| Method (how expected_* files were worked out) | e.g. T-accounts on paper / Tally / Excel working |

## Checklist

- [ ] Opening balances in ledgers.csv: total Dr = total Cr
- [ ] Opening bills of every party add up to that party's opening balance (opening_bills.csv)
- [ ] Every voucher in vouchers.csv is correct and balanced (Dr = Cr); every party line is fully allocated (allocations.csv)
- [ ] expected_trial_balance.csv worked out by hand; TOTAL Dr = TOTAL Cr
- [ ] Outstanding (receivable and payable) worked out by hand; party totals agree with the Trial Balance
- [ ] Ageing buckets worked out by hand; bucket totals = outstanding totals
- [ ] Cash Book: every day's closing worked out by hand, never negative
- [ ] Bank statement: running balance re-added; statement opening differs from books opening by the opening item only
- [ ] BRS as on 30-06-2026 ties to the rupee (expected_brs.csv)
- [ ] MSME legal due dates checked; the legal values (days, section) are confirmed from the official text (status is SECONDARY_VERIFIED until your CA signs)
- [ ] Every wrong voucher / wrong party really is wrong, and expected_rule_id is the right rule
- [ ] Data is dummy / anonymised (no real names, PAN, GSTIN, Udyam, Aadhaar, bank numbers)

## Notes / disagreements with the tool

(write anything unusual here)

## Result

- [ ] Approved
- [ ] Approved with changes (list them above)
- [ ] Rejected

Signature: ______________________   Date: ____________
