# Greenfield Contractors, 2025-26 and 2026-27: hand workings (Phase 4, TDS / TCS)

Dummy client (partnership, TAN MUMG12345A), synthetic PAN numbers. Every figure was worked by hand and typed into the `expected_*.csv` files; the tool is never used to produce an expected value. Rates, thresholds, sections and due dates come ONLY from the seeded rule tables (seeds 0008, 0009, 0010). Status of each rule row is shown as `P` = pending, `S` = secondary_verified (nothing is `verified`: the official text was not read, see `docs/PHASE4_LEGAL_VALUES.md`).

**How the Act is chosen.** Event date = the earlier of payment date and credit date. Event date on or before 31-03-2026 -> Income-tax Act 1961 (section 194x / 206C); on or after 01-04-2026 -> Income-tax Act 2025 (section 393 table / 394). The position (cumulative payments, tax already deducted) is kept per deductee + nature + financial year of the event date.

**Rounding.** Tax is rounded to the nearest whole rupee, halves up (provision 288B, `P`). Where a threshold is crossed the tax is worked on the whole base, then the tax already deducted on that base is set off.

Rates used (all "any / company / firm" rows unless stated): contractor 1% individual / HUF, 2% others, no-PAN 20%, single payment 30,000.00 or annual 1,00,000.00 (whole amount once crossed); commission 2%, annual 20,000.00; professional fees 10%, annual 50,000.00; rent land / building 10%, monthly 50,000.00 (2025 Act `S` per the owner, 1961 `P`); purchase of goods (194Q) 0.1% on the excess over 50,00,000.00, buyer flag needed; TCS scrap 1% (1961) / 2% (2025), TCS motor vehicle 1% above 10,00,000.00 (both `P`). Status: 1961 rows `P`, 2025 non-TCS rows `S`, TCS rows `P`.

## 1. Financial year 2025-26 (Income-tax Act 1961)

| Ref | Event date | Deductee / nature | Working | Tax |
| --- | --- | --- | --- | --- |
| V01 PUR/2025-26/0001 | 01-03-2026 | Mehta and Co, professional fees (194J(b)) 10% | 60,000.00 is more than the annual 50,000.00: crossed, base 60,000.00 x 10% | 6,000.00 |
| V05 SAL/2025-26/0001 | 15-03-2026 | Metro Scrap Traders, TCS scrap (206C(1)) 1% | no threshold: 100,000.00 x 1%; the buyer pays 101,000.00 | 1,000.00 |
| V02 PUR/2025-26/0002 | 20-03-2026 | Alpha (company), contractor 194C 2% | 50,000.00 is more than the single 30,000.00: base 50,000.00 x 2% (annual 1,00,000.00 not crossed) | 1,000.00 |
| V03 PAY/2026-27/0001 | **credit 28-03-2026, payment 03-04-2026**, voucher dated 03-04-2026 | Beta Agencies, commission 194H 2% | earlier date 28-03-2026 -> **1961 Act**, financial year 2025-26; 50,000.00 is more than the annual 20,000.00: base 50,000.00 x 2% | 1,000.00 |

Same nature, other Act: Alpha contractor on 20-03-2026 is section 194C (1961, `P`); on 05-04-2026 (V10 below) it is section 393(1) (2025 Act, `S`), same 2%.

## 2. Financial year 2026-27 (Income-tax Act 2025), by deductee

**Alpha Constructions (company, valid PAN, contractor 2%): catch-up with set-off.**
| Ref | Date | Payment | Cumulative | Working | Tax |
| --- | --- | --- | --- | --- | --- |
| V10 | 05-04 | 50,000.00 | 0 -> 50,000.00 | single threshold passed: 50,000.00 x 2% | 1,000.00 |
| V11 | 20-05 | 20,000.00 | 50,000 -> 70,000.00 | not above 30,000.00 and cumulative below 1,00,000.00: below threshold | 0.00 |
| V12 | 18-06 | 40,000.00 | 70,000 -> 110,000.00 | annual 1,00,000.00 crossed: base = whole cumulative 110,000.00 x 2% = 2,200.00, less tax already deducted 1,000.00 | 1,200.00 |
| V13 | 25-07 | 10,000.00 | 110,000 -> 120,000.00 | already above: base 10,000.00 x 2% | 200.00 |
Check: 120,000.00 x 2% = 2,400.00 = 1,000 + 0 + 1,200 + 200.

**Ravi Kumar (individual, contractor 1%): whole-amount crossing, rounding.**
V20 05-05 25,000.00 and V21 15-06 28,000.00: below (cumulative 53,000.00). V22 12-08 60,000.00: cumulative 113,000.00 crosses 1,00,000.00 -> base 113,000.00 x 1% = 1,130.00 (nothing deducted earlier). V23 10-09 20,050.00: base 20,050.00 x 1% = 200.50 -> **201.00** (half up).

