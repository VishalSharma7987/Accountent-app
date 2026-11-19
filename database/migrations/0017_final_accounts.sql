-- 0017: period-end and final accounts (Phase 6, step 6.0). Schema-agnostic (see 0003).
-- Money: numeric(18,4) + CHECK (x = round(x, 2)) (0004): the database rejects 10.005, it never rounds it. Percentages and rates are
-- numeric(18,6) + CHECK (x = round(x, 4)) for the same reason. Useful life in years: numeric(18,4) + CHECK (x = round(x, 2)).
-- RLS on every table, no policies. Functions pin their search_path; function privileges are closed at the end (0004 / 0016 pattern).
--
-- Design in one paragraph: nothing here changes how ledgers or vouchers work. Adjustments, depreciation and the year-end closing
-- entries are ordinary Journal vouchers created through the voucher service (draft -> approved -> posted, reversal only by a linked
-- reversal voucher); these tables only RECORD why a journal exists and keep the inputs that no voucher line can carry (partners'
-- terms, asset register, block WDV working, approved closing stock, statement classification, statement snapshots, year-end close).
-- Law is data: depreciation rates, Schedule II useful lives, the 180-day half-rate rule and the Schedule III line items are rows with
-- effective_from / effective_to / source_reference / verification_status (seeds 0012, 0013).

-- =====================================================================================================
-- Law tables (rules by date): income-tax depreciation block rates, income-tax rule scalars, Schedule II classes
-- =====================================================================================================
CREATE TABLE dep_it_block_rates (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    block_key           text NOT NULL CONSTRAINT dep_it_block_rates_key_not_blank CHECK (btrim(block_key) <> ''),
    description         text NOT NULL,
    act                 text NOT NULL CONSTRAINT dep_it_block_rates_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    rate                numeric(18, 6) NOT NULL CONSTRAINT dep_it_block_rates_range CHECK (rate >= 0 AND rate <= 100),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT dep_it_block_rates_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT dep_it_block_rates_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT dep_it_block_rates_four_decimals CHECK (rate = round(rate, 4)),
    CONSTRAINT dep_it_block_rates_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT dep_it_block_rates_unique UNIQUE (block_key, act, effective_from)
);
CREATE INDEX dep_it_block_rates_lookup_idx ON dep_it_block_rates (block_key, effective_from);

-- scalar income-tax depreciation rules: 'half_rate_days' (an addition put to use for fewer days than this gets the half rate)
-- and 'half_rate_percent' (the share of the block rate that is allowed in that case)
CREATE TABLE dep_it_rules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key            text NOT NULL CONSTRAINT dep_it_rules_key_check CHECK (rule_key IN ('half_rate_days', 'half_rate_percent')),
    act                 text NOT NULL CONSTRAINT dep_it_rules_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    rule_value          numeric(18, 6) NOT NULL CONSTRAINT dep_it_rules_value_nonneg CHECK (rule_value >= 0),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT dep_it_rules_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT dep_it_rules_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT dep_it_rules_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT dep_it_rules_unique UNIQUE (rule_key, act, effective_from)
);

-- Companies Act 2013 Schedule II (Part C): useful life by class of asset, and the residual value ceiling
CREATE TABLE dep_sched2_classes (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    class_key             text NOT NULL CONSTRAINT dep_sched2_classes_key_not_blank CHECK (btrim(class_key) <> ''),
    description           text NOT NULL,
    useful_life_years     numeric(18, 4) NOT NULL CONSTRAINT dep_sched2_classes_life_pos CHECK (useful_life_years > 0),
    max_residual_percent  numeric(18, 6) NOT NULL DEFAULT 5 CONSTRAINT dep_sched2_classes_residual_range
                          CHECK (max_residual_percent >= 0 AND max_residual_percent <= 100),
    effective_from        date NOT NULL,
    effective_to          date,
    source_reference      text NOT NULL CONSTRAINT dep_sched2_classes_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status   text NOT NULL CONSTRAINT dep_sched2_classes_verification_check
                          CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes                 text,
    CONSTRAINT dep_sched2_classes_life_two_decimals CHECK (useful_life_years = round(useful_life_years, 2)),
    CONSTRAINT dep_sched2_classes_residual_four_decimals CHECK (max_residual_percent = round(max_residual_percent, 4)),
    CONSTRAINT dep_sched2_classes_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT dep_sched2_classes_unique UNIQUE (class_key, effective_from)
);

-- =====================================================================================================
-- Statement classification: Schedule III Division I line items (rule data), the default group -> line map, and the client's
-- ledger-level overrides (a Loans ledger is long-term or short-term only the accountant knows; never guessed)
-- =====================================================================================================
CREATE TABLE fs_lines (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    format_key          text NOT NULL CONSTRAINT fs_lines_format_check CHECK (format_key IN ('sch3_bs', 'sch3_pl')),
    line_code           text NOT NULL CONSTRAINT fs_lines_code_not_blank CHECK (btrim(line_code) <> ''),
    label               text NOT NULL,
    section             text NOT NULL CONSTRAINT fs_lines_section_check
                        CHECK (section IN ('equity', 'non_current_liabilities', 'current_liabilities',
                                           'non_current_assets', 'current_assets', 'income', 'expenses')),
    sort_order          integer NOT NULL,
    note_title          text,
    cf_class            text NOT NULL CONSTRAINT fs_lines_cf_check
                        CHECK (cf_class IN ('operating', 'investing', 'financing', 'cash_equivalent', 'non_cash', 'equity_profit')),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT fs_lines_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT fs_lines_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    CONSTRAINT fs_lines_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT fs_lines_unique UNIQUE (format_key, line_code, effective_from)
);

