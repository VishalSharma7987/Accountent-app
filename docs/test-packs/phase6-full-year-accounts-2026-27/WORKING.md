# Phase 6 pack: hand workings (period-end and final accounts)

Dummy, synthetic clients. Every figure below was worked by hand and typed into the `expected_*.csv` files; the tool is never used to produce an expected value. The unit self-check (`backend/tests/acceptance/test_pack_p6_selfcheck.py`) re-adds the pack's own openings, vouchers and adjustment lines with plain Decimal arithmetic and compares them with the typed files (this caught three slips of the first draft of this working: interest on drawings 4,188.55 -> 4,188.49, depreciation of PM-2 1,188.63 -> 1,188.58, and one voucher too many). Amounts are GST-exclusive; no GST ledgers are used (Phase 3 is not in scope here).

Rule status used (law is data, `docs/PHASE6_LEGAL_VALUES.md`): **nothing is `verified`**. Schedule II useful life 10 years (furniture and fittings) and 15 years (plant and machinery general), residual up to 5 percent: seed 0012, status `pending`. Income-tax block rates: 10 percent (furniture and fittings) and 15 percent (plant and machinery general). For FY 2025-26 they are the Income-tax Act 1961 rows (plant and machinery 15 percent `secondary_verified`; half-rate 180 days / 50 percent `secondary_verified`). For FY 2026-27 they are the Income-tax Act 2025 rows: every one `pending`. Every figure of the income-tax working carries that status. Deed values (profit ratio, interest rates, remuneration) are agreement terms with a deed reference, not law.

Day counts: both days counted. FY 2026-27 has 365 days; FY 2025-26 has 365 days. Rounding: `ROUND_HALF_UP` to 2 places, once per figure.

---------------------------------------------------------------------------------------------------------------------------------------

## 1. Ramesh Hardware Traders (trading proprietorship), FY 2026-27

### 1.1 Opening balances 01-04-2026 (Dr 6,00,000 = Cr 6,00,000)
Dr: Opening Stock 2,00,000; Furniture and Fixtures 1,00,000; Anand Traders 60,000; Bhatia and Sons 50,000; Chopra Stores 40,000; Cash 30,000; HDFC Bank 1,20,000. Cr: Capital 5,00,000; Sharma Suppliers 50,000; Yadav Wholesale 30,000; Bank Loan 20,000.

### 1.2 Year's totals from the 50 vouchers (Trial Balance before adjustments, Dr = Cr = 20,60,000)
Purchases 8,00,000 (credit 7,50,000, cash 50,000); purchase return 10,000 (debit note); sales 12,00,000 (credit 10,50,000, cash 1,50,000); sales return 20,000 (credit note); freight inward 30,000; salary 1,20,000; rent 55,000 (April to February); electricity 20,000; telephone 12,000; bank charges 2,000; drawings 1,00,000; two machines on credit from Kay Engineering 1,00,000 and 50,000.
Debtors: Anand 60,000 + 4,00,000 - 20,000 - 3,40,000 = 1,00,000; Bhatia 50,000 + 3,50,000 - 3,20,000 = 80,000; Chopra 40,000 + 3,00,000 - 2,70,000 = 70,000 (total 2,50,000).
Creditors: Sharma 50,000 + 5,00,000 - 4,20,000 = 1,30,000; Yadav 30,000 + 2,50,000 - 10,000 - 1,90,000 = 80,000; Kay 1,50,000 - 50,000 = 1,00,000.
Cash 30,000 + 1,50,000 - 50,000 - 30,000 - 75,000 (deposited, contra) = 25,000. Bank 1,20,000 + 9,30,000 (debtors) + 75,000 + 5,000 (interest) + 15,000 (rent received) - 6,60,000 (creditors) - 1,20,000 - 55,000 - 20,000 - 12,000 - 2,000 - 1,00,000 = 1,76,000.

