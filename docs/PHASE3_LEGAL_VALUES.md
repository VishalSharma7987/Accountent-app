# Phase 3 (GST) — legal values register

Written 2026-11-13 by the Phase 3 planning agent. Rule of CLAUDE.md section 2.5: law is data, nothing unverified may look verified.
Research method: WebSearch and WebFetch. **Every official site tried was not usable**: `indiacode.nic.in` (HTTP 403), `cbic-gst.gov.in` (404 on the guessed PDF path), `gst.gov.in` help page (404), `gstcouncil.gov.in/node/5522` (readable, but only the title "Seeks to amend Notification 13/2017-CT(Rate) to implement the 55th Council recommendations"; the PDF text was not fetched). No official text was read for any value below. Nothing is `verified`.
Status legend: `secondary_verified` = at least two independent secondary sources agree (named in `source_reference`), still awaiting the CA; `pending` = one secondary source, recalled from memory, or sources disagree. All values live in rule tables (migration 0009) and are seeded by `database/seeds/0004..0007_*.sql`.

## 1. Values seeded, with status

| Value | Table / seed | Status | Source read (secondary) | What could not be verified |
| --- | --- | --- | --- | --- |
| Slabs 0 / 5 / 18 from 1-7-2017 (still in force); 12 and 28 for 1-7-2017 to 21-09-2025; 40 from 22-09-2025 | `gst_rate_slabs` (0005) | secondary_verified | TaxGuru, EY alert on CBIC notifications, Business Today, Tally Solutions, Business Standard, Vyapar, Kotak MF all agree on 5/18/40 from 22-09-2025 (56th Council; notifications 9/2025-CT(Rate) to 17/2025-CT(Rate) of 17-09-2025) and on 5/12/18/28 before | Gazette text of the notifications. One source says 9/2025-CT(Rate) was amended later "in line with Finance Act 2026 from 1 May" (not confirmed). Tobacco / pan masala: sources disagree whether they moved to 40% and when; cess on them continues (not seeded) |
| Special rates 0.25% and 3% | `gst_rate_slabs` (0005) | pending | one search summary (precious metals/stones). 1.5% (cut and polished stones) mentioned by one source: NOT seeded | exact entries and dates |
| HSN/SAC -> rate rows (16 rows) | `gst_rate_rules` (0005) | pending, `is_example = true` | recalled from secondary knowledge | **The full HSN-wise tariff is not shipped.** Owner/CA must import the official HSN-wise rates from the CBIC rate notifications (1/2017-CT(Rate) as amended, 9/2025-CT(Rate) onwards). Value-conditional entries (e.g. footwear, apparel up to Rs 1,000; hotel room tariff bands) are not modelled: the schema has no per-unit-value condition (suggestion) |
| Default services rate 18% | `gst_rate_rules` key `default_services` | pending | secondary (residual entry of the services rate notification 11/2017-CT(Rate)) | notification text. No default for goods is seeded on purpose |
| State / UT codes 01-24, 27, 29-37, 97, 99 | `gst_state_codes` (0004) | secondary_verified | Tally Solutions list (read in full); Masters India, Razorpay, Tofler, Godrej Capital, Tata Nexarc and others agree on the same list (search summaries) | `gst.gov.in` state code page. Code 99 is "Centre Jurisdiction" per most sources; one says "other country" in specific contexts |
| State codes 25, 26, 28, 38 | `gst_state_codes` | pending | Tally; summaries note 25 absorbed in 26 (2020), 28 = old Andhra Pradesh, 38 = Ladakh (UT from Oct 2019) | validity dates of 25 / 38; whether new GSTINs may carry 25 |
| UQC list (45 codes) | `gst_uqc` (0004) | pending | from memory of the GSTR-1 list | official GSTR-1 UQC list |
| RCM categories under Section 9(3): GTA, advocate, sponsorship, director, insurance agent, recovery agent, government services, security services, specified agricultural goods; import of services; Section 9(4) placeholder | `gst_rcm_rules` (0006), all `is_example` | pending | search results confirm Notification 13/2017-CT(Rate) is the services list and was last amended by 7/2025-CT(Rate) of 16-01-2025 (55th Council) and 9/2024 (8-10-2024); content of the entries from memory | **the entry-wise text and conditions of 13/2017 and 4/2017 as amended; the Section 9(4) classes and notification numbers; whether any 2025-26 amendments changed GTA / legal / sponsorship entries.** HSN prefixes only for GTA (9965) and legal (9982), recalled from memory |
| Section 17(5) categories (a), (aa), (ab), (b)(i)-(iii), (c)-(i) | `gst_blocked_credit_rules` (0006) | pending | one section summary (lawx.in) plus commentary pages that agree on the categories but disagree on clause lettering ((b) vs (ab) for insurance, etc.) | official wording, effective dates of (aa), (ab) and the insurance limb (seeded as 1-2-2019, unverified); the 2024 amendment of the section numbers in (i); Finance Act 2025 retrospective "plant and machinery" change in (c)/(d) |
| Section 16(2)(a)-(d) conditions | `gst_itc_conditions` (0006) | pending | commentary only; no clause-by-clause text read | official wording |
| 180-day payment rule (second proviso to 16(2)), Rule 37 | `gst_itc_conditions` key `payment_within_days` = 180 | pending | TaxGuru, TaxTMI, ClearTax, ICAI journal, Taxilla describe: pay supplier within 180 days of invoice date or reverse the proportionate credit, re-avail on payment (Rule 37(4) lifts the Section 16(4) bar for re-availment; commentators differ on edge cases) | Rule 37 text; interest under s.50(3) on late reversal is NOT modelled; the proportionate-reversal formula is per the Rule (to be confirmed); what counts as "payment" (bank, set-off, journal) needs CA ruling |
| Section 16(4) time limit: 30 November following the financial year, or annual return date if earlier | `gst_itc_conditions` key `claim_time_limit`, effective 1-10-2022 | pending | secondary commentary | earlier regimes (20 Sept / 20 Oct) not seeded; the retrospective relief in s.16(5)/(6) (Finance Act 2024) not modelled |
| Composition scheme rates 1% / 1% / 5% / 6%, limits Rs 1.5 crore / Rs 50 lakh | `gst_composition_rules` (0007) | pending | busy.in, tax2win, petpooja, thegstco, legalsuvidha agree; no one cited the notification | notification numbers; special-category-state limit (sources disagree on which states): **not seeded**; tax base per category; CMP-08 / GSTR-4 names and due dates not confirmed by these sources |
| B2C Large invoice value Rs 2,50,000; HSN digits (4 up to Rs 5 crore turnover, 6 above); invoice number max 16 characters | `gst_thresholds` (0007) | pending | recalled from memory / guides | notifications; the HSN digit phase-in dates |
| GSTR-1 / GSTR-3B table numbering | engine constants, NOT law tables (see PHASE3_PLAN step 3.9) | pending | search summaries confirm: GSTR-3B 3.1, 3.2, 4, 5, 6 exist, 3.1/3.2 are now auto-populated from GSTR-1/IFF (one source: from Nov 2025); GSTR-1 table 4 = B2B, 9 = amendments, 12 = HSN summary, 13 = documents issued | **Row-level sub-table numbers (3.1(a)-(e), 3.1.1, 4(A)(1)-(5), 4(B), 4(D), 5, 5.1, 6.1, and GSTR-1 tables 5, 6, 7, 8, 9B, 14, 15) were not confirmed by any source this agent read.** The workings use the numbering in section 5 below and say "numbering to be checked against the portal" until the CA confirms. Portal JSON schemas: not obtained |
| GSTR-2B / IMS file structure | importer | pending | not researched | official JSON schema of GSTR-2B and IMS. The importer must be written against a real sample file supplied by the owner |
| Return due dates | not used in Phase 3 | n/a | | not needed; filing stays manual |

