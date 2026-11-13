-- Seed: owner-supplied legal values for Phase 4 (corrects 0008 / 0009; a recorded seed never re-runs, so corrections live in a new file).
-- Safe to run more than once (plain UPDATEs by key, idempotent). Schema-agnostic.
-- Source of the values: the owner (2026-11-13). The official pages named below returned HTTP 403 to our fetch, so we could not read them ourselves:
-- every value is stored as 'secondary_verified' (not 'verified') until someone with access confirms the official text.
-- Still pending (not touched): TCS rates / limits (section 394), the 194Q buyer-turnover limit (Rs 10 crore), the 1961-Act rows.

-- Rent (ex-194-I): section 393(1) rent entry. Rs 50,000 for a month or part of a month; 2% for a person other than a specified person
-- (ex-194-IB); a specified person: 2% machinery / plant / equipment, 10% land / building / furniture.
UPDATE tds_rates SET monthly_threshold = 50000, annual_threshold = NULL, single_payment_threshold = NULL, threshold_mode = 'whole_amount',
    verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) rent entry, https://www.incometaxindia.gov.in/w/section-393-5 (page not readable by us: HTTP 403)',
    notes = 'Rs 50,000 for a month or part of a month (not Rs 6,00,000 a year). 2% machinery / plant / equipment. No-PAN rate 20% (s.397(2)).'
WHERE nature_key = 'rent_plant_machinery' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

UPDATE tds_rates SET monthly_threshold = 50000, annual_threshold = NULL, single_payment_threshold = NULL, threshold_mode = 'whole_amount',
    verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) rent entry, https://www.incometaxindia.gov.in/w/section-393-5 (page not readable by us: HTTP 403)',
    notes = 'Rs 50,000 for a month or part of a month (not Rs 6,00,000 a year). 10% land / building / furniture for a specified person (the 2% rate for a person other than a specified person, ex-194-IB, is not modelled in this table: owner / CA to confirm how the deductee is classified). No-PAN rate 20% (s.397(2)).'
WHERE nature_key = 'rent_land_building' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

UPDATE tds_section_refs SET table_ref = 'rent entry (Sl. 2 as reported)', verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) rent entry, https://www.incometaxindia.gov.in/w/section-393-5 (page not readable by us: HTTP 403)',
    notes = 'Payment code of the new statement not verified'
WHERE nature_key IN ('rent_plant_machinery', 'rent_land_building') AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

UPDATE tds_natures SET verification_status = 'secondary_verified'
WHERE nature_key IN ('rent_plant_machinery', 'rent_land_building', 'contract_prof_by_individual_huf', 'partner_payment');

-- Ex-194M: Rs 50,00,000 a year, 2%, s.393(1) Table Sl.6(ii).
UPDATE tds_rates SET rate = 2, annual_threshold = 5000000, verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) Table Sl.6(ii); official page not read by us',
    notes = 'Rs 50,00,000 per year (owner-supplied; resolves the 50,00,000 vs 50,000 conflict of the earlier secondary pages). No-PAN rate 20% (s.397(2)).'
WHERE nature_key = 'contract_prof_by_individual_huf' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';
UPDATE tds_section_refs SET table_ref = 'Sl. 6(ii)', verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) Table Sl.6(ii); official page not read by us'
WHERE nature_key = 'contract_prof_by_individual_huf' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

-- Ex-194T: payments to a partner, 10%, Rs 20,000 aggregate a year, s.393(3) Table Sl.7, payment code 1067.
UPDATE tds_rates SET rate = 10, annual_threshold = 20000, verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(3) Table Sl.7; official page not read by us',
    notes = '10% on payments to a partner above Rs 20,000 aggregate in the year. No-PAN rate 20% (s.397(2)).'
WHERE nature_key = 'partner_payment' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';
UPDATE tds_section_refs SET section_ref = '393(3)', table_ref = 'Sl. 7', payment_code = '1067', verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(3) Table Sl.7, payment code 1067; official page not read by us',
    notes = 'Payment code 1067 (owner-supplied)'
