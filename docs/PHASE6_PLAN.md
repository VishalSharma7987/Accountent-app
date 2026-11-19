# Phase 6 plan - Period-end and Final Accounts (adjustments, fixed assets and depreciation, closing stock, Trading / P&L / Balance Sheet, Schedule III, Cash Flow, year-end close, export)

Written 2026-11-19 (planning agent, branch `p6-plan`) under the working mode of CLAUDE.md section 6. Scope: `docs/PHASE_PROMPTS.md` Phase 6. Interfaces: `docs/PHASE6_API_CONTRACT.md`. Legal values and their status: `docs/PHASE6_LEGAL_VALUES.md` (**nothing is `verified`**; blocking list in section 5 there).
Schema (migration **0017**, seeds **0012**, **0013**) is written FIRST and is the shared contract: **agents never edit it**; a needed change goes to the main agent. Step 6.0 (this commit) wrote migration, seeds, types, hook, empty routers and tests only; it applied 0017 to the TEST schema (nothing else) and ran the schema test once.
Nothing in this phase changes how vouchers work. Every journal (adjustment, depreciation, closing entry) is a normal Journal voucher created, approved, posted and reversed **through `services/vouchers.py`** (V-01..V-14 apply). The new tables only record why a journal exists and hold inputs no voucher line can carry.