-- group_code is the stable code of a system account group (0001 seed). is_firm = false: the default is only the usual home of that
-- group; statements print a "classified by default" warning listing those ledgers until the accountant confirms them in
-- client_ledger_fs_map. A group with NO row here must be classified ledger by ledger (rule F-44, blocks the company statements).
CREATE TABLE fs_group_map (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_code          text NOT NULL CONSTRAINT fs_group_map_group_not_blank CHECK (btrim(group_code) <> ''),
    format_key          text NOT NULL CONSTRAINT fs_group_map_format_check CHECK (format_key IN ('sch3_bs', 'sch3_pl')),
    line_code           text NOT NULL,
    is_firm             boolean NOT NULL,
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT fs_group_map_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT fs_group_map_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    CONSTRAINT fs_group_map_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT fs_group_map_unique UNIQUE (group_code, format_key, effective_from)
);

CREATE TABLE client_ledger_fs_map (
    client_id   uuid NOT NULL,
    ledger_id   uuid NOT NULL,
    line_code   text,                       -- Schedule III line; NULL = keep the group default, only cf_class is overridden
    cf_class    text CONSTRAINT client_ledger_fs_map_cf_check
                CHECK (cf_class IN ('operating', 'investing', 'financing', 'cash_equivalent', 'non_cash', 'equity_profit')),
    note        text,
    set_by      text NOT NULL,
    set_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, ledger_id),
    CONSTRAINT client_ledger_fs_map_something CHECK (line_code IS NOT NULL OR cf_class IS NOT NULL),
    CONSTRAINT client_ledger_fs_map_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id)
);

-- =====================================================================================================
-- final_ledger_roles: which ledger plays which part in the closing entries and statements (explicit, like gst / tds ledger roles)
-- =====================================================================================================
CREATE TABLE final_ledger_roles (
    client_id  uuid NOT NULL,
    role       text NOT NULL CONSTRAINT final_ledger_roles_role_check CHECK (role IN (
               'trading_account', 'profit_and_loss', 'surplus_in_pl',
               'stock_ledger',
               'depreciation_expense', 'accumulated_depreciation',
               'bad_debts', 'doubtful_debts_expense', 'provision_doubtful_debts',
               'interest_on_capital', 'interest_on_drawings', 'partner_remuneration')),
    ledger_id  uuid NOT NULL,
    set_by     text NOT NULL,
    set_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, role),
    CONSTRAINT final_ledger_roles_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id)
);

