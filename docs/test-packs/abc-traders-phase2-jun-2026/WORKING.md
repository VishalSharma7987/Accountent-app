# ABC Traders - Phase 2 pack, April to June 2026: hand workings

Everything here was worked out **by hand** from the pack files (`ledgers.csv`, `opening_bills.csv`, `vouchers.csv`,
`allocations.csv`, `reversals.csv`, `bank_statement.csv`, `bank_opening_items.csv`, `parties.csv`). Nothing comes from the
tool. Amounts in rupees; **Dr** = debit, **Cr** = credit. Report date = **30-06-2026**. If the tool and these numbers
differ, the accountants decide which is right.

Day counts: "days past due" = report date minus due date. The five buckets are `not_due` (due date after 30-06),
`0-30`, `31-60`, `61-90`, `90+`. On 30-06-2026 the bucket edges are: 0-30 = due 31-05 to 30-06; 31-60 = due 01-05 to 30-05;
61-90 = due 01-04 to 30-04; 90+ = due 31-03 or earlier.

## 1. Opening balances (01-04-2026)

| Debit | Rs | Credit | Rs |
| --- | ---: | --- | ---: |
| Cash | 40,000 | Amit Verma Capital A/c | 7,72,500 |
| HDFC Bank (books) | 4,87,500 | Sharma Suppliers | 1,90,000 |
| Opening Stock | 2,00,000 | Gupta Wholesale | 60,000 |
| Furniture | 50,000 | Patel Packaging Works | 30,000 |
| Rahul Enterprises | 1,20,000 | Mehta Agencies | 55,000 |
| Meena Traders | 80,000 | | |
| Sunrise Stores | 90,000 | | |
| Kapoor & Sons | 40,000 | | |
| **Total** | **11,07,500** | **Total** | **11,07,500** |

Debit: 40,000 + 4,87,500 = 5,27,500; + 2,00,000 = 7,27,500; + 50,000 = 7,77,500; + 1,20,000 = 8,97,500; + 80,000 = 9,77,500;
+ 90,000 = 10,67,500; + 40,000 = 11,07,500. Credit: 7,72,500 + 1,90,000 = 9,62,500; + 60,000 = 10,22,500; + 30,000 = 10,52,500;
+ 55,000 = 11,07,500. **Equal.**

### Opening bills must equal each party's opening balance

| Party | Bills | Total | Ledger opening |
| --- | --- | ---: | ---: |
| Rahul Enterprises | INV-2025-118 50,000 + INV-2025-131 70,000 | 1,20,000 | 1,20,000 |
| Meena Traders | MT/INV/090 45,000 + MT/INV/104 35,000 | 80,000 | 80,000 |
| Sunrise Stores | SR-077 90,000 | 90,000 | 90,000 |
| Kapoor & Sons | KS-0056 40,000 | 40,000 | 40,000 |
| Sharma Suppliers | SS/2026/0078 40,000 + SS/2026/0091 1,50,000 | 1,90,000 | 1,90,000 |
| Gupta Wholesale | GW/0310 60,000 | 60,000 | 60,000 |
| Patel Packaging Works | PP/118 30,000 | 30,000 | 30,000 |
| Mehta Agencies | MA-441 55,000 | 55,000 | 55,000 |

Opening due dates (bill date + credit days): INV-2025-118 20-01 + 30 = 19-02; INV-2025-131 05-03 + 30 = 04-04;
MT/INV/090 10-02 + 45 = 27-03 (18 days to 28-02, 27 more); MT/INV/104 25-03 + 45 = 09-05; SR-077 28-03 + 60 = 27-05;
KS-0056 15-03 + 30 = 14-04; SS/2026/0078 15-01 + 60 = 16-03; SS/2026/0091 20-02 + 60 = 21-04; GW/0310 10-03 + 30 = 09-04;
PP/118 20-03 + 45 = 04-05; MA-441 01-03 + 45 = 15-04.

