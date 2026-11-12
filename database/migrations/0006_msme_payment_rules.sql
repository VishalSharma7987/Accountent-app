-- 0006: rule table for the MSME payment-due flag (Phase 2, step 2.6). Law is data (CLAUDE.md section 2.5):
-- days, effective dates, source and verification status live here, never in business logic.
-- System data (not per client): rows are seeded by database/seeds/0002_msme_payment_rules.sql.
CREATE TABLE msme_payment_rules (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key             text NOT NULL CONSTRAINT msme_rules_key_not_blank CHECK (btrim(rule_key) <> ''),
    category             text NOT NULL CONSTRAINT msme_rules_category_check CHECK (category IN ('micro', 'small', 'medium')),
    applies              boolean NOT NULL,   -- false = the category is not covered by the payment-time disallowance
    days_with_agreement  integer CONSTRAINT msme_rules_days_a_pos CHECK (days_with_agreement > 0),  -- cap when a written agreement exists
    days_no_agreement    integer CONSTRAINT msme_rules_days_n_pos CHECK (days_no_agreement > 0),    -- default when there is none
    effective_from       date NOT NULL,
    effective_to         date,
    source_reference     text NOT NULL CONSTRAINT msme_rules_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status  text NOT NULL CONSTRAINT msme_rules_verification_check
                         CHECK (verification_status IN ('verified', 'pending')),
    notes                text,
    CONSTRAINT msme_rules_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT msme_rules_days_present CHECK (NOT applies OR (days_with_agreement IS NOT NULL AND days_no_agreement IS NOT NULL)),
    CONSTRAINT msme_rules_key_from UNIQUE (rule_key, category, effective_from)
);
ALTER TABLE msme_payment_rules ENABLE ROW LEVEL SECURITY;
