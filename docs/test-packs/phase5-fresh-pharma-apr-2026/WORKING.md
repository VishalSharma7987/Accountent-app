# Fresh Pharma Traders, April 2026: hand workings (Phase 5, Inventory)

Dummy client (proprietorship, trading), synthetic data. Every figure was worked by hand and typed into the `expected_*.csv` files; the tool is never used to produce an expected value. Three clients run the SAME month, one per valuation method (the method is frozen once a year has movements): **FIFO**, **weighted average periodic**, **weighted average moving**. Window of every report: 01-04-2026 to 30-04-2026 (the first month of the year, so the month window is also the financial-year window). Goods are HSN 3004, unit NOS, IGST 5% (example row of the rule table) and all parties are in Karnataka; GST is recoverable input credit / output tax and is **not** part of stock cost (S-14), so cost = quantity x rate.

Rules of the working (docs/PHASE5_PLAN.md): valuation per item, not per godown; transfers never change value; a sales return comes back at the unit cost of the sale it refers to; a purchase return goes out at the unit cost of the purchase it refers to; an outward that takes the last unit of a layer / of the item takes the whole remaining value; every cost rounded half up to 2 places.

## Opening stock 01-04-2026 (all in godown Main)
| Item | Qty | Value | Rate |
| --- | --- | --- | --- |
| A Paracetamol 500 strip | 100 | 1,000.00 | 10.00 |
| B Cough Syrup 100ml | 40 | 2,000.00 | 50.00 |
| C Vitamin C 500 strip | 10 | 1,000.00 | 100.00 |

Total 4,000.00. C has no movement and no NRV entered.

## Movements (same for the three clients)
| Date | Ref / number | What | Item | Qty | Rate / amount |
| --- | --- | --- | --- | --- | --- |
| 05-04 | P-A1 PUR/0001 | Purchase | A | 200 | 12.00 = 2,400.00 |
| 06-04 | P-B1 PUR/0002 | Purchase | B | 60 | 55.00 = 3,300.00 |
| 10-04 | S-A1 SAL/0001 | Sale | A | 150 | sale price 20.00 (price is not stock cost) |
| 12-04 | S-B1 SAL/0002 | Sale | B | 50 | 80.00 |
| 14-04 | DN-B DBN/0001 | **Debit Note (purchase return)** of P-B1 | B | 5 | at the cost of P-B1 |
| 15-04 | P-A2 PUR/0003 | Purchase | A | 100 | 15.00 = 1,500.00 |
| 18-04 | P-B2 PUR/0004 | Purchase | B | 55 | 60.00 = 3,300.00 |
| 20-04 | S-A2 SAL/0003 | Sale | A | 180 | 22.00 |
| 22-04 | CN-A CRN/0001 | **Credit Note (sales return)** of S-A2, back into Main | A | 10 | at the cost of S-A2 |
| 24-04 | W-1 SJ/0001 | **Write-off** (damage, reason stored) from Main | B | 4 | at the method's cost |
| 25-04 | T-1 SJ/0002 | **Transfer** Main to Shop | A | 20 | no value change |
| 26-04 | S-B2 SAL/0004 | Sale | B | 70 | 85.00 |

Closing quantities (same in all methods). A: 100 + 200 - 150 + 100 - 180 + 10 = **80** (Main 60 after the transfer, Shop 20). B: 40 + 60 - 50 - 5 + 55 - 4 - 70 = **26** (Main). C: **10**.
Chronology check (S-01): A in Main never below 0 (lowest 100 + 200 - 150 = 150 after S-A1); B lowest 40 + 60 - 50 - 5 = 45.

## Item A, FIFO
Layers: L0 100 @ 10 (1,000), L1 200 @ 12 (2,400), L2 100 @ 15 (1,500).
* S-A1 150: 100 from L0 = 1,000.00 + 50 from L1 = 50 x 12 = 600.00 -> **1,600.00**; L1 left 150 (1,800.00).
* S-A2 180: 150 from L1 = 1,800.00 + 30 from L2 = 30 x 15 = 450.00 -> **2,250.00**; L2 left 70 (1,050.00).
* CN-A 10 back at the unit cost of S-A2: 2,250.00 / 180 = 12.50, 10 x 12.50 = **125.00**, a new layer.
* Inward 2,400 + 1,500 + 125 = 4,025.00 (qty 310); outward 1,600 + 2,250 = 3,850.00 (qty 330).
* Closing 80 = 1,050.00 + 125.00 = **1,175.00**. Check 1,000 + 4,025 - 3,850 = 1,175.

