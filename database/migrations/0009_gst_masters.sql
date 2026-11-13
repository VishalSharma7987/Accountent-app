-- 0009: GST masters and rule tables (Phase 3, step 3.0). Schema-agnostic (see 0003). Money: numeric(18,4) + CHECK (x = round(x, 2)) (see 0004).
-- Rates / percentages are NOT money: numeric(7,4). RLS enabled with NO policies on every table; API roles hold nothing (0004).
-- Law is data (CLAUDE.md 2.5): every rule table has effective_from, effective_to, source_reference, verification_status.
-- System rule rows (no client_id) are seeded by database/seeds/0004..0008_*.sql. Per-client tables: gst_registrations,
-- gst_ledger_roles, gst_items. No function is created here; the function-privilege revoke block is at the end of 0010 and 0011.

-- =====================================================================================================
-- Rule tables (system data)
-- =====================================================================================================

-- state / UT codes used in a GSTIN (positions 1-2) and as place of supply
CREATE TABLE gst_state_codes (
    code                text PRIMARY KEY CONSTRAINT gst_state_codes_format CHECK (code ~ '^[0-9]{2}$'),
    name                text NOT NULL CONSTRAINT gst_state_codes_name_not_blank CHECK (btrim(name) <> ''),
    kind                text NOT NULL CONSTRAINT gst_state_codes_kind_check
                        CHECK (kind IN ('state', 'union_territory', 'other_territory', 'centre_jurisdiction')),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_state_codes_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_state_codes_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT gst_state_codes_period CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

-- unit quantity codes of the GST returns (HSN summary)
CREATE TABLE gst_uqc (
    code                text PRIMARY KEY CONSTRAINT gst_uqc_format CHECK (code ~ '^[A-Z]{3}$'),
    description         text NOT NULL CONSTRAINT gst_uqc_description_not_blank CHECK (btrim(description) <> ''),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_uqc_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_uqc_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    CONSTRAINT gst_uqc_period CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

-- the GST rate slabs in force on a date (a rate rule may only use a slab in force: rule G-11, checked by the engine)
CREATE TABLE gst_rate_slabs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rate                numeric(7, 4) NOT NULL CONSTRAINT gst_rate_slabs_rate_range CHECK (rate >= 0 AND rate <= 100),  -- total GST % (CGST + SGST, or IGST)
    is_special          boolean NOT NULL DEFAULT false,   -- special rate (precious metals etc.), not a general slab
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_rate_slabs_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_rate_slabs_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT gst_rate_slabs_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_rate_slabs_key UNIQUE (rate, effective_from)
);

-- HSN/SAC -> rate by effective date. The most specific (longest) code_prefix in force on the supply date wins.
-- 'default' rows (code_prefix NULL) are used only when no prefix matches; the engine flags the line "default rate applied" (a warning).
-- The full HSN-wise tariff is NOT shipped: the owner / CA must import it from the official notification data.
-- is_example = true marks rows seeded only to test the mechanism; they must not be relied on for real filing.
CREATE TABLE gst_rate_rules (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key             text NOT NULL CONSTRAINT gst_rate_rules_key_not_blank CHECK (btrim(rule_key) <> ''),
    code_kind            text NOT NULL CONSTRAINT gst_rate_rules_kind_check CHECK (code_kind IN ('hsn', 'sac', 'default')),
    code_prefix          text CONSTRAINT gst_rate_rules_prefix_format CHECK (code_prefix ~ '^[0-9]{2,8}$'),
    supply_kind          text NOT NULL CONSTRAINT gst_rate_rules_supply_check CHECK (supply_kind IN ('goods', 'services')),
    treatment            text NOT NULL CONSTRAINT gst_rate_rules_treatment_check
                         CHECK (treatment IN ('taxable', 'exempt', 'nil_rated', 'non_gst')),
    rate                 numeric(7, 4) NOT NULL CONSTRAINT gst_rate_rules_rate_range CHECK (rate >= 0 AND rate <= 100),   -- total GST %; CGST = SGST = half
    cess_rate            numeric(7, 4) NOT NULL DEFAULT 0 CONSTRAINT gst_rate_rules_cess_rate_range CHECK (cess_rate >= 0 AND cess_rate <= 1000),
    cess_specific_amount numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT gst_rate_rules_cess_amt_nonneg CHECK (cess_specific_amount >= 0),  -- cess per unit (specific cess)
    cess_uqc             text REFERENCES gst_uqc (code),
    effective_from       date NOT NULL,
    effective_to         date,
    source_reference     text NOT NULL CONSTRAINT gst_rate_rules_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status  text NOT NULL CONSTRAINT gst_rate_rules_verification_check
                         CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    is_example           boolean NOT NULL DEFAULT false,
    notes                text,
    CONSTRAINT gst_rate_rules_cess_amt_two_decimals CHECK (cess_specific_amount = round(cess_specific_amount, 2)),
    CONSTRAINT gst_rate_rules_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_rate_rules_default_shape CHECK ((code_kind = 'default') = (code_prefix IS NULL)),
    CONSTRAINT gst_rate_rules_sac_shape CHECK (code_kind <> 'sac' OR code_prefix LIKE '99%'),
    CONSTRAINT gst_rate_rules_not_taxable_zero CHECK (treatment = 'taxable' OR (rate = 0 AND cess_rate = 0 AND cess_specific_amount = 0)),
    CONSTRAINT gst_rate_rules_cess_uqc CHECK (cess_specific_amount = 0 OR cess_uqc IS NOT NULL)
);
-- one rule per (key, from-date); overlapping periods of one key are rejected by the loader (unit test), not by the database
CREATE UNIQUE INDEX gst_rate_rules_key_from_key ON gst_rate_rules (rule_key, effective_from);
CREATE INDEX gst_rate_rules_prefix_idx ON gst_rate_rules (code_prefix, effective_from);

-- reverse charge categories (Section 9(3), Section 9(4) CGST Act; IGST Act ss.5(3), 5(4), and import of services)
CREATE TABLE gst_rcm_rules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_key        text NOT NULL CONSTRAINT gst_rcm_rules_key_not_blank CHECK (btrim(category_key) <> ''),
    section_ref         text NOT NULL CONSTRAINT gst_rcm_rules_section_not_blank CHECK (btrim(section_ref) <> ''),  -- e.g. 'CGST 9(3)'
    notification_ref    text,
    entry_no            text,
    supply_kind         text NOT NULL CONSTRAINT gst_rcm_rules_supply_check CHECK (supply_kind IN ('goods', 'services')),
    description         text NOT NULL CONSTRAINT gst_rcm_rules_description_not_blank CHECK (btrim(description) <> ''),
    supplier_condition  text NOT NULL DEFAULT 'any' CONSTRAINT gst_rcm_rules_supplier_check
                        CHECK (supplier_condition IN ('any', 'unregistered_only', 'non_resident_only')),
    hsn_sac_prefix      text CONSTRAINT gst_rcm_rules_prefix_format CHECK (hsn_sac_prefix ~ '^[0-9]{2,8}$'),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_rcm_rules_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_rcm_rules_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    is_example          boolean NOT NULL DEFAULT false,
    notes               text,
    CONSTRAINT gst_rcm_rules_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_rcm_rules_key_from UNIQUE (category_key, effective_from)
);

