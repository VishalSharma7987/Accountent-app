# Sunrise Traders, April 2026: hand workings (Phase 3, GST)

Dummy client, synthetic GSTINs. Every figure below was worked by hand (paise by paise) and typed into the `expected_*.csv` files; the tool is never used to produce an expected value. Rates come only from the seeded rule tables (valid from 22-09-2025): AC 8415 = 18%, sugar 1701 = 5%, medicine 3004 = 5%, potatoes 0701 = nil-rated, consulting SAC 998311 = 18% (prefix 9983), GTA freight SAC 996511 = default services rate 18%, gym membership SAC 999699 = default services rate 18%. **All of these rate rows are `pending` (example rows / secondary sources); the default services 18% is `pending` too.** Tax per line: intra-state CGST = SGST = taxable x rate / 200 (rounded half up to the paisa); inter-state IGST = taxable x rate / 100. No invoice round-off (client option off).

Registration: Sunrise Traders, GSTIN 27AAPFU0939F1ZV (Maharashtra, code 27), regular, monthly, from 01-04-2026. Voucher numbers are given at posting, in date order per type: SAL/2026-27/0001.., PUR/2026-27/0001.., CRN/2026-27/0001.

## 1. Invoices (expected_invoice_items.csv, expected_invoices.csv)

| Ref | Date | Party / place of supply | Item working | Taxable | Tax | Party amount |
| --- | --- | --- | --- | --- | --- | --- |
| P1 PUR/0001 | 03-04 | Sharma (27, intra), SUP/101 | 5 x 22,000.00 = 110,000.00; 18% -> 110,000 x 18 / 200 = 9,900.00 each | 110,000.00 | CGST 9,900.00 SGST 9,900.00 | 129,800.00 |
| S1 SAL/0001 | 05-04 | Rahul (27, intra) | AC 2 x 30,000 = 60,000.00 -> 5,400.00 each; sugar 100 x 45.50 = 4,550.00 at 5% -> 4,550 x 5 / 200 = 113.75 each | 64,550.00 | CGST 5,513.75 SGST 5,513.75 | 75,577.50 |
| S2 SAL/0002 | 08-04 | Patel (24, inter) | AC 1 x 30,000 less discount 1,000 = 29,000.00; IGST 29,000 x 18 / 100 = 5,220.00 | 29,000.00 | IGST 5,220.00 | 34,220.00 |
| P2 PUR/0002 | 10-04 | Verma (07, inter), VT/55 | sugar 1,000 x 40.00 = 40,000.00; IGST 5% = 2,000.00 | 40,000.00 | IGST 2,000.00 | 42,000.00 |
| S3 SAL/0003 | 12-04 | Walk-in (unregistered, 27) | sugar 20 x 45.50 = 910.00 -> 910 x 5 / 200 = 22.75 each; medicine 10 x 120 = 1,200.00 -> 30.00 each | 2,110.00 | CGST 52.75 SGST 52.75 | 2,215.50 |
| P3 PUR/0003 | 14-04 | Karnataka Comp. (29, inter), KC/9 | 2 x 18,000 = 36,000.00; IGST 18% = 6,480.00 | 36,000.00 | IGST 6,480.00 | 42,480.00 |
| S4 SAL/0004 | 15-04 | Walk-in outstation (unregistered, POS 29, inter) | AC 10 x 30,000 = 300,000.00; IGST = 54,000.00 | 300,000.00 | IGST 54,000.00 | 354,000.00 |
| P4 PUR/0004 | 16-04 | Madras Metals (33, inter), MM-204 | 20,000.00; IGST 18% = 3,600.00 | 20,000.00 | IGST 3,600.00 | 23,600.00 |
| S5 SAL/0005 | 18-04 | Rahul, bill of supply | potatoes 500 x 20.00 = 10,000.00 nil-rated | 10,000.00 | none | 10,000.00 |
| P5 PUR/0005 | 20-04 | Sharma SUP/102, gym membership, blocked 17(5) | 10,000.00; 900.00 + 900.00; the tax goes into the cost (Dr Staff Welfare 11,800.00); no Input tax | 10,000.00 | 900.00 + 900.00 (in cost) | 11,800.00 |
| S6 SAL/0006 | 20-04 | Rahul, consulting | 25,000.00; 18% -> 2,250.00 each | 25,000.00 | CGST 2,250.00 SGST 2,250.00 | 29,500.00 |
| P6 PUR/0006 | 22-04 | Fast Roadways (unregistered), GTA, reverse charge | 10,000.00; 18% -> 900.00 each, paid by us: Dr Input CGST 900 / Dr Input SGST 900 / Cr RCM payable 900 + 900; supplier is credited 10,000.00 only | 10,000.00 | 900.00 + 900.00 (RCM) | 10,000.00 |
| P7 PUR/0007 | 24-04 | Sharma SUP/103 | sugar 200 x 40.00 = 8,000.00; 5% -> 200.00 each | 8,000.00 | CGST 200.00 SGST 200.00 | 8,400.00 |
| CN1 CRN/0001 | 25-04 | Rahul, return of 1 AC against SAL/2026-27/0001 | 30,000.00; 2,700.00 each | 30,000.00 | CGST 2,700.00 SGST 2,700.00 | 35,400.00 |

