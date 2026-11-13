# Phase 4 legal values (TDS / TCS) and their status

Written 2026-11-13 (planning step 4.0). **No value is `verified`** (see section 0 for the owner-supplied values added later, stored `secondary_verified`). incometaxindia.gov.in, the text of the Income-tax Act 2025 and the CBDT
notifications were not read in this step (web search / fetch returned only secondary pages). Per CLAUDE.md 2.5 every value is data in the rule
tables (`database/seeds/0008_*`, `0009_*`); the status shown is the status stored. The owner / CA must confirm the items in section 4 before the
tool is used for real deduction.

Statuses: `secondary_verified` = the figure is on two secondary pages we read (taxguru.in "TDS Master Sheet - Income Tax Act 2025", cleartax.in
"TDS and TCS changes from April 2026" / TDS rate chart FY 2026-27, taxaj.com form table, taxscan.in, taxheal.com, businesstoday.in). `pending` = recalled
from the Finance Act 2025 position, seen on one page only, or reported differently by two pages.

## 0. Owner-supplied values applied (seed 0010, 2026-11-13)
The owner supplied the values below as verified from official sources. We tried to read the official pages (incometaxindia.gov.in, s.393 and the s.397 FAQ): both returned HTTP 403 to our fetch, so we could not confirm them ourselves. They are stored as `secondary_verified` (the schema enum has `verified`, `secondary_verified`, `pending`; the owner's "official_verified" would map to `verified`, which we do not set without reading the text). Upgrade to `verified` once someone reads the official page. Applied by `database/seeds/0010_tds_owner_verified_values.sql` (2025-Act rows only, from 01-04-2026).

| Value | Applied | Status | Source |
| --- | --- | --- | --- |
| Rent (ex-194-I), s.393(1) rent entry | Rs 50,000 for a month or part of a month (not 6,00,000 a year); 2% machinery / plant / equipment; 10% land / building / furniture (specified person); 2% for a person other than a specified person (ex-194-IB) is NOT modelled in the table (needs a deductee flag) | secondary_verified | https://www.incometaxindia.gov.in/w/section-393-5 (owner; 403 for us) |
| No PAN, s.397(2) | higher of specified rate, rate in force, 20%; 5% for purchase of goods (ex-194Q) and e-commerce (ex-194-O); provision `no_pan_higher_rate` 2025 row now cites 397(2) | secondary_verified | https://www.incometaxindia.gov.in/documents/d/guest/faqs-on-higher-rate-of-tds-under-section-397 (owner; 403 for us) |
| Ex-194M, s.393(1) Sl.6(ii) | 2%, Rs 50,00,000 a year (conflict resolved) | secondary_verified | owner |
| Ex-194T, s.393(3) Sl.7 | 10%, Rs 20,000 aggregate a year, payment code 1067 | secondary_verified | owner |
| Ex-194Q, s.393(1) Sl.8(ii) | 0.1% on purchases above Rs 50,00,000 in the year, no-PAN 5% | secondary_verified | owner |
| Deposit, Rule 218 | 7th of next month; March deductions by 30 April | secondary_verified | owner |
| Statements, Rule 219 | 31 Jul, 31 Oct, 31 Jan, 31 May | secondary_verified | owner |
| Forms | 138 salary, 140 non-salary resident, 130 salary certificate | secondary_verified | owner |
| STILL PENDING | TCS rates / limits (s.394); ex-194Q buyer-turnover limit (Rs 10 crore) under the 2025 Act; TCS no-PAN rule; the 1961-Act rows (rent 1961 rows still carry the 50,000 monthly figure and stay `pending`) | pending | none |

Sections 2 to 5 below are the earlier planning-step text; where they conflict with this table (rent threshold, 194M threshold, 194T, no-PAN and 194Q rate, 30 April rule), this table wins.

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


## Phase 4.1 additions (owner-supplied 2026-11-13, seed 0011)
| Item | Value | Status |
| --- | --- | --- |
| Rent by an individual / HUF not liable to tax audit (ex-194-IB), s.393 entry | 2%, Rs 50,000 per month; nature `rent_194ib`; 1961 rows `pending` | `secondary_verified` (2025 Act) |
| Rent classification follows the DEDUCTOR (individual / HUF not liable to tax audit = ex-194-IB, everyone else ex-194-I) | provision `rent_deductor_classification` | `secondary_verified` |
| ex-194-IB: the WHOLE month's rent once the month is above Rs 50,000 (not only the excess) | provision `rent_194ib_whole_month_reading` | **`pending` for the CA** |
| Tax on a GST invoice is on the value without GST shown separately | provision `gst_excluded_from_base`; the circular number is NOT recorded | `secondary_verified` (owner-supplied position; circular number to be confirmed by the CA) |
| Interest on late deduction 1% and on late deposit 1.5% per month or part of a month | `tds_interest_rules` | `secondary_verified` |
| Tax rounded to the nearest rupee (old s.288B; 2025-Act section number not verified) | provision `rounding_nearest_rupee` | `secondary_verified` |
