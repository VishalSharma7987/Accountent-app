# Phase 7 pack: sign-off

| Field | Value |
| --- | --- |
| Pack | phase7-documents-and-ai-2026-27 (synthetic data only) |
| Verified by (name, role) | |
| Date verified (YYYY-MM-DD) | |
| Method (Tally / Excel / paper) | |
| Result | [ ] Approved   [ ] Approved with changes   [ ] Rejected |

## What the accountant checks
1. Each of the 12 documents (`invoices/*.txt`, or the PDF in `pdf/`): the tool must catch the deliberate error listed in `expected_findings.csv`, and nothing else.
2. The tax of every posted invoice and of the credit note (`expected_postings.csv`, `WORKING.md`), and the final balances (`expected_ledger_balances.csv`).
3. The seven items that are not posted and the reason (`expected_decisions.csv`): P7-05 (rate table gap, pending), P7-06, P7-09, P7-10 (rejected), Tally T-S-1 and J-1 (rejected) and Tally J-2 (pending).
4. Masking evidence, bank narrations, the two Tally files and the export read back (`VERIFICATION_SHEET.xlsx`).

## Questions for the accountant (decisions the owner needs; nothing here is law)
1. **Rounding tolerance of 1.00.** A printed figure that differs from the recomputed one by up to 1.00 is a warning (acknowledge and the draft uses the recomputed value);
   above 1.00 it is an error. P7-03 (CGST 360.50 against 360.00) shows the effect: the tool books 4,720.00 although the supplier's bill says 4,720.50, so the creditor ledger is 0.50 below
   the bill. Is 1.00 right? Should the booked value follow the bill when the difference is within the tolerance, or should the 0.50 go to a round-off ledger?
2. **Minimum confidence 0.85.** A field read with a lower confidence is a warning that must be acknowledged (P7-03 invoice date 0.60). Is 0.85 a sensible line for a real model and real scans?
3. **Credit and debit notes.** The reading schema has no field for the reason and the original invoice date, so every note stops with two review findings until the accountant types them
   (P7-12). Should these two be read from the document by the model (the original invoice number already is), with the accountant only confirming?
4. **D-35 gap (Tally GST vouchers).** A Tally sales or purchase voucher with GST ledger lines is imported as plain lines: the books balance, but the voucher is not a GST invoice, so it will
   not reach GSTR-1 / GSTR-3B, the ITC register or GST reconciliation, and no rate / HSN / place-of-supply rule was applied. The tool only warns (rule id D-35, which is also the id of the debit/credit sign rule).
   The pack rejects T-S-1 for this reason. Is a warning enough, or must such vouchers be blocked until entered in GST invoice mode?
5. **Documents that cannot be fixed by typing.** P7-06 (IGST charged on an intra-state supply) and P7-09 (previous year, no number) are rejected; P7-05 waits for a rate rule. Is rejecting with a reason
   the practice you want, and who adds the missing 9403 rate rule?
6. **Rate rules.** Every rate in this pack comes from the seeded EXAMPLE rules (status `pending`: 8415, 1701, 851712, 3004, 9983 and the slabs 0 / 5 / 18 / 40). Please confirm them against the tariff
   before a real client is booked; the tool never invents a missing rate (D-15).
7. **Learning.** After an accept the tool saves the supplier (by GSTIN and by name) and the line mappings from the FINAL values. Is that the behaviour you want, or should each mapping be confirmed separately?

## What real files are still needed (the pack proves the logic, not the real-world input)
* **Real scanned and photographed invoices and a real OCR engine.** The text files here are clean. Real OCR text has misread digits, broken tables and missing columns; a few dozen anonymised invoices of the
  office's usual suppliers (text PDFs and scans) are needed to measure how often the checks fire.
* **A real language model's answers.** The answers in `fixtures/llm_answers.json` are scripted by hand. Real models paraphrase, drop lines, swap columns and sometimes answer outside the schema.
  Run a sample of real documents through the configured free model (owner's switch on, synthetic or anonymised data only) and compare.
* **A real Tally export.** Our reader accepts only the structure of the sample files; Tally Prime / ERP 9 exports (all masters, day book) must be run through the reader before the import is relied on.
  Group names, ISDEEMEDPOSITIVE signs, bill allocations, inventory entries and GST details differ by version.
* **Real bank statements** (CSV, Excel, PDF) from the banks the office uses, including multi-page PDFs and statements with running balances in other layouts.
* The **HSN / SAC tariff** (official), to replace the example rate rules.

## Notes / disagreements with the tool

Signature:
