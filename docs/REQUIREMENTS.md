# LedgerMind AI — Final Requirements & Phase Plan

Approved by owner: 11 Nov 2026. Source: the requirements doc (claude.ai artifact). This file is the repo copy.

## 1. Tool kya hai

LedgerMind AI ek **accountant ka calculator** hai: accountant client ka data deta hai, tool accounting rules lagakar entries, ledger, reports, GST aur TDS working nikalta hai. Har number rule se aayega, guess se nahi.

**User:** CA office ka accountant / article assistant jo bahut saare clients ki accounting aur audit karta hai. Pehle owner khud use karega; owner ki accountant team test karke verify karegi. Sab test pass hone ke baad hi doosre accountants ko dene ka socha jayega.

**Business type se fark:** Accountant ek hai, rules har client ke alag. Tool client profile (business type, entity type, GST type) dekh kar sahi rules chunega.

**Core principle:**
1. AI sirf documents padhta aur samjhata hai. Koi number calculate ya post nahi karta.
2. Python rule engine har calculation karta hai.
3. Har entry: draft → validate → accountant approve → post.
4. Posted entry kabhi delete/edit nahi hoti. Sudhaar sirf reversal entry se.
5. Data adhoora ho to tool guess nahi karta; sawal poochhta hai ya review mein daalta hai.

## 2. Decisions

| Sawal | Decision | Kyun |
| --- | --- | --- |
| Kaun se business | Saare business (trading, service, manufacturing) aur saari entities (proprietor, partnership, LLP, company) | Core sabke liye common, upar business-wise layer |
| Kis order mein | Pehle common core (voucher, ledger, TB, bank, GST, TDS), phir trading stock, manufacturing last | Core har client ko chahiye; manufacturing sabse complex |
| Tally ke saath | Tool ki apni poori books; Tally aur Excel se import aur export dono | Zyadatar clients Tally/Busy par hain |
| Stock | Item-wise quantity hamesha; value period-end par (FIFO ya Weighted Average, client policy). Periodic accounting (Purchase account + year-end Closing Stock) | Indian small business aur Tally ka tarika; AS 2: cost ya NRV jo kam |
| GST setup | Regular aur Composition, Monthly aur QRMP — client profile mein | Har client alag |
| Data input | Excel/CSV, Tally export, PDF, photo, manual — sab ek standard "draft voucher" format mein | Calculator ko input ek format mein chahiye |
| Kahan chalega | Web app (FastAPI + PostgreSQL + React), pehle din se multi-client | Baad mein doosre CA offices ko dena ho to architecture na badle |
| Database | PostgreSQL on Supabase (Free plan for dev/test with dummy data; Pro with backups before real client data). Code plain PostgreSQL ke liye | Free + scalable; provider badalna sirf connection setting |
| AI kab | Engine aur reports sahi hone ke baad (Phase 7). Pehle Excel import se test | Pehle engine khud sahi ho |
| Law ka version | Har rate/rule effective date ke saath rule table mein; transaction date se law chuna jayega | TDS 1961 Act → 2025 Act (1 Apr 2026); GST slabs 22 Sep 2025 se badle |

## 3. Real accountant ka workflow

Source document → Draft voucher → Rules pass? → Accountant OK? → Post voucher → Ledger → Trial Balance → Final Accounts.
Rules fail ya accountant reject → Review queue → sudhaar → dobara draft.
Ledger se GST + TDS working; Period-end adjustments Trial Balance mein; poori books par Audit checks.

## 4. Rules aur checks

Law se aane wali rate/limit code mein nahi, rule table mein effective date aur official source ke saath. Section numbers aur limits build ke waqt official source se verify honge.

**Har voucher par:** Dr total = Cr total (Decimal, paise tak); har line par sirf Dr ya sirf Cr; negative/zero nahi; sirf active ledger aur voucher type ke hisaab se sahi ledger; date open period mein; duplicate check (party + bill no + amount); source document ya authorised reason; posted voucher sirf reversal se sudhrega.

**Voucher types:** Sales, Purchase, Payment, Receipt, Contra, Journal, Credit Note, Debit Note.

**Party/bill-wise:** har payment/receipt bill ke against, advance ya on-account; ageing 0-30/31-60/61-90/90+; MSME supplier payment days ka check (disallowance flag).

**GST:** GSTIN format + check digit; place of supply → CGST+SGST ya IGST; rate HSN/SAC + date se rule table (5%, 18%, 40%, exempt — 22 Sep 2025 se); RCM; ITC eligible tabhi jab tax invoice, goods/service received, supplier ne GSTR-1 mein dikhaya aur GSTR-2B/IMS mein ho, blocked list mein na ho; 180 din unpaid → ITC reversal flag; monthly match Books ↔ GSTR-1 aur Purchase register ↔ IMS ↔ GSTR-2B; GSTR-1 aur GSTR-3B working (filing accountant karega).

**TDS:** payment ya credit jo pehle ho, us date se law: 1 Apr 2026 se pehle 1961 Act, baad mein 2025 Act (Sec 392 salary, Sec 393 baaki); nature/threshold/rate rule table se; PAN na ho to higher rate flag; TDS payable, challan matching, quarterly return data, 26AS/AIS match.

