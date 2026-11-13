-- 0012: TDS / TCS rule tables and per-client masters (Phase 4, step 4.0). Schema-agnostic (see 0003). Money: numeric(18,4) + CHECK (x = round(x, 2)) (0004).
-- Rates / percentages are NOT money: numeric(7,4). RLS enabled with NO policies on every table; API roles hold nothing (0004).
-- Law is data (CLAUDE.md 2.5): every rule table has effective_from, effective_to, source_reference, verification_status.
-- The Act in force is chosen by DATE (the earlier of payment / credit): rows of act 'it_act_1961' end 2026-03-31, rows of 'it_act_2025' start 2026-04-01.
-- System rule rows are seeded by database/seeds/0008_tds_sections_rates.sql and 0009_tds_due_dates_interest_forms.sql.
-- No function is created here; the function-privilege revoke block is at the end of 0013 and 0014.

-- =====================================================================================================
-- Rule tables (system data)
-- =====================================================================================================

-- the natures of payment / collection the tool knows (stable keys used by the engine and by deductee defaults)
CREATE TABLE tds_natures (
    nature_key          text PRIMARY KEY CONSTRAINT tds_natures_key_format CHECK (nature_key ~ '^[a-z][a-z0-9_]*$'),
    kind                text NOT NULL CONSTRAINT tds_natures_kind_check CHECK (kind IN ('tds', 'tcs')),
    description         text NOT NULL CONSTRAINT tds_natures_description_not_blank CHECK (btrim(description) <> ''),
    rate_mode           text NOT NULL DEFAULT 'flat' CONSTRAINT tds_natures_rate_mode_check CHECK (rate_mode IN ('flat', 'slab_manual')),   -- salary: the accountant types the amount (no payroll engine in Phase 4)
    sort_order          integer NOT NULL DEFAULT 0,
    source_reference    text NOT NULL CONSTRAINT tds_natures_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT tds_natures_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending'))
);

-- old <-> new mapping: the section / table entry / payment code of a nature under each Act, by date
CREATE TABLE tds_section_refs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nature_key          text NOT NULL REFERENCES tds_natures (nature_key),
    act                 text NOT NULL CONSTRAINT tds_section_refs_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    section_ref         text NOT NULL CONSTRAINT tds_section_refs_section_not_blank CHECK (btrim(section_ref) <> ''),   -- '194C' | '393(1)' | '392' | '394'
    table_ref           text,                       -- Act 2025: serial / entry inside the section-393 (or 394) table, as reported
    payment_code        text,                       -- payment code used in the statement (NULL = not verified)
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT tds_section_refs_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT tds_section_refs_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT tds_section_refs_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT tds_section_refs_key UNIQUE (nature_key, act, effective_from)
);

-- rate and thresholds by nature, deductee group and date. The row in force on the event date wins (engine rule T-02).
--   deductee_group 'any' = one rate for everybody; otherwise 'individual_huf' / 'others' (companies, firms, LLPs, AOPs ... are 'others').
--   thresholds: NULL = none. single_payment_threshold: one payment / credit above it is taxable on its own;
--   monthly_threshold: rent (per month or part of a month); annual_threshold: total of the financial year per deductee and nature.
--   threshold_mode 'whole_amount': once a threshold is crossed tax is deducted on the whole amount (the crossing payment carries the catch-up);
--                  'excess_only': tax only on the amount above the threshold (Section 194Q, TCS above a limit).
--   no_pan_rate: rate when the deductee's PAN is missing / invalid (Section 206AA and equivalent), a rate, never computed in code.
CREATE TABLE tds_rates (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nature_key              text NOT NULL REFERENCES tds_natures (nature_key),
    act                     text NOT NULL CONSTRAINT tds_rates_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    deductee_group          text NOT NULL CONSTRAINT tds_rates_group_check CHECK (deductee_group IN ('any', 'individual_huf', 'others')),
    rate                    numeric(7, 4) NOT NULL CONSTRAINT tds_rates_rate_range CHECK (rate >= 0 AND rate <= 100),
    no_pan_rate             numeric(7, 4) NOT NULL CONSTRAINT tds_rates_no_pan_range CHECK (no_pan_rate >= 0 AND no_pan_rate <= 100),
    single_payment_threshold numeric(18, 4) CONSTRAINT tds_rates_single_nonneg CHECK (single_payment_threshold >= 0),
    monthly_threshold       numeric(18, 4) CONSTRAINT tds_rates_monthly_nonneg CHECK (monthly_threshold >= 0),
    annual_threshold        numeric(18, 4) CONSTRAINT tds_rates_annual_nonneg CHECK (annual_threshold >= 0),
    threshold_mode          text NOT NULL DEFAULT 'whole_amount' CONSTRAINT tds_rates_mode_check CHECK (threshold_mode IN ('whole_amount', 'excess_only')),
    effective_from          date NOT NULL,
    effective_to            date,
    source_reference        text NOT NULL CONSTRAINT tds_rates_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status     text NOT NULL CONSTRAINT tds_rates_verification_check
                            CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes                   text,
    CONSTRAINT tds_rates_single_two_decimals CHECK (single_payment_threshold = round(single_payment_threshold, 2)),
    CONSTRAINT tds_rates_monthly_two_decimals CHECK (monthly_threshold = round(monthly_threshold, 2)),
    CONSTRAINT tds_rates_annual_two_decimals CHECK (annual_threshold = round(annual_threshold, 2)),
    CONSTRAINT tds_rates_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT tds_rates_key UNIQUE (nature_key, deductee_group, effective_from)
);
CREATE INDEX tds_rates_nature_idx ON tds_rates (nature_key, effective_from);

-- other legal provisions the engine relies on (higher rate without PAN, lower-deduction certificate, interest, certificates,
-- rounding, GST in the base ...): the section reference and the rule in words, by Act and date
CREATE TABLE tds_provisions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provision_key       text NOT NULL CONSTRAINT tds_provisions_key_not_blank CHECK (btrim(provision_key) <> ''),
    act                 text NOT NULL CONSTRAINT tds_provisions_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    section_ref         text NOT NULL CONSTRAINT tds_provisions_section_not_blank CHECK (btrim(section_ref) <> ''),
    description         text NOT NULL CONSTRAINT tds_provisions_description_not_blank CHECK (btrim(description) <> ''),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT tds_provisions_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT tds_provisions_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT tds_provisions_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT tds_provisions_key UNIQUE (provision_key, act, effective_from)
);

-- challan deposit, statement and certificate due dates (seed 0009). Pattern, not a calendar: the engine computes the date.
--   challan: due_day of the month that is month_offset months after the month of deduction / collection (month_of_year set = exception month only, e.g. March)
--   return:  due_day of the month that is month_offset months after the END month of the quarter (quarter 1-4, Indian FY quarters)
--   certificate: days_after_return days after the due date of the return of that quarter (quarter set), or the salary certificate (quarter NULL, due_day, month_offset after March)
CREATE TABLE tds_due_dates (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    due_key             text NOT NULL CONSTRAINT tds_due_dates_key_not_blank CHECK (btrim(due_key) <> ''),
    event               text NOT NULL CONSTRAINT tds_due_dates_event_check CHECK (event IN ('challan', 'return', 'certificate')),
    kind                text NOT NULL CONSTRAINT tds_due_dates_kind_check CHECK (kind IN ('tds', 'tcs')),
    quarter             integer CONSTRAINT tds_due_dates_quarter_check CHECK (quarter BETWEEN 1 AND 4),
    month_of_year       integer CONSTRAINT tds_due_dates_month_check CHECK (month_of_year BETWEEN 1 AND 12),
    due_day             integer CONSTRAINT tds_due_dates_day_check CHECK (due_day BETWEEN 1 AND 31),
    month_offset        integer CONSTRAINT tds_due_dates_offset_check CHECK (month_offset BETWEEN 0 AND 12),
    days_after_return   integer CONSTRAINT tds_due_dates_days_check CHECK (days_after_return > 0),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT tds_due_dates_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT tds_due_dates_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT tds_due_dates_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT tds_due_dates_shape CHECK ((days_after_return IS NOT NULL AND due_day IS NULL AND month_offset IS NULL)
                                          OR (days_after_return IS NULL AND due_day IS NOT NULL AND month_offset IS NOT NULL)),
    CONSTRAINT tds_due_dates_return_quarter CHECK (event <> 'return' OR quarter IS NOT NULL),
    CONSTRAINT tds_due_dates_key UNIQUE (due_key, kind, effective_from)
);