## 2. GSTIN structure and check digit (algorithm, not law)

Structure (15 characters): 2-digit state code; 10-character PAN; 1 entity number (`1-9`, `A-Z`); fixed `Z`; 1 check character. The format regex used in `parties` and `gst_registrations`: `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$`.

Check character (Luhn mod 36, as implemented by the open-source `python-stdnum` `in_.gstin` module and described by several third-party validators; **no official publication was readable**, so this is `secondary_verified` as an algorithm):
1. Alphabet `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ`; value = index (0-35).
2. For the first 14 characters, left to right, index i from 0: `factor = 1` if i is even, `2` if i is odd.
3. `p = value * factor`; add `p // 36 + p % 36` to the running sum.
4. check value = `(36 - sum % 36) % 36`; the check character is its alphabet symbol.

Verified by running the algorithm in a scratch script: the widely quoted sample GSTIN `27AAPFU0939F1ZV` validates (14-character body gives `V`). One blog example (`27AACCM9910C1Z` + `5`) did **not** validate (algorithm gives `N`): that blog value is not used.
Synthetic valid GSTINs generated by the same algorithm (not real registrations; use only in tests): `27ABCDE1234F1Z0`, `29ABCDE1234F1ZW`, `07AAAAA0000A1Z4`, `33AAAAA0000A1Z9`, `24ABCPA1234B1ZT`. The corresponding PANs are the characters 3-12: `ABCDE1234F`, `AAAAA0000A`, `ABCPA1234B`.
Invalid-check-digit tests: change the last character of any of these.

