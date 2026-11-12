# ABC Traders — April 2026: hand workings

How the expected answers were worked out: **by hand, T-account by T-account**, from `ledgers.csv` (openings) and
`vouchers.csv` (30 vouchers) and `reversals.csv` (1 reversal). Nothing here comes from the tool. The accountants check
these workings; if the tool and these numbers differ, the accountants decide which is right.

Amounts in rupees. **Dr** = debit, **Cr** = credit. A running balance is shown after every entry.

## 1. Opening balances (1 April 2026)

| Debit balances | Rs | Credit balances | Rs |
| --- | ---: | --- | ---: |
| Cash | 25,000 | Amit Verma Capital A/c | 6,00,000 |
| HDFC Bank | 4,00,000 | Sharma Suppliers | 45,000 |
| Opening Stock | 1,50,000 | Gupta Wholesale | 30,000 |
| Rahul Enterprises | 60,000 | | |
| Furniture | 40,000 | | |
| **Total** | **6,75,000** | **Total** | **6,75,000** |

Check, debit side: 25,000 + 4,00,000 = 4,25,000; + 1,50,000 = 5,75,000; + 60,000 = 6,35,000; + 40,000 = 6,75,000.
Check, credit side: 6,00,000 + 45,000 = 6,45,000; + 30,000 = 6,75,000. **Equal.**

## 2. The vouchers (all April 2026; GST amounts are typed as plain amounts)

| Ref | Date | Type | Entry (Dr / Cr) | Amount |
| --- | --- | --- | --- | ---: |
| V01 | 01-04 | Receipt | HDFC Bank Dr / Capital Cr (capital introduced) | 1,00,000 |
| V02 | 02-04 | Purchase | Purchases 2,00,000 + Input GST 36,000 Dr / Sharma Cr 2,36,000 (bill SS/0412) | 2,36,000 |
| V03 | 02-04 | Payment | Rent Dr / HDFC Bank Cr | 25,000 |
| V04 | 03-04 | Sales | Rahul Dr 1,18,000 / Sales Cr 1,00,000 + Output GST Cr 18,000 (INV-001) | 1,18,000 |
| V05 | 03-04 | Sales | Cash Dr 23,600 / Sales Cr 20,000 + Output GST Cr 3,600 (INV-002) | 23,600 |
| V06 | 04-04 | Sales | Meena Dr 59,000 / Sales Cr 50,000 + Output GST Cr 9,000 (INV-003) | 59,000 |
| V07 | 05-04 | Receipt | HDFC Bank Dr / Rahul Cr | 60,000 |
| V08 | 06-04 | Payment | Sharma Dr / HDFC Bank Cr | 45,000 |
| V09 | 07-04 | Purchase | Purchases 80,000 + Input GST 14,400 Dr / Gupta Cr 94,400 (bill GW/221) | 94,400 |
| V10 | 08-04 | Payment | Salary Dr / HDFC Bank Cr | 35,000 |
| V11 | 08-04 | Payment | Electricity Dr / Cash Cr | 4,200 |
| V12 | 09-04 | Contra | HDFC Bank Dr / Cash Cr (cash deposited) | 20,000 |
| V13 | 10-04 | Credit Note | Sales Returns 10,000 + Output GST 1,800 Dr / Rahul Cr 11,800 | 11,800 |
| V14 | 11-04 | Debit Note | Sharma Dr 11,800 / Purchase Returns Cr 10,000 + Input GST Cr 1,800 | 11,800 |
| V15 | 12-04 | Payment | Telephone & Internet Dr / Cash Cr | 1,500 |
| V16 | 12-04 | Payment | Printing & Stationery Dr / Cash Cr | 2,300 |
| V17 | 13-04 | Receipt | Cash Dr / Meena Cr | 30,000 |
| V18 | 14-04 | Payment | Travelling Dr / Cash Cr | 3,600 |
| V19 | 15-04 | Payment | Drawings Dr / HDFC Bank Cr | 15,000 |
| V20 | 15-04 | Payment | Repairs & Maintenance Dr / HDFC Bank Cr | 5,400 |
| V21 | 16-04 | Purchase | Furniture 22,000 + Input GST 3,960 Dr / Gupta Cr 25,960 (bill GW/229) | 25,960 |
| V22 | 17-04 | Payment | Gupta Dr / HDFC Bank Cr | 50,000 |
| V23 | 18-04 | Sales | Rahul Dr 82,600 / Sales Cr 70,000 + Output GST Cr 12,600 (INV-004) | 82,600 |
| V24 | 20-04 | Payment | Bank Charges Dr / HDFC Bank Cr | 590 |
| V25 | 21-04 | Receipt | HDFC Bank Dr / Rahul Cr | 1,00,000 |
| V26 | 22-04 | Payment | Office Expenses Dr / Cash Cr | 2,800 |
| V27 | 25-04 | Journal | Electricity Dr / Outstanding Expenses Cr (bill not yet paid) | 3,100 |
| V28 | 27-04 | Contra | Cash Dr / HDFC Bank Cr (cash withdrawn) | 10,000 |
| V29 | 28-04 | Sales | Meena Dr 35,400 / Sales Cr 30,000 + Output GST Cr 5,400 (INV-005) | 35,400 |
| V30 | 29-04 | Payment | Rent Dr / Cash Cr (godown rent booked in the wrong month) | 12,000 |
| REV | 30-04 | Reversal of V30 | Cash Dr 12,000 / Rent Cr 12,000 (swap of V30) | 12,000 |