-- Section 17(5) blocked-credit categories. The ACCOUNTANT tags a purchase line with a category_key (never guessed from the item name).
-- has_exception = the section lists exceptions (e.g. vehicle used for passenger transport); the line then needs itc_exception_claimed + a note.
CREATE TABLE gst_blocked_credit_rules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_key        text NOT NULL CONSTRAINT gst_blocked_rules_key_not_blank CHECK (btrim(category_key) <> ''),
    clause_ref          text NOT NULL CONSTRAINT gst_blocked_rules_clause_not_blank CHECK (btrim(clause_ref) <> ''),  -- e.g. 'CGST 17(5)(a)'
    description         text NOT NULL CONSTRAINT gst_blocked_rules_description_not_blank CHECK (btrim(description) <> ''),
    has_exception       boolean NOT NULL DEFAULT false,
    exception_text      text,
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_blocked_rules_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_blocked_rules_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT gst_blocked_rules_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_blocked_rules_exception_text CHECK (NOT has_exception OR exception_text IS NOT NULL),
    CONSTRAINT gst_blocked_rules_key_from UNIQUE (category_key, effective_from)
);

-- Section 16 conditions and time limits of ITC, with the evidence field the accountant fills on the itc_entries row.
-- parameter_days: e.g. 180 for the payment condition; deadline_month/day: e.g. 30 November (Section 16(4)).
CREATE TABLE gst_itc_conditions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condition_key       text NOT NULL CONSTRAINT gst_itc_conditions_key_check CHECK (condition_key IN
                        ('tax_document_held', 'goods_services_received', 'supplier_tax_paid', 'return_filed',
                         'payment_within_days', 'claim_time_limit')),
    clause_ref          text NOT NULL CONSTRAINT gst_itc_conditions_clause_not_blank CHECK (btrim(clause_ref) <> ''),
    description         text NOT NULL CONSTRAINT gst_itc_conditions_description_not_blank CHECK (btrim(description) <> ''),
    evidence_field      text,
    parameter_days      integer CONSTRAINT gst_itc_conditions_days_pos CHECK (parameter_days > 0),
    deadline_month      integer CONSTRAINT gst_itc_conditions_month CHECK (deadline_month BETWEEN 1 AND 12),
    deadline_day        integer CONSTRAINT gst_itc_conditions_day CHECK (deadline_day BETWEEN 1 AND 31),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_itc_conditions_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_itc_conditions_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT gst_itc_conditions_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_itc_conditions_key_from UNIQUE (condition_key, effective_from),
    CONSTRAINT gst_itc_conditions_deadline_both CHECK ((deadline_month IS NULL) = (deadline_day IS NULL))
);

