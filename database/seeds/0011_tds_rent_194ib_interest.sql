-- Seed: Phase 4.1 owner-supplied legal values (2026-11-13): rent by an individual / HUF not liable to tax audit (ex-194-IB), the rent
-- classification rule, the GST-excluded base, interest on late deduction / deposit and the rounding rule.
-- Safe to run more than once (INSERT ... ON CONFLICT and plain UPDATEs by key). Schema-agnostic. A recorded seed never re-runs, so
-- corrections to 0008 / 0009 live in this new file (like 0010).
-- Every value below is 'secondary_verified' at best (the owner supplied it; the official pages could not be read by us), EXCEPT the
-- reading "the whole month's rent once the month is above Rs 50,000" for ex-194-IB, which stays 'pending' for the CA.

-- ---- ex-194-IB: rent by an individual / HUF not liable to tax audit in the preceding year ---------------------------------------
-- The nature is never chosen by the accountant: the engine turns 'rent_land_building' into 'rent_194ib' from the client's answer
-- (tds_deductor_fy_profile, migration 0015), rule T-19.
INSERT INTO tds_natures (nature_key, kind, description, rate_mode, sort_order, source_reference, verification_status)
VALUES
    ('rent_194ib', 'tds', 'Rent of land, building or furniture paid by an individual / HUF not liable to tax audit (ex-194-IB; picked by the system from the client profile)', 'flat', 55,
     'Owner-supplied (2026-11-13): rent paid by an individual / HUF not liable to tax audit in the preceding year; Income-tax Act 2025 s.393 entry for ex-194-IB; official page not read by us', 'secondary_verified')
ON CONFLICT (nature_key) DO UPDATE SET kind = EXCLUDED.kind, description = EXCLUDED.description, rate_mode = EXCLUDED.rate_mode,
    sort_order = EXCLUDED.sort_order, source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status;