Each voucher balances by itself: V02 2,00,000 + 36,000 = 2,36,000; V04 1,00,000 + 18,000 = 1,18,000;
V05 20,000 + 3,600 = 23,600; V06 50,000 + 9,000 = 59,000; V09 80,000 + 14,400 = 94,400;
V13 10,000 + 1,800 = 11,800; V14 10,000 + 1,800 = 11,800; V21 22,000 + 3,960 = 25,960;
V23 70,000 + 12,600 = 82,600; V29 30,000 + 5,400 = 35,400.

## 3. T-accounts (one per ledger)

### Cash (Cash-in-hand)
| Date | Voucher | Dr | Cr | Balance |
| --- | --- | ---: | ---: | ---: |
| 01-04 | Opening | 25,000 | | 25,000 Dr |
| 03-04 | V05 | 23,600 | | 48,600 Dr |
| 08-04 | V11 | | 4,200 | 44,400 Dr |
| 09-04 | V12 | | 20,000 | 24,400 Dr |
| 12-04 | V15 | | 1,500 | 22,900 Dr |
| 12-04 | V16 | | 2,300 | 20,600 Dr |
| 13-04 | V17 | 30,000 | | 50,600 Dr |
| 14-04 | V18 | | 3,600 | 47,000 Dr |
| 22-04 | V26 | | 2,800 | 44,200 Dr |
| 27-04 | V28 | 10,000 | | 54,200 Dr |
| 29-04 | V30 | | 12,000 | 42,200 Dr |
| 30-04 | REV (V30) | 12,000 | | 54,200 Dr |

Total Dr: 25,000 + 23,600 + 30,000 + 10,000 + 12,000 = 1,00,600. Total Cr: 4,200 + 20,000 + 1,500 + 2,300 + 3,600 + 2,800 + 12,000 = 46,400.
**Closing: 1,00,600 − 46,400 = 54,200 Dr.**