Payments (not GST documents): 05-05 Sharma 85,100.00 = 64,900.00 on SUP/101 (part) + 11,800.00 SUP/102 + 8,400.00 SUP/103; 06-05 Karnataka 42,480.00; 07-05 Madras 23,600.00; 08-05 Fast Roadways 10,000.00. Left open: SUP/101 balance 64,900.00 and VT/55 42,000.00.

Ledger balances after posting (expected_ledger_balances.csv): Sales Cr = 64,550 + 29,000 + 2,110 + 300,000 + 10,000 = 405,660.00; Service Income 25,000.00; Sales Returns Dr 30,000.00 (net sales 400,660.00); Purchases Dr = 110,000 + 40,000 + 36,000 + 20,000 + 8,000 = 214,000.00; Input CGST Dr = 9,900 + 900 + 200 = 11,000.00 (same SGST); Input IGST Dr = 2,000 + 6,480 + 3,600 = 12,080.00; Output CGST Cr = 5,513.75 + 52.75 + 2,250.00 - 2,700.00 = 5,116.50 (same SGST); Output IGST Cr = 5,220 + 54,000 = 59,220.00.

## 2. GSTR-2B (gstr2b_042026.json, gstr2b_052026.json) and reconciliation

Books side = posted purchases with a supplier GSTIN dated in April. P1 and P5 agree to the paisa: **matched**. P2: 2B shows taxable 40,500.00 / IGST 2,025.00 against books 40,000.00 / 2,000.00: **value mismatch**, differences +500.00 and +25.00. P4: 2B lists the bill under 33AAAAA0000A2Z8 (books 33AAAAA0000A1Z9), everything else equal: **GSTIN mismatch**. P3: not in April 2B but in the May 2B (period 052026): **period mismatch**. P7: nowhere: **only in books**. MF/77 (Mumbai Fasteners, 5,000.00 + 450 + 450): **only in 2B**. P6 has no supplier GSTIN, so it is outside the reconciliation.

Totals (period-mismatch document is left out of the 2B side): Books taxable 110,000 + 10,000 + 40,000 + 20,000 + 36,000 + 8,000 = 224,000.00; IGST 2,000 + 3,600 + 6,480 = 12,080.00; CGST 9,900 + 900 + 200 = 11,000.00 (SGST same). 2B taxable 110,000 + 10,000 + 40,500 + 20,000 + 5,000 = 185,500.00; IGST 2,025 + 3,600 = 5,625.00; CGST 9,900 + 900 + 450 = 11,250.00. Difference (2B - books): taxable -38,500.00, IGST -6,455.00, CGST +250.00, SGST +250.00.