### Bank opening
Statement opening balance on 01-04-2026 = 5,00,000.00. Books opening = 4,87,500.00. Difference 12,500.00 = cheque no
000451 issued on 28-03-2026, not yet presented on 31-03 (`bank_opening_items.csv`, kind issued_not_presented):
4,87,500 + 12,500 = 5,00,000. It is presented on 03-04-2026 (statement line 2).

## 2. Vouchers (all with party / bill-wise allocations in `allocations.csv`)

| Ref | Date | What | Bill-wise effect |
| --- | --- | --- | --- |
| V01 | 02-04 | Receipt Rahul 40,000 NEFT | against INV-2025-131 |
| V02 | 03-04 | Sales Meena 1,18,000 (1,00,000 + GST 18,000) | new INV-2026-001, due 03-04 + 45 = 18-05 |
| V03 | 03-04 | Cash sale 23,600 | - |
| V04 | 06-04 | Payment Gupta 60,000 cheque 000452 | against GW/0310 (cleared) |
| V05 | 08-04 | Payment Sharma 1,00,000 NEFT | against SS/2026/0091 |
| V06 | 09-04 | Contra: cash deposited 20,000 | - |
| V07 | 10-04 | Electricity 3,400 cash | - |
| V08 | 13-04 | Receipt Kapoor 25,000 cash | against KS-0056 |
| V09 | 15-04 | Purchase Patel 35,400 (30,000 + 5,400) | new PP/131, due 15-04 + 45 = 30-05 |
| V10 | 16-04 | Office expenses 4,800 cash | - |
| V11 | 20-04 | Purchase Mehta 59,000 (50,000 + 9,000) | new MA-502, due 20-04 + 45 = 04-06 |
| V12 | 22-04 | Salary 35,000 NEFT | - |
| V13 | 24-04 | Receipt Meena 20,000 NEFT | against MT/INV/090 |
| V14 | 27-04 | Travelling 2,600 cash | - |
| V15 | 28-04 | Rent 25,000 cheque 000453 | - |
| V16 | 30-04 | Cash sale 11,800 | - |
| V17 | 02-05 | Contra: cash withdrawn 30,000 (self cheque 000455) | - |
| V18 | 02-05 | Salary 35,000 cash | - |
| V19 | 05-05 | Purchase Gupta 23,600 (20,000 + 3,600) | new GW/0412, due 05-05 + 30 = 04-06 |
| V20 | 06-05 | Receipt Sunrise 30,000 UPI (advance) | advance ADV-SR-01 |
| V21 | 08-05 | Payment Patel 30,000 cheque 000456 | against PP/118 (cleared) |
| V22 | 10-05 | Electricity 3,900 cash | - |
| V23 | 12-05 | Sales Rahul 1,77,000 (1,50,000 + 27,000) | new INV-2026-004, due 12-05 + 30 = 11-06 |
| V24 | 12-05 | Receipt Kapoor 11,000 cheque | against KS-0056 |
| V25 | 13-05 | Receipt Rahul 12,500 cheque | against INV-2025-131 |
| V26 | 14-05 | Receipt Meena 8,500 cheque | against INV-2026-001 |
| V27 | 16-05 | Travelling 3,100 cash | - |
| V28 | 18-05 | Office expenses 5,500 cash | - |
| V29 | 20-05 | Sales Sunrise 1,18,000 (1,00,000 + 18,000) | ONE party line: new INV-2026-006 88,000 + against ADV-SR-01 30,000 = 1,18,000; due 20-05 + 60 = 19-07 |
| V30 | 22-05 | Receipt Sunrise 40,000 NEFT | against SR-077 |
| V31 | 25-05 | Credit note Rahul 23,600 (20,000 + 3,600) | against INV-2026-004 |
| V32 | 30-05 | Rent 25,000 cheque 000457 | - |
| V33 | 31-05 | Contra: cash deposited 25,000 | - |
| V34 | 03-06 | Cash sale 17,700 | - |
| V35 | 05-06 | Electricity 4,100 cash | - |
| V36 | 08-06 | Receipt Meena 45,000 NEFT | against INV-2026-001 |
| V37 | 10-06 | Purchase Sharma 94,400 (80,000 + 14,400) | new SS/2026/0140, due 10-06 + 60 = 09-08 |
| V38 | 11-06 | Purchase Mehta 11,800 entered by mistake; REVERSED 14-06 | new MA-519, then mirrored: nets to nil |
| V39 | 12-06 | Debit note Sharma 11,800 (10,000 + 1,800) | against SS/2026/0140 |
| V40 | 15-06 | Sales Kapoor 59,000 (50,000 + 9,000) | new INV-2026-009, **explicit** due date 30-07 |
| V41 | 16-06 | Travelling 2,200 cash | - |
| V42 | 18-06 | Purchase Gupta 47,200 (40,000 + 7,200) | new GW/0455, due 18-06 + 30 = 18-07 |
| V43 | 20-06 | Payment Mehta 20,000 NEFT | against MA-502 |
| V44 | 22-06 | Receipt Rahul 50,000 NEFT | against INV-2026-004 |
| V45 | 26-06 | Payment Mehta 30,000 cheque 000471 | ON ACCOUNT |
| V46 | 29-06 | Salary 36,500 cheque 000472 | - |
| V47 | 29-06 | Receipt Sunrise 40,000 cheque 889900 | against SR-077 |
| V48 | 30-06 | Receipt Rahul 10,000 cheque 902177 | against INV-2025-131 |
| V49 | 30-06 | Office expenses 2,900 cash | - |

