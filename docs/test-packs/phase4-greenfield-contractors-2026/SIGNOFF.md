# Sign-off: Greenfield Contractors, Phase 4 TDS / TCS pack (2025-26 and 2026-27)

Fill this in after you have checked the pack by hand (WORKING.md and VERIFICATION_SHEET.xlsx). An unsigned pack is not a pass criterion.

| Item | Value |
| --- | --- |
| Pack folder | phase4-greenfield-contractors-2026 |
| Verified by (name, role) | |
| Date verified | YYYY-MM-DD |
| Method | e.g. T-accounts on paper / Tally / Excel working |

## Checklist

- [ ] Act follows the earlier of payment and credit date (credit 28-03-2026, paid 03-04-2026 stays under the 1961 Act); same nature shows 194C in March and 393(1) in April
- [ ] Alpha: catch-up when the annual 1,00,000.00 is crossed, with the tax already deducted set off (1,200.00 on V12)
- [ ] Ravi, Mehta: whole-amount tax from the crossing payment; rounding half up (200.50 -> 201)
- [ ] Silver Estates: monthly rent threshold (45,000.00 free, June 25,000.00 makes the month 55,000.00 taxable)
- [ ] Delta: higher no-PAN rate 20%; Omega: partial use of the lower-deduction certificate (2,500.00); Kiran: nil certificate; Steel Mart: 194Q on the excess only
- [ ] TCS: scrap 1% (1961) and 2% (2025), motor vehicle above 10,00,000.00
- [ ] Challans, deposit due dates (7th; March deductions 30 April), interest months and amounts
- [ ] Quarterly statement rows, totals, forms by quarter-end date; certificate data and the refusal for undeposited tax
- [ ] 26AS reconciliation classes and the manual link; the statement file is hand-made, not a TRACES file
- [ ] Every wrong case really is wrong, with the right rule

## Legal values still PENDING or only secondary_verified (the CA must confirm before this pack is a legal pass)

Nothing in the rule tables is `verified`: the official Act text and CBDT notifications were not read (owner-supplied values are stored `secondary_verified`).

| Value used in the pack | Status in the rule table |
| --- | --- |
| Every 1961-Act row used (194C, 194H, 194J(b), 206C(1) TCS scrap) and the section numbers | pending |
| TCS rates: scrap 1% (1961) / 2% (2025); motor vehicle 1% above 10,00,000.00; table serial of section 394 | pending |
| Interest on late deduction 1% and late deposit 1.5% per month, month or part of a month (201(1A); 2025-Act section not found) | pending |
| Rounding of tax to the whole rupee, half up (288B) | pending |
| Deposit due date 30 April for March deductions (both Acts) | pending |
| Certificate due dates (15 days after the statement due date) and the 2025-Act section for a lower-deduction certificate (Form 128) | pending |
| Payment codes of the statement (the T-50 warning in every working) | pending |
| 194Q buyer-turnover limit (the client flag is entered by the accountant) and 194Q limit 50,00,000.00 for 1961 rows | pending / secondary_verified (2025) |
| Rent: monthly threshold 50,000.00, 10% / 2% (owner-supplied for the 2025 Act; 1961 rows still pending). The reading "whole month once above" is the engine's rule, to be confirmed | secondary_verified (2025) / pending (1961) |
| Contractor 1% / 2%, thresholds 30,000.00 / 1,00,000.00; commission 2% / 20,000.00; professional fees 10% / 50,000.00 (2025 Act) | secondary_verified |
| Higher rate when PAN is missing (397(2), 20%; 5% for 194Q) | secondary_verified |
| Deposit due 7th of next month (Rule 218); statements 31 Jul / 31 Oct / 31 Jan / 31 May (Rule 219); forms 138, 140, 143, 130, 131 | secondary_verified |
| Treatment of the threshold-crossing catch-up and of GST in the TDS base (CBDT circulars) | not checked |
| The 26AS / AIS file layout (the pack file is hand-made) | not verified |

## Notes / disagreements with the tool

(write anything unusual here)

## Result

- [ ] Approved
- [ ] Approved with changes (list them above)
- [ ] Rejected

Signature: ______________________   Date: ____________

## Phase 4.1 items for the CA (2026-11-13)
- ex-194-IB (rent by an individual / HUF not liable to tax audit): 2% and Rs 50,000 a month are owner-supplied (`secondary_verified`); the reading "the WHOLE month's rent once the month is above Rs 50,000" (case R4 of `p41`) is **pending**.
- Tax on a GST invoice is on the value without GST: owner-supplied position (`secondary_verified`); the CBDT circular number is not recorded and must be confirmed.
- A certificate chosen on a payment below the threshold is not applied to it, also not at the later catch-up: confirm.
- Interest 1% / 1.5% per month or part of a month and rounding to the rupee: owner-supplied (`secondary_verified`).