Apply to ITC: matched -> supplier tax in 2B (P1 becomes eligible, P5 stays blocked); only in books -> pending "not in 2B" (P7). Value / GSTIN / period mismatches change nothing: the accountant decides first.

## 3. ITC register (expected_itc.csv)

Evidence held and goods received is recorded for P1, P2, P3, P4, P6, P7 (not P5, it is blocked). P1 eligible (evidence + in 2B), claimed 04-2026; P6 eligible under reverse charge (no 2B test), claimed 04-2026; P2, P3, P4, P7 pending, reason "not in 2B"; P5 blocked (club / fitness membership, Section 17(5)). Claim deadline for an invoice of FY 2026-27: 30-11-2027.

## 4. GSTR-1 (expected_gstr1.csv, expected_gstr1_documents.csv)

- B2B Rahul: SAL/0001 value 75,577.50: 5% taxable 4,550.00 CGST 113.75 SGST 113.75; 18% taxable 60,000.00 CGST 5,400.00 SGST 5,400.00. SAL/0006 value 29,500.00: 18% 25,000.00, 2,250.00 each. B2B Patel: SAL/0002 value 34,220.00: 18% 29,000.00, IGST 5,220.00.
- B2C large (inter-state, unregistered, over 2,50,000): SAL/0004, POS 29, value 354,000.00: 300,000.00, IGST 54,000.00. (The 2,50,000 limit is `pending`.)
- B2C small: S3 only, POS 27, 5%: taxable 2,110.00, CGST 52.75, SGST 52.75.
- Credit note to registered: CRN/0001 value 35,400.00 against SAL/2026-27/0001: 30,000.00, 2,700.00 each.
- Nil-rated (table 8), intra-state to registered: 10,000.00.
- HSN summary: 0701: 500.000 kg, value 10,000.00. 1701 @5%: 120.000 kg (100 + 20), taxable 5,460.00, CGST 136.50 + SGST 136.50, value 5,460 + 273 = 5,733.00. 3004 @5%: 10, 1,200.00, 30.00 + 30.00, value 1,260.00. 8415 @18%: 2 + 1 + 10 - 1 = 12 nos, taxable 60,000 + 29,000 + 300,000 - 30,000 = 359,000.00, IGST 59,220.00, CGST 5,400 - 2,700 = 2,700.00, SGST 2,700.00, value 359,000 + 59,220 + 2,700 + 2,700 = 423,620.00. 998311 @18%: 1, 25,000.00, 2,250 + 2,250, value 29,500.00.
- Documents issued: invoices SAL/2026-27/0001 to 0006 (6, none cancelled); credit note CRN/2026-27/0001 (1).
- Totals (credit note deducted): taxable 64,550 + 29,000 + 2,110 + 300,000 + 10,000 + 25,000 - 30,000 = 400,660.00; IGST 59,220.00; CGST 7,816.50 - 2,700 = 5,116.50 (7,816.50 = 5,513.75 + 52.75 + 2,250.00); SGST 5,116.50.

## 5. GSTR-3B (expected_gstr3b.csv)

3.1(a) taxable 420,660.00 - 30,000.00 = 390,660.00, IGST 59,220.00, CGST 5,116.50, SGST 5,116.50. 3.1(c) nil 10,000.00. 3.1(d) reverse charge: 10,000.00, CGST 900.00, SGST 900.00. 3.1(b), (e) nil. 3.2 inter-state to unregistered, POS 29: 300,000.00, IGST 54,000.00. 4(A): inward reverse charge CGST 900.00 + SGST 900.00; all other ITC (P1) CGST 9,900.00 + SGST 9,900.00; total CGST 10,800.00, SGST 10,800.00. 4(B) nil. 4(C) net = 4(A): 10,800.00 each. 4(D) ineligible/not claimed (information): blocked P5 900 + 900; pending P7 200 + 200; pending P2 + P3 + P4 IGST 2,000 + 6,480 + 3,600 = 12,080.00: CGST 1,100.00, SGST 1,100.00, IGST 12,080.00. 6.1 tax payable: IGST 59,220.00, CGST 5,116.50, SGST 5,116.50; reverse-charge tax payable in cash CGST 900.00 + SGST 900.00; ITC available as 4(C). The utilisation order (Section 49) is not worked: the CA confirms it.

