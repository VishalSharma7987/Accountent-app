# Phase 4 legal values (TDS / TCS) and their status

Written 2026-11-13 (planning step 4.0). **No value below is `verified`.** incometaxindia.gov.in, the text of the Income-tax Act 2025 and the CBDT
notifications were not read in this step (web search / fetch returned only secondary pages). Per CLAUDE.md 2.5 every value is data in the rule
tables (`database/seeds/0008_*`, `0009_*`); the status shown is the status stored. The owner / CA must confirm the items in section 4 before the
tool is used for real deduction.

Statuses: `secondary_verified` = the figure is on two secondary pages we read (taxguru.in "TDS Master Sheet - Income Tax Act 2025", cleartax.in
"TDS and TCS changes from April 2026" / TDS rate chart FY 2026-27, taxaj.com form table, taxscan.in, taxheal.com, businesstoday.in). `pending` = recalled
from the Finance Act 2025 position, seen on one page only, or reported differently by two pages.

## 1. Law selection (owner requirement; not a rate)
- The earlier of the date of payment and the date of credit (the `event_date`) decides the Act: on or before 31-03-2026 -> Income-tax Act 1961 (rows `it_act_1961`, `effective_to` 2026-03-31); on or after 01-04-2026 -> Income-tax Act 2025 (rows `it_act_2025`, `effective_from` 2026-04-01).
- Under the 2025 Act (as reported): section 392 salary, section 393 all other TDS (table entries, 393(1) residents), section 394 TCS. Table serials are stored in `tds_section_refs.table_ref`; they are `pending` where sources disagree.
- Rule data starts on 2025-04-01 (FY 2025-26). A payment before that date has no rule and is refused (T-02); earlier years differ (e.g. 194H 5% -> 2% on 1-10-2024, thresholds changed 1-4-2025) and are not seeded.

## 2. Rates and thresholds seeded (both Acts carry the same values unless noted)
| Nature | 1961 section | 2025 reference (as reported) | Rate | Threshold | No-PAN rate | Status 1961 / 2025 |
| --- | --- | --- | --- | --- | --- | --- |
| Contractor, individual/HUF | 194C | 393(1) Sl.6(i) | 1% | single 30,000 or annual 1,00,000 (whole amount once crossed) | 20% | pending / secondary_verified |
| Contractor, others | 194C | 393(1) Sl.6(i) | 2% | same | 20% | pending / secondary_verified |
| Commission, brokerage | 194H | 393(1) Sl.1(ii) | 2% | annual 20,000 | 20% | pending / secondary_verified |
| Rent, plant and machinery | 194I(a) | 393(1) Sl.2(ii)(a) (conflicting reports) | 2% | **conflict**: 50,000 per month or part (secondary pages) vs 6,00,000 per year (recalled Finance Act 2025). Seeded as 50,000 per month | 20% | pending / pending |
| Rent, land / building / furniture | 194I(b) | 393(1) Sl.2(ii)(b) (conflicting reports) | 10% | same conflict | 20% | pending / pending |
| Technical fees, call centre, film royalty | 194J(a) | 393(1) Sl.6(iii)(a) | 2% | annual 50,000 | 20% | pending / secondary_verified |
| Professional fees | 194J(b) | 393(1) Sl.6(iii)(b) | 10% | annual 50,000 | 20% | pending / secondary_verified |
| Interest other than bank | 194A | 393(1) Sl.5(iii) | 10% | annual 10,000 | 20% | pending / secondary_verified |
| Purchase of goods | 194Q | 393(1) Sl.8(ii) | 0.1% | tax only on the excess over 50,00,000 per seller per year; buyer condition (prior-year turnover above the limit, recalled Rs 10 crore: **limit pending**) is a client flag `tds_client_fy_flags` | 5% (recalled; not on a page) | pending / secondary_verified |
| E-commerce participant | 194O | 393(1) Sl.8(v) | 0.1% | 5,00,000 (individual/HUF sellers only, recalled) | 5% (recalled) | pending / secondary_verified |
| Contract/professional by individual/HUF | 194M | 393(1) Sl.6(ii) | 2% | **conflict**: 50,00,000 (cleartax.in) vs 50,000 (taxguru.in) | 20% | pending / pending |
| Payment to a partner | 194T | not found | 10% | annual 20,000 (new from 1-4-2025, recalled; cleartax.in lists it for FY 2026-27) | 20% | pending / pending |
| Salary | 192 | 392 | slab (amount typed by the accountant; no payroll engine) | none | not applicable | section number only |
| TCS: liquor / tendu / timber / scrap / minerals | 206C(1) | 394 | 1961: 1% / 5% / 2.5% / 1% / 1% (recalled); 2025: 2% each per cleartax.in (one source) | none | twice the rate or 5% (206CC, recalled) | pending / pending |
| TCS: motor vehicle | 206C(1F) | 394 | 1% | on the value above 10,00,000 | recalled | pending / pending |
| TCS: overseas tour | 206C(1G) | 394 | 1961: 5% up to 10,00,000, 20% above (**20% tier not modelled**); 2025: flat 2% (several secondary pages) | none | recalled | pending / pending |
| TCS: LRS education / medical | 206C(1G) | 394 | 1961: 5% above 10,00,000; 2025: 2% (limit reported differently by two sources) | 10,00,000 | recalled | pending / pending |
| TCS: LRS other | 206C(1G) | 394 | 20% above 10,00,000 (recalled) | 10,00,000 | recalled | pending / pending |

