# Phase 8 acceptance pack: audit checks A-01 to A-18 (working for the accountants)

Client: **Sunrise Audit Traders** (SYNTHETIC: a trading proprietorship, GST registered from 01-09-2026, five contractors who are TDS deductees, two MSME
suppliers, a cash book, a bank account and two stock items). The audit period is **01-04-2026 to 31-10-2026** of FY 2026-27, compared with the same dates of
FY 2025-26. The books are built from the CSV input files of this folder by `scripts/build_pack_p8_inputs.py`. **Exactly one error is injected per check**;
every other entry is a clean control that must NOT be flagged. The expected answers (`expected_*.csv`) were typed by hand from the working below; the
runner compares the audit report with them and never changes them. Amounts are in rupees; dates are dd-mm-yyyy in this note.

How to read: "V-xx" is a voucher of this pack (`vouchers.csv`, `lines.csv`), "P-xx" a voucher of last year. Limits and rates come from the seeded rule
tables by the transaction date; their verification status is shown, because the audit prints it on every finding.

## 1. Legal values used (from the seeded tables, dated, with their status)

| Value | Used for | Row in force | Status | Where it must be confirmed |
| --- | --- | --- | --- | --- |
| Cash payment limit 10,000.00 per person per day, "above", 100% disallowance | A-05 for dates from 01-04-2026 | `cash_payment_daily_limit`, Income-tax Act 2025 (section number not found) | **pending** | SIGNOFF Q1 |
| Same limit for dates up to 31-03-2026 | A-05 in FY 2025-26 (P-02) | Income-tax Act 1961 s.40A(3) | **pending** | SIGNOFF Q1 |
| Cash receipt limit 2,00,000.00 per person per day, "at or above" | A-06 from 01-04-2026 | Income-tax Act 2025 s.186 (secondary) | **pending** | SIGNOFF Q2 |
| MSME legal days 15 (no written agreement) / 45 (agreement) | A-07 | `msme_37_2_g_2025` micro / small, from 01-04-2026 | secondary_verified | SIGNOFF Q3 |
| Contractor (individual) 1% above single payment 30,000.00 or yearly 1,00,000.00 | A-09, A-10 | section 393(1) Sl. 6(i), from 01-04-2026 | secondary_verified | SIGNOFF Q4 |
| TDS deposit by the 7th of the next month | A-11 | `tds_challan_regular`, from 01-04-2026 | secondary_verified | SIGNOFF Q4 |
| GST portal numbering / rate rows | A-08 (the finding carries the worst status of the tie-out) | tie-out rule status | **pending** | Phase 3 sign-off |

Judgement parameters (not law, stored on the run): duplicate window 7 days, round unit 1,000.00 with minimum 10,000.00, late posting 30 days, variance
band 50%, and **variance minimum 5,00,000.00** (the default is 1,00,000.00; this pack sets 5,00,000.00 so that only the doubled ledger is reported, see A-15).

## 2. The injected errors (one per check) and why each one triggers