**Compliance:** ek din mein ek party ko cash payment limit (disallowance flag); cash receipt limit (penalty flag); capital vs revenue; proprietor ka personal kharcha Drawings mein.

**Period-end:** outstanding, prepaid, accrued income, provisions; depreciation do books (Companies Act Schedule II aur Income-tax block WDV); closing stock (cost ya NRV jo kam); final accounts format entity-wise (proprietor/firm: Trading, P&L, BS; company: Schedule III; Cash Flow jahan applicable); profit transfer (Capital / partners / Reserves); year close par carry forward.

## 5. Phase-wise plan

Har phase tabhi done jab accountant team ke test cases ka answer tool se paise tak match kare. Ek phase done hue bina agla shuru nahi. Web screens har phase ke saath.

0. **Requirements aur test pack** — done: document approve + pehla test pack (input + expected answer).
1. **Accounting core** — client profile, COA templates, 8 voucher types, voucher rules, posting, ledger, TB, period lock, reversal, Excel import. Done: test pack exact match + har galat voucher reject.
2. **Parties, bank, cash** — bill-wise, ageing, advances, Cash/Bank Book, bank statement import, BRS. Done: BRS haath wale BRS se match.
3. **GST** — rule table, CGST/SGST/IGST, RCM, ITC, GSTR-1/3B working, Books ↔ GSTR-2B/IMS. Done: GST working match + galat invoices pakde jayein.
4. **TDS** — date-wise section mapping, threshold, rate, payable, challan, return data, 26AS/AIS. Done: TDS amount/section match.
5. **Inventory (trading)** — items, stock in/out, FIFO/WAvg, closing stock, stock register. Done: closing stock value match.
6. **Period-end aur Final Accounts** — adjustments, FA register, dono depreciation books, closing entries, final accounts, Schedule III, Cash Flow, Excel/PDF. Done: poore saal ka final account match.
7. **Document input aur AI** — Tally import, OCR, AI draft voucher, approval queue, field source. Done: extraction errors engine/review mein pakde jayein.
8. **Audit assistant** — duplicates, missing bills, cash limits, MSME, GST mismatch, round-amount/Sunday entries, ratio comparison, Form 3CD data. Done: saare injected errors report mein.
9. **Advanced** — payroll (PF/ESI, salary TDS), loans, manufacturing (RM, WIP, FG, BOM). Done: har module ka test pack match.

## 6. Testing aur verification

- Test pack accountant team banayegi/verify karegi: input + expected answer.
- Har pack mein jaan-boojh kar galtiyan (duplicate, galat GSTIN, unbalanced, closed period, cash limit).
- Real data sirf anonymised (PAN, Aadhaar, bank no., naam hata kar). Free AI model par real data kabhi nahi.
- Har phase ke end par saare purane tests dobara.
- Har phase ke end par accountant ka written sign-off.

## 7. Kya nahi banayenge

Portal par filing; audit opinion; LangGraph/agent framework (abhi); accounting Q&A chatbot (core nahi); international accounting; bank/GST portal live connection (abhi sirf file import).

## 8. Open items (defaults)

Phase 1 ka dummy test pack (ABC Traders) Claude banayega, expected answers accountant team verify karegi. Anonymised Tally export Phase 7 se pehle chahiye. Screen ki bhasha English.

## 9. Phase 1 detailed plan (accounting core)

End result: ek client ke vouchers se sahi ledger aur balanced TB; har galat voucher reject. GST/TDS calculation nahi (GST ledgers normal ledger, amount accountant bharega).

1. Project setup: Python + FastAPI, PostgreSQL on Supabase (dev + test projects), pytest, React. Login abhi nahi (sirf owner); doosre users se pehle login aur roles.
2. Tables: clients, financial_years, periods, account_groups, ledgers, opening_balances, vouchers, voucher_lines, audit_log. Amount NUMERIC(18,2). Har table mein client_id.
3. Account groups: Tally jaise standard groups (list in CLAUDE.md).
4. COA templates entity aur business type ke hisaab se.
5. Opening balances: total Dr = total Cr, warna difference dikhe aur posting ruke.
6. Voucher engine: 8 types, FY-wise gapless numbering, Draft → Approved → Posted → Reversed, saare voucher rules.
7. Ledger report: opening, entries, running balance Dr/Cr, closing.
8. Trial Balance: group-wise aur ledger-wise, totals; Dr ≠ Cr to error.
9. Period lock aur reversal (linked).
10. Audit log: create/approve/post/reverse kisne, kab.
11. Excel import: fixed template, galat row ka number aur wajah.
12. Web screens: client, ledger list, voucher entry, ledger report, TB.

Test pack (ABC Traders, April 2026): opening balances + ~30 sahi vouchers + 10 galat vouchers; expected balances haath se, team verify kare.

Phase 1 done: team-verified pack paise tak match; saare galat vouchers sahi wajah se reject; automated tests pass; accountant sign-off.