WHERE nature_key = 'partner_payment' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

-- Ex-194Q: 0.1% on purchases above Rs 50,00,000 in the year, s.393(1) Table Sl.8(ii); no-PAN 5% (s.397(2)). Buyer-turnover limit stays pending.
UPDATE tds_rates SET rate = 0.1, annual_threshold = 5000000, threshold_mode = 'excess_only', no_pan_rate = 5, verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) Table Sl.8(ii); no-PAN 5% from s.397(2) FAQ; official pages not read by us',
    notes = 'Tax only on purchases above Rs 50,00,000 per seller per year. No-PAN rate 5% (s.397(2)). The buyer-turnover limit (recalled Rs 10 crore) is STILL PENDING (client flag tds_client_fy_flags).'
WHERE nature_key = 'purchase_of_goods' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';
UPDATE tds_section_refs SET table_ref = 'Sl. 8(ii)', verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393(1) Table Sl.8(ii); official page not read by us'
WHERE nature_key = 'purchase_of_goods' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

-- Ex-194O e-commerce: no-PAN 5% (s.397(2)); rate and threshold unchanged.
UPDATE tds_rates SET no_pan_rate = 5, verification_status = 'secondary_verified',
    source_reference = 'Secondary pages (rate, threshold); no-PAN 5% from s.397(2) FAQ https://www.incometaxindia.gov.in/documents/d/guest/faqs-on-higher-rate-of-tds-under-section-397 (owner-supplied; page not readable by us: HTTP 403)'
WHERE nature_key = 'ecommerce_participant' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

-- No PAN, s.397(2): the higher of the specified rate, the rate in force and 20%; 5% instead of 20% for purchase of goods (ex-194Q) and e-commerce (ex-194-O).
UPDATE tds_provisions SET section_ref = '397(2)', verification_status = 'secondary_verified',
    description = 'Higher rate of tax when the deductee''s PAN is not furnished or is invalid: the higher of the specified rate, the rate in force and 20%; 5% instead of 20% for purchase of goods (ex-194Q) and e-commerce (ex-194-O). The rate used is no_pan_rate of tds_rates.',
    source_reference = 'Owner-supplied (2026-11-13): https://www.incometaxindia.gov.in/documents/d/guest/faqs-on-higher-rate-of-tds-under-section-397 (page not readable by us: HTTP 403)',
    notes = 'Section 397(2) (owner-supplied). TCS no-PAN (ex-206CC) is NOT covered: still pending.'
WHERE provision_key = 'no_pan_higher_rate' AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';

-- Deposit by the 7th (Rule 218), March deductions by 30 April, statements 31 Jul / 31 Oct / 31 Jan / 31 May (Rule 219).
UPDATE tds_due_dates SET verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13): Income-tax Rules 2026, Rule 218 (deposit by 7th; March deductions by 30 April), Rule 219 (statements 31 Jul, 31 Oct, 31 Jan, 31 May); official rules not read by us'
WHERE due_key IN ('tds_challan_regular', 'tds_challan_march', 'tcs_challan_regular', 'tcs_challan_march',
                  'tds_return_q1', 'tds_return_q2', 'tds_return_q3', 'tds_return_q4',
                  'tcs_return_q1', 'tcs_return_q2', 'tcs_return_q3', 'tcs_return_q4')
  AND effective_from = DATE '2026-04-01';

-- Forms: 138 salary, 140 non-salary (resident), 130 salary certificate (owner-confirmed; already secondary_verified in 0009).
UPDATE tds_forms SET verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13) and secondary pages (taxaj.com, taxscan.in, businesstoday.in); CBDT form list not read by us'
WHERE form_key IN ('return_salary', 'return_non_salary_resident', 'certificate_salary') AND act = 'it_act_2025' AND effective_from = DATE '2026-04-01';