## 6. Tie-out (expected_tieout.csv)

Books output (ledger credits less debits in the month) equals GSTR-1 equals GSTR-3B for every head: taxable 400,660.00 (net sales 405,660 + 25,000 - 30,000), IGST 59,220.00, CGST 5,116.50, SGST 5,116.50. ITC: Input ledgers CGST 11,000.00 / SGST 11,000.00 / IGST 12,080.00; register eligible CGST 10,800 (P1 9,900 + P6 900), pending CGST 200, so 10,800 + 200 = 11,000; IGST pending 12,080. No difference; ties.

## 7. 180-day check on 01-10-2026 (expected_exposure.csv, expected_reversals.csv, expected_register_tie.csv)

P1 (invoice 03-04-2026): days to 01-10 = 27 (rest of April) + 31 + 30 + 31 + 31 + 30 + 1 = 181, the 180th day was 30-09-2026. Bill 129,800.00, paid 64,900.00, outstanding 64,900.00, fraction 64,900 / 129,800 = 0.5000. Unpaid tax: CGST 9,900 x 0.5 = 4,950.00, SGST 4,950.00. P2 (invoice 10-04, 174 days, unpaid 42,000.00, fraction 1.0000, IGST 2,000.00) is not yet due (day 180 = 07-10-2026) but within 30 days: "approaching". All other bills are paid in full. Draft reversal journal for P1: Dr ITC Reversal 9,900.00 / Cr Input CGST 4,950.00 / Cr Input SGST 4,950.00 (a second request for the same amount is refused). RCM and blocked entries are outside the 180-day check. Register tie: Input ledgers equal the register including reverse-charge credit: CGST 9,900 + 200 + 900 = 11,000.00, IGST 12,080.00.

## 8. Composition client (Sai Bakers, composition_client.yaml, expected_composition.csv)

Trader, composition. Bills of supply: 10-04-2026 1,000 kg x 45.00 = 45,000.00; 15-05-2026 2,000 kg x 50.00 = 100,000.00. Quarter April-June turnover 145,000.00. Tax at 1% (rate PENDING) = 1,450.00: CGST 725.00 + SGST 725.00. Year-to-date 145,000.00, limit 1.5 crore (15,000,000.00, PENDING) not crossed. No invoice carries tax.

## 9. Deliberately wrong items (wrong_cases.csv)

W01 14-character GSTIN: G-01. W02 wrong check character: G-02. W03 party state 27 with GSTIN of 24: G-04. W04 tax and lines typed in invoice mode (IGST typed on an intra-state sale): G-14. W05 HSN 7777 without a rate rule: G-10. W06 claiming the blocked P5 credit: refused (`itc_invalid_transition`). W07 composition dealer raising a tax invoice: G-18. W08 second reversal draft for the same unpaid share: `reversal_exists`. The mismatches in the 2B (value, GSTIN, missing, extra, other period) and the 181-day case are checked in sections 2 and 7.

## What is NOT verified

HSN rates (example rows), default services 18%, the GTA reverse-charge category, the Section 17(5) club / fitness clause, the 180-day rule (and what counts as payment), the B2C-large limit, the composition rate and limit, and the GSTR-1 / GSTR-3B table numbers are `pending` in the rule tables (docs/PHASE3_LEGAL_VALUES.md). The GSTR-2B file shape is NOT verified against a real portal file.