## Item A, weighted average moving
* After P-A1: qty 300, value 3,400.00. S-A1: 150 x 3,400 / 300 = **1,700.00**; left 150, 1,700.00.
* After P-A2: qty 250, value 3,200.00 (12.80). S-A2: 180 x 12.80 = **2,304.00**; left 70, 896.00.
* CN-A 10 at the cost of S-A2: 2,304.00 / 180 = 12.80 -> **128.00**; qty 80, value 1,024.00.
* Inward 2,400 + 1,500 + 128 = 4,028.00; outward 1,700 + 2,304 = 4,004.00; closing **1,024.00**. Check 1,000 + 4,028 - 4,004.

## Item A, weighted average periodic (April window)
Pool: quantity 100 + 200 + 100 = 400, value 1,000 + 2,400 + 1,500 = 4,900.00, average 4,900 / 400 = 12.25. Sales and the return that traces to a sale are valued at the period average and net off by quantity: sales 150 + 180 = 330, less the return 10 = 320 net outward.
* Outward 320 x 12.25 = **3,920.00**; closing 80 x 12.25 = **980.00** (4,900 - 3,920).
* Single movements at 12.25: S-A1 150 x 12.25 = 1,837.50; S-A2 180 x 12.25 = 2,205.00; CN-A 10 x 12.25 = 122.50 (1,837.50 + 2,205.00 - 122.50 = 3,920.00).
* Presentation: the return is shown as less outward, not as inward. Inward = purchases 300 / 3,900.00, outward 320 / 3,920.00.

## Item B, FIFO
Layers: L0 40 @ 50 (2,000), L1 60 @ 55 (3,300), L2 55 @ 60 (3,300, from 18-04).
* S-B1 50: 40 from L0 = 2,000.00 + 10 from L1 = 550.00 -> **2,550.00**; L1 left 50 (2,750.00).
* DN-B 5 out of L1 (the layer of the purchase it returns): 5 x 55 = **275.00**; L1 left 45 (2,475.00).
* W-1 write-off 4 (oldest layer is L1): 4 x 55 = **220.00**; L1 left 41 (2,255.00).
* S-B2 70: 41 from L1 = whole remaining 2,255.00 + 29 from L2 = 29 x 60 = 1,740.00 -> **3,995.00**; L2 left 26 = **1,560.00**.
* Inward 3,300 + 3,300 = 6,600.00 (qty 115); outward 2,550 + 275 + 220 + 3,995 = 7,040.00 (qty 129). Check 2,000 + 6,600 - 7,040 = 1,560.

## Item B, weighted average moving
* After P-B1: qty 100, value 5,300.00. S-B1 50 x 53.00 = **2,650.00**; left 50, 2,650.00.
* DN-B 5 at the cost of P-B1 (55.00): **275.00**; left 45, 2,375.00.
* After P-B2: qty 100, value 5,675.00 (56.75). W-1 4 x 56.75 = **227.00**; left 96, 5,448.00.
* S-B2 70 x 56.75 = **3,972.50**; left 26, **1,475.50** (26 x 56.75).
* Inward 6,600.00; outward 2,650 + 275 + 227 + 3,972.50 = 7,124.50. Check 2,000 + 6,600 - 7,124.50 = 1,475.50.