## Decisions that shape the design (details in `docs/decisions_parts/P6.md`)
1. **Statements are computed, never stored as truth.** They are recomputed from posted lines every time (like Phase 5 reports). `statement_snapshots` stores what was signed off at year-end (hash + payload) for comparatives and reproducible exports.
2. **Statements exclude the year-end closing vouchers** (and their reversals), so the Trading A/c, P&L and Balance Sheet of a closed year still show the year's trading and profit, not a zeroed year. The closing journals exist for the ledgers and the next year's openings, not for the statements.
3. **Closing entries are three Journal vouchers** (trading, profit and loss, appropriation) dated the last day of the FY, posted through the voucher service, linked in `year_end_close_vouchers`. They can only be reversed together by the year-end reopen (hook `guard_reverse`, rule F-64). Two clearing ledgers (`trading_account`, `profit_and_loss`, group Reserves & Surplus) are created explicitly by `POST /final/setup-ledgers`, never silently.
4. **One stock ledger.** Opening stock = sum of the FY opening balances of the Stock-in-hand ledgers; closing stock = the approved `final_closing_stock.carrying_value` (cost less AS 2 write-down from Phase 5). The trading closing journal credits each stock ledger's opening and debits the `stock_ledger` role ledger with the closing value, so next year's opening balance of that ledger is the closing stock.
5. **Partnership**: interest on capital, interest on drawings and partners' remuneration are posted by the adjustment helpers to their own ledgers (roles). The statements show them in a **Profit & Loss Appropriation** section below "net profit before appropriation"; the closing journal moves them with everything else into P&L A/c, and the **balance** (profit after interest and remuneration) is shared in the profit ratio. The last partner takes the rounding remainder so the shares add up exactly (F-62).
6. **Company**: the P&L balance goes to the `surplus_in_pl` ledger (Reserves & Surplus). Dividend, reserve transfers and tax provisioning are outside this phase (suggestions).
7. **Carry-forward** writes (a) `opening_balances` of the next FY for every balance-sheet ledger with a non-zero closing balance (Dr total = Cr total or the close is refused, F-65), (b) `opening_bills` of the next FY for open bills (migration 0017 makes the bill reference unique per FY, not per client), (c) `stock_opening` per item and godown from the closing-stock report (carrying value per item, spread over godowns by quantity), (d) `it_block_openings` from the final IT workings. Everything carried is listed in `year_end_closes.carried` and the audit log. Nothing existing is deleted or rewritten without the DB guards (reopen rewrites only the NEXT year's openings, and only while that year has no posted voucher).
8. **No guessing.** Missing closing stock (F-41), unclassified Schedule III ledger (F-44), unset ledger role (F-02), partners' shares not 100 (F-62), a debtor bad-debt above its balance (F-06) block with a plain message; defaults are never filled in silently.

## Database design (migration 0017; 20 tables)
| Table | Kind | Purpose |
| --- | --- | --- |
| `dep_it_block_rates`, `dep_it_rules`, `dep_sched2_classes` | rule tables | income-tax block rates by Act and date; `half_rate_days` / `half_rate_percent`; Schedule II useful life and residual ceiling. All with effective_from / effective_to / source_reference / verification_status |
| `fs_lines`, `fs_group_map` | rule tables | Schedule III Division I line items (with default cash-flow class) and the default map group -> line (`is_firm` false = warn until confirmed) |
| `client_ledger_fs_map` | client data | ledger -> Schedule III line and / or cash-flow class override (audited by the service) |
| `final_ledger_roles` | client data | PK (client, role): trading_account, profit_and_loss, surplus_in_pl, stock_ledger, depreciation_expense, accumulated_depreciation, bad_debts, doubtful_debts_expense, provision_doubtful_debts, interest_on_capital, interest_on_drawings, partner_remuneration |
| `partners`, `partner_fy_terms` | client data | partners with capital / current ledger; per FY profit share %, deed interest rates, annual remuneration, deed reference (required whenever a deed value is entered). Deed values are not law; the reference text is mandatory |
| `adjustment_entries` | record | type, date, amount, inputs (`params`), basis note, the draft journal `voucher_id` (+ optional next-year auto-reversal draft); editable only while the voucher is draft (shared guard `gst_voucher_child_guard`); voucher must be a Journal of the same FY |
| `fixed_assets`, `fixed_asset_events` | register | asset (ledger, accumulated-depreciation ledger, IT block, Schedule II class or override reason, life, residual, SLM / WDV); events opening / purchase / addition / disposal with `put_to_use_date`; trigger keeps chronology and freezes closed years |
| `depreciation_runs`, `depreciation_run_lines` | record | the Companies Act run per FY (one active run, trigger), per-asset lines, the Schedule II rows used; linked to the draft Journal; lines change only while the voucher is draft |
| `it_block_openings`, `it_depreciation_workings` | working | opening WDV per block per FY (entered or carried); the block working (draft recomputed in place, final append-only, superseded when the year is reopened) - **no voucher** |
| `final_closing_stock` | record | approved closing stock (cost, write-down, carrying, source, method, item detail); no row = F-41 |
| `statement_snapshots` | record | signed-off statements (append-only, hash, superseded flag) |
| `year_end_closes`, `year_end_close_vouchers` | record | the close (closed -> reopened only, never deleted, reopen needs reason and all three closing vouchers reversed) and the voucher links |
| alter `opening_bills` | index | `opening_bills_ref_key` now includes `financial_year_id` |

Database guards (do not weaken): closed FY freezes closing stock, partner terms, adjustments, depreciation runs, IT openings, `opening_balances`, `opening_bills`, `stock_opening` and asset events dated in it (`final_year_open_guard`); one active depreciation run per FY; adjustment and depreciation vouchers must be Journals of the same FY; snapshots / final workings append-only; closes never deleted. Money columns `numeric(18,4)` + `round(x,2)` check; rates `numeric(18,6)` + `round(x,4)` check; RLS on all 20 tables, no policies; function privileges closed at the end.

## Rules (IDs used in messages and test names)
| ID | Rule |
| --- | --- |
| F-01 | Adjustment amount > 0, at most 2 decimals (rejected, not rounded); date inside the FY; period open (V-06 / V-07); basis note required |
| F-02 | The two ledgers of an adjustment are chosen by the accountant and must fit the type (expense under an expense group; outstanding / income-in-advance / provision under Current Liabilities groups; prepaid / accrued income under Current Assets groups); ledger roles must be set where a type needs one |
| F-03 | Outstanding expense: Dr expense, Cr outstanding; prepaid: Dr prepaid, Cr expense; accrued income: Dr accrued, Cr income; income in advance: Dr income, Cr in advance; provision: Dr expense, Cr provision |
| F-04 | Optional auto-reversal: a second draft journal on the first day of the next FY with every line swapped (needs the next FY; else refused with the reason) |
| F-05 | Provision for doubtful debts is **computed**: required = `round_half_up(closing debtors x rate / 100, 2)` after bad debts; entry = required - existing provision credit balance (increase: Dr expense Cr provision; decrease: Dr provision Cr expense; zero: refused "no change"). A typed amount is rejected |
| F-06 | Bad debt: ledger is a Sundry Debtors ledger with a debit balance >= amount on the date; credit side is the debtor, debit side the `bad_debts` ledger |
| F-07 | Interest on capital / drawings only for partnership and LLP; rate = the deed rate of `partner_fy_terms` (deed reference required); computed day-weighted from the ledger's posted balance (capital: balance segments; drawings: each drawing from its date to the FY end, both days counted); rounded half-up once; a typed amount is rejected |
| F-08 | Partner's remuneration: `remuneration_annual x months / 12` (months 1..12, default 12), half-up; only partnership / LLP; Dr `partner_remuneration`, Cr the partner's profit ledger |
| F-09 | Entity gate: interest / remuneration helpers refuse proprietorship and company clients |
| F-10 | Same type + same ledger pair + same FY while an earlier adjustment's voucher is not reversed: blocked unless a reason is given (stored) |
| F-11 | Every adjustment is a Journal voucher through the voucher service; the draft carries the adjustment's narration; audit-logged |
| F-20 | Fixed asset: ledger in Fixed Assets group; depreciable asset needs IT block, life, method and a Schedule II class or an override reason; asset no unique per client |
| F-21 | Events: cost > 0; put-to-use date >= purchase date; an addition needs an earlier opening / purchase; no event after a disposal; disposal date >= put-to-use date; one start and one disposal per asset |
| F-22 | Disposal: sale proceeds >= 0; disposal date inside the FY; profit / loss on sale is a working (proceeds - (cost - accumulated book depreciation to the disposal date)); the sale voucher is entered by the accountant |
| F-23 | Companies Act book depreciation: SLM `(cost - residual) / life x days / days-in-FY`; WDV `(cost - accumulated) x rate x days / days-in-FY` with `rate% = round_half_up((1 - (residual/cost)^(1/life)) x 100, 2)`; days = put-to-use (or FY start) to FY end (or disposal date), both counted; each addition is its own tranche with the same residual percentage |
| F-24 | Residual value above the class ceiling (5%) -> warning; life different from the class -> override reason shown on the run |
| F-25 | Depreciation never exceeds cost - residual (cumulative); an asset fully depreciated gets 0 |
| F-26 | One active Companies Act run per FY; it posts ONE draft Journal: Dr `depreciation_expense`, Cr the asset's accumulated-depreciation ledger (or the asset ledger when none) per asset; re-running needs the previous run's voucher reversed (or the draft deleted) |
| F-27 | Run lines keep days, rate, method and rule row used (reproducible) |
| F-30 | Income-tax depreciation is block-wise: rate = `dep_it_block_rates` row of the FY end date, opening WDV from `it_block_openings` (first year typed, later carried) |
| F-31 | Half rate: an addition put to use for **fewer than** `half_rate_days` (180) days in the FY (days = put-to-use to 31 March, both counted) gets `half_rate_percent` (50%) of the rate; 180 or more gets the full rate |
| F-32 | `depreciation = round_half_up(base_full x rate + base_half x rate x half%, 2)` where `base_full = opening + additions_full - disposals`; a deficit (disposals above base_full) is set against `additions_half`; if still negative the block is flagged `negative_block` (short-term capital gain, for the CA; no depreciation, no number invented) |
| F-33 | Block with no asset left but WDV > 0, or any other case the law treats specially (terminal depreciation, additional depreciation, assets of a business not in use): **flag only**, never computed |
| F-34 | The IT working is a working only: no voucher, no ledger effect; `final` finalises it for carry-forward; rate row status (`pending`) is printed on the working |
| F-40 | Statements read posted / reversed vouchers only, excluding the closing vouchers of a closed year; the Trial Balance must balance and the FY's opening balances must satisfy Dr = Cr (else blocked, using the Phase 1 check) |
| F-41 | Closing stock approved for the FY (`final_closing_stock`) is required for trading and manufacturing clients; a service client may record `source = none` explicitly. Never guessed |
| F-42 | Trading A/c: Dr opening stock + purchases - purchase returns + direct expenses (+ gross loss); Cr sales - sales returns + direct incomes + closing stock (+ gross profit) |
| F-43 | Profit and Loss: gross profit / loss + indirect incomes - indirect expenses; for partnership / LLP net profit **before** appropriation, then the appropriation account (interest, remuneration, share per ratio) |
| F-44 | Schedule III: every ledger must map to a line (ledger override, else group default). A ledger in a group with no default is an **error**; a ledger on a non-firm default is a **warning** listing the ledger |
| F-44b | Balance sheet balances: total assets = total equity and liabilities including the current year's profit; any difference is shown and blocks finalising |
| F-45 | Previous-year comparatives: the signed-off snapshot of the previous FY, else a recomputation if the previous FY has data and an approved closing stock; otherwise the column shows "-" and a warning; never guessed |
| F-46 | Schedule III notes: every line with a note title carries the ledger breakup (note number, drill-down ledgers); property, plant and equipment note = gross block, additions, disposals, accumulated depreciation, net block from the register |
| F-47 | Format by entity: company -> Schedule III (Division I); proprietorship / partnership / LLP -> vertical or horizontal (the user chooses, default horizontal for non-company) |
| F-48 | Every statement line carries drill-down references (ledger ids and amounts) that open the ledger statement; exports print them as the ledger names and amounts |
| F-49 | Cash Flow (AS 3, indirect): net profit before tax and extraordinary items, + non-cash (depreciation and amortisation), +/- items classified investing / financing (interest and dividends by the ledger's cash-flow class), working-capital movements from the balance-sheet lines (opening balances of the FY vs closing), investing, financing; opening and closing cash = Cash-in-hand + Bank (cash and cash equivalents) |
| F-50 | The Cash Flow closing cash must equal the balance sheet cash and bank; a difference blocks the statement. Required only where the client is a company or the accountant asks for it |
| F-60 | Year-end close prerequisites: no draft / approved voucher in the FY; TB balanced; opening Dr = Cr; Companies Act depreciation run posted when the client has depreciable assets (or an explicit "no depreciation" confirmation); closing stock approved; balance sheet balances; the next FY exists (created by the service with its 12 periods if the accountant confirms) |
| F-61 | Close is blocked while the client is a partnership / LLP and any partner has no profit share for the FY |
| F-62 | Partners' shares for the FY add to exactly 100.0000; shares of the closing balance are `round_half_up(balance x share / 100, 2)`, the last partner takes the remainder |
| F-63 | The three closing vouchers are Journals dated the FY end, narrated, `reference_no = YEC/<fy>/<step>`; created, approved, posted through the voucher service in one transaction; then the year's periods are locked (`periods` service), snapshots are stored final, IT workings are finalised, `year_end_closes` is written, carry-forward is done |
| F-64 | A closing voucher cannot be reversed on its own; reopen reverses trading / P&L / appropriation vouchers in reverse order dated the FY end (period unlocked first), supersedes the snapshots and final workings, marks the close `reopened` with reason; blocked if the next FY has a posted voucher (carry-forward would be wrong) |
| F-65 | Carry-forward: opening for the next FY = closing balance of every ledger of Asset / Liability nature (after the closing entries) that is not zero; total Dr must equal total Cr exactly or nothing is written |
| F-66 | Open bills carry with the same reference, dates and amounts (Phase 2 bill engine closing position); they must tie to the party ledger's carried opening (B-07); stock carries per item and godown (Phase 5 S-08) |
| F-67 | Re-closing after reopen replaces the NEXT FY's openings only if that FY has no posted voucher; otherwise refused |
| F-70 | Export: Excel (openpyxl, one sheet per statement, ledger drill-down references as a column and as hyperlinks to a `Ledgers` sheet) and PDF (one document, statement pages and the schedule notes); both carry client, FY, basis (format, closing stock method, rule statuses `pending`) and the engine version |
| F-71 | Nothing is exported while a statement has an error finding; warnings are printed on the page |

## Engine design (pure functions; no DB, web, AI imports; Decimal only; `round_half_up` from `engine/money.py`)
* `engine/final_adjustments.py` - `build_adjustment(inp, ctx) -> AdjustmentResult | list[Finding]`; `doubtful_provision(debtors_closing, rate, existing_provision)`; `interest_on_capital(balance_segments, rate, fy_start, fy_end)`; `interest_on_drawings(drawings, rate, fy_end)`; `remuneration(annual, months)`; `reversal_lines(lines)`.
* `engine/final_assets.py` - `days_inclusive(a, b)`, `days_in_year(fy_start, fy_end)`, `wdv_rate_percent(cost, residual, life)`, `book_depreciation(setup, fy_start, fy_end, rules) -> list[BookDepreciationLine]`, `disposal_working(...)`, `depreciation_journal_lines(lines, roles)`.
* `engine/final_it_depreciation.py` - `it_block_depreciation(ItBlockInput) -> ItBlockResult` (F-30..F-34).
* `engine/final_statements.py` - `build_trading`, `build_profit_loss`, `build_appropriation`, `build_balance_sheet(format)` over `LedgerBalanceIn` + `ClosingStockIn` + entity; drill-down on every line; findings F-40..F-44b.
* `engine/final_sch3.py` - `build_sch3_balance_sheet`, `build_sch3_pl`, `build_notes`, comparatives merge (F-44..F-47).
* `engine/final_cashflow.py` - `build_cash_flow(opening_positions, closing_positions, profit, ...)` (F-49, F-50).
* `engine/final_close.py` - `build_closing_vouchers(...) -> list[ClosingVoucherDraft]`, `share_profit(balance, partners)` (F-62), `carry_forward(closing_balances) -> CarryForward` (F-65).
* `engine/final_types.py` - the data types (this step).
Services load data and call the engine; **no service computes an amount**. Services: `services/final_adjustments.py`, `final_assets.py`, `final_closing_stock.py`, `final_statements.py` (loaders: ledger balances for the FY excluding closing vouchers, closing stock, classification, partners), `final_sch3.py`, `final_cashflow.py`, `final_export.py`, `final_close.py`; hook `final_hooks.py` (this step: `year_is_closed`, `guard_reverse`).

## Worked mini-example (one proprietorship, trading; every figure typed by hand; used as test data in packages A..G)
Opening balances 01-04-2026 (Dr = Cr = 6,00,000): Dr Opening Stock 2,00,000; Furniture 1,00,000; Sundry Debtors 1,50,000; Cash 30,000; Bank 1,20,000. Cr Capital 5,00,000; Creditors 80,000; Loan 20,000.
Trial balance before adjustments, 31-03-2027 (Dr = Cr = 18,85,000): Dr Opening Stock 2,00,000; Purchases 8,00,000; Freight 30,000; Salary 1,20,000; Rent 60,000; Electricity 20,000; Drawings 1,00,000; Furniture 1,00,000; Debtors 2,50,000; Cash 25,000; Bank 1,80,000. Cr Capital 5,00,000; Loan 20,000; Creditors 1,60,000; Sales 12,00,000; Interest Income 5,000.

**Adjustments (draft journals, package A)**
| # | Helper | Entry | Rule |
| --- | --- | --- | --- |
| 1 | Outstanding rent 5,000 | Dr Rent 5,000 / Cr Outstanding Expenses 5,000 | F-03 |
| 2 | Prepaid electricity 2,000 | Dr Prepaid Expenses 2,000 / Cr Electricity 2,000 | F-03 |
| 3 | Bad debt Mr A 10,000 | Dr Bad Debts 10,000 / Cr Debtor 10,000 (debtors 2,40,000) | F-06 |
| 4 | Provision 5% on 2,40,000 | required 12,000.00, existing 0 -> Dr Provision for Doubtful Debts Exp 12,000 / Cr Provision 12,000 | F-05 |
| 5 | Depreciation furniture (see below) | Dr Depreciation 10,000 / Cr Accumulated Depreciation 10,000 | F-23, F-26 |
Closing stock approved: cost 2,60,000; AS 2 write-down 10,000 (NRV lower on one item); **carrying 2,50,000** (F-41).

**Book depreciation (package B).** SLM, furniture cost 1,00,000, life 10 years, residual 0, in use all year: `100000/10 x 365/365` = **10,000.00**. SLM, machine cost 2,00,000, residual 10,000 (5%), life 15, put to use 01-10-2026 (182 days of 365): `190000/15 x 182/365 = 34,580,000 / 5,475` = **6,315.98**. WDV, cost 1,00,000, residual 4,000, life 2: rate `1 - (0.04)^(1/2) = 80.00%`; year 1 = 80,000.00 (closing WDV 20,000), year 2 = 16,000.00 (WDV 4,000 = residual, then 0, F-25).
**Income-tax block (working, package B).** Plant and machinery 15%: opening WDV 5,00,000; addition A 2,00,000 put to use 01-10-2026 (182 days, >= 180, full); addition B 1,00,000 put to use 15-11-2026 (137 days, < 180, half); disposal proceeds 50,000. `base_full = 5,00,000 + 2,00,000 - 50,000 = 6,50,000` x 15% = 97,500.00; `base_half = 1,00,000` x 7.5% = 7,500.00; **depreciation 1,05,000.00**; closing WDV `5,00,000 + 3,00,000 - 50,000 - 1,05,000` = **6,45,000.00**.

**Trading A/c (package C, F-42)**
| Dr | Amount | Cr | Amount |
| --- | --- | --- | --- |
| To Opening Stock | 2,00,000 | By Sales | 12,00,000 |
| To Purchases | 8,00,000 | By Closing Stock (carrying) | 2,50,000 |
| To Freight (direct expense) | 30,000 | | |
| To Gross Profit c/d | 4,20,000 | | |
| | 14,50,000 | | 14,50,000 |

**Profit and Loss A/c (F-43)**
| Dr | Amount | Cr | Amount |
| --- | --- | --- | --- |
| To Salary | 1,20,000 | By Gross Profit b/d | 4,20,000 |
| To Rent (60,000 + 5,000) | 65,000 | By Interest Income | 5,000 |
| To Electricity (20,000 - 2,000) | 18,000 | | |
| To Depreciation | 10,000 | | |
| To Bad Debts | 10,000 | | |
| To Provision for Doubtful Debts | 12,000 | | |
| To Net Profit (to Capital) | 1,90,000 | | |
| | 4,25,000 | | 4,25,000 |

**Balance Sheet, horizontal (as on 31-03-2027)**
| Liabilities | Amount | Assets | Amount |
| --- | --- | --- | --- |
| Capital 5,00,000 + profit 1,90,000 - drawings 1,00,000 | 5,90,000 | Furniture 1,00,000 - dep 10,000 | 90,000 |
| Loan | 20,000 | Closing Stock | 2,50,000 |
| Sundry Creditors | 1,60,000 | Sundry Debtors 2,40,000 - provision 12,000 | 2,28,000 |
| Outstanding Expenses | 5,000 | Prepaid Expenses | 2,000 |
| | | Cash | 25,000 |
| | | Bank | 1,80,000 |
| | 7,75,000 | | 7,75,000 |
Vertical format (one column, F-47): **Sources of funds** Capital 5,90,000 + Loan 20,000 = 6,10,000. **Application of funds** Net fixed assets 90,000 + Net current assets 5,20,000 (current assets: stock 2,50,000 + debtors net 2,28,000 + prepaid 2,000 + cash 25,000 + bank 1,80,000 = 6,85,000; less current liabilities: creditors 1,60,000 + outstanding 5,000 = 1,65,000) = 6,10,000.

**Partnership appropriation (package C, F-43, F-62; separate case)** Net profit before appropriation 2,50,000; partners A and B, ratio 3:2; capital A 3,00,000, B 2,00,000 at 10% (deed): interest 30,000 and 20,000 (F-07: 3,00,000 x 10% x 365/365); A's remuneration 5,000 x 12 = 60,000 (F-08). Balance to share `2,50,000 - 50,000 - 60,000 = 1,40,000`: A 84,000.00, B 56,000.00. A's total 30,000 + 60,000 + 84,000 = 1,74,000; B 76,000; sum 2,50,000. Remainder case: balance 1,00,001.00 split 3:2 -> A 60,000.60, B (last) 40,000.40.

**Schedule III (package D; the same books as a company with no drawings and an extra 1,00,000 in bank, closing stock and profit as above)**
Equity and liabilities: Shareholders' funds - Share capital 5,00,000 (note 1); Reserves and surplus 1,90,000 (note 2); Non-current liabilities - Long-term borrowings 20,000 (note 3, ledger override); Current liabilities - Trade payables 1,60,000 (note 4); Other current liabilities 5,000 (note 5). **Total 8,75,000.** Assets: Non-current - PPE (net) 90,000 (note 6); Current - Inventories 2,50,000 (note 7); Trade receivables 2,28,000 (note 8); Cash and cash equivalents 2,05,000 + 1,00,000 = 3,05,000 (note 9); Short-term loans and advances / other current assets - prepaid 2,000 (note 10). **Total 8,75,000.** Previous-year column "-" with warning F-45 for a first year. P&L: Revenue from operations 12,00,000; Other income 5,000; Expenses: purchases of stock-in-trade 8,00,000; changes in inventories `2,00,000 - 2,50,000 = (50,000)`; employee benefits 1,20,000 (salary, ledger override); depreciation 10,000; other expenses (freight 30,000 + rent 65,000 + electricity 18,000 + bad debts 10,000 + provision 12,000) 1,35,000; total expenses 10,15,000; **profit before tax 1,90,000**.

**Cash Flow, indirect (package E, proprietorship book, F-49)**
Opening cash and bank 30,000 + 1,20,000 = 1,50,000. A. Operating: net profit 1,90,000 + depreciation 10,000 - interest income 5,000 (shown under investing) = 1,95,000; increase in inventories (2,50,000 - 2,00,000) = (50,000); increase in debtors net (2,28,000 - 1,50,000) = (78,000); increase in prepaid (2,000); increase in creditors (1,60,000 - 80,000) = +80,000; increase in outstanding expenses +5,000 -> **cash from operations 1,50,000**. B. Investing: interest received +5,000 (no fixed asset purchase). C. Financing: drawings (1,00,000); loan unchanged 0. **Net increase 55,000**; closing 2,05,000 = cash 25,000 + bank 1,80,000 (F-50 check).

**Year-end close (package F, F-63)** Voucher 1 "Trading" (Journal, 31-03-2027): Dr Sales 12,00,000; Dr Stock ledger 50,000 (closing 2,50,000 less opening 2,00,000); Cr Purchases 8,00,000; Cr Freight 30,000; Cr Trading A/c 4,20,000 (Dr = Cr = 12,50,000). Voucher 2 "Profit and loss": Dr Trading A/c 4,20,000; Dr Interest Income 5,000; Cr Salary 1,20,000; Cr Rent 65,000; Cr Electricity 18,000; Cr Depreciation 10,000; Cr Bad Debts 10,000; Cr Provision Expense 12,000; Cr P&L A/c 1,90,000 (4,25,000 each side). Voucher 3 "Appropriation" (proprietor): Dr P&L A/c 1,90,000; Cr Drawings 1,00,000; Cr Capital 90,000.
Carried to 01-04-2027 (Dr = Cr = 7,97,000): Dr Furniture 1,00,000; Stock ledger 2,50,000; Debtors 2,40,000; Prepaid 2,000; Cash 25,000; Bank 1,80,000. Cr Capital 5,90,000; Loan 20,000; Creditors 1,60,000; Outstanding Expenses 5,000; Provision for Doubtful Debts 12,000; Accumulated Depreciation 10,000. Open bills of the debtors and creditors carry with their references; stock carries per item at carrying value; IT block WDV carries from the final working.

## Packages and file ownership (parallel agents never collide)
After 6.0 nobody edits `main.py`, `database/**`, `engine/final_types.py` signatures (add optional fields at the end, via the main agent), `services/final_hooks.py`. `services/vouchers.py` is edited **only by package F** (one line: `final_hooks.guard_reverse` in `reverse`) and `services/client_setup.py` **only by F** (opening-balance freeze). Decision rows go to `docs/decisions_parts/<pkg>.md`, status to `docs/progress_parts/<pkg>.md`; tests in new files named for the area. DB runs through `scripts/dbrun.sh`.

| Pkg | Creates / edits | Never touches | Depends on |
| --- | --- | --- | --- |
| A adjustments + partners | `engine/final_adjustments.py` (F-01..F-11), `services/final_adjustments.py` (partners, partner terms, ledger roles, `setup-ledgers`, helper -> draft journal via voucher service, auto-reversal), `db/repositories_final_adjustments.py`, `api/final_adjustments.py`, `api/schemas_final_adjustments.py` | statements, assets, close | none (voucher service read-only use) |
| B fixed assets + depreciation | `engine/final_assets.py`, `engine/final_it_depreciation.py` (F-20..F-34, pure; worked examples above are the first tests), `services/final_assets.py` (register, events, Companies Act run -> draft journal, IT working, finalise), `db/repositories_final_assets.py`, `api/final_assets.py`, `api/schemas_final_assets.py` | statements, close | none (engine); A for role ledgers (literal ids before merge) |
| C closing stock + Trading / P&L / Balance Sheet (non-company) | `engine/final_statements.py` (F-40..F-43, F-44b non-company, F-48), `services/final_closing_stock.py` (approve from Phase 5 closing-stock report or manual, F-41, audit), `services/final_statements.py` (loaders: ledger balances excluding closing vouchers; role overlay; appropriation), `db/repositories_final_statements.py`, `api/final_statements.py`, `api/schemas_final_statements.py` | schedule III, cash flow, close | none (pure engine, literal data); Phase 5 `inventory_reports.closing_stock` read-only |
| D Schedule III | `engine/final_sch3.py` (F-44..F-47), `services/final_sch3.py` (classification CRUD for `client_ledger_fs_map`, notes assembly, comparatives from snapshots / recomputation), `db/repositories_final_sch3.py`, `api/final_sch3.py`, `api/schemas_final_sch3.py` | other statements | C's loader (`final_statements.ledger_positions`) after merge; literal data before |
| E cash flow + export | `engine/final_cashflow.py` (F-49, F-50), `services/final_cashflow.py`, `services/final_export.py` (openpyxl; PDF library per decision), `api/final_cashflow.py`, `api/final_export.py`, schemas | engine of C / D | C and D (consumes their Statement objects) |
| F year-end close | `engine/final_close.py` (F-62, F-65), `services/final_close.py` (prerequisites F-60, create / approve / post three journals through the voucher service, lock periods, snapshots, IT finalise, carry-forward of openings / bills / stock / IT, reopen), `db/repositories_final_close.py`, `api/final_close.py`, `api/schemas_final_close.py`, the two one-line hook calls in `services/vouchers.py` and `services/client_setup.py`, a `create_next_financial_year` function in `services/final_close.py` (not in client_setup) | statements engines | C (statements for snapshots), B (IT finalise), Phase 2 bill engine, Phase 5 stock repository |
| G test pack + acceptance | `docs/test-packs/phase6-*/**` (accountant-prepared full-year proprietor and partnership clients; company Schedule III case), `backend/tests/acceptance/pack_loader_p6.py`, `pack_runner_p6.py`, `scripts/build_verification_sheet_p6.py`, `PHASE6_SIGNOFF.md` | engines, services | A..F merged |

**Parallel split.** Wave 1 (no dependencies): **A, B, C, D** (D and C meet only through `LedgerBalanceIn`; D uses literal inputs until C's loader merges) and the hand-worked packs of G. Wave 2: **E** (needs C and D Statement objects) and **F** (needs C; B for the IT finalise) in parallel. Wave 3: G acceptance. A UI package (separate, later) can start from the contract in wave 2. Shared-file conflicts: only `main.py` (done in 6.0), `vouchers.py` / `client_setup.py` (F only).

## Steps
6.0 plan + schema + seeds + types + stubs + hook (this commit). 6.1 A + B + C + D (parallel). 6.2 E + F (parallel). 6.3 G acceptance (a full-year accountant-prepared client; every statement matches to the rupee), report to owner. Each step: tests first, full suite + `ruff check .` before every commit (owner's limit on test runs: targeted tests per package, the full suite by the main agent at merge), 5-line status in PROGRESS.md.

## Sign-off questions (for the accountant at the end of the phase)
1. Statements exclude the closing vouchers (the year's trading stays visible after close). 2. One stock ledger carries closing stock into next year's opening. 3. Partnership: interest and remuneration shown in an appropriation section; profit share on the balance; last partner takes the rounding remainder. 4. Book depreciation: each addition is its own tranche with the same residual percentage; days counted inclusively. 5. IT block: disposal deficit set against half-rate additions (F-32); terminal depreciation, additional depreciation and negative blocks are flagged, not computed. 6. Stock carried at carrying value (cost or NRV) per item. 7. Drawings closed to capital for a proprietorship at year end.

## Suggestions (not built)
Dividend / reserve transfer and tax provision journals for companies; Ind AS (Division II) formats; additional (first-year) depreciation; terminal depreciation; extra-shift depreciation; income-tax computation and deferred tax; Companies Act borrowing-cost and CWIP schedules; partners' remuneration limits under the Income-tax Act (book profit); carry-forward of unreconciled bank items (Phase 2 `bank_opening_items`); consolidated multi-year comparatives beyond one previous year; Tally export of closing entries (Phase 7); XBRL.