Convention for a line with two allocations (V29): all allocation amounts are positive and add up to the party line's
amount (88,000 + 30,000 = 1,18,000). The new bill is the invoice net of the advance it absorbs.

## 3. Party-wise bills as on 30-06-2026 (outstanding = original less the settlements above)

### Receivable
**Rahul Enterprises** (closing 1,20,000 + 1,77,000 - 40,000 - 12,500 - 23,600 - 50,000 - 10,000 = 1,60,900)

| Bill | Due | Calculation | Outstanding | Days past due | Bucket |
| --- | --- | --- | ---: | ---: | --- |
| INV-2025-118 | 19-02 | untouched | 50,000 | 9 (Feb) + 31 + 30 + 31 + 30 = 131 | 90+ |
| INV-2025-131 | 04-04 | 70,000 - 40,000 (V01) - 12,500 (V25) - 10,000 (V48) | 7,500 | 26 + 31 + 30 = 87 | 61-90 |
| INV-2026-004 | 11-06 | 1,77,000 - 23,600 (V31) - 50,000 (V44) | 1,03,400 | 19 | 0-30 |

50,000 + 7,500 + 1,03,400 = 1,60,900. Ties.

**Meena Traders** (closing 80,000 + 1,18,000 - 20,000 - 8,500 - 45,000 = 1,24,500)

| Bill | Due | Calculation | Outstanding | Days | Bucket |
| --- | --- | --- | ---: | ---: | --- |
| MT/INV/090 | 27-03 | 45,000 - 20,000 (V13) | 25,000 | 4 + 30 + 31 + 30 = 95 | 90+ |
| MT/INV/104 | 09-05 | untouched | 35,000 | 22 + 30 = 52 | 31-60 |
| INV-2026-001 | 18-05 | 1,18,000 - 8,500 (V26) - 45,000 (V36) | 64,500 | 13 + 30 = 43 | 31-60 |

25,000 + 35,000 + 64,500 = 1,24,500. Ties.

**Sunrise Stores** (closing 90,000 + 1,18,000 - 30,000 - 40,000 - 40,000 = 98,000)

| Bill | Due | Calculation | Outstanding | Days | Bucket |
| --- | --- | --- | ---: | ---: | --- |
| SR-077 | 27-05 | 90,000 - 40,000 (V30) - 40,000 (V47) | 10,000 | 4 + 30 = 34 | 31-60 |
| ADV-SR-01 | - | advance 30,000 fully adjusted by V29 | nil (not listed) | - | - |
| INV-2026-006 | 19-07 | new bill 88,000 | 88,000 | -19 (19 days still to run) | not due |

10,000 + 88,000 = 98,000. Ties.

**Kapoor & Sons** (closing 40,000 - 25,000 - 11,000 + 59,000 = 63,000)

| Bill | Due | Calculation | Outstanding | Days | Bucket |
| --- | --- | --- | ---: | ---: | --- |
| KS-0056 | 14-04 | 40,000 - 25,000 (V08) - 11,000 (V24) | 4,000 | 16 + 31 + 30 = 77 | 61-90 |
| INV-2026-009 | 30-07 | 59,000 (explicit due date) | 59,000 | -30 | not due |

4,000 + 59,000 = 63,000. Ties.

### Payable
**Sharma Suppliers** (closing 1,90,000 + 94,400 - 1,00,000 - 11,800 = 1,72,600)

| Bill | Due | Calculation | Outstanding | Days | Bucket |
| --- | --- | --- | ---: | ---: | --- |
| SS/2026/0078 | 16-03 | untouched | 40,000 | 15 + 30 + 31 + 30 = 106 | 90+ |
| SS/2026/0091 | 21-04 | 1,50,000 - 1,00,000 (V05) | 50,000 | 9 + 31 + 30 = 70 | 61-90 |
| SS/2026/0140 | 09-08 | 94,400 - 11,800 (V39) | 82,600 | -40 | not due |

40,000 + 50,000 + 82,600 = 1,72,600. Ties. (Sharma is a MEDIUM supplier: never flagged for MSME.)

**Gupta Wholesale** (closing 60,000 + 23,600 + 47,200 - 60,000 = 70,800)
GW/0310 settled by V04 (nil). GW/0412 due 04-06: 23,600, days 26, bucket 0-30. GW/0455 due 18-07: 47,200, not due (-18).

**Patel Packaging Works** (closing 30,000 + 35,400 - 30,000 = 35,400)
PP/118 settled by V21 (nil). PP/131 due 30-05: 35,400, days 1 + 30 = 31, bucket 31-60.

**Mehta Agencies** (closing 55,000 + 59,000 + 11,800 - 11,800 - 20,000 - 30,000 = 64,000)

| Item | Due | Calculation | Outstanding | Days | Bucket |
| --- | --- | --- | ---: | ---: | --- |
| MA-441 | 15-04 | untouched | 55,000 | 15 + 31 + 30 = 76 | 61-90 |
| MA-502 | 04-06 | 59,000 - 20,000 (V43) | 39,000 | 26 | 0-30 |
| MA-519 | - | entered 11,800 (V38) and reversed (14-06): mirrored | nil | - | - |
| on account | 26-06 | V45 payment 30,000 (Dr side, opposite to the bills) | 30,000 Dr | 4 | 0-30 |

55,000 + 39,000 - 30,000 = 64,000. Ties. The on-account item is counted at its voucher date, with no credit period.

## 4. Ageing as on 30-06-2026 (party-wise, plain addition)

Receivable (Dr):

| Party | not due | 0-30 | 31-60 | 61-90 | 90+ | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Rahul | 0 | 1,03,400 | 0 | 7,500 | 50,000 | 1,60,900 |
| Meena | 0 | 0 | 35,000 + 64,500 = 99,500 | 0 | 25,000 | 1,24,500 |
| Sunrise | 88,000 | 0 | 10,000 | 0 | 0 | 98,000 |
| Kapoor | 59,000 | 0 | 0 | 4,000 | 0 | 63,000 |
| **Total** | **1,47,000** | **1,03,400** | **1,09,500** | **11,500** | **75,000** | **4,46,400** |

Column checks: not due 88,000 + 59,000 = 1,47,000; 31-60 99,500 + 10,000 = 1,09,500; 61-90 7,500 + 4,000 = 11,500;
90+ 50,000 + 25,000 = 75,000. Row total: 1,47,000 + 1,03,400 = 2,50,400; + 1,09,500 = 3,59,900; + 11,500 = 3,71,400;
+ 75,000 = 4,46,400 = 1,60,900 + 1,24,500 + 98,000 + 63,000. Also equals the four debtor ledgers in the Trial Balance.

Payable (Cr):