**Mehta and Co (firm, professional fees 10%).** V30 30-04 40,000.00 below 50,000.00 -> 0. V31 25-08 30,000.00: cumulative 70,000.00 crosses -> base 70,000.00 x 10% = 7,000.00 (none deducted earlier in this year).

**Beta Agencies (commission 2%).** V40 10-04 25,000.00 above 20,000.00: 25,000.00 x 2% = 500.00. (The V03 payment belongs to 2025-26.)

**Silver Estates (landlord, rent land / building 10%, monthly 50,000.00, whole amount for the month once above).** V50 05-04 60,000.00: month total 60,000.00 > 50,000.00 -> 6,000.00. V51 05-05 45,000.00: month total 45,000.00 not above -> 0. V52 05-06 30,000.00: 30,000.00 -> 0. V53 20-06 25,000.00: June total 55,000.00 > 50,000.00 -> base 55,000.00 (the whole month, including V52) x 10% = 5,500.00 (nothing set off: V52 had no tax). Rent is a `Payment` voucher: party Dr gross, bank Cr gross less tax, TDS Payable Cr tax.

**Delta Fabricators (company, PAN missing): higher rate.** V60 05-06 80,000.00 above 30,000.00; no PAN -> the no-PAN rate 20% (not the lower of 2% and 20%): 80,000.00 x 20% = 16,000.00 (with a valid PAN: 1,600.00).

**Omega Engineers (company): lower-deduction certificate LDC/2026/0007, 0.5%, limit 3,00,000.00, valid 01-04-2026 to 31-03-2027.**
V70 10-07 200,000.00: cumulative crosses 1,00,000.00, base 200,000.00; certificate covers all: 200,000.00 x 0.5% = 1,000.00. V71 15-09 200,000.00: certificate left 3,00,000.00 - 2,00,000.00 = 1,00,000.00: 100,000.00 x 0.5% = 500.00 + 100,000.00 x 2% = 2,000.00 = **2,500.00** (effective 1.25%; the tool shows the certificate rate 0.5%, so the pack does not state a rate for V71). V72 10-10 50,000.00: certificate used up -> normal 2% = 1,000.00.

**Kiran Consultants (firm): nil certificate NIL/2026/0001 (rate 0), limit 5,00,000.00.** V80 05-08 100,000.00: base 100,000.00 x 0% = 0.00, reason `nil_certificate`, no tax line.

**Steel Mart (company, 194Q, buyer flag for 2026-27 = Yes; the buyer-turnover limit itself is `P`).** V90 12-07 40,00,000.00: below 50,00,000.00 -> 0. V91 12-09 20,00,000.00: cumulative 60,00,000.00; excess over 50,00,000.00 = 10,00,000.00 x 0.1% = 1,000.00 (only the excess is taxed).

**TCS 2026-27 (Metro Scrap Traders, valid PAN; `P`).** V95 10-04 scrap 200,000.00 x 2% = 4,000.00 (the 1961 rate was 1%). V96 20-08 motor vehicle 12,00,000.00: excess over 10,00,000.00 = 2,00,000.00 x 1% = 2,000.00.

Totals 2026-27: TDS 1,000 + 1,200 + 200 + 1,130 + 201 + 7,000 + 500 + 6,000 + 5,500 + 16,000 + 1,000 + 2,500 + 1,000 + 1,000 = 44,231.00; TCS 4,000 + 2,000 = 6,000.00; together 50,231.00. 2025-26: TDS 8,000.00, TCS 1,000.00.

## 3. Ledger balances (expected_ledger_balances.csv; each year on its own, no brought-forward)
As on 31-03-2026: TDS Payable Cr 7,000.00 (V01 + V02; V03 is booked on 03-04-2026), TCS Payable Cr 1,000.00, Alpha Cr 49,000.00 (50,000 less tax), Mehta Cr 54,000.00, Metro Dr 101,000.00. As on 30-11-2026: TDS Payable Cr 44,231.00 + 1,000.00 (V03) = 45,231.00; TCS Payable 6,000.00; HDFC Bank Cr = 49,000 + 54,000 + 45,000 + 30,000 + 19,500 = 197,500.00; Alpha Cr 120,000 - 2,400 = 117,600.00; Silver Dr 160,000.00; Beta Dr 50,000 - (25,000 - 500) = 25,500.00; Metro Dr 1,406,000.00; Omega Cr 445,500.00; Ravi Cr 133,050 - 1,331 = 131,719.00; Steel Mart Cr 5,999,000.00.

## 4. Challans, due dates and interest (as on 31-10-2026)
Deposit due: 7th of the next month; **March deductions: 30 April** (`P`). Interest: late deduction 1% per month, late deposit 1.5% per month, month or part of a month (`P`); late deposit runs from the date of deduction to the deposit date. Part of a month counts as a full month (10-04 to 10-05 = 1; to 11-05 = 2).