INSERT INTO tds_section_refs (nature_key, act, section_ref, table_ref, payment_code, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('rent_194ib', 'it_act_1961', '194-IB', NULL, NULL, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 section number as recalled; the 1961 row is not owner-supplied', 'pending', 'Payment code of the old statements not seeded.'),
    ('rent_194ib', 'it_act_2025', '393(1)', 'rent entry (ex-194-IB)', NULL, DATE '2026-04-01', NULL,
     'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393 entry for ex-194-IB; official page not read by us', 'secondary_verified',
     'Table serial and payment code of the new statement not verified.')
ON CONFLICT (nature_key, act, effective_from) DO UPDATE SET section_ref = EXCLUDED.section_ref, table_ref = EXCLUDED.table_ref,
    payment_code = EXCLUDED.payment_code, effective_to = EXCLUDED.effective_to, source_reference = EXCLUDED.source_reference,
    verification_status = EXCLUDED.verification_status, notes = EXCLUDED.notes;

INSERT INTO tds_rates (nature_key, act, deductee_group, rate, no_pan_rate, single_payment_threshold, monthly_threshold, annual_threshold, threshold_mode,
    effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('rent_194ib', 'it_act_1961', 'any', 2, 20, NULL, 50000, NULL, 'whole_amount', DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 section 194-IB as recalled; not owner-supplied; official text not read', 'pending',
     '2% (the 5% rate before 1-10-2024 is outside the seeded period); Rs 50,000 for a month or part of a month. No-PAN rate 20%.'),
    ('rent_194ib', 'it_act_2025', 'any', 2, 20, NULL, 50000, NULL, 'whole_amount', DATE '2026-04-01', NULL,
     'Owner-supplied (2026-11-13), Income-tax Act 2025 s.393 entry for ex-194-IB: 2%, Rs 50,000 per month; official page not read by us', 'secondary_verified',
     '2% on rent above Rs 50,000 a month. How the month above the limit is taxed (the whole month''s rent, as the engine does for ex-194-I) is the reading recorded in the provision rent_194ib_whole_month_reading: PENDING for the CA. No-PAN rate 20% (s.397(2)).')
ON CONFLICT (nature_key, deductee_group, effective_from) DO UPDATE SET act = EXCLUDED.act, rate = EXCLUDED.rate, no_pan_rate = EXCLUDED.no_pan_rate,
    single_payment_threshold = EXCLUDED.single_payment_threshold, monthly_threshold = EXCLUDED.monthly_threshold,
    annual_threshold = EXCLUDED.annual_threshold, threshold_mode = EXCLUDED.threshold_mode, effective_to = EXCLUDED.effective_to,
    source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status, notes = EXCLUDED.notes;

INSERT INTO tds_provisions (provision_key, act, section_ref, description, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('rent_deductor_classification', 'it_act_1961', '194-I / 194-IB',
     'Rent: the section depends on the DEDUCTOR. A deductor that is an individual or HUF not liable to tax audit in the preceding year deducts under ex-194-IB (nature rent_194ib: 2%, Rs 50,000 a month); every other deductor under ex-194-I (2% plant / machinery / equipment, 10% land / building / furniture / fittings). The answer is entered per financial year in the client profile (tds_deductor_fy_profile); a missing answer is refused (engine rule T-19).',
     DATE '2025-04-01', DATE '2026-03-31', 'Owner-supplied (2026-11-13); official text not read by us', 'secondary_verified',
     'Plant / machinery rent stays under ex-194-I(a) for every deductor (ex-194-IB covers land, building and furniture only).'),
    ('rent_deductor_classification', 'it_act_2025', 'to be confirmed (Income-tax Act 2025 section number not verified)',
     'Rent: the section depends on the DEDUCTOR. A deductor that is an individual or HUF not liable to tax audit in the preceding year deducts under ex-194-IB (nature rent_194ib: 2%, Rs 50,000 a month); every other deductor under ex-194-I (2% plant / machinery / equipment, 10% land / building / furniture / fittings). The answer is entered per financial year in the client profile (tds_deductor_fy_profile); a missing answer is refused (engine rule T-19).',
     DATE '2026-04-01', NULL, 'Owner-supplied (2026-11-13); official text not read by us', 'secondary_verified',
     'Plant / machinery rent stays under ex-194-I(a) for every deductor (ex-194-IB covers land, building and furniture only).'),
    ('rent_194ib_whole_month_reading', 'it_act_1961', '194-IB',
     'Reading used by the engine for ex-194-IB: once the rent of a month is above Rs 50,000, tax is deducted on the WHOLE rent of that month (earlier payments of the month included), not only on the excess.',
     DATE '2025-04-01', DATE '2026-03-31', 'Earlier owner-supplied value (2026-11-13) "whole month''s rent once above 50,000"; to be confirmed by the CA', 'pending',
     'PENDING for the CA: confirm whether the whole month''s rent or only the excess over Rs 50,000 is the base.'),
    ('rent_194ib_whole_month_reading', 'it_act_2025', 'to be confirmed (Income-tax Act 2025 section number not verified)',
     'Reading used by the engine for ex-194-IB: once the rent of a month is above Rs 50,000, tax is deducted on the WHOLE rent of that month (earlier payments of the month included), not only on the excess.',
     DATE '2026-04-01', NULL, 'Earlier owner-supplied value (2026-11-13) "whole month''s rent once above 50,000"; to be confirmed by the CA', 'pending',
     'PENDING for the CA: confirm whether the whole month''s rent or only the excess over Rs 50,000 is the base.')
ON CONFLICT (provision_key, act, effective_from) DO UPDATE SET section_ref = EXCLUDED.section_ref, description = EXCLUDED.description,
    effective_to = EXCLUDED.effective_to, source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status,
    notes = EXCLUDED.notes;

-- ---- TDS on a GST invoice: the base is the value WITHOUT GST when GST is shown separately ------------------------------------------
UPDATE tds_provisions SET verification_status = 'secondary_verified',
    section_ref = CASE act WHEN 'it_act_1961' THEN 'CBDT circular on GST shown separately in the invoice (number to be confirmed by the CA)'
                           ELSE 'to be confirmed (Income-tax Act 2025 section number not verified)' END,
    description = 'Where GST is shown separately in the invoice, tax is deducted on the invoice value WITHOUT GST (not on a GST-inclusive amount). The engine refuses (T-18) a base above the invoice value without GST on an invoice-mode voucher; on a plain voucher the accountant states the base.',
    source_reference = 'Owner-supplied position (2026-11-13): CBDT guidance that tax is deducted on the amount excluding GST shown separately in the invoice. The circular number is NOT recorded here: to be confirmed by the CA.',
    notes = 'Owner-supplied position; the circular number must be confirmed by the CA before this is called verified.'
WHERE provision_key = 'gst_excluded_from_base';

-- ---- interest on late deduction / late deposit and the rounding rule (owner-supplied) ----------------------------------------------
-- 1% a month (or part of a month) from the date the tax was deductible to the date it was deducted; 1.5% a month (or part) from the
-- date it was deducted to the date it was deposited. Tax is rounded to the nearest rupee (the old s.288B rule; Act 2025 equivalent).
UPDATE tds_interest_rules SET verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13): interest on late deduction 1% per month or part of a month, on late deposit 1.5% per month or part of a month; official text not read by us'
WHERE interest_key IN ('late_deduction', 'late_deposit');

UPDATE tds_provisions SET verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13): tax is rounded to the nearest rupee (old s.288B; the Income-tax Act 2025 equivalent section number not verified); official text not read by us',
    notes = 'Nearest rupee, halves up (engine rule T-06).'
WHERE provision_key = 'rounding_nearest_rupee';

UPDATE tds_provisions SET verification_status = 'secondary_verified',
    source_reference = 'Owner-supplied (2026-11-13): interest 1% / 1.5% per month or part of a month; official text not read by us'
WHERE provision_key = 'interest_late_deduction_deposit';