-- numeric thresholds of the return forms and schemes that are law (B2C large invoice value, HSN digits, ...)
CREATE TABLE gst_thresholds (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    threshold_key       text NOT NULL CONSTRAINT gst_thresholds_key_not_blank CHECK (btrim(threshold_key) <> ''),
    unit                text NOT NULL CONSTRAINT gst_thresholds_unit_check CHECK (unit IN ('inr', 'digits', 'days', 'percent')),
    numeric_value       numeric(18, 4) NOT NULL CONSTRAINT gst_thresholds_value_nonneg CHECK (numeric_value >= 0),
    description         text NOT NULL CONSTRAINT gst_thresholds_description_not_blank CHECK (btrim(description) <> ''),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_thresholds_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_thresholds_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT gst_thresholds_inr_two_decimals CHECK (unit <> 'inr' OR numeric_value = round(numeric_value, 2)),
    CONSTRAINT gst_thresholds_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_thresholds_key_from UNIQUE (threshold_key, effective_from)
);

-- composition scheme (Section 10): rate on turnover and turnover limits by category
CREATE TABLE gst_composition_rules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category            text NOT NULL CONSTRAINT gst_composition_category_check
                        CHECK (category IN ('manufacturer', 'trader', 'restaurant', 'service_provider')),
    rate                numeric(7, 4) NOT NULL CONSTRAINT gst_composition_rate_range CHECK (rate > 0 AND rate <= 100),  -- total % of turnover; CGST = SGST = half
    turnover_limit      numeric(18, 4) NOT NULL CONSTRAINT gst_composition_limit_pos CHECK (turnover_limit > 0),
    section_ref         text NOT NULL CONSTRAINT gst_composition_section_not_blank CHECK (btrim(section_ref) <> ''),
    turnover_basis      text NOT NULL CONSTRAINT gst_composition_basis_check
                        CHECK (turnover_basis IN ('taxable_turnover', 'turnover_in_state')),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT gst_composition_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT gst_composition_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT gst_composition_limit_two_decimals CHECK (turnover_limit = round(turnover_limit, 2)),
    CONSTRAINT gst_composition_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_composition_key_from UNIQUE (category, effective_from)
);

-- =====================================================================================================
-- Per-client masters
-- =====================================================================================================

-- one row per GSTIN of a client (a client may hold several, one per state)
CREATE TABLE gst_registrations (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL REFERENCES clients (id),
    gstin             text NOT NULL CONSTRAINT gst_registrations_gstin_format
                      CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),   -- check digit: engine rule G-02
    state_code        text NOT NULL REFERENCES gst_state_codes (code),
    registration_type text NOT NULL CONSTRAINT gst_registrations_type_check CHECK (registration_type IN ('regular', 'composition')),
    return_frequency  text NOT NULL DEFAULT 'monthly' CONSTRAINT gst_registrations_frequency_check
                      CHECK (return_frequency IN ('monthly', 'qrmp')),
    composition_category text CONSTRAINT gst_registrations_comp_category_check
                      CHECK (composition_category IN ('manufacturer', 'trader', 'restaurant', 'service_provider')),
    trade_name        text,
    effective_from    date NOT NULL,           -- registration date (or date of change of type)
    effective_to      date,                    -- cancellation / surrender / change of type
    is_active         boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gst_registrations_id_client_key UNIQUE (id, client_id),
    CONSTRAINT gst_registrations_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT gst_registrations_state_matches_gstin CHECK (substr(gstin, 1, 2) = state_code),
    CONSTRAINT gst_registrations_comp_needs_category CHECK ((registration_type = 'composition') = (composition_category IS NOT NULL)),
    CONSTRAINT gst_registrations_comp_monthly_na CHECK (registration_type = 'regular' OR return_frequency = 'monthly')
);
-- a GSTIN is entered once per (client, from-date); overlapping periods of one GSTIN are refused by engine rule G-06
CREATE UNIQUE INDEX gst_registrations_client_gstin_from_key ON gst_registrations (client_id, gstin, effective_from);
CREATE INDEX gst_registrations_client_idx ON gst_registrations (client_id);