### 1.3 Adjustments (Journals dated 31-03-2027, rules F-01 to F-11)
| Ref | Entry | Working |
| --- | --- | --- |
| A1 outstanding rent | Dr Rent 5,000 / Cr Outstanding Expenses 5,000 | March rent not paid (F-03) |
| A2 prepaid electricity | Dr Prepaid Expenses 2,000 / Cr Electricity 2,000 | bill of 10-03-2027 covers 15-03 to 14-04 (F-03) |
| A3 accrued income | Dr Accrued Income 1,200 / Cr Interest Income 1,200 | (F-03) |
| A4 income in advance | Dr Rent Received 3,000 / Cr Income Received in Advance 3,000 | April 2027 rent received in March (F-03) |
| A5 bad debt | Dr Bad Debts 10,000 / Cr Chopra Stores 10,000 | Chopra balance 70,000 is at least 10,000 (F-06) |
| A6 provision | Dr Provision for Doubtful Debts Expense 12,000 / Cr Provision for Doubtful Debts 12,000 | debit balances of debtors after the bad debt: 1,00,000 + 80,000 + 60,000 = 2,40,000; 5 percent = 12,000.00; existing provision 0 (F-05) |
| A7 depreciation | Dr Depreciation 14,346.57 / Cr Accumulated Depreciation 14,346.57 | section 1.4 (F-23, F-26) |

### 1.4 Fixed assets and depreciation
Companies Act (straight line, Schedule II lives from seed 0012, status `pending`): `(cost - residual) x days / (life x days in year)`.
| Asset | Cost | Residual | Life | Put to use | Days | Depreciation |
| --- | --- | --- | --- | --- | --- | --- |
| FU-1 furniture (opening event) | 1,00,000 | 0 | 10 | 01-04-2026 | 365 | 1,00,000 / 10 = 10,000.00 |
| PM-1 packing machine | 1,00,000 | 5,000 | 15 | 01-10-2026 | 182 | 95,000 x 182 / 5,475 = 3,157.99 (3,157.9909) |
| PM-2 sealing machine | 50,000 | 2,500 | 15 | 15-11-2026 | 137 | 47,500 x 137 / 5,475 = 1,188.58 (1,188.5845) |
Total 14,346.57. Net block: 90,000 + 96,842.01 + 48,811.42 = 2,35,653.43.
Income tax (a working only, no voucher; rate 10 and 15 percent, 2025-Act rows, `pending`):
- Furniture and fittings (10 percent): opening WDV typed 90,000.00 (the income-tax value brought forward). Depreciation 90,000 x 10 percent = 9,000.00. Closing WDV 81,000.00.
- Plant and machinery (15 percent): opening WDV 0.00. PM-1 put to use 01-10-2026 = 182 days, which is 180 or more: full rate. PM-2 put to use 15-11-2026 = 137 days, fewer than 180: **half rate**. Full base 1,00,000 x 15 percent = 15,000.00; half base 50,000 x 15 percent x 50 percent = 3,750.00. Depreciation 18,750.00. Closing WDV 1,50,000 - 18,750 = 1,31,250.00.

### 1.5 Closing stock (F-41)
Approved manually as on 31-03-2027: cost 2,60,000, write-down to net realisable value (AS 2) 10,000, carrying value 2,50,000. (The Phase 5 inventory report is the other source; the Phase 5 pack covers it.)

### 1.6 Trial Balance after the adjustments (Dr = Cr = 20,92,546.57)
Dr: Opening Stock 2,00,000; Purchases 8,00,000; Sales Returns 20,000; Freight Inward 30,000; Salary 1,20,000; Rent 60,000; Electricity 18,000; Telephone and Internet 12,000; Bank Charges 2,000; Bad Debts 10,000; Provision Expense 12,000; Depreciation 14,346.57; Drawings 1,00,000; Furniture 1,00,000; Plant and Machinery 1,50,000; Anand 1,00,000; Bhatia 80,000; Chopra 60,000; Prepaid 2,000; Accrued Income 1,200; Cash 25,000; Bank 1,76,000.
Cr: Capital 5,00,000; Bank Loan 20,000; Sharma 1,30,000; Yadav 80,000; Kay 1,00,000; Sales 12,00,000; Purchase Returns 10,000; Interest Income 6,200; Rent Received 12,000; Outstanding Expenses 5,000; Income Received in Advance 3,000; Provision for Doubtful Debts 12,000; Accumulated Depreciation 14,346.57.

