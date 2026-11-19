# Sign-off: Phase 6 pack (period-end and final accounts), FY 2026-27

Fill this in after you have checked the pack by hand (WORKING.md and VERIFICATION_SHEET.xlsx). An unsigned pack is not a pass criterion. The three clients are dummy / synthetic.

| Item | Value |
| --- | --- |
| Pack folder | phase6-full-year-accounts-2026-27 (proprietor, partnership, company) |
| Verified by (name, role) | |
| Date verified | YYYY-MM-DD |
| Method | e.g. Tally / Excel working / paper |

## Checklist

- [ ] Proprietor: adjustments (outstanding rent 5,000; prepaid electricity 2,000; accrued interest 1,200; rent in advance 3,000; bad debt 10,000; provision 5 percent on 2,40,000 = 12,000) give the Trial Balance of WORKING.md section 1.6 (Dr = Cr = 20,92,546.57)
- [ ] Proprietor: Companies Act depreciation FU-1 10,000.00, PM-1 3,157.99, PM-2 1,188.58 (total 14,346.57); income-tax blocks: furniture 9,000.00; plant and machinery 18,750.00 with the 137-day addition at half rate
- [ ] Proprietor: Trading A/c gross profit 4,10,000; P&L net profit 1,79,853.43; Balance Sheet 9,17,853.43 (horizontal) and 5,99,853.43 (vertical); Cash Flow net increase 51,000.00 (closing 2,01,000)
- [ ] Proprietor: year-end close vouchers, carried openings (Dr = Cr = 9,44,200.00) and income-tax blocks carried (81,000.00 and 1,31,250.00); reopen and close again give the same figures
- [ ] Partnership: interest on capital 30,000.00 / 22,493.15 (day-weighted), interest on drawings 4,188.49 / 3,284.38, remuneration 60,000.00 / 24,000.00 (6 of 12 months); balance to share 2,95,979.72 -> 1,77,587.83 and 1,18,391.89; Balance Sheet 8,80,000.00
- [ ] Company: Schedule III Balance Sheet 10,63,717.54 and profit 1,25,980.55 with the previous-year column from the signed-off FY 2025-26 (9,37,736.99 and 1,84,736.99); 15 notes; Cash Flow net decrease (2,89,500.00)
- [ ] Company: FY 2025-26 close carries 9,52,000.00 into FY 2026-27 (stock 1,10,000 and income-tax WDV 2,55,000 included); reopening FY 2025-26 is refused while FY 2026-27 has postings
- [ ] Data is dummy / synthetic; nothing from a real client

## Questions for the CA / accountant (readings the tool made; each is in docs/decisions_parts/*6.md)

1. **Debtors base of the provision for doubtful debts.** The base is the sum of the DEBIT balances of Sundry Debtors ledgers on the date after bad debts (credit balances are advances, not netted); the rate is the accountant's (5 percent here). Result 12,000.00 on 2,40,000. Is this your practice (and is a rate on total debtors acceptable, rather than ageing)?
2. **Interest on capital and on drawings.** Capital: only the CREDIT balance of the partner's capital ledger earns interest, day-weighted by balance segments (a mid-year introduction counts from its voucher date, both days). Drawings: each drawing from its voucher date to 31 March, both days counted, rate over 365 days, only the drawings ledger's debits, opening balance ignored. Interest is credited / charged to the partner's CURRENT account. Is this the basis of your deeds? (No income-tax limit such as section 40(b) is applied; the tool shows the deed values.)
3. **Remuneration for part of a year.** Annual figure x months / 12 (Rakesh 48,000 x 6 / 12 = 24,000.00). Fine?
4. **Profit sharing.** The balance after interest and remuneration is shared in the ratio; each partner but the last gets the rounded share, the last takes the remainder so the shares add up exactly. Do you want a different rule for the rounding paisa?
5. **Companies Act depreciation.** Straight line from the put-to-use date, both days counted, over the days of the financial year; a later addition is its own tranche with the same residual percentage; the life is the Schedule II class life. Is the day count and the tranche rule your practice? Is the 5 percent residual acceptable?
6. **Income-tax half rate.** An addition put to use for FEWER than 180 days gets half the block rate (137 days: half; 182 days: full); days counted from the put-to-use date to 31 March, both days. Confirm the 180 days, the 50 percent and the counting. The disposal case (deficit against the half-rate additions) is built but not exercised in this pack.
7. **Cash-flow classification.** Interest income is classed investing by the accountant's classification; interest paid by a company is financing (Schedule III line default); depreciation is added back through the accumulated-depreciation ledger; working capital by ledger group; drawings and partners' accounts are financing; a firm starts from profit BEFORE appropriation and deducts interest and remuneration credited to partners (non-cash). Do you agree? Tax paid and dividends are not exercised.
8. **Closing stock source.** Approved by the accountant (manual here, cost less AS 2 write-down); the Phase 5 inventory report is the other source. Nothing is guessed: a missing approval blocks every statement and the close. For a service firm "none" is recorded. Is the manual approval with a basis note acceptable for the clients that do not use the inventory module?
9. **Drawings ledger identification.** The year-end close moves a proprietor's drawings to capital only for a Capital Account ledger whose NAME contains "drawing", and the profit goes to the ONE other Capital Account ledger. For interest on drawings the accountant names the partner's drawings ledger on the entry. Would you rather have an explicit "drawings" role on the ledger?
10. **Statements exclude the closing vouchers.** After the year-end close the Trading A/c, P&L and Balance Sheet of that year still show the year's trading and profit (the closing journals only move the ledgers and the next year's openings). Do you want the closed year to show the transfer entries instead?
11. **One stock ledger.** The trading closing entry brings the closing stock into the stock ledger, so next year's opening stock is the carried closing stock (carrying value, after the write-down). Fine?
12. **Schedule III classification.** Salary, depreciation, interest, term loan, outstanding and prepaid ledgers are classified by the accountant (the tool warns on every group default and refuses to guess loans, investments and deposits). Is the classification of this pack right? No tax provision, dividend or reserve transfer is in Phase 6.

## Pending legal values (nothing in this pack is `verified`; docs/PHASE6_LEGAL_VALUES.md)

- Income-tax block rates and the half-rate rule for FY 2026-27 are Income-tax Act 2025 rows with status `pending` (section / schedule numbers unknown). The FY 2025-26 plant and machinery 15 percent and the 180 days / 50 percent are `secondary_verified` only (secondary web pages), not read from the Act.
- Schedule II useful lives (furniture 10, plant and machinery 15 years) and the 5 percent residual ceiling are `pending`.
- Schedule III line items and the group defaults are `pending`.
- Please confirm each against the Income-tax Rules / Act and the Companies Act before the output is used for a real client.

## Known limits reported to the owner (not for sign-off)

- Asset disposal, terminal and additional depreciation, tax provision, dividend and Ind AS are outside this phase and are not in the pack. Open bills and bill-wise carry-forward are covered by the Phase 2 pack, not repeated here.