-- interest on late deduction / late deposit (per month or part of a month)
CREATE TABLE tds_interest_rules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    interest_key        text NOT NULL CONSTRAINT tds_interest_key_check CHECK (interest_key IN ('late_deduction', 'late_deposit')),
    monthly_rate        numeric(7, 4) NOT NULL CONSTRAINT tds_interest_rate_range CHECK (monthly_rate > 0 AND monthly_rate <= 100),   -- % per month
    part_month_counts_full boolean NOT NULL DEFAULT true,
    from_event          text NOT NULL CONSTRAINT tds_interest_from_not_blank CHECK (btrim(from_event) <> ''),
    to_event            text NOT NULL CONSTRAINT tds_interest_to_not_blank CHECK (btrim(to_event) <> ''),
    section_ref         text NOT NULL CONSTRAINT tds_interest_section_not_blank CHECK (btrim(section_ref) <> ''),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT tds_interest_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT tds_interest_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT tds_interest_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT tds_interest_key UNIQUE (interest_key, effective_from)
);

-- official form numbers by purpose (return, certificate, challan, lower-deduction certificate ...) and Act
CREATE TABLE tds_forms (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    form_key            text NOT NULL CONSTRAINT tds_forms_key_not_blank CHECK (btrim(form_key) <> ''),
    act                 text NOT NULL CONSTRAINT tds_forms_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    form_no             text NOT NULL CONSTRAINT tds_forms_no_not_blank CHECK (btrim(form_no) <> ''),
    description         text NOT NULL CONSTRAINT tds_forms_description_not_blank CHECK (btrim(description) <> ''),
    rule_ref            text,
    replaces_form_no    text,
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT tds_forms_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT tds_forms_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT tds_forms_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT tds_forms_key UNIQUE (form_key, act, effective_from)
);

-- =====================================================================================================
-- Per-client masters
-- =====================================================================================================

-- the deductor's TAN (nullable until the accountant enters it; the statement needs it: rule T-30)
ALTER TABLE clients ADD COLUMN tan text CONSTRAINT clients_tan_format CHECK (tan ~ '^[A-Z]{4}[0-9]{5}[A-Z]$');

-- per client and financial year facts the law makes conditional (Section 194Q: buyer's turnover in the preceding year above the limit).
-- Entered by the accountant, never guessed from the books.
CREATE TABLE tds_client_fy_flags (
    client_id           uuid NOT NULL REFERENCES clients (id),
    financial_year_id   uuid NOT NULL,
    prev_year_turnover_over_threshold boolean NOT NULL,       -- the 194Q buyer condition; the limit itself is in PHASE4_LEGAL_VALUES.md (pending)
    note                text,
    entered_by          text NOT NULL,
    entered_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, financial_year_id),
    CONSTRAINT tds_client_fy_flags_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- the deductee (or collectee) master, one row per party ledger
CREATE TABLE tds_deductees (
    ledger_id           uuid PRIMARY KEY,
    client_id           uuid NOT NULL,
    pan                 text CONSTRAINT tds_deductees_pan_format CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
    pan_status          text NOT NULL CONSTRAINT tds_deductees_pan_status_check
                        CHECK (pan_status IN ('valid', 'missing', 'invalid', 'applied_for')),   -- valid = confirmed by the accountant (e.g. on the portal)
    deductee_type       text NOT NULL CONSTRAINT tds_deductees_type_check CHECK (deductee_type IN
                        ('individual', 'huf', 'company', 'firm', 'llp', 'aop_boi', 'co_operative_society', 'local_authority', 'trust', 'other')),
    default_nature_key  text REFERENCES tds_natures (nature_key),   -- a suggestion on entry; the accountant confirms per voucher
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_deductees_ledger_client_key UNIQUE (ledger_id, client_id),
    CONSTRAINT tds_deductees_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT tds_deductees_pan_needed CHECK ((pan_status IN ('valid', 'invalid')) = (pan IS NOT NULL))   -- missing / applied_for carry no PAN; PAN type letter vs deductee_type is engine rule T-10
);
CREATE INDEX tds_deductees_client_idx ON tds_deductees (client_id);

-- lower / nil deduction certificate (Form 13 / Form 128): number, rate, limit, validity. Used-up amount is computed from tds_voucher_items.
CREATE TABLE tds_lower_deduction_certs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    deductee_ledger_id  uuid NOT NULL,
    certificate_no      text NOT NULL CONSTRAINT tds_ldc_no_not_blank CHECK (btrim(certificate_no) <> ''),
    nature_key          text REFERENCES tds_natures (nature_key),    -- NULL = the certificate names no single nature (accountant states the nature on each use)
    rate                numeric(7, 4) NOT NULL CONSTRAINT tds_ldc_rate_range CHECK (rate >= 0 AND rate <= 100),     -- 0 = nil deduction
    max_amount          numeric(18, 4) NOT NULL CONSTRAINT tds_ldc_max_pos CHECK (max_amount > 0),                   -- limit of payments covered by the certificate
    valid_from          date NOT NULL,
    valid_to            date NOT NULL,
    note                text,
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_ldc_max_two_decimals CHECK (max_amount = round(max_amount, 2)),
    CONSTRAINT tds_ldc_period CHECK (valid_to >= valid_from),
    CONSTRAINT tds_ldc_id_client_key UNIQUE (id, client_id),
    CONSTRAINT tds_ldc_key UNIQUE (client_id, certificate_no, valid_from),
    CONSTRAINT tds_ldc_deductee_fk FOREIGN KEY (deductee_ledger_id, client_id) REFERENCES tds_deductees (ledger_id, client_id)
);
CREATE INDEX tds_ldc_deductee_idx ON tds_lower_deduction_certs (deductee_ledger_id, valid_from);

-- which ledger of the client plays which TDS / TCS role (TDS payable under Duties & Taxes, TCS payable, TDS / TCS receivable)
-- nature_key NULL = the default ledger of the role; a row with a nature_key overrides it for that nature (e.g. 'TDS Payable - 194C')
CREATE TABLE tds_ledger_roles (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL REFERENCES clients (id),
    role                text NOT NULL CONSTRAINT tds_ledger_roles_role_check
                        CHECK (role IN ('tds_payable', 'tcs_payable', 'tds_receivable', 'tcs_receivable', 'interest_expense', 'late_fee_expense')),
    nature_key          text REFERENCES tds_natures (nature_key),
    ledger_id           uuid NOT NULL,
    CONSTRAINT tds_ledger_roles_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE UNIQUE INDEX tds_ledger_roles_key ON tds_ledger_roles (client_id, role, coalesce(nature_key, ''));
CREATE INDEX tds_ledger_roles_ledger_idx ON tds_ledger_roles (ledger_id);

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE tds_natures               ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_section_refs          ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_rates                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_provisions            ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_due_dates             ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_interest_rules        ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_forms                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_client_fy_flags       ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_deductees             ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_lower_deduction_certs ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_ledger_roles          ENABLE ROW LEVEL SECURITY;