### HDFC Bank (Bank Accounts)
| Date | Voucher | Dr | Cr | Balance |
| --- | --- | ---: | ---: | ---: |
| 01-04 | Opening | 4,00,000 | | 4,00,000 Dr |
| 01-04 | V01 | 1,00,000 | | 5,00,000 Dr |
| 02-04 | V03 | | 25,000 | 4,75,000 Dr |
| 05-04 | V07 | 60,000 | | 5,35,000 Dr |
| 06-04 | V08 | | 45,000 | 4,90,000 Dr |
| 08-04 | V10 | | 35,000 | 4,55,000 Dr |
| 09-04 | V12 | 20,000 | | 4,75,000 Dr |
| 15-04 | V19 | | 15,000 | 4,60,000 Dr |
| 15-04 | V20 | | 5,400 | 4,54,600 Dr |
| 17-04 | V22 | | 50,000 | 4,04,600 Dr |
| 20-04 | V24 | | 590 | 4,04,010 Dr |
| 21-04 | V25 | 1,00,000 | | 5,04,010 Dr |
| 27-04 | V28 | | 10,000 | 4,94,010 Dr |

Total Dr: 4,00,000 + 1,00,000 + 60,000 + 20,000 + 1,00,000 = 6,80,000. Total Cr: 25,000 + 45,000 + 35,000 + 15,000 + 5,400 + 50,000 + 590 + 10,000 = 1,85,990.
**Closing: 6,80,000 − 1,85,990 = 4,94,010 Dr.**

### Opening Stock (Stock-in-hand) — no entries
Opening 1,50,000 Dr. **Closing 1,50,000 Dr.**

### Furniture (Fixed Assets)
Opening 40,000 Dr; V21 Dr 22,000 → **Closing 62,000 Dr.**

### Rahul Enterprises (Sundry Debtors)
| Date | Voucher | Dr | Cr | Balance |
| --- | --- | ---: | ---: | ---: |
| 01-04 | Opening | 60,000 | | 60,000 Dr |
| 03-04 | V04 | 1,18,000 | | 1,78,000 Dr |
| 05-04 | V07 | | 60,000 | 1,18,000 Dr |
| 10-04 | V13 | | 11,800 | 1,06,200 Dr |
| 18-04 | V23 | 82,600 | | 1,88,800 Dr |
| 21-04 | V25 | | 1,00,000 | 88,800 Dr |

Total Dr: 60,000 + 1,18,000 + 82,600 = 2,60,600. Total Cr: 60,000 + 11,800 + 1,00,000 = 1,71,800.
**Closing: 2,60,600 − 1,71,800 = 88,800 Dr.**

### Meena Traders (Sundry Debtors)
| Date | Voucher | Dr | Cr | Balance |
| --- | --- | ---: | ---: | ---: |
| 04-04 | V06 | 59,000 | | 59,000 Dr |
| 13-04 | V17 | | 30,000 | 29,000 Dr |
| 28-04 | V29 | 35,400 | | 64,400 Dr |

Total Dr: 59,000 + 35,400 = 94,400. Total Cr: 30,000. **Closing: 94,400 − 30,000 = 64,400 Dr.**

### Sharma Suppliers (Sundry Creditors)
| Date | Voucher | Dr | Cr | Balance |
| --- | --- | ---: | ---: | ---: |
| 01-04 | Opening | | 45,000 | 45,000 Cr |
| 02-04 | V02 | | 2,36,000 | 2,81,000 Cr |
| 06-04 | V08 | 45,000 | | 2,36,000 Cr |
| 11-04 | V14 | 11,800 | | 2,24,200 Cr |

Total Cr: 45,000 + 2,36,000 = 2,81,000. Total Dr: 45,000 + 11,800 = 56,800. **Closing: 2,81,000 − 56,800 = 2,24,200 Cr.**

### Gupta Wholesale (Sundry Creditors)
| Date | Voucher | Dr | Cr | Balance |
| --- | --- | ---: | ---: | ---: |
| 01-04 | Opening | | 30,000 | 30,000 Cr |
| 07-04 | V09 | | 94,400 | 1,24,400 Cr |
| 16-04 | V21 | | 25,960 | 1,50,360 Cr |
| 17-04 | V22 | 50,000 | | 1,00,360 Cr |

