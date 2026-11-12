-- Seed: MSME payment-time rules. Safe to run more than once. ALL ROWS ARE verification_status = 'pending':
-- the statute text could not be read from an official site (indiacode / incometaxindia returned errors); the days and
-- section numbers below come from secondary sources and must be checked by the owner/CA before relying on them.
INSERT INTO msme_payment_rules
    (rule_key, category, applies, days_with_agreement, days_no_agreement, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('msme_43bh_1961', 'micro', true, 45, 15, DATE '2024-04-01', DATE '2026-03-31',
     'MSMED Act 2006 s.15 (time limit); Income-tax Act 1961 s.43B(h) (inserted by Finance Act 2023, w.e.f. 1-4-2024)', 'pending',
     'Written agreement: agreed days, never more than 45 from acceptance; no agreement: 15 days.'),
    ('msme_43bh_1961', 'small', true, 45, 15, DATE '2024-04-01', DATE '2026-03-31',
     'MSMED Act 2006 s.15 (time limit); Income-tax Act 1961 s.43B(h) (inserted by Finance Act 2023, w.e.f. 1-4-2024)', 'pending',
     'Same as micro.'),
    ('msme_43bh_1961', 'medium', false, NULL, NULL, DATE '2024-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 s.43B(h): only micro and small enterprises are covered', 'pending',
     'Medium enterprises are not covered by the disallowance.'),
    ('msme_37_2_g_2025', 'micro', true, 45, 15, DATE '2026-04-01', NULL,
     'MSMED Act 2006 s.15; Income-tax Act 2025 s.37(2)(g) (section number from a Rajya Sabha reply of 21-07-2026, secondary source)', 'pending',
     'Replaces s.43B(h) of the 1961 Act from 1-4-2026.'),
    ('msme_37_2_g_2025', 'small', true, 45, 15, DATE '2026-04-01', NULL,
     'MSMED Act 2006 s.15; Income-tax Act 2025 s.37(2)(g) (secondary source)', 'pending',
     'Same as micro.'),
    ('msme_37_2_g_2025', 'medium', false, NULL, NULL, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 s.37(2)(g): only micro and small enterprises are covered (secondary source)', 'pending',
     'Medium enterprises are not covered.')
ON CONFLICT (rule_key, category, effective_from) DO NOTHING;
