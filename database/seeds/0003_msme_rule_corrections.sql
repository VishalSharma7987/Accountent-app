-- Seed: corrected MSME payment-time rules (Phase 2.1). Safe to run more than once (ON CONFLICT DO UPDATE).
-- Replaces the 'pending' rows of 0002 with the owner's corrected reading: s.43B(h) of the Income-tax Act 1961 up to
-- 31-03-2026, s.37(2)(g) of the Income-tax Act 2025 from 01-04-2026; MSMED Act 2006 s.15: 15 days without a written
-- agreement, the agreed days (never more than 45) with one, counted from the day of acceptance or deemed acceptance.
-- verification_status = 'secondary_verified': checked against secondary sources, NOT yet signed by the owner's CA
-- (it becomes 'verified' only after that sign-off). Medium enterprises are not covered (applies = false).
INSERT INTO msme_payment_rules
    (rule_key, category, applies, days_with_agreement, days_no_agreement, effective_from, effective_to,
     source_reference, verification_status, notes, covered_activities)
VALUES
    ('msme_43bh_1961', 'micro', true, 45, 15, DATE '2024-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 s.43B(h) (inserted by Finance Act 2023, w.e.f. 1-4-2024); MSMED Act 2006 s.15 (time limit: 15 days without a written agreement, agreed days capped at 45, from acceptance or deemed acceptance)',
     'secondary_verified',
     'Written agreement: agreed days, never more than 45 from acceptance; no agreement: 15 days. Awaiting CA confirmation.',
     ARRAY['manufacturing', 'services']),
    ('msme_43bh_1961', 'small', true, 45, 15, DATE '2024-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 s.43B(h) (inserted by Finance Act 2023, w.e.f. 1-4-2024); MSMED Act 2006 s.15 (time limit: 15 days without a written agreement, agreed days capped at 45, from acceptance or deemed acceptance)',
     'secondary_verified', 'Same as micro. Awaiting CA confirmation.', ARRAY['manufacturing', 'services']),
    ('msme_43bh_1961', 'medium', false, NULL, NULL, DATE '2024-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 s.43B(h): only micro and small enterprises are covered',
     'secondary_verified', 'Medium enterprises are not covered by the disallowance.', '{}'),
    ('msme_37_2_g_2025', 'micro', true, 45, 15, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 s.37(2)(g) (replaces s.43B(h) of the 1961 Act from 1-4-2026); MSMED Act 2006 s.15 (time limit: 15 days without a written agreement, agreed days capped at 45, from acceptance or deemed acceptance)',
     'secondary_verified',
     'Replaces s.43B(h) of the 1961 Act from 1-4-2026. Awaiting CA confirmation.',
     ARRAY['manufacturing', 'services']),
    ('msme_37_2_g_2025', 'small', true, 45, 15, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 s.37(2)(g) (replaces s.43B(h) of the 1961 Act from 1-4-2026); MSMED Act 2006 s.15 (time limit: 15 days without a written agreement, agreed days capped at 45, from acceptance or deemed acceptance)',
     'secondary_verified', 'Same as micro. Awaiting CA confirmation.', ARRAY['manufacturing', 'services']),
    ('msme_37_2_g_2025', 'medium', false, NULL, NULL, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 s.37(2)(g): only micro and small enterprises are covered',
     'secondary_verified', 'Medium enterprises are not covered.', '{}')
ON CONFLICT (rule_key, category, effective_from) DO UPDATE SET
    applies = EXCLUDED.applies, days_with_agreement = EXCLUDED.days_with_agreement,
    days_no_agreement = EXCLUDED.days_no_agreement, effective_to = EXCLUDED.effective_to,
    source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status,
    notes = EXCLUDED.notes, covered_activities = EXCLUDED.covered_activities;