| Challan | Deposit | Pays | Working |
| --- | --- | --- | --- |
| CH0 (2025-26 Q4) | 30-04-2026 | V01 6,000 + V02 1,000 + V03 1,000 = 8,000.00 | on the due date 30-04-2026: no interest |
| CH0T (TCS) | 07-04-2026 | V05 1,000.00 | before 30-04-2026 |
| CH1 | 07-05-2026 | V10 1,000 + V40 500 + V50 6,000 = 7,500.00 | due 07-05-2026: on time |
| CH3 (TCS) | 07-05-2026 | V95 4,000.00 | on time |
| CH2 | 12-08-2026 | V12 1,200 + V53 5,500 + V60 16,000 = 22,700.00 | due 07-07-2026: late. V12 from 18-06: 2 months x 1.5% x 1,200 = 36.00; V53 from 20-06: 2 months x 1.5% x 5,500 = 165.00; V60 from 05-06: 3 months x 1.5% x 16,000 = 720.00. Interest 921.00 paid on the challan; total 23,621.00 |

**Late deduction (V03):** tax was deductible on 28-03-2026 (earlier date) but deducted on 03-04-2026: 1 month x 1% x 1,000.00 = 10.00.

Not deposited at 31-10-2026 (interest to date, whole rupees half up): V70 1,000.00 from 10-07: 4 months x 1.5% = 60.00; V13 200.00 from 25-07: 4 months = 12.00; V22 1,130.00 from 12-08: 3 months = 50.85 -> 51.00; V96 2,000.00 from 20-08: 3 months = 90.00; V31 7,000.00 from 25-08: 3 months = 315.00; V23 201.00 from 10-09: 2 months = 6.03 -> 6.00; V91 1,000.00 from 12-09: 2 months = 30.00; V71 2,500.00 from 15-09: 2 months = 75.00; V72 1,000.00 (due 07-11-2026, not yet late): 0.00.

## 5. Quarterly statements (expected_return_rows.csv, expected_return_totals.csv)
Form by the quarter-END date: quarter ending 31-03-2026 -> Form 26Q (non-salary) / 27EQ (TCS), 1961 rows `P`; quarter ending 30-06-2026 -> Form 140 / 143 (2025 Act, `S`). Q1 2026-27 non-salary: 12 rows (items of Apr-Jun, including the zero-tax ones), paid 468,000.00, tax deducted 30,200.00 (= CH1 7,500 + CH2 22,700), all deposited; challans CH1 and CH2, interest 921.00, total 31,121.00; one error row (Delta, no valid PAN, T-30) and the T-50 warning (payment codes not verified). Q4 2025-26: Alpha, Beta, Mehta, paid 160,000.00, tax 8,000.00, challan CH0. TCS Q1 2026-27: V95 4,000.00 on CH3; TCS Q4 2025-26: V05 1,000.00 on CH0T.

## 6. Certificate data (expected_certificates.csv)
Alpha Q1 2026-27 (Form 131): V10 + V12, paid 90,000.00, tax 2,200.00, all deposited, 2 challans. Alpha Q2: V13 (200.00) is not allocated to a challan -> refused (T-34). Mehta Q4 2025-26 (Form 16A, 1961 `P`): 60,000.00, tax 6,000.00, challan CH0.

## 7. 26AS reconciliation (statement_26as_fy2026-27.csv, expected_recon.csv)
Hand-made file (layout not verified against a real file; a Deductee PAN column is added because the client is the deductor). Tolerance 1.00. Rows: 1 Alpha 194C Apr 1,000.00 = V10 matched; 2 Alpha Jun 1,200.00 = V12 matched; 3 Ravi Aug 1,100.00 against 1,130.00 -> amount mismatch (-30.00); 4 Mehta printed 194J(b) = V31 (old section code finds the 2025 item) matched; 5 Silver printed 194I(b) = V50 matched; 6 unknown PAN ZZZZZ9999Z -> only in 26AS (unknown PAN); 7 Omega printed 393(1) (one table entry for many natures -> ambiguous section, never guessed) -> linked by hand to V70 with a note -> matched (manual); 8 Beta 500.00 dated 02-05-2026 against V40 dated 10-04-2026 -> date mismatch. Books not in the statement (9): V13, V23, V53, V60 (PAN missing), V71, V72, V91, V95, V96. Summary: matched 5, amount mismatch 1, date mismatch 1, only in 26AS 1, only in books 9.

## 8. Wrong cases (wrong_cases.csv): refused with the rule named
W01 T-09 no deductee row; W02 T-03 tax typed by the caller; W03 T-12 certificate before its validity; W04 T-15 no buyer flag for 2025-26; W05 T-01 no date; W06 T-16 TDS on a Receipt; W07 T-10 PAN of 6 characters; W08 reversal of V10 refused (challan allocation exists); W09 T-24 allocation 300.00 against item tax 200.00; W10 same challan number twice; W11 T-20 BSR code of 5 digits.