| Party | not due | 0-30 | 31-60 | 61-90 | 90+ | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sharma | 82,600 | 0 | 0 | 50,000 | 40,000 | 1,72,600 |
| Gupta | 47,200 | 23,600 | 0 | 0 | 0 | 70,800 |
| Patel | 0 | 0 | 35,400 | 0 | 0 | 35,400 |
| Mehta | 0 | 39,000 - 30,000 = 9,000 | 0 | 55,000 | 0 | 64,000 |
| **Total** | **1,29,800** | **32,600** | **35,400** | **1,05,000** | **40,000** | **3,42,800** |

Column checks: not due 82,600 + 47,200 = 1,29,800; 0-30 23,600 + 9,000 = 32,600; 61-90 50,000 + 55,000 = 1,05,000.
Row total: 1,29,800 + 32,600 = 1,62,400; + 35,400 = 1,97,800; + 1,05,000 = 3,02,800; + 40,000 = 3,42,800
= 1,72,600 + 70,800 + 35,400 + 64,000.

## 5. Cash Book (Cash ledger, 01-04-2026 to 30-06-2026)

Opening 40,000. Only days with entries are listed. Closing = previous closing + receipts - payments.

| Date | Entries | Receipts | Payments | Closing |
| --- | --- | ---: | ---: | ---: |
| 03-04 | V03 cash sale | 23,600 | 0 | 40,000 + 23,600 = 63,600 |
| 09-04 | V06 deposited into bank | 0 | 20,000 | 43,600 |
| 10-04 | V07 | 0 | 3,400 | 40,200 |
| 13-04 | V08 Kapoor | 25,000 | 0 | 65,200 |
| 16-04 | V10 | 0 | 4,800 | 60,400 |
| 27-04 | V14 | 0 | 2,600 | 57,800 |
| 30-04 | V16 cash sale | 11,800 | 0 | 69,600 |
| 02-05 | V17 withdrawn 30,000; V18 salary 35,000 | 30,000 | 35,000 | 69,600 + 30,000 - 35,000 = 64,600 |
| 10-05 | V22 | 0 | 3,900 | 60,700 |
| 16-05 | V27 | 0 | 3,100 | 57,600 |
| 18-05 | V28 | 0 | 5,500 | 52,100 |
| 31-05 | V33 deposited into bank | 0 | 25,000 | 27,100 |
| 03-06 | V34 cash sale | 17,700 | 0 | 44,800 |
| 05-06 | V35 | 0 | 4,100 | 40,700 |
| 16-06 | V41 | 0 | 2,200 | 38,500 |
| 30-06 | V49 | 0 | 2,900 | 35,600 |
| **Total** | | **1,08,100** | **1,12,500** | **35,600** |

Receipts: 23,600 + 25,000 + 11,800 + 30,000 + 17,700 = 1,08,100. Payments: 20,000 + 3,400 + 4,800 + 2,600 + 35,000 +
3,900 + 3,100 + 5,500 + 25,000 + 4,100 + 2,200 + 2,900 = 1,12,500. Check: 40,000 + 1,08,100 - 1,12,500 = 35,600.
The lowest closing is 27,100 (31-05): cash never goes negative on any day, even inside 02-05 (30,000 comes in first).

## 6. Bank Reconciliation Statement as on 30-06-2026 (HDFC Bank)

**Books balance.** 4,87,500 + deposits (V01 40,000, V06 20,000, V13 20,000, V20 30,000, V24-26 32,000, V30 40,000,
V33 25,000, V36 45,000, V44 50,000, V47 40,000, V48 10,000 = 3,52,000) - payments (V04 60,000, V05 1,00,000, V12 35,000,
V15 25,000, V17 30,000, V21 30,000, V32 25,000, V43 20,000, V45 30,000, V46 36,500 = 3,91,500)
= 4,87,500 + 3,52,000 - 3,91,500 = **4,48,000**.

