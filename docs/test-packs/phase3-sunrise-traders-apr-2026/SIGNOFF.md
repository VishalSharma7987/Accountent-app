# Sign-off: Sunrise Traders, Phase 3 GST pack (April 2026)

Fill this in after you have checked the pack by hand (WORKING.md and VERIFICATION_SHEET.xlsx). An unsigned pack is not a pass criterion.

| Item | Value |
| --- | --- |
| Pack folder | phase3-sunrise-traders-apr-2026 |
| Verified by (name, role) | |
| Date verified | YYYY-MM-DD |
| Method | e.g. T-accounts on paper / Tally / Excel working |

## Checklist

- [ ] Every GSTIN in the pack is synthetic and its check character is right (or deliberately wrong in wrong_cases.csv)
- [ ] Tax of every item re-worked (intra-state CGST + SGST, inter-state IGST, half-up to the paisa); party amounts agree
- [ ] Blocked credit (P5) and reverse charge (P6) are booked the way your practice books them
- [ ] ITC statuses (expected_itc.csv) agree with the evidence, GSTR-2B result and Section 17(5)
- [ ] GSTR-2B classes (matched / value / GSTIN / other period / only in books / only in 2B) are right; the 2B file is a hand-made file, not a portal file
- [ ] GSTR-1 tables and HSN summary re-worked; documents issued agree with the voucher numbers
- [ ] GSTR-3B 3.1, 3.2, 4, 5, 6.1 re-worked; ITC utilisation order (Section 49) is left to you
- [ ] Tie-out: books = GSTR-1 = GSTR-3B for every head; Input ledgers = ITC register (reverse-charge credit included)
- [ ] 180-day days counted, unpaid share and the draft reversal journal checked
- [ ] Composition quarter (Sai Bakers) checked; rate and limit confirmed from the notification
- [ ] Every wrong case really is wrong, with the right rule

## Legal values still PENDING (the CA must confirm before this pack is a legal pass)

HSN/SAC rate rows are examples; default services rate 18% (GTA freight and gym membership use it); the GTA reverse-charge category; Section 17(5) club / fitness clause; the 180-day rule and what counts as payment; B2C-large limit 2,50,000; composition rate 1% and limit 1.5 crore; GSTR-1 and GSTR-3B table numbers. The GSTR-2B JSON shape is not verified against a portal file.

## Notes / disagreements with the tool

(write anything unusual here)

## Result

- [ ] Approved
- [ ] Approved with changes (list them above)
- [ ] Rejected

Signature: ______________________   Date: ____________