## 9. Phase 4.1 addendum (folder `p41`: second client Sunrise Traders, a proprietor; files `p41/*.csv`)
Order of the owner, 2026-11-13. All items are Act 2025 (2026-27), `S` = secondary_verified. Rent on this client is ex-194-IB because the answer "individual not liable to tax audit in the preceding year" is Yes for 2026-27 (not entered for 2025-26: wrong case W2). The main Greenfield client is a partnership: its answer is No for both years, so V50..V53 above are ex-194-I (10%), unchanged.

**G1 TDS on a GST invoice (purchase, Mumbai Works Pvt Ltd, company, contractor 2%).** Invoice 1,00,000.00 + CGST 9,000.00 + SGST 9,000.00 = 1,18,000.00. The base is the value WITHOUT GST: 100,000.00 is above the single limit 30,000.00 -> 100,000.00 x 2% = **2,000.00** (not 2% of 1,18,000.00 = 2,360.00). Lines: Mumbai Works Cr 1,18,000.00 less 2,000.00 = **1,16,000.00**; Contract Expenses Dr 1,00,000.00; Input CGST Dr 9,000.00; Input SGST Dr 9,000.00; TDS Payable Cr 2,000.00 (Dr 1,18,000.00 = Cr 1,18,000.00). W1: typing 1,18,000.00 as the base is refused (T-18).

**M1..M4 crossing with earlier payments at their own rates (Rajesh Fabricators Pvt Ltd, company, contractor: 2%, no PAN 20%, single 30,000.00, annual 1,00,000.00).**
| Ref | Date | Payment | PAN that day | Cumulative | Working | Tax |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | 10-05 | 20,000.00 | missing | 0 -> 20,000.00 | not above 30,000.00, below 1,00,000.00 | 0.00 |
| M2 | 10-06 | 25,000.00 | valid (confirmed before this voucher) | 20,000 -> 45,000.00 | below | 0.00 |
| M3 | 10-07 | 40,000.00 | valid | 45,000 -> 85,000.00 | above the single limit: 40,000.00 x 2% | 800.00 |
| M4 | 10-08 | 30,000.00 | valid | 85,000 -> 115,000.00 | annual limit crossed. M1: 20,000.00 x **20%** (its own no-PAN rate) = 4,000.00; M2: 25,000.00 x 2% = 500.00; M3: 2% x 40,000.00 = 800.00 less 800.00 already = 0.00; M4: 30,000.00 x 2% = 600.00 | **5,100.00** |
Check: base 1,15,000.00; tax already deducted 800.00; effective rate = (5,100.00 + 800.00) / 1,15,000.00 = 5.1304%. (A whole-year rate of 2% would give 2,300.00 less 800.00 = 1,500.00: wrong, M1 had no PAN.)

**Z1, Z2 partial certificate (Zenith Engineers Pvt Ltd, certificate LDC/2026/0101: 0.5%, limit 1,50,000.00, valid 01-04-2026 to 31-03-2027).** Z1 10-09 120,000.00: crossing, certificate covers all: 120,000.00 x 0.5% = **600.00**; certificate rate 0.5%, effective 0.5%. Z2 10-10 60,000.00: limit left 1,50,000.00 - 1,20,000.00 = 30,000.00: 30,000.00 x 0.5% = 150.00 + 30,000.00 x 2% = 600.00 = **750.00**; the tool shows certificate rate **0.5%** and effective rate 750.00 / 60,000.00 = **1.25%**.

**R1..R4 rent by an individual not liable to tax audit (Mrs Sharma, individual, ex-194-IB: 2%, Rs 50,000.00 per month; nature shown as rent_194ib, section 393(1)).** R1 05-06 60,000.00: June 60,000.00 is above 50,000.00 -> 60,000.00 x 2% = **1,200.00**; Payment voucher: Mrs Sharma Dr 60,000.00, HDFC Bank Cr 60,000.00 - 1,200.00 = 58,800.00, TDS Payable Cr 1,200.00. R2 05-07 50,000.00: exactly the limit -> 0.00. R3 05-08 30,000.00: 0.00. R4 20-08 30,000.00: August 60,000.00 is above the limit -> base 60,000.00 (whole month, `P`: the reading is pending for the CA) x 2% = **1,200.00**. For comparison the partnership (Greenfield V50): 60,000.00 x 10% = 6,000.00.

**Wrong cases (p41/wrong_cases.csv).** W1 T-18 base with GST; W2 T-19 rent dated 15-01-2026 when the client's answer for 2025-26 is not entered; W3 T-03 rent typed as `rent_194ib`.
