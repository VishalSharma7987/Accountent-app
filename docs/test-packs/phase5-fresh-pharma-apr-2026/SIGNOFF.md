# Sign-off: Fresh Pharma Traders, Phase 5 Inventory pack (April 2026)

Fill this in after you have checked the pack by hand (WORKING.md and VERIFICATION_SHEET.xlsx). An unsigned pack is not a pass criterion.

| Item | Value |
| --- | --- |
| Pack folder | phase5-fresh-pharma-apr-2026 |
| Verified by (name, role) | |
| Date verified | YYYY-MM-DD |
| Method | e.g. stock cards on paper / Tally / Excel working |

## Checklist

- [ ] FIFO, weighted average periodic and weighted average moving each give the closing stock of WORKING.md (A 1,175.00 / 980.00 / 1,024.00; B 1,560.00 / 1,443.00 / 1,475.50)
- [ ] Sales return (Credit Note) comes back at the cost of the original sale; purchase return (Debit Note) goes out at the cost of the original purchase
- [ ] Transfer between godowns changes quantities by godown and no value
- [ ] Write-off (damage) carries a reason and is valued at the method's cost
- [ ] No negative stock: a sale, a transfer or a write-off above the quantity on hand (also per godown) is refused (S-01)
- [ ] AS 2: lower of cost and NRV item by item, write-down shown; an item without NRV is shown at cost with a warning
- [ ] Data is dummy / synthetic

## Questions for the accountant (Phase 5 sign-off questions)

1. **Returns valued at the original cost.** A sales return is brought back into stock at the unit cost of the sale it came from (A: 125.00 under FIFO, 128.00 moving, 122.50 periodic), and a purchase return leaves at the unit cost of the purchase it returns (B: 275.00). Is this the practice you follow, rather than the current average?
2. **Weighted average periodic windows chain.** For a report window that starts after the financial-year start, the opening of the window is the same method's valuation of "FY start to the day before" as one period. This pack is the first month, so it does not test the chaining. Do you accept chaining, or do you want each month averaged on its own?
3. **Valuation per item, not per godown.** Cost layers and averages are kept per item; godowns carry quantities only, so a transfer never changes value. Acceptable?
4. **Freight is not capitalised into stock.** Only the taxable value of the purchase line (plus GST that is blocked credit) is stock cost; freight inward and other direct costs are not spread over the items in Phase 5. Do you accept this for now?
5. **Purchase return presentation under weighted average periodic.** The purchase return is shown as an outward of 5 / 275.00 and reduces the pool before the average is worked (B average 55.50); a sales return reduces the period's outward quantity instead of showing as an inward (A outward 320, not 330). Is that how you present the stock register?

## Known limit reported to the owner (not for sign-off)

Reversing a sale puts its goods back as a new FIFO layer; reversing the original purchase afterwards is therefore still refused (S-17). Safe (no wrong cost) but a false block.