### 1.7 Trading A/c (F-42), P&L (F-43), Balance Sheet
Trading: Dr opening stock 2,00,000 + purchases 8,00,000 + sales returns 20,000 + freight 30,000 + gross profit 4,10,000 = 14,60,000. Cr sales 12,00,000 + purchase returns 10,000 + closing stock 2,50,000 = 14,60,000.
P&L: Dr salary 1,20,000 + rent 60,000 + electricity 18,000 + telephone 12,000 + bank charges 2,000 + depreciation 14,346.57 + bad debts 10,000 + provision 12,000 = 2,48,346.57; net profit 1,79,853.43. Cr gross profit 4,10,000 + interest income 6,200 + rent received 12,000 = 4,28,200. (2,48,346.57 + 1,79,853.43 = 4,28,200.00.)
Balance Sheet, horizontal. Liabilities: Capital 5,00,000 - drawings 1,00,000 + profit 1,79,853.43 = 5,79,853.43; Bank Loan 20,000; Sundry Creditors 3,10,000; Income Received in Advance 3,000; Outstanding Expenses 5,000. Total 9,17,853.43. Assets: Fixed Assets 2,50,000 - 14,346.57 = 2,35,653.43; Closing stock 2,50,000; Bank 1,76,000; Cash 25,000; Sundry Debtors 2,40,000 - 12,000 = 2,28,000; Accrued Income 1,200; Prepaid 2,000. Total 9,17,853.43.
Vertical: Sources of funds Capital 5,79,853.43 + Bank Loan 20,000 = 5,99,853.43. Application: Fixed Assets 2,35,653.43 + net current assets 3,64,200 (current assets 6,82,200 less current liabilities 3,18,000) = 5,99,853.43.

### 1.8 Cash Flow (AS 3, indirect, F-49, F-50)
Interest income is classed "investing" by the accountant (ledger classification). Operating: net profit 1,79,853.43 - interest income 6,200 + depreciation 14,346.57 = 1,88,000.00; stock increase (50,000); debtors net increase (78,000); creditors +2,30,000; current liabilities +8,000; current assets (3,200) -> **2,94,800.00**. Investing: machines (1,50,000) + interest 6,200 = (1,43,800). Financing: drawings (1,00,000). Net increase **51,000.00**; opening cash and bank 1,50,000; closing 2,01,000 = cash 25,000 + bank 1,76,000 (F-50 ties).

### 1.9 Year-end close (F-63), carry-forward (F-65), reopen (F-64)
Voucher 1 trading: Dr Sales 12,00,000, Purchase Returns 10,000, Stock ledger 50,000 (closing 2,50,000 less opening 2,00,000); Cr Purchases 8,00,000, Sales Returns 20,000, Freight 30,000, Trading Account 4,10,000 (12,60,000 each side). Voucher 2: Dr Trading Account 4,10,000, Interest Income 6,200, Rent Received 12,000; Cr the eight expense ledgers 2,48,346.57, Profit and Loss Account 1,79,853.43 (4,28,200 each side). Voucher 3: Dr Profit and Loss Account 1,79,853.43; Cr Drawings 1,00,000, Capital 79,853.43.
Carried to 01-04-2027 (Dr = Cr = 9,44,200.00): Dr Furniture 1,00,000; Plant and Machinery 1,50,000; Anand 1,00,000; Bhatia 80,000; Chopra 60,000; Stock 2,50,000; Prepaid 2,000; Accrued 1,200; Cash 25,000; Bank 1,76,000. Cr Capital 5,79,853.43; Bank Loan 20,000; Sharma 1,30,000; Yadav 80,000; Kay 1,00,000; Outstanding 5,000; Income in Advance 3,000; Provision 12,000; Accumulated Depreciation 14,346.57. Income-tax blocks carried: furniture 81,000.00, plant and machinery 1,31,250.00.
Reopen: three reversal vouchers, periods unlocked, next year's openings removed, ledger balances back to section 1.6; close again gives the same carried openings.

---------------------------------------------------------------------------------------------------------------------------------------

## 2. Sharma and Verma Associates (service partnership, ratio 3:2), FY 2026-27