## Item B, weighted average periodic (April window)
Known-cost movements: purchases (3,300 + 3,300) and the purchase return at the cost of its purchase (275.00). Pool: quantity 40 + 60 - 5 + 55 = 150, value 2,000 + 3,300 - 275 + 3,300 = 8,325.00, average 8,325 / 150 = 55.50. Sales and write-off at the average: 50 + 4 + 70 = 124 x 55.50 = **6,882.00** (S-B1 2,775.00, W-1 222.00, S-B2 3,885.00).
* Closing 26 x 55.50 = **1,443.00** (8,325 - 6,882).
* Register: inward 115 / 6,600.00; outward = purchase return 5 / 275.00 + 124 / 6,882.00 = 129 / **7,157.00**. Check 2,000 + 6,600 - 7,157 = 1,443.

## Totals of the register
| Method | Opening | Inward | Outward | Closing (cost) |
| --- | --- | --- | --- | --- |
| FIFO | 4,000.00 | 4,025 + 6,600 = 10,625.00 | 3,850 + 7,040 = 10,890.00 | 1,175 + 1,560 + 1,000 = 3,735.00 |
| WA periodic | 4,000.00 | 3,900 + 6,600 = 10,500.00 | 3,920 + 7,157 = 11,077.00 | 980 + 1,443 + 1,000 = 3,423.00 |
| WA moving | 4,000.00 | 4,028 + 6,600 = 10,628.00 | 4,004 + 7,124.50 = 11,128.50 | 1,024 + 1,475.50 + 1,000 = 3,499.50 |

The three closing values differ (3,735.00 / 3,423.00 / 3,499.50) on the same goods: that is the point of the pack.

## AS 2: lower of cost and NRV, item by item, as on 30-04-2026
NRV per unit entered: A 13.00 (80 x 13.00 = 1,040.00), B 55.00 (26 x 55.00 = 1,430.00). C: none entered, so shown at cost with warning S-15 and no write-down.
| Method | Item | Cost | NRV value | Write-down | Carrying |
| --- | --- | --- | --- | --- | --- |
| FIFO | A | 1,175.00 | 1,040.00 | 1,175 - 1,040 = 135.00 | 1,040.00 |
| FIFO | B | 1,560.00 | 1,430.00 | 130.00 | 1,430.00 |
| FIFO | C | 1,000.00 | none | 0.00 | 1,000.00 |
| WA periodic | A | 980.00 | 1,040.00 | 0.00 (cost is lower) | 980.00 |
| WA periodic | B | 1,443.00 | 1,430.00 | 13.00 | 1,430.00 |
| WA moving | A | 1,024.00 | 1,040.00 | 0.00 | 1,024.00 |
| WA moving | B | 1,475.50 | 1,430.00 | 45.50 | 1,430.00 |

Totals (write-downs are never netted against items where NRV is above cost): FIFO cost 3,735.00, write-down 265.00 (135 + 130), carrying 3,470.00. WA periodic 3,423.00, 13.00, 3,410.00. WA moving 3,499.50, 45.50, 3,454.00.

## Transfer (no value change)
T-1 moves 20 of A from Main to Shop on 25-04: transfer_out 20 and transfer_in 20, value 0.00 in every method, item value unchanged. By godown: A Main 60, Shop 20; B Main 26; C Main 10.

## Wrong cases (each must be refused, nothing posted)
| Case | What | Why | Rule |
| --- | --- | --- | --- |
| W1 | Sale of 500 A on 27-04 | 80 on hand | S-01 (refused at approval) |
| W2 | Transfer of 30 A from Shop to Main | Shop holds 20 (godown level) | S-01 |
| W3 | Write-off of 100 B (damage) | 26 on hand | S-01 |
| W4 | Sale with quantity 1.0005 | more than 3 decimals, rejected not rounded | G-17 (the invoice quantity rule of Phase 3 fires before stock rule S-02) |
| W5 | Credit Note returning 200 A against S-A1 (150 sold) | return above original quantity | S-12 |
| W6 | Write-off without reason | reason code and note required | S-10 |
| W7 | Sale of 70 A out of Shop | Shop holds 20 although the item has 80 | S-01 |

## Known tool limit (not a pack error)
Package B's FIFO puts the goods of a reversed sale back as a NEW layer, so reversing the original purchase afterwards is still refused by S-17 although the goods are physically back (a false block: conservative, never a wrong cost). Not exercised by this pack; reported to the owner.