**Statement, running balance** (opening 5,00,000; every line re-added):
5,00,000 + 40,000 = 5,40,000; - 12,500 = 5,27,500; - 1,00,000 = 4,27,500; + 20,000 = 4,47,500; - 60,000 = 3,87,500;
- 35,000 = 3,52,500; + 20,000 = 3,72,500; - 590 = 3,71,910; - 25,000 = 3,46,910; - 30,000 = 3,16,910; + 30,000 = 3,46,910;
- 30,000 = 3,16,910; + 32,000 = 3,48,910; + 40,000 = 3,88,910; + 25,000 = 4,13,910; - 25,000 = 3,88,910; + 45,000 = 4,33,910;
- 236 = 4,33,674; - 20,000 = 4,13,674; + 50,000 = 4,63,674; + 1,875 = **4,65,549** = balance per bank.

**Matching** (`expected_matches.csv`): 18 of the 21 statement lines match a book item (17 voucher references, one opening item
000451, and one one-to-many: 32,000 = V24 11,000 + V25 12,500 + V26 8,500; no other combination of deposits adds to
32,000). Statement lines not in the books (bank-only): line 8 charges 590 (28-04), line 18 charges 236 (10-06),
line 21 interest 1,875 (30-06). Book items not on the statement by 30-06: V45, V46 (cheques issued), V47, V48 (cheques deposited).

| Step | Rs |
| --- | ---: |
| Balance as per books | 4,48,000 |
| Add: cheques issued, not yet presented: 000471 (30,000) + 000472 (36,500) | 66,500 |
| Less: cheques deposited, not yet cleared: 889900 (40,000) + 902177 (10,000) | (50,000) |
| Add: bank-only credit (interest not in books) | 1,875 |
| Less: bank-only debits (charges not in books): 590 + 236 | (826) |
| **Computed balance as per bank** | **4,65,549** |
| Balance as per bank statement | 4,65,549 |
| Difference | **nil - ties** |

4,48,000 + 66,500 = 5,14,500; - 50,000 = 4,64,500; + 1,875 = 4,66,375; - 826 = 4,65,549.

The bank-only items are explained in the BRS but are NOT in the books or in the Trial Balance above (the tool only makes
DRAFT vouchers for them: `expected_bank_only_drafts.csv`). Once those drafts are approved and posted the books balance
would become 4,48,000 + 1,875 - 826 = 4,49,049, with the same reconciling cheques: 4,49,049 + 66,500 - 50,000 = 4,65,549.

## 7. MSME payment-time flags as on 30-06-2026 (rule status: PENDING - see below)

Rule used (all rows `verification_status = pending` in the seed): micro and small only; with a written agreement the
agreed days (never more than 45); without one, 15 days; counted from the bill date (acceptance date assumed = bill date).

| Supplier | Category | Agreement | Bill | Bill date | Legal days | Legal due | Overdue | Open | Flagged |
| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | --- |
| Gupta Wholesale | micro | yes, 30 days | GW/0412 | 05-05 | 30 | 04-06 (05-05 + 30) | 26 | 23,600 | yes |
| Gupta Wholesale | micro | yes, 30 days | GW/0455 | 18-06 | 30 | 18-07 | - | 47,200 | no (not yet past legal due) |
| Patel Packaging Works | small | no | PP/131 | 15-04 | 15 | 30-04 (15-04 + 15) | 61 (30-04 to 30-06) | 35,400 | yes |
| Sharma Suppliers | medium | - | all | - | - | - | - | - | never (medium is not covered) |
| Mehta Agencies | none | - | all | - | - | - | - | - | never (not MSME) |

Flagged total 23,600 + 35,400 = 59,000. Settled bills (GW/0310 paid 06-04, PP/118 paid 08-05) are not open and are not
flagged. Note PP/131's agreed credit period (45 days, due 30-05) is longer than the legal 15 days: the legal date governs.
**The legal values are unverified (pending) and must be confirmed by the owner / CA from the official text.**

## 8. Trial Balance as on 30-06-2026 (ledger by ledger, plain addition)

