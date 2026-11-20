-- Seed 0015 (Phase 8): tax audit report forms and the clauses that can be derived from the books. System data, idempotent.
-- Form 3CD (Income-tax Act 1961, Rule 6G) is replaced by Form 26 (Income-tax Act 2025 s.63, Income-tax Rules 2026 r.47) for tax year 2026-27
-- onwards, per the CBDT FAQ and secondary pages seen in planning step 8.0. The CLAUSE NUMBERING of Form 26 was NOT read: no Form 26 clause is seeded
-- (package F reads the official form at https://www.incometaxindia.gov.in/documents/d/guest/fn-26 and adds them, still 'pending' until the owner confirms).
-- Form 3CD clause numbers and titles are recalled and all 'pending'. Clauses not listed here are entered by hand (origin = manual).

INSERT INTO audit_form_defs (form_key, title, law, section_ref, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('form_3cd', 'Form 3CD - statement of particulars (tax audit, Income-tax Act 1961)', 'it_act_1961', 'section 44AB, Rule 6G',
     DATE '1900-01-01', DATE '2026-03-31',
     'Income-tax Act 1961 / Rules 1962; replacement by Form 26 reported by visaverge.com and taxscan.in (secondary pages)', 'secondary_verified',
     'Applies to FY 2025-26 and earlier.'),
    ('form_26', 'Form 26 - tax audit report and statement of particulars (Income-tax Act 2025)', 'it_act_2025', 'section 63, Rule 47 of the Income-tax Rules 2026',
     DATE '2026-04-01', NULL,
     'CBDT FAQ https://www.incometaxindia.gov.in/documents/d/guest/form-26-faqs and https://www.incometaxindia.gov.in/documents/d/guest/fn-26 (names found by search, pages not read); secondary pages say it consolidates Forms 3CA / 3CB / 3CD',
     'secondary_verified',
     'Clause numbering not verified. Applies from tax year 2026-27. Draft and final form may differ.')
ON CONFLICT (form_key) DO NOTHING;

INSERT INTO audit_form_clauses (form_key, clause_no, title, derivability, data_source, sort_order, source_reference, verification_status)
VALUES
    ('form_3cd', '18', 'Depreciation allowable under the Income-tax Act (block-wise)', 'partly_books', 'Phase 6 IT depreciation workings', 180,
     'Form 3CD clause 18 as recalled; official form not read', 'pending'),
    ('form_3cd', '21', 'Amounts debited to profit and loss that are inadmissible (capital, personal, 40A(3) cash payments and similar)', 'partly_books', 'A-05 (40A(3)); other heads manual', 210,
     'Form 3CD clause 21 as recalled; official form not read', 'pending'),
    ('form_3cd', '22', 'Interest inadmissible under section 23 of the MSMED Act', 'partly_books', 'A-07', 220,
     'Form 3CD clause 22 as recalled; official form not read', 'pending'),
    ('form_3cd', '23', 'Payments to related persons (section 40A(2)(b))', 'partly_books', 'A-18', 230,
     'Form 3CD clause 23 as recalled; official form not read', 'pending'),
    ('form_3cd', '26', 'Sums covered by section 43B (including payments to MSME)', 'partly_books', 'A-07; statutory dues from Duties & Taxes ledgers', 260,
     'Form 3CD clause 26 as recalled; official form not read', 'pending'),
    ('form_3cd', '27', 'GST input tax credit and indirect tax particulars', 'partly_books', 'A-08; Phase 3 ITC register', 270,
     'Form 3CD clause 27 as recalled; official form not read', 'pending'),
    ('form_3cd', '31', 'Loans, deposits and specified sums taken or repaid in cash (sections 269SS, 269T, 269ST)', 'partly_books', 'A-06', 310,
     'Form 3CD clause 31 as recalled; official form not read', 'pending'),
    ('form_3cd', '34', 'TDS / TCS compliance (deduction, deposit, returns)', 'partly_books', 'A-09, A-10, A-11; Phase 4 returns', 340,
     'Form 3CD clause 34 as recalled; official form not read', 'pending'),
    ('form_3cd', '35', 'Quantitative details of principal items of goods traded', 'books', 'Phase 5 stock register', 350,
     'Form 3CD clause 35 as recalled; official form not read', 'pending'),
    ('form_3cd', '40', 'Accounting ratios (gross profit, net profit, stock-in-trade, material consumed to turnover)', 'books', 'Phase 6 final statements', 400,
     'Form 3CD clause 40 as recalled; official form not read', 'pending'),
    ('form_3cd', '44', 'Break-up of total expenditure by GST registration status of suppliers', 'partly_books', 'party GSTIN / registration; Phase 3 masters', 440,
     'Form 3CD clause 44 as recalled; official form not read', 'pending')
ON CONFLICT (form_key, clause_no) DO NOTHING;