Total Cr: 30,000 + 94,400 + 25,960 = 1,50,360. Total Dr: 50,000. **Closing: 1,50,360 − 50,000 = 1,00,360 Cr.**

### Amit Verma Capital A/c (Capital Account)
Opening 6,00,000 Cr; V01 Cr 1,00,000 → **Closing 7,00,000 Cr.**

### Drawings A/c (Capital Account)
V19 Dr 15,000 → **Closing 15,000 Dr.**

### Purchases (Purchase Accounts)
V02 Dr 2,00,000; V09 Dr 80,000 → **Closing 2,80,000 Dr.**

### Purchase Returns (Purchase Accounts)
V14 Cr 10,000 → **Closing 10,000 Cr.**

### Sales (Sales Accounts)
| Voucher | Cr | Balance |
| --- | ---: | ---: |
| V04 | 1,00,000 | 1,00,000 Cr |
| V05 | 20,000 | 1,20,000 Cr |
| V06 | 50,000 | 1,70,000 Cr |
| V23 | 70,000 | 2,40,000 Cr |
| V29 | 30,000 | 2,70,000 Cr |

**Closing 2,70,000 Cr.**

### Sales Returns (Sales Accounts)
V13 Dr 10,000 → **Closing 10,000 Dr.**

### Output GST (Duties & Taxes)
| Voucher | Dr | Cr | Balance |
| --- | ---: | ---: | ---: |
| V04 | | 18,000 | 18,000 Cr |
| V05 | | 3,600 | 21,600 Cr |
| V06 | | 9,000 | 30,600 Cr |
| V13 | 1,800 | | 28,800 Cr |
| V23 | | 12,600 | 41,400 Cr |
| V29 | | 5,400 | 46,800 Cr |

Total Cr: 18,000 + 3,600 + 9,000 + 12,600 + 5,400 = 48,600. Total Dr: 1,800. **Closing: 48,600 − 1,800 = 46,800 Cr.**

### Input GST (Duties & Taxes)
| Voucher | Dr | Cr | Balance |
| --- | ---: | ---: | ---: |
| V02 | 36,000 | | 36,000 Dr |
| V09 | 14,400 | | 50,400 Dr |
| V14 | | 1,800 | 48,600 Dr |
| V21 | 3,960 | | 52,560 Dr |

Total Dr: 36,000 + 14,400 + 3,960 = 54,360. Total Cr: 1,800. **Closing: 54,360 − 1,800 = 52,560 Dr.**

### Outstanding Expenses (Current Liabilities)
V27 Cr 3,100 → **Closing 3,100 Cr.**

### Suspense A/c — no entries. **Closing nil.**

### Expense ledgers (Indirect Expenses)
| Ledger | Entries | Closing |
| --- | --- | ---: |
| Rent | V03 Dr 25,000; V30 Dr 12,000 (running 37,000); REV Cr 12,000 | **25,000 Dr** |
| Salary | V10 Dr 35,000 | **35,000 Dr** |
| Electricity | V11 Dr 4,200; V27 Dr 3,100 (4,200 + 3,100) | **7,300 Dr** |
| Telephone & Internet | V15 Dr 1,500 | **1,500 Dr** |
| Printing & Stationery | V16 Dr 2,300 | **2,300 Dr** |
| Travelling | V18 Dr 3,600 | **3,600 Dr** |
| Repairs & Maintenance | V20 Dr 5,400 | **5,400 Dr** |
| Bank Charges | V24 Dr 590 | **590 Dr** |
| Office Expenses | V26 Dr 2,800 | **2,800 Dr** |

## 4. Trial Balance as on 30 April 2026

| Ledger | Dr | Cr |
| --- | ---: | ---: |
| Cash | 54,200 | |
| HDFC Bank | 4,94,010 | |
| Opening Stock | 1,50,000 | |
| Furniture | 62,000 | |
| Rahul Enterprises | 88,800 | |
| Meena Traders | 64,400 | |
| Input GST | 52,560 | |
| Drawings A/c | 15,000 | |
| Purchases | 2,80,000 | |
| Sales Returns | 10,000 | |
| Rent | 25,000 | |
| Salary | 35,000 | |
| Electricity | 7,300 | |
| Telephone & Internet | 1,500 | |
| Printing & Stationery | 2,300 | |
| Travelling | 3,600 | |
| Repairs & Maintenance | 5,400 | |
| Bank Charges | 590 | |
| Office Expenses | 2,800 | |
| Sharma Suppliers | | 2,24,200 |
| Gupta Wholesale | | 1,00,360 |
| Amit Verma Capital A/c | | 7,00,000 |
| Purchase Returns | | 10,000 |
| Sales | | 2,70,000 |
| Output GST | | 46,800 |
| Outstanding Expenses | | 3,100 |
| Suspense A/c | nil | nil |
| **Total** | **13,54,460** | **13,54,460** |

Debit side added in two different ways:
- Running total in the order above: 54,200 + 4,94,010 = 5,48,210; + 1,50,000 = 6,98,210; + 62,000 = 7,60,210; + 88,800 = 8,49,010;
  + 64,400 = 9,13,410; + 52,560 = 9,65,970; + 15,000 = 9,80,970; + 2,80,000 = 12,60,970; + 10,000 = 12,70,970; + 25,000 = 12,95,970;
  + 35,000 = 13,30,970; + 7,300 = 13,38,270; + 1,500 = 13,39,770; + 2,300 = 13,42,070; + 3,600 = 13,45,670; + 5,400 = 13,51,070;
  + 590 = 13,51,660; + 2,800 = 13,54,460.
- By blocks: assets and receivables (54,200 + 4,94,010 + 1,50,000 + 62,000 + 88,800 + 64,400 + 52,560) = 9,65,970;
  expenses, purchases, drawings, returns (15,000 + 2,80,000 + 10,000 + 25,000 + 35,000 + 7,300 + 1,500 + 2,300 + 3,600 + 5,400 + 590 + 2,800) = 3,88,490;
  9,65,970 + 3,88,490 = **13,54,460**.

Credit side: 2,24,200 + 1,00,360 = 3,24,560; + 7,00,000 = 10,24,560; + 10,000 = 10,34,560; + 2,70,000 = 13,04,560;
+ 46,800 = 13,51,360; + 3,100 = **13,54,460**.

**Total debits = total credits = Rs 13,54,460.** The Trial Balance agrees.

## 5. The wrong vouchers (`invalid_vouchers.csv`)

Sixteen vouchers, each wrong in exactly one way. None of them may change the books above.

| Ref | Rule | What is wrong |
| --- | --- | --- |
| X01 | V-01 | Only one line |
| X02 | V-02 | A line with both a debit and a credit |
| X03 | V-03 | A negative amount |
| X04 | V-03 | An amount with three decimal places |
| X05 | V-04 | Debit 35,000.00 against credit 30,000.00 |
| X06 | V-05 | Ledger "Cash In Hand" does not exist |
| X07 | V-06 | Dated 02-04-2027, outside the financial year |
| X08 | V-07 | Dated 10-05-2026; May 2026 is locked (`locked_periods.csv`) |
| X09 | V-08 | A Journal that uses the bank |
| X10 | V-08 | A Contra that uses a customer ledger |
| X11 | V-08 | A Payment with cash and bank on both sides (should be a Contra) |
| X12 | V-09 | No narration |
| X13 | V-10 | Bill SS/0412 of Sharma Suppliers for 2,36,000 entered a second time |
| X14 | V-13 | Party ledger Rahul Enterprises is not in the lines |
| X15 | V-14 | Purchase without the supplier's bill number |
| X16 | V-14 | Debit Note without the original bill reference |
