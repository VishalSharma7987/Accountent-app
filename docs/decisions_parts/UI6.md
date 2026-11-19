| date | step | decision | reason |
| --- | --- | --- | --- |
| 2026-11-19 | UI6 | Drill-down opens the existing Ledger statement as /statement?ledger=&from=&to=; Statement.tsx reads these params (small edit, auto-runs). | Contract says drill-down opens the Phase 1 statement; the screen had no URL input. |
| 2026-11-19 | UI6 | Cash flow, export and year-end close screens are coded to the contract only (p6-e / p6-f had no commits). | Packages E and F built in parallel. |
| 2026-11-19 | UI6 | Company clients: Trading/P&L/BS screen links to Schedule III; Schedule III shows the statement plus F-44 findings from the 422 `unclassified` details. | Contract: company uses /final/sch3/*. |
| 2026-11-19 | UI6 | No accounting maths in the browser: only text validation (2 decimals, months 1-12, deed reference present); totals and shares come from the server. | CLAUDE.md principle 1. |
