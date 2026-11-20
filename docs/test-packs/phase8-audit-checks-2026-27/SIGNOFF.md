# Phase 8 sign-off questions for the accountant (audit assistant)

Please read `WORKING.md` first, work the sample items yourself (Tally / Excel / paper) and compare with `expected_findings.csv`, then tick `VERIFICATION_SHEET.xlsx`.
All data in the pack is synthetic. Nothing below is a legal opinion of the tool: every limit, rate and clause named here is data in a rule table with its
verification status, and the audit prints "limit pending verification" on a finding whose limit is not yet confirmed.

## A. Legal values the owner / CA must confirm (status `pending` or `secondary_verified`)

| # | Question | Where it shows in the pack | Seeded value and status |
| --- | --- | --- | --- |
| Q1 | The cash payment rule for expenditure from 01-04-2026 (successor of s.40A(3)): section number, the 10,000.00 daily limit, "above", the 100% disallowance; and the separate higher limit for transporters (35,000.00). Rule 6DD exceptions stay a reviewer decision. | F-05 (11,000.00, disallowance 11,000.00); F-22 (FY 2025-26, 1961 Act) | all `pending`; the section number was NOT found |
| Q2 | The cash receipt limit from 01-04-2026 (successor of s.269ST): 2,00,000.00 "at or above", per person per day; "one event" and "one transaction" are reviewer judgements. | F-06 (exactly 2,00,000.00); control 1,99,999.99 | 1961 Act row `secondary_verified`; 2025 Act row `pending` |
| Q3 | MSME: 15 days without a written agreement, agreed days up to 45 with one; covered activities manufacturing and services (traders are not covered). Is "bill date" right when no date of acceptance is recorded? | F-07 (45 days late); control Patel Plastics | `secondary_verified` |
| Q4 | Contractor TDS 1% (individual) above 30,000.00 per payment / 1,00,000.00 a year; deposit by the 7th of the next month. | F-09, F-10, F-11 | `secondary_verified` |
| Q5 | Form 3CD clause numbers (18, 21, 22, 23, 26, 27, 31, 34, 35, 40, 44) and which of them the books can fill. | Form 3CD derived data of FY 2025-26 | clause rows `pending` (recalled, not verified) |
| Q8 | **Form 26 (FY 2026-27 onwards) clause list is missing**: the official form could not be read (HTTP 403), so no Form 26 clause is seeded and a Form 26 set accepts hand entries only. Please supply the clause list (or the form) so that a clause seed and a derivation map can be added. | Form data of FY 2026-27 | not seeded |

## B. Choices made by the packages (decisions rows in `docs/decisions_parts/B8.md`, `C8.md`, `D8.md`, `E8.md`, `F8.md`) that need your yes / no

| # | Choice | Package |
| --- | --- | --- |
| Q6 | Judgement parameters: duplicate window 7 days; round unit 1,000.00 and minimum 10,000.00; late posting 30 days; variance band 50% and minimum 1,00,000.00 (this pack uses 5,00,000.00 to keep the A-15 list short; with 1,00,000.00 about a dozen ledgers are listed). Which values do you want as defaults? | B, D |
| Q7 | A "live" voucher is posted and not a reversal; a reversed voucher and its reversal are ignored by A-01, A-02, A-03, A-05, A-06, A-12; A-13 and A-14 still look at reversed vouchers; A-04 counts reversed numbers as used. | B |
| Q9 | A-01 compares Purchase vouchers only and normalises the bill number (case, spaces and punctuation ignored): is "INV-17" = "inv 17 " = "INV17" right, and should Debit Notes be included? | B |
| Q10 | A-02: payments of one party with the same total whose consecutive dates are at most N days apart; payments with no party are not compared. | B |
| Q11 | A-05 / A-06 use Payment / Receipt vouchers settled through Cash-in-hand only. Cash Sales and Cash Purchases booked as Sales / Purchase vouchers are NOT included. Person = the party ledger, else the single ledger on the other side, else the voucher alone. Include cash sales and purchases? | B |
| Q12 | The transport limit applies only to a ledger the accountant marks as a transporter; the ledger table has no such mark yet, so it is not applied today. | B |
| Q13 | A-14: a voucher posted after any `lock` of its period in the audit log (the first lock and the next unlock with its reason are quoted), or more than 30 days after the period end; dates in Indian time. | B |
| Q14 | A-13: Sundays are computed; there is no seeded holiday list (it varies by state and client): each client's holidays are entered by the accountant. | B |
| Q15 | A-09 / A-10: the whole year is re-worked in date order; an entered TDS item is tested on its typed base; a voucher without an item is tested only when its party is an active deductee with a default nature; a payment that settles an earlier bill is not tested; GST is not removed from the base of an untested voucher. | C |
| Q16 | A-07 / A-11: as-on date is the end of the audit window, never later than today. A-08 tests every month of an active regular registration. | C |
| Q17 | A-15 compares the NET movement (debit minus credit; a reversed pair nets to zero) of the period with the same dates one year earlier; a ledger with no movement last year is flagged on the amount alone ("new"). Is net movement the right measure (rather than closing balances)? | D |
| Q18 | A-18 lists the live postings (reversed pairs left out) of each active flagged ledger; a flagged ledger with no postings gives a note, not a finding. | D |
| Q19 | Working paper: the population is the check's findings unless the run stores the examined ids; a second decision on an item and a new sample are allowed until sign-off (old and new values are logged); sign-off needs every exception decided and your own conclusion text. | E |
| Q20 | Form data: a clause is derived only when every feeding check ran; a manual entry is never overwritten by a derive; derived entries carry the weakest rule status. Clauses 18, 35, 40, 44 stay manual. | F |
| Q21 | AI summary: Python rejects a summary that quotes a number, date or identifier not in the findings, or that uses conclusion wording (opinion, compliant, cleared, confirmed, disallowed, recommend ...). Is that list of words right for your office? | F |

## C. Please also answer

1. The pack puts the GST registration from 01-09-2026 (so the tie-out is tested for September and October only) and types the filed GSTR-1 figures. Do you want an
   invoice-level GST sales sample added in a later pack?
2. The lock / unlock of July 2026 is shown through the audit log (the voucher service blocks posting into a locked period). Is the A-14 wording clear to a reviewer?
3. Items the audit does NOT cover in this phase (suggestions): cash loans and deposits above the s.269SS / 269T successor limit, fair-value checks on related-party
   transactions, Benford-style digit analysis, GSTR-2B ITC mismatch as an audit check, scheduled periodic runs, a management-letter generator.

Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected          Name and date: ______________________