-- which ledger of the client plays which GST role for a registration (Output CGST, Input IGST, Round off, ...)
CREATE TABLE gst_ledger_roles (
    registration_id uuid NOT NULL,
    client_id       uuid NOT NULL,
    role            text NOT NULL CONSTRAINT gst_ledger_roles_role_check CHECK (role IN (
                    'output_cgst', 'output_sgst', 'output_igst', 'output_cess',
                    'input_cgst', 'input_sgst', 'input_igst', 'input_cess',
                    'rcm_cgst', 'rcm_sgst', 'rcm_igst', 'rcm_cess',
                    'round_off', 'itc_reversal',
                    'composition_tax_expense', 'composition_tax_payable')),
    ledger_id       uuid NOT NULL,
    PRIMARY KEY (registration_id, role),
    CONSTRAINT gst_ledger_roles_registration_fk FOREIGN KEY (registration_id, client_id)
        REFERENCES gst_registrations (id, client_id),
    CONSTRAINT gst_ledger_roles_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE INDEX gst_ledger_roles_ledger_idx ON gst_ledger_roles (ledger_id);

-- item / service master with HSN / SAC. Defaults only: the tax rate is NEVER stored here (it comes from gst_rate_rules by date).
CREATE TABLE gst_items (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL REFERENCES clients (id),
    name                text NOT NULL CONSTRAINT gst_items_name_not_blank CHECK (btrim(name) <> ''),
    item_kind           text NOT NULL CONSTRAINT gst_items_kind_check CHECK (item_kind IN ('goods', 'service')),
    hsn_sac             text NOT NULL CONSTRAINT gst_items_hsn_sac_format CHECK (hsn_sac ~ '^[0-9]{4}([0-9]{2}([0-9]{2})?)?$'),
    uqc                 text REFERENCES gst_uqc (code),
    sales_ledger_id     uuid,
    purchase_ledger_id  uuid,
    default_itc_category_key text,           -- a Section 17(5) key to suggest on purchase lines (the accountant confirms)
    default_rcm_category_key text,           -- an RCM key to suggest (the accountant confirms)
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gst_items_id_client_key UNIQUE (id, client_id),
    CONSTRAINT gst_items_goods_need_uqc CHECK (item_kind = 'service' OR uqc IS NOT NULL),
    CONSTRAINT gst_items_service_sac CHECK (item_kind = 'goods' OR hsn_sac LIKE '99%'),
    CONSTRAINT gst_items_sales_ledger_fk FOREIGN KEY (sales_ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT gst_items_purchase_ledger_fk FOREIGN KEY (purchase_ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE UNIQUE INDEX gst_items_client_name_key ON gst_items (client_id, lower(btrim(name)));
CREATE INDEX gst_items_client_idx ON gst_items (client_id);

-- party master: the GST registration type of the counterparty (nullable: not filled = unknown, never defaulted - principle 3)
ALTER TABLE parties ADD COLUMN gst_registration_type text
    CONSTRAINT parties_gst_registration_type_check
    CHECK (gst_registration_type IN ('regular', 'composition', 'unregistered', 'sez', 'overseas', 'uin_holder', 'government'));
ALTER TABLE parties ADD CONSTRAINT parties_gst_type_needs_gstin
    CHECK (gst_registration_type IS NULL OR gst_registration_type NOT IN ('regular', 'composition', 'sez', 'uin_holder')
           OR gstin IS NOT NULL) NOT VALID;
ALTER TABLE parties ADD CONSTRAINT parties_gst_type_unregistered_no_gstin
    CHECK (gst_registration_type IS DISTINCT FROM 'unregistered' OR gstin IS NULL) NOT VALID;

-- client option: round every GST invoice to the nearest rupee (difference to the round_off ledger, rule G-16); default off
ALTER TABLE clients ADD COLUMN round_off_invoices boolean NOT NULL DEFAULT false;

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE gst_state_codes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_uqc                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_rate_slabs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_rate_rules           ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_rcm_rules            ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_blocked_credit_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_itc_conditions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_thresholds           ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_composition_rules    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_registrations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_ledger_roles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_items                ENABLE ROW LEVEL SECURITY;