Not seeded (owner / CA to add rows, no code change): 194D, 194G, 194B, 194BB, 194IA, 194IB, 194N, 194R, 194S, 194LA, non-resident payments (Section 195 / Table 2), TCS 206C(1H) (omitted 1-4-2025, recalled).

## 3. Other provisions (all `pending`; 2025-Act section numbers not found)
| Provision | 1961 reference (recalled) | 2025 reference |
| --- | --- | --- |
| Higher rate when PAN missing | 206AA (20% or the specified higher rate) | not found |
| Lower / nil deduction certificate | 197 (Form 13) -> Form 128 (Rule 213, taxaj.com) | section not found |
| Higher rate for TCS without PAN | 206CC | not found |
| Interest on late deduction / deposit | 201(1A): 1% per month (deduction), 1.5% per month (deposit), month or part of a month; cleartax.in states the same rates | section not found |
| Rounding of tax | 288B (nearest rupee) | not found |
| GST shown separately is excluded from the base | CBDT Circular 23/2017 | not checked |
| Threshold crossed: tax on whole amount (194Q and TCS excess: excess only) | CBDT circular | not checked |
| Special rate for non-filers (206AB / 206CCA) | omitted from 1-4-2025 (recalled): **not modelled** | n/a |

## 4. Due dates, forms (seed 0009)
- Deposit of tax: 7th of the next month (Rule 218 of the Income-tax Rules 2026, taxheal.com; Rule 30 of the 1962 Rules, recalled); March deductions: 30 April (recalled, `pending` in both Acts).
- Quarterly statements: 31 July, 31 October, 31 January, 31 May (taxheal.com summary of Rules 2026; same dates recalled for the 1962 Rules). Certificates: 15 days after the statement due date (non-salary), 15 June (salary) - `pending`.
- Forms under the Income-tax Rules 2026 (notified 20-03-2026 as reported; taxaj.com + taxscan.in + businesstoday.in): TDS statements 138 (salary, was 24Q), 140 (non-salary residents, was 26Q), 144 (non-residents, was 27Q; one page says 140: **conflict, not used**), 143 (TCS, was 27EQ); certificates 130 (was 16), 131 (was 16A), 133 (was 27D); 128 (was 13, lower deduction); 121 (was 15G/15H); 168 (was 26AS). The Q4 FY 2025-26 statement stays in 24Q/26Q (secondary report). The challan-cum-statement forms (26QB etc.) are Form 141 schedules: **not modelled** (suggestion). Status `secondary_verified` for 138/140/143/130/131/133/128/121/168; official CBDT form list not read.
- File layouts of the statement (FVU / `.txt`) and of 26AS / AIS are NOT verified: Phase 4 produces working data (JSON / Excel), not a file for the TRACES / e-filing utility.

## 5. What the owner / CA must confirm (blocking list, in order)
1. Rent threshold (50,000 per month vs 6,00,000 per year) for both Acts; 194M threshold; 194T rate and threshold.
2. The 194Q buyer-turnover limit and the 194Q / 194O no-PAN rate (5%); the no-PAN rule (20%) and TCS no-PAN rule.
3. TCS rates from 1-4-2026 (liquor, scrap, minerals, tendu, timber) and the LRS / overseas-tour limits; table serials of section 393 / 394.
4. Section numbers of the 2025 Act for no-PAN, lower deduction, interest, certificates; the 30 April rule for March; certificate due dates.
5. Treatment of GST in the TDS base and the threshold-crossing catch-up (CBDT circulars) - the engine implements the rule as written in `tds_provisions` and tests it with hand-worked cases; the CA signs the cases in the test pack.