| Ledger | Working | Dr | Cr |
| --- | --- | ---: | ---: |
| Cash | see section 5 | 35,600 | |
| HDFC Bank | see section 6 | 4,48,000 | |
| Opening Stock | no movement | 2,00,000 | |
| Furniture | no movement | 50,000 | |
| Rahul Enterprises | section 3 | 1,60,900 | |
| Meena Traders | section 3 | 1,24,500 | |
| Sunrise Stores | section 3 | 98,000 | |
| Kapoor & Sons | section 3 | 63,000 | |
| Sharma Suppliers | section 3 | | 1,72,600 |
| Gupta Wholesale | section 3 | | 70,800 |
| Patel Packaging Works | section 3 | | 35,400 |
| Mehta Agencies | section 3 | | 64,000 |
| Amit Verma Capital A/c | opening only | | 7,72,500 |
| Purchases | Dr 30,000 + 50,000 + 20,000 + 80,000 + 10,000 + 40,000 = 2,30,000; Cr 10,000 (reversal of V38) | 2,20,000 | |
| Purchase Returns | V39 | | 10,000 |
| Sales | 1,00,000 + 20,000 + 10,000 + 1,50,000 + 1,00,000 + 15,000 + 50,000 | | 4,45,000 |
| Sales Returns | V31 | 20,000 | |
| Output GST | Cr 18,000 + 3,600 + 1,800 + 27,000 + 18,000 + 2,700 + 9,000 = 80,100; Dr 3,600 (V31) | | 76,500 |
| Input GST | Dr 5,400 + 9,000 + 3,600 + 14,400 + 1,800 + 7,200 = 41,400; Cr 1,800 (V38 reversal) + 1,800 (V39) | 37,800 | |
| Rent | 25,000 + 25,000 | 50,000 | |
| Salary | 35,000 + 35,000 + 36,500 | 1,06,500 | |
| Electricity | 3,400 + 3,900 + 4,100 | 11,400 | |
| Office Expenses | 4,800 + 5,500 + 2,900 | 13,200 | |
| Travelling | 2,600 + 3,100 + 2,200 | 7,900 | |
| Others (Drawings, Telephone, Printing, Repairs, Bank Charges, Interest Received, Suspense) | nil | 0 | 0 |
| **Total** | | **16,46,800** | **16,46,800** |

Dr: 35,600 + 4,48,000 = 4,83,600; + 2,00,000 = 6,83,600; + 50,000 = 7,33,600; + 4,46,400 (debtors) = 11,80,000;
+ 20,000 = 12,00,000; + 2,20,000 = 14,20,000; + 37,800 = 14,57,800; + 50,000 = 15,07,800; + 1,06,500 = 16,14,300;
+ 11,400 = 16,25,700; + 13,200 = 16,38,900; + 7,900 = 16,46,800.
Cr: 3,42,800 (creditors) + 7,72,500 = 11,15,300; + 4,45,000 = 15,60,300; + 10,000 = 15,70,300; + 76,500 = 16,46,800. **Equal.**

## 9. The wrong vouchers (`wrong_vouchers.csv`, tried after all correct vouchers are posted) and wrong parties

| Ref | Why it is wrong | Rule |
| --- | --- | --- |
| X01 | Sales to Rahul 1,18,000: only 1,00,000 allocated | B-01 |
| X02 | Receipt (Cr Rahul): a NEW reference on the credit side of a debtor | B-02 |
| X03 | Sales to Rahul with new reference INV-2025-118, already an opening bill of Rahul | B-03 |
| X04 | Receipt from Kapoor 15,000 against KS-0056, only 4,000 outstanding | B-04 |
| X05 | Cash payment 1,00,000 on 05-04 when the cash balance is 63,600 | C-01 |
| X06 | Payment to Sharma 1,00,000 on 11-04, same party and amount as V05 on 08-04 (3 days) | D-01 |
| WP1 | GSTIN of 14 characters (`27ABCPM5678K1Z`) | P-01 |
| WP2 | PAN `ABCPM5679K` differs from characters 3-12 of the GSTIN (`ABCPM5678K`) | P-03 |
| WP3 | Mehta Agencies marked small MSME with no Udyam number | P-05 |

Rahul's valid GSTIN `27ABCPR1234F1Z5`: characters 3-12 = `ABCPR1234F` = his PAN; state 27. (Format only; the check
digit is not verified in Phase 2.)