### 2.1 Opening 01-04-2026 (Dr 5,30,000 = Cr 5,30,000)
Dr HDFC Bank 4,20,000; Client Alpha 1,10,000. Cr Anil Sharma Capital 3,00,000; Rakesh Verma Capital 2,00,000; Vendor Z 30,000. Deed (reference "Partnership deed dated 01-04-2020 clause 7"): profit 60 : 40; interest on capital 10 percent; interest on drawings 12 percent; remuneration Anil 60,000 a year, Rakesh 48,000 a year paid for 6 months.
### 2.2 Year's totals (Trial Balance before adjustments, Dr = Cr = 14,60,000)
Fees: billed to Alpha 6,00,000, direct 3,00,000 (service income 9,00,000). Receipts from Alpha 6,10,000 (Alpha closes at 1,00,000). Rakesh brings in 50,000 capital on 01-10-2026. Expenses: salary 2,40,000, rent 1,20,000, electricity 30,000, telephone 24,000, office 40,000, printing 6,000. Vendor Z paid 20,000 (closes at 10,000 Cr). Drawings: Anil 20,000 on 01-05, 01-09, 01-01; Rakesh 30,000 on 01-07 and 01-02. Bank 4,20,000 + 3,00,000 + 6,10,000 + 50,000 - 4,60,000 - 20,000 - 1,20,000 = 7,80,000.
### 2.3 Adjustments (F-07, F-08)
- Audit fees outstanding 15,000 (Dr Audit Fees / Cr Outstanding Expenses).
- Interest on capital (day-weighted, 365 days, rate 10 percent): Anil 3,00,000 x 365 -> 30,000.00. Rakesh: 2,00,000 for 01-04 to 30-09 (183 days) + 2,50,000 for 01-10 to 31-03 (182 days) = 3,66,00,000 + 4,55,00,000 = 8,21,00,000 x 10 percent / 365 = 22,493.15. Dr Interest on Capital, Cr the partner's Current A/c.
- Interest on drawings (each draw from its date to 31-03, both days counted, rate 12 percent): Anil: 20,000 x (335 + 212 + 90 = 637 days) = 1,27,40,000 x 12 percent / 365 = 4,188.49 (4,188.4932). Rakesh: 30,000 x (274 + 59 = 333 days) = 99,90,000 x 12 percent / 365 = 3,284.38 (3,284.3836). Dr the partner's Current A/c, Cr Interest on Drawings. Total 7,472.87.
- Remuneration: Anil 60,000 x 12 / 12 = 60,000.00; Rakesh 48,000 x 6 / 12 = 24,000.00. Dr Partners Remuneration, Cr Current A/c. Total 84,000.
### 2.4 Statements
Trading: service income 9,00,000 (gross profit 9,00,000; no stock: closing stock "none" is recorded for a service business). P&L: expenses 2,40,000 + 1,20,000 + 30,000 + 24,000 + 40,000 + 6,000 + 15,000 = 4,75,000; **net profit before appropriation 4,25,000**.
Appropriation: Dr interest on capital 52,493.15 + remuneration 84,000 = 1,36,493.15; Cr net profit 4,25,000 + interest on drawings 7,472.87. Balance to share 4,25,000 + 7,472.87 - 52,493.15 - 84,000 = **2,95,979.72**. Anil 60 percent = 1,77,587.832 -> 1,77,587.83; Rakesh (last partner, remainder) 2,95,979.72 - 1,77,587.83 = 1,18,391.89 (F-62). Total each side 4,32,472.87.
Balance Sheet: Anil Capital 3,00,000; Anil Current 30,000 + 60,000 - 4,188.49 = 85,811.51; Anil Drawings (60,000); Rakesh Capital 2,50,000; Rakesh Current 22,493.15 + 24,000 - 3,284.38 = 43,208.77; Rakesh Drawings (60,000); profit shares 1,77,587.83 + 1,18,391.89; Sundry Creditors 10,000; Outstanding Expenses 15,000. Total 8,80,000.00. Assets: Bank 7,80,000 + Debtors 1,00,000 = 8,80,000. Vertical: sources 8,55,000 = application 8,55,000 (current assets 8,80,000 less current liabilities 25,000).
### 2.5 Cash Flow
Net profit before appropriation 4,25,000; less interest and remuneration credited to partners (52,493.15 + 84,000 - 7,472.87) 1,29,020.28; debtors +10,000; creditors (20,000); outstanding +15,000 -> operating 3,00,979.72. Financing: partners' accounts 85,811.51 + 50,000 + 43,208.77 - 1,20,000 = 59,020.28. Net increase 3,60,000; opening 4,20,000; closing 7,80,000.
### 2.5 Close and carry-forward
Voucher 1: Dr Service Income 9,00,000 / Cr Trading Account 9,00,000. Voucher 2: Dr Trading Account 9,00,000 and Interest on Drawings 7,472.87; Cr the seven expense ledgers 4,75,000, Interest on Capital 52,493.15, Remuneration 84,000, Profit and Loss Account 2,95,979.72. Voucher 3: Dr Profit and Loss 2,95,979.72; Cr Anil Current 1,77,587.83, Rakesh Current 1,18,391.89. Carried (Dr = Cr = 10,00,000): Dr Bank 7,80,000, Alpha 1,00,000, the two drawings ledgers 60,000 each; Cr Anil Capital 3,00,000, Anil Current 2,63,399.34, Rakesh Capital 2,50,000, Rakesh Current 1,61,600.66, Vendor Z 10,000, Outstanding 15,000. Drawings are not closed to capital for a firm (they stay as debit balances).