-- =====================================================================================================
-- Partners: capital / current ledgers of each partner (created at client setup) and the deed terms per financial year.
-- These are DEED values (not law): every interest rate / remuneration needs the deed reference text.
-- =====================================================================================================
CREATE TABLE partners (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id          uuid NOT NULL REFERENCES clients (id),
    name               text NOT NULL CONSTRAINT partners_name_not_blank CHECK (btrim(name) <> ''),
    capital_ledger_id  uuid NOT NULL,
    current_ledger_id  uuid,               -- the share of profit is credited here when set, else to the capital ledger
    is_active          boolean NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT partners_id_client_key UNIQUE (id, client_id),
    CONSTRAINT partners_ledgers_differ CHECK (current_ledger_id IS NULL OR current_ledger_id <> capital_ledger_id),
    CONSTRAINT partners_capital_fk FOREIGN KEY (capital_ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT partners_current_fk FOREIGN KEY (current_ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE UNIQUE INDEX partners_client_name_key ON partners (client_id, lower(btrim(name)));
CREATE UNIQUE INDEX partners_capital_ledger_key ON partners (capital_ledger_id);

CREATE TABLE partner_fy_terms (
    partner_id                uuid NOT NULL,
    client_id                 uuid NOT NULL,
    financial_year_id         uuid NOT NULL,
    profit_share_percent      numeric(18, 6) NOT NULL CONSTRAINT partner_fy_terms_share_range CHECK (profit_share_percent >= 0 AND profit_share_percent <= 100),
    interest_on_capital_rate  numeric(18, 6) CONSTRAINT partner_fy_terms_ioc_range CHECK (interest_on_capital_rate >= 0 AND interest_on_capital_rate <= 100),
    interest_on_drawings_rate numeric(18, 6) CONSTRAINT partner_fy_terms_iod_range CHECK (interest_on_drawings_rate >= 0 AND interest_on_drawings_rate <= 100),
    remuneration_annual       numeric(18, 4) CONSTRAINT partner_fy_terms_rem_nonneg CHECK (remuneration_annual >= 0),
    deed_reference            text,
    set_by                    text NOT NULL,
    set_at                    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (partner_id, financial_year_id),
    CONSTRAINT partner_fy_terms_share_four_decimals CHECK (profit_share_percent = round(profit_share_percent, 4)),
    CONSTRAINT partner_fy_terms_ioc_four_decimals CHECK (interest_on_capital_rate = round(interest_on_capital_rate, 4)),
    CONSTRAINT partner_fy_terms_iod_four_decimals CHECK (interest_on_drawings_rate = round(interest_on_drawings_rate, 4)),
    CONSTRAINT partner_fy_terms_rem_two_decimals CHECK (remuneration_annual = round(remuneration_annual, 2)),
    CONSTRAINT partner_fy_terms_deed_needed CHECK (
        (interest_on_capital_rate IS NULL AND interest_on_drawings_rate IS NULL AND remuneration_annual IS NULL)
        OR btrim(coalesce(deed_reference, '')) <> ''),
    CONSTRAINT partner_fy_terms_partner_fk FOREIGN KEY (partner_id, client_id) REFERENCES partners (id, client_id),
    CONSTRAINT partner_fy_terms_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- =====================================================================================================
-- adjustment_entries: why a draft journal exists (outstanding expense, prepaid, accrued income, income in advance, provision,
-- bad debt, provision for doubtful debts, interest on capital / drawings, partner's remuneration). The journal itself is a voucher.
-- The row is written together with the draft voucher and changes only while that voucher is a draft (same guard as the GST child tables).
-- =====================================================================================================
CREATE TABLE adjustment_entries (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id               uuid NOT NULL,
    financial_year_id       uuid NOT NULL,
    adj_type                text NOT NULL CONSTRAINT adjustment_entries_type_check CHECK (adj_type IN (
                            'outstanding_expense', 'prepaid_expense', 'accrued_income', 'income_in_advance', 'provision',
                            'bad_debt', 'provision_doubtful_debts', 'interest_on_capital', 'interest_on_drawings', 'partner_remuneration')),
    as_on_date              date NOT NULL,
    amount                  numeric(18, 4) NOT NULL CONSTRAINT adjustment_entries_amount_pos CHECK (amount > 0),
    params                  jsonb NOT NULL DEFAULT '{}'::jsonb,       -- the inputs the engine used (base, rate, days, partner ...)
    basis_note              text NOT NULL CONSTRAINT adjustment_entries_basis_not_blank CHECK (btrim(basis_note) <> ''),
    voucher_id              uuid NOT NULL,
    auto_reverse_voucher_id uuid,                                     -- optional draft journal in the next FY on its first day
    created_by              text NOT NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT adjustment_entries_amount_two_decimals CHECK (amount = round(amount, 2)),
    CONSTRAINT adjustment_entries_voucher_key UNIQUE (voucher_id),
    CONSTRAINT adjustment_entries_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT adjustment_entries_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id),
    CONSTRAINT adjustment_entries_reverse_fk FOREIGN KEY (auto_reverse_voucher_id, client_id) REFERENCES vouchers (id, client_id)
);
CREATE INDEX adjustment_entries_year_idx ON adjustment_entries (client_id, financial_year_id, adj_type);

-- =====================================================================================================
-- Fixed Asset Register
-- =====================================================================================================
CREATE TABLE fixed_assets (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id                uuid NOT NULL REFERENCES clients (id),
    asset_no                 text NOT NULL CONSTRAINT fixed_assets_no_not_blank CHECK (btrim(asset_no) <> ''),
    name                     text NOT NULL CONSTRAINT fixed_assets_name_not_blank CHECK (btrim(name) <> ''),
    asset_ledger_id          uuid NOT NULL,                      -- a ledger of the Fixed Assets group (service rule F-20)
    accumulated_dep_ledger_id uuid,                              -- NULL = book depreciation is credited to the asset ledger itself
    is_depreciable           boolean NOT NULL DEFAULT true,      -- false: land, capital work in progress
    it_block_key             text,                               -- income-tax block (dep_it_block_rates.block_key); needed when depreciable
    sched2_class_key         text,                               -- Schedule II class (dep_sched2_classes.class_key)
    useful_life_years        numeric(18, 4),                     -- the life used for book depreciation (class life or an overridden life)
    life_override_reason     text,                               -- required when there is no class (life typed by the accountant)
    residual_value           numeric(18, 4) NOT NULL DEFAULT 0,
    book_method              text CONSTRAINT fixed_assets_method_check CHECK (book_method IN ('slm', 'wdv')),
    is_active                boolean NOT NULL DEFAULT true,
    created_by               text NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fixed_assets_id_client_key UNIQUE (id, client_id),
    CONSTRAINT fixed_assets_residual_nonneg CHECK (residual_value >= 0),
    CONSTRAINT fixed_assets_residual_two_decimals CHECK (residual_value = round(residual_value, 2)),
    CONSTRAINT fixed_assets_life_two_decimals CHECK (useful_life_years = round(useful_life_years, 2)),
    CONSTRAINT fixed_assets_life_pos CHECK (useful_life_years IS NULL OR useful_life_years > 0),
    CONSTRAINT fixed_assets_depreciable_needs_setup CHECK (
        NOT is_depreciable OR (it_block_key IS NOT NULL AND useful_life_years IS NOT NULL AND book_method IS NOT NULL
                               AND (sched2_class_key IS NOT NULL OR btrim(coalesce(life_override_reason, '')) <> ''))),
    CONSTRAINT fixed_assets_asset_fk FOREIGN KEY (asset_ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT fixed_assets_accum_fk FOREIGN KEY (accumulated_dep_ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE UNIQUE INDEX fixed_assets_client_no_key ON fixed_assets (client_id, lower(btrim(asset_no)));

-- events: opening (an asset already in the books at the start: cost and accumulated book depreciation brought forward),
-- purchase (the first acquisition), addition (later capital addition to the asset), disposal (sale / scrapping; amount = sale proceeds)
CREATE TABLE fixed_asset_events (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    asset_id            uuid NOT NULL,
    kind                text NOT NULL CONSTRAINT fixed_asset_events_kind_check CHECK (kind IN ('opening', 'purchase', 'addition', 'disposal')),
    event_date          date NOT NULL,                          -- purchase date / date of addition / date of disposal; opening: the books-begin date
    put_to_use_date     date,                                   -- needed for every cost event (half-rate rule, pro-rata book depreciation)
    amount              numeric(18, 4) NOT NULL CONSTRAINT fixed_asset_events_amount_nonneg CHECK (amount >= 0),
    accumulated_dep_bf  numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT fixed_asset_events_accum_nonneg CHECK (accumulated_dep_bf >= 0),
    voucher_id          uuid,                                   -- the purchase / sale voucher this came from (information)
    note                text,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fixed_asset_events_amount_two_decimals CHECK (amount = round(amount, 2)),
    CONSTRAINT fixed_asset_events_accum_two_decimals CHECK (accumulated_dep_bf = round(accumulated_dep_bf, 2)),
    CONSTRAINT fixed_asset_events_cost_rules CHECK (
        (kind = 'disposal' AND put_to_use_date IS NULL AND accumulated_dep_bf = 0)
        OR (kind IN ('opening', 'purchase', 'addition') AND amount > 0 AND put_to_use_date IS NOT NULL
            AND (kind = 'opening' OR put_to_use_date >= event_date))),
    CONSTRAINT fixed_asset_events_accum_only_opening CHECK (kind = 'opening' OR accumulated_dep_bf = 0),
    CONSTRAINT fixed_asset_events_asset_fk FOREIGN KEY (asset_id, client_id) REFERENCES fixed_assets (id, client_id),
    CONSTRAINT fixed_asset_events_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id)
);
CREATE INDEX fixed_asset_events_asset_idx ON fixed_asset_events (asset_id, event_date);
CREATE UNIQUE INDEX fixed_asset_events_one_disposal_key ON fixed_asset_events (asset_id) WHERE kind = 'disposal';
CREATE UNIQUE INDEX fixed_asset_events_one_start_key ON fixed_asset_events (asset_id) WHERE kind IN ('opening', 'purchase');

-- Companies Act book depreciation: ONE run per financial year (while its voucher is not reversed) and its journal voucher
CREATE TABLE depreciation_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    book                text NOT NULL DEFAULT 'companies_act' CONSTRAINT depreciation_runs_book_check CHECK (book = 'companies_act'),
    as_on_date          date NOT NULL,
    total_depreciation  numeric(18, 4) NOT NULL CONSTRAINT depreciation_runs_total_nonneg CHECK (total_depreciation >= 0),
    voucher_id          uuid NOT NULL,
    rule_snapshot       jsonb NOT NULL DEFAULT '{}'::jsonb,     -- the Schedule II rows (class, life, source, status) the engine used
    engine_version      text NOT NULL,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT depreciation_runs_total_two_decimals CHECK (total_depreciation = round(total_depreciation, 2)),
    CONSTRAINT depreciation_runs_voucher_key UNIQUE (voucher_id),
    CONSTRAINT depreciation_runs_id_voucher_key UNIQUE (id, voucher_id),
    CONSTRAINT depreciation_runs_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT depreciation_runs_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id)
);
CREATE INDEX depreciation_runs_year_idx ON depreciation_runs (client_id, financial_year_id);

CREATE TABLE depreciation_run_lines (
    run_id              uuid NOT NULL,
    voucher_id          uuid NOT NULL,                          -- repeated from the run so the draft-only guard can be shared
    client_id           uuid NOT NULL,
    asset_id            uuid NOT NULL,
    method              text NOT NULL CONSTRAINT depreciation_run_lines_method_check CHECK (method IN ('slm', 'wdv')),
    cost                numeric(18, 4) NOT NULL CONSTRAINT depreciation_run_lines_cost_nonneg CHECK (cost >= 0),
    opening_accumulated numeric(18, 4) NOT NULL CONSTRAINT depreciation_run_lines_open_nonneg CHECK (opening_accumulated >= 0),
    wdv_rate_percent    numeric(18, 6) CONSTRAINT depreciation_run_lines_rate_range CHECK (wdv_rate_percent >= 0 AND wdv_rate_percent <= 100),
    days_used           integer NOT NULL CONSTRAINT depreciation_run_lines_days_nonneg CHECK (days_used >= 0),
    days_in_year        integer NOT NULL CONSTRAINT depreciation_run_lines_year_days CHECK (days_in_year IN (365, 366)),
    depreciation        numeric(18, 4) NOT NULL CONSTRAINT depreciation_run_lines_dep_nonneg CHECK (depreciation >= 0),
    closing_accumulated numeric(18, 4) NOT NULL,
    details             jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, asset_id),
    CONSTRAINT depreciation_run_lines_cost_two CHECK (cost = round(cost, 2)),
    CONSTRAINT depreciation_run_lines_open_two CHECK (opening_accumulated = round(opening_accumulated, 2)),
    CONSTRAINT depreciation_run_lines_rate_two CHECK (wdv_rate_percent = round(wdv_rate_percent, 2)),
    CONSTRAINT depreciation_run_lines_dep_two CHECK (depreciation = round(depreciation, 2)),
    CONSTRAINT depreciation_run_lines_close_two CHECK (closing_accumulated = round(closing_accumulated, 2)),
    CONSTRAINT depreciation_run_lines_close_sum CHECK (closing_accumulated = opening_accumulated + depreciation),
    CONSTRAINT depreciation_run_lines_run_fk FOREIGN KEY (run_id, voucher_id) REFERENCES depreciation_runs (id, voucher_id) ON DELETE CASCADE,
    CONSTRAINT depreciation_run_lines_asset_fk FOREIGN KEY (asset_id, client_id) REFERENCES fixed_assets (id, client_id)
);

-- Income-tax block depreciation: a WORKING only (no voucher). Opening WDV of the first year is typed; later years are carried
-- from the previous year's final working by the year-end close.
CREATE TABLE it_block_openings (
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    block_key           text NOT NULL,
    opening_wdv         numeric(18, 4) NOT NULL CONSTRAINT it_block_openings_nonneg CHECK (opening_wdv >= 0),
    source              text NOT NULL CONSTRAINT it_block_openings_source_check CHECK (source IN ('entered', 'carried')),
    set_by              text NOT NULL,
    set_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, financial_year_id, block_key),
    CONSTRAINT it_block_openings_two_decimals CHECK (opening_wdv = round(opening_wdv, 2)),
    CONSTRAINT it_block_openings_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

CREATE TABLE it_depreciation_workings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    block_key           text NOT NULL,
    status              text NOT NULL DEFAULT 'draft' CONSTRAINT it_depreciation_workings_status_check CHECK (status IN ('draft', 'final')),
    act                 text NOT NULL CONSTRAINT it_depreciation_workings_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    rate                numeric(18, 6) NOT NULL CONSTRAINT it_depreciation_workings_rate_range CHECK (rate >= 0 AND rate <= 100),
    rate_verification   text NOT NULL CONSTRAINT it_depreciation_workings_verif_check CHECK (rate_verification IN ('verified', 'secondary_verified', 'pending')),
    opening_wdv         numeric(18, 4) NOT NULL,
    additions_full      numeric(18, 4) NOT NULL CONSTRAINT it_depreciation_workings_addf_nonneg CHECK (additions_full >= 0),
    additions_half      numeric(18, 4) NOT NULL CONSTRAINT it_depreciation_workings_addh_nonneg CHECK (additions_half >= 0),
    disposals           numeric(18, 4) NOT NULL CONSTRAINT it_depreciation_workings_disp_nonneg CHECK (disposals >= 0),
    depreciation        numeric(18, 4) NOT NULL CONSTRAINT it_depreciation_workings_dep_nonneg CHECK (depreciation >= 0),
    closing_wdv         numeric(18, 4) NOT NULL,
    details             jsonb NOT NULL DEFAULT '{}'::jsonb,
    engine_version      text NOT NULL,
    computed_by         text NOT NULL,
    computed_at         timestamptz NOT NULL DEFAULT now(),
    superseded_at       timestamptz,
    CONSTRAINT it_depreciation_workings_rate_four CHECK (rate = round(rate, 4)),
    CONSTRAINT it_depreciation_workings_open_two CHECK (opening_wdv = round(opening_wdv, 2)),
    CONSTRAINT it_depreciation_workings_addf_two CHECK (additions_full = round(additions_full, 2)),
    CONSTRAINT it_depreciation_workings_addh_two CHECK (additions_half = round(additions_half, 2)),
    CONSTRAINT it_depreciation_workings_disp_two CHECK (disposals = round(disposals, 2)),
    CONSTRAINT it_depreciation_workings_dep_two CHECK (depreciation = round(depreciation, 2)),
    CONSTRAINT it_depreciation_workings_close_two CHECK (closing_wdv = round(closing_wdv, 2)),
    CONSTRAINT it_depreciation_workings_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);
CREATE UNIQUE INDEX it_depreciation_workings_draft_key ON it_depreciation_workings (client_id, financial_year_id, block_key)
    WHERE status = 'draft' AND superseded_at IS NULL;
CREATE UNIQUE INDEX it_depreciation_workings_final_key ON it_depreciation_workings (client_id, financial_year_id, block_key)
    WHERE status = 'final' AND superseded_at IS NULL;

-- =====================================================================================================
-- final_closing_stock: the closing stock figure the accountant approved for the FY (from the Phase 5 closing-stock report at cost
-- less AS 2 write-down, or typed for a client without inventory). Never guessed: no row = F-41.
-- =====================================================================================================
CREATE TABLE final_closing_stock (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    as_on_date          date NOT NULL,
    source              text NOT NULL CONSTRAINT final_closing_stock_source_check CHECK (source IN ('inventory_report', 'manual', 'none')),
    inventory_method    text,                                   -- fifo / wa_periodic / wa_moving when from the report
    cost_value          numeric(18, 4) NOT NULL CONSTRAINT final_closing_stock_cost_nonneg CHECK (cost_value >= 0),
    write_down          numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT final_closing_stock_wd_nonneg CHECK (write_down >= 0),
    carrying_value      numeric(18, 4) NOT NULL,
    basis_note          text NOT NULL CONSTRAINT final_closing_stock_basis_not_blank CHECK (btrim(basis_note) <> ''),
    detail              jsonb NOT NULL DEFAULT '{}'::jsonb,     -- the item rows of the report at approval time
    approved_by         text NOT NULL,
    approved_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT final_closing_stock_cost_two CHECK (cost_value = round(cost_value, 2)),
    CONSTRAINT final_closing_stock_wd_two CHECK (write_down = round(write_down, 2)),
    CONSTRAINT final_closing_stock_carrying_two CHECK (carrying_value = round(carrying_value, 2)),
    CONSTRAINT final_closing_stock_carrying_sum CHECK (carrying_value = cost_value - write_down AND write_down <= cost_value),
    CONSTRAINT final_closing_stock_none_is_zero CHECK (source <> 'none' OR cost_value = 0),
    CONSTRAINT final_closing_stock_key UNIQUE (client_id, financial_year_id),
    CONSTRAINT final_closing_stock_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- =====================================================================================================
-- statement_snapshots: the statements as they were when signed off (append-only; a re-run inserts a new row and the old one is
-- marked superseded). Used for previous-year comparatives and for reproducible exports.
-- =====================================================================================================
CREATE TABLE statement_snapshots (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    statement_key       text NOT NULL CONSTRAINT statement_snapshots_key_check
                        CHECK (statement_key IN ('trading', 'profit_loss', 'balance_sheet', 'cash_flow')),
    format_key          text NOT NULL CONSTRAINT statement_snapshots_format_check
                        CHECK (format_key IN ('vertical', 'horizontal', 'sch3')),
    payload             jsonb NOT NULL,
    payload_sha256      text NOT NULL CONSTRAINT statement_snapshots_sha_check CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    engine_version      text NOT NULL,
    is_final            boolean NOT NULL DEFAULT false,
    generated_by        text NOT NULL,
    generated_at        timestamptz NOT NULL DEFAULT now(),
    superseded_at       timestamptz,
    CONSTRAINT statement_snapshots_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);
CREATE UNIQUE INDEX statement_snapshots_final_key ON statement_snapshots (client_id, financial_year_id, statement_key)
    WHERE is_final AND superseded_at IS NULL;
CREATE INDEX statement_snapshots_year_idx ON statement_snapshots (client_id, financial_year_id);

-- =====================================================================================================
-- Year-end close. The closing entries are three Journal vouchers made by the voucher service (trading, profit and loss,
-- appropriation); this table family records the close and links those vouchers (and their reversals on reopen).
-- =====================================================================================================
CREATE TABLE year_end_closes (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id               uuid NOT NULL,
    financial_year_id       uuid NOT NULL,
    next_financial_year_id  uuid NOT NULL,
    status                  text NOT NULL CONSTRAINT year_end_closes_status_check CHECK (status IN ('closed', 'reopened')),
    net_profit              numeric(18, 4) NOT NULL,            -- negative = loss
    appropriation           jsonb NOT NULL DEFAULT '{}'::jsonb, -- who got what (capital / partners / surplus)
    carried                 jsonb NOT NULL DEFAULT '{}'::jsonb, -- counts and totals carried forward (ledger openings, bills, stock, IT blocks)
    closed_by               text NOT NULL,
    closed_at               timestamptz NOT NULL DEFAULT now(),
    reopened_by             text,
    reopened_at             timestamptz,
    reopen_reason           text,
    CONSTRAINT year_end_closes_net_profit_two CHECK (net_profit = round(net_profit, 2)),
    CONSTRAINT year_end_closes_id_client_key UNIQUE (id, client_id),
    CONSTRAINT year_end_closes_reopen_fields CHECK (
        (status = 'reopened') = (reopened_by IS NOT NULL AND reopened_at IS NOT NULL AND btrim(coalesce(reopen_reason, '')) <> '')),
    CONSTRAINT year_end_closes_next_differs CHECK (next_financial_year_id <> financial_year_id),
    CONSTRAINT year_end_closes_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT year_end_closes_next_fk FOREIGN KEY (next_financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);
CREATE UNIQUE INDEX year_end_closes_one_closed_key ON year_end_closes (client_id, financial_year_id) WHERE status = 'closed';

CREATE TABLE year_end_close_vouchers (
    close_id    uuid NOT NULL,
    client_id   uuid NOT NULL,
    step        text NOT NULL CONSTRAINT year_end_close_vouchers_step_check CHECK (step IN ('trading', 'profit_loss', 'appropriation')),
    kind        text NOT NULL CONSTRAINT year_end_close_vouchers_kind_check CHECK (kind IN ('closing', 'reversal')),
    voucher_id  uuid NOT NULL,
    PRIMARY KEY (close_id, step, kind),
    CONSTRAINT year_end_close_vouchers_voucher_key UNIQUE (voucher_id),
    CONSTRAINT year_end_close_vouchers_close_fk FOREIGN KEY (close_id, client_id) REFERENCES year_end_closes (id, client_id),
    CONSTRAINT year_end_close_vouchers_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id)
);

-- =====================================================================================================
-- Bills carried across years: the Phase 2 unique index was per client + party + reference. A bill that is still open at the year end is
-- carried to the next FY's opening_bills under the SAME reference, so the key must include the financial year (no data is touched).
-- =====================================================================================================
DROP INDEX opening_bills_ref_key;
CREATE UNIQUE INDEX opening_bills_ref_key ON opening_bills (client_id, financial_year_id, party_ledger_id, lower(btrim(bill_ref)));

-- =====================================================================================================
-- Guards
-- =====================================================================================================

-- A financial year with a 'closed' year_end_closes row is frozen: its inputs (and its opening balances / bills) cannot change.
-- Reopening (status -> 'reopened', reason stored) lifts the freeze. Used by tables that carry client_id + financial_year_id.
CREATE FUNCTION final_year_open_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF EXISTS (SELECT 1 FROM year_end_closes
                   WHERE client_id = OLD.client_id AND financial_year_id = OLD.financial_year_id AND status = 'closed') THEN
            RAISE EXCEPTION '% of a closed financial year cannot be changed (reopen the year first)', TG_TABLE_NAME;
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF EXISTS (SELECT 1 FROM year_end_closes
                   WHERE client_id = NEW.client_id AND financial_year_id = NEW.financial_year_id AND status = 'closed') THEN
            RAISE EXCEPTION '% of a closed financial year cannot be changed (reopen the year first)', TG_TABLE_NAME;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER final_closing_stock_year_guard BEFORE INSERT OR UPDATE OR DELETE ON final_closing_stock
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER adjustment_entries_year_guard BEFORE INSERT OR UPDATE OR DELETE ON adjustment_entries
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER partner_fy_terms_year_guard BEFORE INSERT OR UPDATE OR DELETE ON partner_fy_terms
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER it_block_openings_year_guard BEFORE INSERT OR UPDATE OR DELETE ON it_block_openings
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER depreciation_runs_year_guard BEFORE INSERT OR UPDATE OR DELETE ON depreciation_runs
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER opening_balances_year_guard BEFORE INSERT OR UPDATE OR DELETE ON opening_balances
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER opening_bills_year_guard BEFORE INSERT OR UPDATE OR DELETE ON opening_bills
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();
CREATE TRIGGER stock_opening_year_guard BEFORE INSERT OR UPDATE OR DELETE ON stock_opening
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();

-- adjustment journal rows and depreciation runs change only while their voucher is a draft (shared guard of 0010)
CREATE TRIGGER adjustment_entries_guard BEFORE INSERT OR UPDATE OR DELETE ON adjustment_entries
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();
CREATE TRIGGER depreciation_runs_guard BEFORE INSERT OR UPDATE OR DELETE ON depreciation_runs
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();
CREATE TRIGGER depreciation_run_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON depreciation_run_lines
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();

-- one active depreciation run per financial year: a new run is refused while another run's voucher is draft, approved or posted
CREATE FUNCTION depreciation_runs_single_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext(NEW.financial_year_id::text || 'depreciation'));
    IF EXISTS (
        SELECT 1 FROM depreciation_runs r JOIN vouchers v ON v.id = r.voucher_id
        WHERE r.client_id = NEW.client_id AND r.financial_year_id = NEW.financial_year_id AND r.id <> NEW.id
          AND v.status IN ('draft', 'approved', 'posted')
    ) THEN
        RAISE EXCEPTION 'this financial year already has a depreciation run that is not reversed';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER depreciation_runs_single_guard BEFORE INSERT ON depreciation_runs
    FOR EACH ROW EXECUTE FUNCTION depreciation_runs_single_guard();

-- the voucher of an adjustment or a depreciation run must be a Journal of the same financial year
CREATE FUNCTION final_journal_voucher_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    vt text;
    vfy uuid;
BEGIN
    SELECT voucher_type, financial_year_id INTO vt, vfy FROM vouchers WHERE id = NEW.voucher_id AND client_id = NEW.client_id;
    IF vt IS DISTINCT FROM 'journal' THEN
        RAISE EXCEPTION 'an adjustment or depreciation voucher must be a Journal';
    END IF;
    IF vfy IS DISTINCT FROM NEW.financial_year_id THEN
        RAISE EXCEPTION 'the voucher must belong to the same financial year as the % row', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER depreciation_runs_journal_guard BEFORE INSERT ON depreciation_runs
    FOR EACH ROW EXECUTE FUNCTION final_journal_voucher_guard();
CREATE TRIGGER adjustment_entries_journal_guard BEFORE INSERT ON adjustment_entries
    FOR EACH ROW EXECUTE FUNCTION final_journal_voucher_guard();

-- asset events: chronology (a disposal is the last event; an addition needs an earlier opening / purchase) and the closed-year freeze
CREATE FUNCTION fixed_asset_events_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    last_use date;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF EXISTS (SELECT 1 FROM year_end_closes y JOIN financial_years f ON f.id = y.financial_year_id
                   WHERE y.client_id = OLD.client_id AND y.status = 'closed' AND OLD.event_date BETWEEN f.start_date AND f.end_date) THEN
            RAISE EXCEPTION 'an asset event dated in a closed financial year cannot be changed (reopen the year first)';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF EXISTS (SELECT 1 FROM year_end_closes y JOIN financial_years f ON f.id = y.financial_year_id
                   WHERE y.client_id = NEW.client_id AND y.status = 'closed' AND NEW.event_date BETWEEN f.start_date AND f.end_date) THEN
            RAISE EXCEPTION 'an asset event dated in a closed financial year cannot be changed (reopen the year first)';
        END IF;
        IF NEW.kind = 'disposal' THEN
            SELECT max(put_to_use_date) INTO last_use FROM fixed_asset_events WHERE asset_id = NEW.asset_id AND id <> NEW.id;
            IF last_use IS NULL THEN
                RAISE EXCEPTION 'an asset cannot be disposed of before it was acquired';
            END IF;
            IF NEW.event_date < last_use THEN
                RAISE EXCEPTION 'the disposal date % is before the asset was put to use (%)', NEW.event_date, last_use;
            END IF;
        ELSE
            IF EXISTS (SELECT 1 FROM fixed_asset_events WHERE asset_id = NEW.asset_id AND kind = 'disposal' AND id <> NEW.id
                       AND event_date < NEW.event_date) THEN
                RAISE EXCEPTION 'an asset event cannot be dated after the asset was disposed of';
            END IF;
            IF NEW.kind = 'addition' AND NOT EXISTS (SELECT 1 FROM fixed_asset_events WHERE asset_id = NEW.asset_id
                       AND kind IN ('opening', 'purchase') AND event_date <= NEW.event_date AND id <> NEW.id) THEN
                RAISE EXCEPTION 'an addition needs an earlier opening or purchase event of the same asset';
            END IF;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER fixed_asset_events_guard BEFORE INSERT OR UPDATE OR DELETE ON fixed_asset_events
    FOR EACH ROW EXECUTE FUNCTION fixed_asset_events_guard();

-- snapshots and IT workings: never deleted; a row can only be marked superseded (once). A DRAFT working may be recomputed in place;
-- finalising a working = inserting a 'final' row and marking the draft superseded.
CREATE FUNCTION final_append_only_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '% rows cannot be deleted', TG_TABLE_NAME;
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'it_depreciation_workings' THEN   -- (nested: plpgsql does not short-circuit, snapshots have no status column)
        IF OLD.status = 'draft' AND NEW.status = 'draft' AND OLD.superseded_at IS NULL AND NEW.superseded_at IS NULL THEN
            RETURN NEW;
        END IF;
    END IF;
    IF OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') <> (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION '% rows are append-only (a row can only be marked superseded, once)', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER statement_snapshots_guard BEFORE INSERT OR UPDATE OR DELETE ON statement_snapshots
    FOR EACH ROW EXECUTE FUNCTION final_append_only_guard();
CREATE TRIGGER it_depreciation_workings_guard BEFORE INSERT OR UPDATE OR DELETE ON it_depreciation_workings
    FOR EACH ROW EXECUTE FUNCTION final_append_only_guard();
CREATE TRIGGER it_depreciation_workings_year_guard BEFORE INSERT OR UPDATE ON it_depreciation_workings
    FOR EACH ROW EXECUTE FUNCTION final_year_open_guard();

-- year_end_closes: created as 'closed'; the only update is closed -> reopened (reason stored); never deleted
CREATE FUNCTION year_end_closes_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a year-end close record cannot be deleted (reopen the year instead)';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'closed' THEN
            RAISE EXCEPTION 'a year-end close is created as closed';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status <> 'closed' OR NEW.status <> 'reopened'
       OR (to_jsonb(NEW) - 'status' - 'reopened_by' - 'reopened_at' - 'reopen_reason')
          <> (to_jsonb(OLD) - 'status' - 'reopened_by' - 'reopened_at' - 'reopen_reason') THEN
        RAISE EXCEPTION 'a year-end close can only change from closed to reopened (with who, when and why)';
    END IF;
    IF (SELECT count(*) FROM year_end_close_vouchers WHERE close_id = OLD.id AND kind = 'reversal')
       <> (SELECT count(*) FROM year_end_close_vouchers WHERE close_id = OLD.id AND kind = 'closing') THEN
        RAISE EXCEPTION 'reopen needs every closing voucher to be reversed first';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER year_end_closes_guard BEFORE INSERT OR UPDATE OR DELETE ON year_end_closes
    FOR EACH ROW EXECUTE FUNCTION year_end_closes_guard();

-- close voucher links: insert-only; the voucher must be a posted Journal; a reversal row must point at the reversal voucher of the
-- same step's closing voucher
CREATE FUNCTION year_end_close_vouchers_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    v vouchers%ROWTYPE;
    orig uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'year_end_close_vouchers rows cannot be changed or deleted';
    END IF;
    SELECT * INTO v FROM vouchers WHERE id = NEW.voucher_id AND client_id = NEW.client_id;
    IF v.voucher_type IS DISTINCT FROM 'journal' OR v.status NOT IN ('posted', 'reversed') THEN
        RAISE EXCEPTION 'a closing voucher must be a posted Journal';
    END IF;
    IF NEW.kind = 'reversal' THEN
        SELECT voucher_id INTO orig FROM year_end_close_vouchers
            WHERE close_id = NEW.close_id AND step = NEW.step AND kind = 'closing';
        IF orig IS NULL OR v.reverses_voucher_id IS DISTINCT FROM orig THEN
            RAISE EXCEPTION 'a reversal row must point at the reversal voucher of the same step''s closing voucher';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER year_end_close_vouchers_guard BEFORE INSERT OR UPDATE OR DELETE ON year_end_close_vouchers
    FOR EACH ROW EXECUTE FUNCTION year_end_close_vouchers_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE dep_it_block_rates       ENABLE ROW LEVEL SECURITY;
ALTER TABLE dep_it_rules             ENABLE ROW LEVEL SECURITY;
ALTER TABLE dep_sched2_classes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE fs_lines                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE fs_group_map             ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_ledger_fs_map     ENABLE ROW LEVEL SECURITY;
ALTER TABLE final_ledger_roles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE partners                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE partner_fy_terms         ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustment_entries       ENABLE ROW LEVEL SECURITY;
ALTER TABLE fixed_assets             ENABLE ROW LEVEL SECURITY;
ALTER TABLE fixed_asset_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE depreciation_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE depreciation_run_lines   ENABLE ROW LEVEL SECURITY;
ALTER TABLE it_block_openings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE it_depreciation_workings ENABLE ROW LEVEL SECURITY;
ALTER TABLE final_closing_stock      ENABLE ROW LEVEL SECURITY;
ALTER TABLE statement_snapshots      ENABLE ROW LEVEL SECURITY;
ALTER TABLE year_end_closes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE year_end_close_vouchers  ENABLE ROW LEVEL SECURITY;

-- =====================================================================================================
-- Close function privileges again (see 0004): functions created by this migration must not be executable
-- by PUBLIC or the Supabase API roles. On a PostgreSQL without those roles this does nothing.
-- =====================================================================================================
DO $$
DECLARE
    s text := current_schema();
    r text;
BEGIN
    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM PUBLIC', s);
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM %I', s, r);
        END IF;
    END LOOP;
END $$;