| Check | Injected error | Why it triggers (hand working) | Expected finding |
| --- | --- | --- | --- |
| A-01 Duplicate bills | V-04 (12-05-2026) and V-05 (14-05-2026): Kumar Steel bill "INV-17" and "inv 17 ", each 23,450.00 | References compare equal ignoring case, spaces and punctuation ("inv17"); same party, two live purchase vouchers | F-01, warning, amount 23,450.00 |
| A-02 Duplicate payments | V-16 (03-07-2026) and V-17 (06-07-2026): 18,750.50 to Verma Cooling Solutions | Same party, same total, 3 days apart (window 7) | F-02, warning |
| A-03 Missing document | V-08 (26-05-2026): purchase of 9,640.00 with no supporting document | 26 purchases / payments need a document; 25 have one | F-03, warning |
| A-04 Number gap | Sales numbers SAL/2026-27/0001, 0002, **0004**, 0005 (0003 never issued) | Posted numbers 1..5 miss 3; counter 5 equals the highest (so only the gap is reported) | F-04, error |
| A-05 Cash payment limit | V-24 6,000.00 + V-25 5,000.00 cash to Sharma Traders on 14-08-2026 | 6,000.00 + 5,000.00 = 11,000.00 is above 10,000.00; disallowance 11,000.00 x 100% = 11,000.00; limit pending | F-05, error |
| A-06 Cash receipt limit | V-30 1,50,000.50 + V-31 49,999.50 cash from Mehta & Co on 03-09-2026 | 1,50,000.50 + 49,999.50 = 2,00,000.00 is at the limit ("at or above"); limit pending | F-06, error |
| A-07 MSME dues | V-29 (01-09-2026) bill GE/884 of 38,260.00, micro supplier Gupta Enterprises, unpaid | No written agreement: 15 days from 01-09-2026 = due 16-09-2026; as on 31-10-2026 it is 45 days late (the bill is 60 days old) | F-07, error |
| A-08 GST books vs returns | Filed GSTR-1 for October 2026 shows taxable value 50,000.00, CGST 4,500.00, SGST 4,500.00; the books have no sale in October | Books 0.00 minus filed: taxable -50,000.00, CGST -4,500.00, SGST -4,500.00; sum of the three 59,000.00 | F-08, error |
| A-09 TDS not deducted | V-11 (10-06-2026): 1,01,500.00 paid to Raj Contractors, no tax item | 1,01,500.00 is above the 30,000.00 single limit; 1% = 1,015.00; deducted 0.00 | F-09, error, 1,015.00 |
| A-10 TDS short deducted | V-13 (15-06-2026): 1,08,250.00 to Mehta Builders, tax 400.00 deducted | 1% of 1,08,250.00 = 1,082.50, rounded half up to the rupee = 1,083.00; deducted 400.00; short 683.00 | F-10, error, 683.00 |
| A-11 TDS late deposited | V-12 (12-06-2026): tax 1,058.00 on Dutta Associates deposited 20-07-2026 | Due 07-07-2026 (7th of next month); 07-07 to 20-07 = 13 days late | F-11, error |
| A-12 Round amounts | V-36 (15-09-2026): journal of 50,000.00 (rent accrual to Singh Brothers) | 50,000.00 is a multiple of 1,000.00 and not below 10,000.00 | F-12, info |
| A-13 Sunday / holiday | V-33 dated 06-09-2026 (a Sunday); V-40 dated 20-10-2026 (Dussehra, in the client's own holiday list) | Sunday is computed; the holiday comes from `audit_holidays` (no national list is seeded) | F-14 (Sunday), F-15 (holiday) |
| A-14 After lock | V-20 dated 20-07-2026, posted 12-08-2026; July 2026 was locked on 05-08-2026 and unlocked on 10-08-2026 ("Late bill received from supplier") | Posted after the lock of its period; only 12 days after the period end, so the 30-day rule does not apply | F-16, warning |
| A-15 Unusual movement | Repairs & Maintenance 8,40,250.00 (V-28) against 2,60,150.00 last year (P-01) | Change 5,80,100.00 is at least 5,00,000.00 and 5,80,100.00 / 2,60,150.00 = 222.99% is above 50% | F-17, review |
| A-16 Negative cash | V-34 (08-09-2026): 4,200.00 paid from Petty Cash that had no balance | Petty Cash is -4,200.00 at the end of 08-09-2026 (refilled 10-09-2026 by V-35) | F-19, error |
| A-17 Negative stock | Steel Rod 12mm: opening 10.000, write-off of 12.000 on 15-09-2026 (SJ/2026-27/0002) | 10.000 - 12.000 = -2.000 | F-20, error |
| A-18 Related party | Singh Brothers flagged as related (landlord, brother of the proprietor) | Postings in the period: V-36 credit 50,000.00 and V-39 debit 30,150.00 | F-21, info, amount 80,150.00 |

Three findings are real but not "injected" (listed in the expected file with their kind): **F-13** (V-27, a cash payment of exactly 10,000.00 is a control for
A-05 but it IS a round amount, so A-12 lists it), **F-15** (the holiday variant of A-13) and **F-18** (Reliable Repairs: the other leg of the doubled repair bill:
-8,40,250.00 against -63,800.00 last year, change -7,76,450.00 = 1,217.01%). Total this year 21 findings: 10 error, 4 warning, 2 review, 5 info; total
disallowance 11,000.00. FY 2025-26 (P-02: 12,500.00 cash to Sharma Traders on 15-09-2025, limit of the 1961 Act, pending) gives one finding, F-22.

## 3. Clean controls (must NOT be flagged; `expected_controls.csv`, 32 of them)

Same bill number but another supplier (V-06), same supplier another number (V-07), same payment 21 days later (V-21), bank payment the same day (V-26), cash
payment exactly at the limit (V-27), 1,99,999.99 cash receipt (V-32), small cash receipt (V-01) and a big bank receipt (V-23), a small supplier bill 10 days old
(Patel Plastics, V-41) and an MSME bill paid inside its legal days (GE/771), September 2026 with a nil GSTR-1 and nothing in the books, correctly deducted tax
(V-12, V-14), a payment below the threshold (V-15), tax deposited on 06-07-2026 (V-13, V-14), totals 25,000.50 and 9,000.00 (A-12), the day after the
holiday (V-41), three other July vouchers posted in July (V-19, V-21, V-22), movements of Cash (+4,28,849.99), HDFC Bank (-2,30,341.10) and Sharma Traders
(90.80% but 11,350.00), the main cash book that never goes negative, a stock write-off that leaves 15.000, and Gamma Retail which is not flagged as related.

## 4. Hand working of the figures that are not obvious

* **A-15.** This year (01-04 to 31-10-2026) the net movement (debit minus credit) of Repairs & Maintenance is Dr 8,40,250.00; last year (01-04 to 31-10-2025) Dr
  2,60,150.00. Change 5,80,100.00; 5,80,100.00 x 100 / 2,60,150.00 = 222.9867 -> 222.99%. Reliable Repairs: this year Cr 8,40,250.00 (-8,40,250.00); last year bill
  Cr 2,60,150.00 and payment Dr 1,96,350.00 = -63,800.00; change -7,76,450.00; 7,76,450.00 x 100 / 63,800.00 = 1,217.0063 -> 1,217.01%. No other ledger changes by
  5,00,000.00 or more: Cash +4,16,349.99 against -12,500.00 (change 4,28,849.99), HDFC Bank -4,26,691.10 against -1,96,350.00 (change -2,30,341.10), Purchases
  2,51,850.00, Sales -2,61,365.00 and the rest below that. With the default minimum of 1,00,000.00 about a dozen ledgers would be listed, which is why the pack
  fixes 5,00,000.00 for this run (SIGNOFF Q6).
* **A-16.** Cash has an opening balance of 3,00,000.00 and ends at 7,16,349.99; Petty Cash has no opening: -4,200.00 on 08-09-2026, +800.00 after V-35.
* **A-08.** The registration starts on 01-09-2026, so only September and October 2026 are tested. September: filed nil figures equal the books (ties).
* **A-11.** Challan CH-1 (06-07-2026) pays V-13 400.00 and V-14 1,032.00 (1,432.00); CH-2 (20-07-2026) pays V-12 1,058.00 (1% of 1,05,750.00 = 1,057.50, rounded half up to 1,058.00).
* **Populations** (the items each check examined, from the inputs): A-01 11, A-02 14, A-03 26, A-04 41, A-05 4, A-06 4, A-07 2, A-08 2, A-09 5, A-10 5, A-11 3,
  A-12 41, A-13 41, A-14 41, A-15 26, A-16 2, A-17 2, A-18 2.

## 5. Working paper, sampling, Form 3CD, AI summary

* **Working paper (A-12, 2 exceptions)**: create; sign-off before review is refused (paper_status_invalid); in review; sign-off with open exceptions is refused;
  the 10,000.00 payment is cleared and the 50,000.00 journal is confirmed, each with a reason; a note; a blank conclusion is refused; a sample (random, seed 7,
  size 1) is repeatable; sign-off; afterwards decide, note, reopen, review, sign off again and sample are all refused (paper_signed_off) and direct SQL on
  the items, the paper and the notes is refused by the database; the audit log holds the sign-off with old (in_review) and new (signed_off) status.
* **Sampling** (population = the 26 purchase / payment vouchers of A-03, sorted by voucher ref; SplitMix64; derived with an independent implementation, test
  vector seed 0 -> E220A8397B1DCDAF): random seed 7, size 5 -> V-08, V-16, V-27, V-29, V-39; systematic seed 7, size 5 -> interval 26 // 5 = 5, start = first draw
  mod 5 = 2 -> V-05, V-12, V-17, V-24, V-29; systematic with start 0 -> V-03, V-08, V-15, V-21, V-27; value sample, threshold 1,00,000.00 (key items V-11, V-12,
  V-13, V-14, V-28) plus 3 random from the 21 others with seed 11 -> V-11, V-12, V-13, V-14, V-15, V-26, V-28, V-34. The same seed gives the same sample, also
  when the population arrives in another order.
* **Form 3CD (FY 2025-26 run; the form follows the financial year end)**: clause 21: 1 cash payment exception, 12,500.00, disallowable 12,500.00, status pending;
  clauses 22, 23, 26, 27, 31, 34: count 0 and amount 0.00; clauses 18, 35, 40, 44 are left for hand entry. FY 2026-27 uses Form 26: its clause list is not seeded,
  so only hand entries are possible (SIGNOFF Q8).
* **AI summary (fake model only)**: with the client's AI switch off the summary makes no model call and stores nothing; after the owner switches it on (synthetic
  data) the A-05 and A-08 findings are summarised, each stored as a *suggestion*; the A-08 text carries a GSTIN that must not appear in what the model sees;
  no working paper is created or changed by a summary.

## 6. What the run asserts (headline)

1. Every one of the 18 injected errors is in the report as a finding with non-empty evidence (voucher ids, ledger ids, figures) matching the expected file.
2. Nothing else is reported: the set of findings equals the expected set (21 this year, 1 last year); none of the 32 controls is flagged.
3. After everything (two runs, papers, sample, sign-off, summaries, Form 3CD set) the books are unchanged: row counts of 18 books tables and a SHA-256 over every
   voucher and line are equal before and after.
4. No network access, only the fake model, two model requests.

Known limits of this synthetic client: TDS items, challans and the GST filed figures are typed rows (as the accountant would enter them), the GST registration
starts on 01-09-2026 so the tie-out tests only two months, stock quantities are not posted to accounting, and the lock events are audit-log rows with their
original time stamps (the voucher service blocks a posting into a locked period, so "unlock, post" is shown by the log).
