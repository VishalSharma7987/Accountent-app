-- 0008: MSME rule corrections (Phase 2.1). Schema-agnostic (see 0003).
--  * msme_payment_rules: verification_status may be 'secondary_verified' (checked against secondary sources,
--    awaiting the CA's signature); covered_activities holds which enterprise activities the rule covers.
--  * parties: msme_activity, udyam_registration_date, msme_agreed_days (the per-supplier agreed credit period;
--    replaces the use of the generic credit_days for the MSME legal days).
--  * vouchers: goods_received_date (rule V-15), the acceptance date of a purchase when it differs from the bill date.
-- The data of the rule rows is corrected by database/seeds/0003_msme_rule_corrections.sql (applied after the migrations).
-- Constraints that existing rows may not satisfy are added NOT VALID: they bind every new and changed row.

-- rule table ------------------------------------------------------------------------------------------
ALTER TABLE msme_payment_rules DROP CONSTRAINT msme_rules_verification_check;
ALTER TABLE msme_payment_rules ADD CONSTRAINT msme_rules_verification_check
    CHECK (verification_status IN ('verified', 'secondary_verified', 'pending'));
ALTER TABLE msme_payment_rules ADD COLUMN covered_activities text[] NOT NULL DEFAULT '{}'
    CONSTRAINT msme_rules_activities_check CHECK (covered_activities <@ ARRAY['manufacturing', 'services', 'trading']::text[]);

-- party master ----------------------------------------------------------------------------------------
ALTER TABLE parties ADD COLUMN msme_activity text
    CONSTRAINT parties_msme_activity_check CHECK (msme_activity IN ('manufacturing', 'services', 'trading'));
ALTER TABLE parties ADD COLUMN udyam_registration_date date;
ALTER TABLE parties ADD COLUMN msme_agreed_days integer
    CONSTRAINT parties_msme_agreed_days_range CHECK (msme_agreed_days BETWEEN 1 AND 45);

-- the old documented use of credit_days as the agreed MSME days moves to its own column
UPDATE parties SET msme_agreed_days = credit_days
 WHERE msme_written_agreement AND credit_days BETWEEN 1 AND 45;

ALTER TABLE parties ADD CONSTRAINT parties_msme_agreement_days
    CHECK (msme_written_agreement = (msme_agreed_days IS NOT NULL)) NOT VALID;
ALTER TABLE parties ADD CONSTRAINT parties_udyam_needs_date
    CHECK (udyam_no IS NULL OR udyam_registration_date IS NOT NULL) NOT VALID;
ALTER TABLE parties ADD CONSTRAINT parties_msme_needs_activity
    CHECK (msme_category NOT IN ('micro', 'small') OR msme_activity IS NOT NULL) NOT VALID;

-- vouchers: goods received date (V-15). vouchers_guard compares whole rows, so an unchanged value passes;
-- a draft may change it like any other header field, a posted voucher cannot.
ALTER TABLE vouchers ADD COLUMN goods_received_date date;
ALTER TABLE vouchers ADD CONSTRAINT vouchers_goods_received_purchase_only
    CHECK (goods_received_date IS NULL OR voucher_type = 'purchase');
ALTER TABLE vouchers ADD CONSTRAINT vouchers_goods_received_window
    CHECK (goods_received_date IS NULL OR abs(goods_received_date - voucher_date) <= 365);