## 3. Items the owner / CA must decide or supply (STOP-and-ask list, CLAUDE.md 6(a))
1. Import the official HSN-wise rate data (full tariff) and confirm or replace the 16 example rows.
2. Confirm the RCM lists (13/2017, 4/2017, Section 9(4) classes and notification numbers) and the Section 17(5) wording and dates.
3. Confirm the 180-day rule mechanics (proportion, what counts as payment) and whether interest under s.50 should be worked (not built).
4. Confirm composition rates, limits, special-category-state limit, and the GSTR-4 / CMP-08 forms.
5. Confirm the return table numbering (section 5) and supply a real GSTR-2B JSON and Excel, an IMS file, and a GSTR-1 / GSTR-3B JSON from the portal so the importers and exporters can be built against official shapes. Until then JSON outputs are labelled "working format, not validated against the portal schema".
6. Confirm 22-09-2025 transition rules (invoice or payment or supply date decides the rate: the plan uses the date of supply = invoice date, owner/CA to confirm).

## 4. What is NOT legal data in Phase 3 (configuration constants, documented in DECISIONS.md)
Reconciliation value tolerance (default 0.00), reconciliation date window, invoice round-off bound (0.50), unit quantity precision, rate precision (4 decimals).

## 5. Return working structure used by the plan (to be confirmed against the portal)
GSTR-1: 4A/4B/4C (B2B regular, reverse charge), 5 (B2C large), 6A/6B/6C (exports, SEZ, deemed), 7 (B2C small, state-wise), 8 (nil, exempt, non-GST), 9B (CDNR and CDNUR credit/debit notes), 9A/9C amendments (not built), 12 (HSN summary), 13 (documents issued).
GSTR-3B: 3.1(a) outward taxable, (b) zero rated, (c) nil/exempt, (d) inward RCM, (e) non-GST; 3.2 inter-state supplies to unregistered / composition / UIN; 4(A)(1)-(5) ITC available, 4(B)(1) per rules 38/42/43 and section 17(5), 4(B)(2) others (incl. 180-day reversals), 4(C) net, 4(D) ineligible; 5 inward exempt/nil/non-GST; 6.1 payment of tax. Composition: CMP-08 quarterly statement, GSTR-4 annual. These are recalled from memory and from the search summaries only.