---------------------------------------------------------------------------------------------------------------------------------------

## 3. Orion Trading Company Private Limited (company, Schedule III), FY 2025-26 (closed in the pack) and FY 2026-27

### 3.1 FY 2025-26
Opening: Dr HDFC Bank 5,00,000 / Cr Share Capital 5,00,000. Year: purchases 4,50,000 (paid 4,00,000; Supplier S1 closes 50,000 Cr); term loan 2,00,000 received on 01-06-2025; plant 3,00,000 bought and put to use 01-07-2025; sales 7,00,000 (Delta 4,00,000 received in full; Echo 3,00,000 less 2,50,000 received = 50,000); salary 1,20,000; rent 33,000 (+ 3,000 outstanding, adjustment A1); interest on term loan 8,000; interest income 4,000; bank charges 1,000. Bank 5,00,000 - 4,00,000 + 2,00,000 - 3,00,000 + 4,00,000 + 2,50,000 - 1,20,000 - 33,000 - 8,000 + 4,000 - 1,000 = 4,92,000.
Depreciation (A2, Schedule II 15 years, residual 5 percent = 15,000, `pending`): 2,85,000 x 274 / 5,475 = 14,263.01 (14,263.0137); days 01-07-2025 to 31-03-2026 = 274. Income tax (1961 Act rows, 15 percent, `secondary_verified`): opening WDV 0.00; the addition has 274 days (full rate); depreciation 3,00,000 x 15 percent = 45,000.00; closing WDV 2,55,000.00 (carried).
Closing stock: cost 1,20,000, write-down 10,000, carrying 1,10,000.
Schedule III: Revenue 7,00,000; other income 4,000; expenses: purchases 4,50,000, change in inventories (1,10,000), employee benefits 1,20,000, finance costs 8,000, depreciation 14,263.01, other expenses (rent 36,000 + bank charges 1,000) 37,000 = 5,19,263.01; **profit 1,84,736.99** (no tax provision: outside Phase 6). Balance Sheet: share capital 5,00,000; reserves and surplus 1,84,736.99; long-term borrowings 2,00,000; trade payables 50,000; other current liabilities 3,000 = **9,37,736.99**. Assets: PPE 3,00,000 - 14,263.01 = 2,85,736.99; inventories 1,10,000; trade receivables 50,000; cash 4,92,000 = 9,37,736.99.
Close: Dr Sales 7,00,000, Stock 1,10,000; Cr Purchases 4,50,000, Trading Account 3,60,000. Dr Trading Account 3,60,000, Interest Income 4,000; Cr salary, rent, interest, bank charges, depreciation 1,79,263.01, Profit and Loss Account 1,84,736.99. Dr Profit and Loss 1,84,736.99 / Cr Surplus in Profit and Loss 1,84,736.99. Carried (Dr = Cr = 9,52,000): Bank 4,92,000, Echo 50,000, Plant 3,00,000, Stock 1,10,000; Share Capital 5,00,000, Surplus 1,84,736.99, Term Loan 2,00,000, Supplier S1 50,000, Outstanding 3,000, Accumulated Depreciation 14,263.01. Income-tax block carried: 2,55,000.00.

