# Phase 6 legal values (depreciation, Schedule II, Schedule III, half-rate rule) and their status

Written 2026-11-19 (planning step 6.0). **No value is `verified`.** incometaxindia.gov.in, indiacode.nic.in and the Companies Act / Schedule III texts were not read in this step; one web search (query: "Income-tax Act 2025 depreciation block of assets rates Schedule section 33 half rate 180 days") returned only secondary pages (cleartax.in, legaldev.in, taxgarden.in, 5paisa.com, motilaloswal.com, compliancecalendar.in, visaverge.com, taxclue.in) and they were not opened one by one. Per CLAUDE.md 2.5 every value is data in the rule tables (`database/seeds/0012_*`, `0013_*`); the status shown is the status stored. The owner / CA must confirm the items in section 5 before the tool is used for real tax depreciation.

Statuses: `secondary_verified` = the figure is on several secondary pages for the Income-tax Act 1961 rate chart (search result summary; pages not individually read). `pending` = recalled from the Income-tax Rules 1962 Appendix I / Companies Act 2013 Schedule II / Schedule III, or sources disagree, or it is a 2025-Act row.

## 1. Law selection
Depreciation of a financial year is claimed under the Act in force at the **end of the financial year**: FY 2025-26 and earlier -> Income-tax Act 1961 (rows `it_act_1961`, `effective_to` 2026-03-31); FY 2026-27 onwards -> Income-tax Act 2025 (rows `it_act_2025`, `effective_from` 2026-04-01). The engine takes the row by the FY end date. Companies Act Schedule II applies from 01-04-2014 (rows `effective_from` 2014-04-01). Rule data for income tax starts at FY 2025-26; an earlier year has no row and is refused (`no_rule`).
Reports disagree on where depreciation sits in the 2025 Act (section 33 / 34 / 35; "Schedule II" / "Schedule XIV"). The section is NOT stored as a fact: rows say "section / schedule number not verified". The rates are reported as carried over from the 1961 Act.

## 2. Income-tax block rates (WDV, per block; seed 0012 `dep_it_block_rates`)
| Block key | Block | Rate % | 1961 status | 2025 status |
| --- | --- | --- | --- | --- |
| building_residential | Buildings, residential | 5 | pending (one page says 10 for all buildings) | pending |
| building_other | Buildings, other than residential | 10 | secondary_verified | pending |
| building_temporary | Temporary structures | 40 | pending | pending |
| furniture_fittings | Furniture and fittings | 10 | secondary_verified | pending |
| plant_machinery_general | Plant and machinery, general | 15 | secondary_verified | pending |
| motor_car | Motor cars (not on hire) | 15 | pending | pending |
| motor_vehicle_hire | Buses, lorries, taxis on hire | 30 | pending | pending |
| computers_software | Computers including software | 40 | secondary_verified | pending |
| intangible_assets | Know-how, patents, licences, franchises etc. | 25 | secondary_verified | pending |
| pollution_control | Pollution control equipment | 40 | pending | pending |
Not seeded (specific blocks and incentives): ships, aircraft, energy-saving and renewable devices, books for professionals, specified plant at 30 / 40 / 100 percent, additional (first-year) depreciation, terminal depreciation, assets of a business not in use. They need the CA's block list.

## 3. Half-rate rule (seed 0012 `dep_it_rules`)
An addition put to use for **fewer than 180 days** in the financial year gets **50%** of the block rate; 180 days or more gets the full rate. Sources agree on 180 days and 50% (1961 Act s.32(1) second proviso; 2025 Act equivalent not verified). Day count used by the engine: put-to-use date to 31 March, both days counted (an asset put to use on 01-10 has 182 days). The counting convention and the treatment of a disposal that exceeds the full-rate base (F-32) are **not legal values but accounting readings; they need the CA's confirmation**.

## 4. Companies Act 2013 Schedule II (useful life, seed 0012 `dep_sched2_classes`) and Schedule III (seed 0013)
All **pending**. Useful lives (single shift): RCC buildings 60, other buildings 30, factory buildings 30, temporary 3, plant and machinery general 15, furniture and fittings 10, office equipment 5, computers (desktops, laptops) 3, servers and networks 6, motor cars 8, motor cycles and scooters 10, motor buses / lorries / taxis on hire 6, electrical installations 10 years; residual value not more than 5% of original cost. Schedule III Division I line items and the default group map are recalled. Division II (Ind AS) is not modelled.

## 5. BLOCKING LIST for the owner / CA (nothing below is verified)
1. Confirm every income-tax block rate above against the Income-tax Rules 1962 Appendix I (FY 2025-26) and against the Income-tax Act 2025 depreciation schedule (FY 2026-27 on) and give the section / schedule numbers of the 2025 Act; confirm the residential-building rate (5 or 10).
2. Confirm the half-rate rule (180 days, 50%) under the 2025 Act and the day-count convention.
3. Confirm the Schedule II useful lives and the 5% residual ceiling against the Act (Part C).
4. Confirm the Schedule III Division I line items and the default classification of each group (section 4); the accountant must classify loans, investments and deposits ledger by ledger (the tool does not default them).
5. Decide the accounting readings listed in PHASE6_PLAN.md "Sign-off questions" (disposal deficit against half-rate additions; tranche treatment of additions; inclusive day counts).
6. Interest on capital / drawings rates and partners' remuneration are **deed values**, entered per partner per FY with the deed reference. The tool does not apply any Income-tax Act limit on them (section 40(b) of the 1961 Act and its 2025-Act equivalent); that is a suggestion, not built.
Until these are confirmed the depreciation run prints "rule status: pending" on every line and the export header lists the pending rows.