### 3.2 FY 2026-27 (opening = the carry-forward above)
Year: purchases 9,00,000 (paid 8,50,000; S1 closes 1,00,000); sales 13,00,000 (Delta 5,00,000 + 4,00,000 less 6,00,000 received = 3,00,000; Echo 50,000 + 4,00,000 - 4,00,000 = 50,000); plant addition 1,20,000 put to use 01-12-2026; salary 1,80,000; rent 33,000 (including the settled 3,000 of March 2026); electricity 24,000; telephone 9,000; office 12,000 (2,000 prepaid, adjustment B2); bank charges 1,500; interest on term loan 12,000; interest income 5,000; term loan repaid 50,000; March rent outstanding 3,000 (B1). Bank 4,92,000 + 10,05,000 - 12,94,500 = 2,02,500.
Depreciation (B3): first tranche 2,85,000 / 15 x 365/365 = 19,000.00; the addition is its own tranche with the same residual percentage (residual 1,20,000 x 15,000 / 3,00,000 = 6,000): 1,14,000 x 121 / 5,475 = 2,519.45 (2,519.4521; 121 days 01-12-2026 to 31-03-2027). Total 21,519.45; accumulated 14,263.01 + 21,519.45 = 35,782.46; net block 4,20,000 - 35,782.46 = 3,84,217.54. Income tax (2025-Act rows, `pending`): opening WDV 2,55,000 (carried); the addition has 121 days (half rate): 2,55,000 x 15 percent = 38,250.00 + 1,20,000 x 15 percent x 50 percent = 9,000.00 = 47,250.00; closing WDV 3,27,750.00.
Closing stock: cost 1,30,000, write-down 5,000, carrying 1,25,000.
Schedule III P&L: revenue 13,00,000 (previous 7,00,000); other income 5,000; expenses: purchases 9,00,000; change in inventories 1,10,000 - 1,25,000 = (15,000); employee benefits 1,80,000; finance costs 12,000; depreciation 21,519.45; other expenses (rent 36,000 + electricity 24,000 + telephone 9,000 + office 10,000 + bank charges 1,500) 80,500; total 11,79,019.45. **Profit 1,25,980.55.**
Balance Sheet: share capital 5,00,000; reserves and surplus 1,84,736.99 + 1,25,980.55 = 3,10,717.54; long-term borrowings 1,50,000; trade payables 1,00,000; other current liabilities 3,000 = **10,63,717.54**. Assets: PPE 3,84,217.54; inventories 1,25,000; trade receivables 3,50,000; cash 2,02,500; other current assets (prepaid) 2,000 = 10,63,717.54. The previous-year column is the signed-off snapshot of FY 2025-26 (figures in the table of section 3.1); a line new in the year (other current assets) shows 0.00 before.
Notes: 15 numbered notes (balance sheet lines first, then profit and loss lines); the PPE note comes from the register (gross block opening 3,00,000, additions 1,20,000, closing 4,20,000; accumulated depreciation 14,263.01 + 21,519.45 = 35,782.46; net block 3,84,217.54); the inventory note shows cost 1,30,000 less write-down 5,000.
Cash Flow: profit before tax 1,25,980.55 + interest paid 12,000 (shown under financing) + depreciation 21,519.45 = 1,59,500.00; inventories (15,000); trade receivables (3,00,000); trade payables +50,000; other current assets (2,000) -> operating (1,07,500.00). Investing: plant (1,20,000). Financing: loan repaid (50,000) and interest (12,000) = (62,000). Net decrease (2,89,500.00); opening 4,92,000; closing 2,02,500 = bank (F-50 ties; required for a company).
Reopen of FY 2025-26: refused (`reopen_blocked`, F-64) because FY 2026-27 has posted vouchers.
