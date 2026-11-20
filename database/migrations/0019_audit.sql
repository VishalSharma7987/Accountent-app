-- 0019: audit assistant (Phase 8, step 8.0). Schema-agnostic (see 0003). RLS on every table, no policies; function privileges are closed
-- at the end (0004 / 0016 / 0017 / 0018 pattern). Functions pin their search_path.
--
-- Design in one paragraph: the audit is READ-ONLY on the books. A run (`audit_runs`) reads vouchers, ledgers, bills, returns and documents,
-- applies pure engine checks (catalogue `audit_checks`, limits in the rule table `audit_rule_limits` picked by date) and stores its
-- exceptions (`audit_findings`) with evidence (voucher ids, ledger, document). Nothing here has a foreign key that can change a voucher, and
-- the audit service never writes to a books table. Runs and findings are insert-only evidence. A working paper per check
-- (`audit_working_papers`) records population, sample (method + seed, reproducible), exceptions with the reviewer's decision
-- (`audit_paper_items`: open / cleared / confirmed, a reason is mandatory), and notes. Once SIGNED OFF the paper, its items and its notes
-- are immutable (database trigger). An AI summary (`audit_ai_summaries`) is plain-language text stored as a suggestion; it never carries a
-- conclusion (the conclusion is the reviewer's text on the paper). Form 3CD / Form 26 data points live in `audit_form_sets` and
-- `audit_form_entries` (derived from a run or typed by the accountant); a finalised set is immutable.
-- Money columns follow 0004 (numeric(18,4) + CHECK = round(x, 2)); money inside jsonb evidence is carried as strings.

-- =====================================================================================================
-- Rule table: legal limits for the audit checks (law is data: effective dates, source, verification status)
-- =====================================================================================================
CREATE TABLE audit_rule_limits (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_key            text NOT NULL CONSTRAINT audit_rule_limits_key_check CHECK (rule_key IN
                        ('cash_payment_daily_limit', 'cash_payment_daily_limit_transport', 'cash_receipt_limit')),
    law                 text NOT NULL CONSTRAINT audit_rule_limits_law_check CHECK (law IN ('it_act_1961', 'it_act_2025')),
    section_ref         text NOT NULL CONSTRAINT audit_rule_limits_section_not_blank CHECK (btrim(section_ref) <> ''),
    amount              numeric(18, 4) NOT NULL CONSTRAINT audit_rule_limits_amount_positive CHECK (amount > 0),
    -- the law's wording: 40A(3) bites on a payment ABOVE the limit, 269ST on a receipt of the limit OR MORE
    breach_when         text NOT NULL CONSTRAINT audit_rule_limits_breach_check CHECK (breach_when IN ('above', 'at_or_above')),
    disallow_percent    numeric(5, 2) CONSTRAINT audit_rule_limits_percent_range CHECK (disallow_percent IS NULL OR disallow_percent BETWEEN 0 AND 100),
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT audit_rule_limits_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT audit_rule_limits_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT audit_rule_limits_amount_two_decimals CHECK (amount = round(amount, 2)),
    CONSTRAINT audit_rule_limits_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT audit_rule_limits_key_law_from UNIQUE (rule_key, law, effective_from)
);

-- =====================================================================================================
-- Check catalogue (system data): ID, description, rule, default severity, evidence query
-- =====================================================================================================
CREATE TABLE audit_checks (
    check_id       text PRIMARY KEY CONSTRAINT audit_checks_id_format CHECK (check_id ~ '^A-[0-9]{2}$'),
    title          text NOT NULL CONSTRAINT audit_checks_title_not_blank CHECK (btrim(title) <> ''),
    description    text NOT NULL CONSTRAINT audit_checks_description_not_blank CHECK (btrim(description) <> ''),
    rule_text      text NOT NULL CONSTRAINT audit_checks_rule_not_blank CHECK (btrim(rule_text) <> ''),
    severity       text NOT NULL CONSTRAINT audit_checks_severity_check CHECK (severity IN ('error', 'review', 'warning', 'info')),
    category       text NOT NULL CONSTRAINT audit_checks_category_check CHECK (category IN ('books', 'compliance', 'analytical')),
    evidence_query text NOT NULL CONSTRAINT audit_checks_evidence_not_blank CHECK (btrim(evidence_query) <> ''),
    rule_key       text,                 -- audit_rule_limits.rule_key the check reads, if any
    sort_order     integer NOT NULL DEFAULT 0,
    active         boolean NOT NULL DEFAULT true
);

-- =====================================================================================================
-- Tax audit report forms (system data): Form 3CD (1961 Act) and Form 26 (2025 Act) and their derivable clauses
-- =====================================================================================================
CREATE TABLE audit_form_defs (
    form_key            text PRIMARY KEY CONSTRAINT audit_form_defs_key_check CHECK (form_key IN ('form_3cd', 'form_26')),
    title               text NOT NULL,
    law                 text NOT NULL CONSTRAINT audit_form_defs_law_check CHECK (law IN ('it_act_1961', 'it_act_2025')),
    section_ref         text NOT NULL,
    effective_from      date NOT NULL,
    effective_to        date,
    source_reference    text NOT NULL CONSTRAINT audit_form_defs_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT audit_form_defs_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    notes               text,
    CONSTRAINT audit_form_defs_period CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE audit_form_clauses (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    form_key            text NOT NULL REFERENCES audit_form_defs (form_key),
    clause_no           text NOT NULL CONSTRAINT audit_form_clauses_no_not_blank CHECK (btrim(clause_no) <> ''),
    title               text NOT NULL,
    derivability        text NOT NULL CONSTRAINT audit_form_clauses_derivability_check CHECK (derivability IN ('books', 'partly_books', 'manual')),
    data_source         text,            -- check id / phase the data comes from, e.g. 'A-05' or 'phase 6 IT depreciation'
    sort_order          integer NOT NULL DEFAULT 0,
    source_reference    text NOT NULL CONSTRAINT audit_form_clauses_source_not_blank CHECK (btrim(source_reference) <> ''),
    verification_status text NOT NULL CONSTRAINT audit_form_clauses_verification_check
                        CHECK (verification_status IN ('verified', 'secondary_verified', 'pending')),
    CONSTRAINT audit_form_clauses_form_clause_key UNIQUE (form_key, clause_no)
);

-- =====================================================================================================
-- Client masters used by the checks: holidays (Sundays are computed) and flagged related parties
-- =====================================================================================================
CREATE TABLE audit_holidays (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL REFERENCES clients (id),
    holiday_date date NOT NULL,
    name         text NOT NULL CONSTRAINT audit_holidays_name_not_blank CHECK (btrim(name) <> ''),
    kind         text NOT NULL DEFAULT 'client' CONSTRAINT audit_holidays_kind_check CHECK (kind IN ('national', 'state', 'local', 'client')),
    note         text,
    created_by   text NOT NULL CONSTRAINT audit_holidays_created_by_not_blank CHECK (btrim(created_by) <> ''),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_holidays_client_date_key UNIQUE (client_id, holiday_date)
);

CREATE TABLE audit_related_parties (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL,
    ledger_id    uuid NOT NULL,
    relationship text NOT NULL CONSTRAINT audit_related_parties_relationship_not_blank CHECK (btrim(relationship) <> ''),
    active       boolean NOT NULL DEFAULT true,
    flagged_by   text NOT NULL CONSTRAINT audit_related_parties_flagged_by_not_blank CHECK (btrim(flagged_by) <> ''),
    flagged_at   timestamptz NOT NULL DEFAULT now(),
    note         text,
    CONSTRAINT audit_related_parties_ledger_key UNIQUE (client_id, ledger_id),
    CONSTRAINT audit_related_parties_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id)
);

-- =====================================================================================================
-- Runs and findings: insert-only evidence of what the checks found on the books at that time
-- =====================================================================================================
CREATE TABLE audit_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    from_date         date NOT NULL,
    to_date           date NOT NULL,
    check_ids         text[] NOT NULL CONSTRAINT audit_runs_checks_not_empty CHECK (cardinality(check_ids) > 0),
    params            jsonb NOT NULL DEFAULT '{}'::jsonb CONSTRAINT audit_runs_params_object CHECK (jsonb_typeof(params) = 'object'),
    rules_used        jsonb NOT NULL DEFAULT '[]'::jsonb CONSTRAINT audit_runs_rules_array CHECK (jsonb_typeof(rules_used) = 'array'),
    engine_version    text NOT NULL,
    status            text NOT NULL CONSTRAINT audit_runs_status_check CHECK (status IN ('completed', 'failed')),
    finding_count     integer NOT NULL DEFAULT 0 CONSTRAINT audit_runs_count_nonneg CHECK (finding_count >= 0),
    summary           jsonb NOT NULL DEFAULT '{}'::jsonb CONSTRAINT audit_runs_summary_object CHECK (jsonb_typeof(summary) = 'object'),
    error_message     text,
    created_by        text NOT NULL CONSTRAINT audit_runs_created_by_not_blank CHECK (btrim(created_by) <> ''),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_runs_id_client_key UNIQUE (id, client_id),
    CONSTRAINT audit_runs_period CHECK (to_date >= from_date),
    CONSTRAINT audit_runs_failed_has_reason CHECK (status <> 'failed' OR btrim(coalesce(error_message, '')) <> ''),
    CONSTRAINT audit_runs_financial_year_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);
CREATE INDEX audit_runs_client_idx ON audit_runs (client_id, created_at);

CREATE TABLE audit_findings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    run_id              uuid NOT NULL,
    check_id            text NOT NULL REFERENCES audit_checks (check_id),
    finding_key         text NOT NULL CONSTRAINT audit_findings_key_not_blank CHECK (btrim(finding_key) <> ''),  -- deterministic per subject, e.g. A-05:<party>:<date>
    severity            text NOT NULL CONSTRAINT audit_findings_severity_check CHECK (severity IN ('error', 'review', 'warning', 'info')),
    subject_kind        text NOT NULL CONSTRAINT audit_findings_subject_kind_check
                        CHECK (subject_kind IN ('voucher', 'ledger', 'party', 'document', 'return', 'period', 'stock_item', 'bill')),
    subject_id          uuid,
    subject_ref         text NOT NULL CONSTRAINT audit_findings_subject_ref_not_blank CHECK (btrim(subject_ref) <> ''),
    finding_date        date,
    amount              numeric(18, 4),
    disallowance_amount numeric(18, 4),
    message             text NOT NULL CONSTRAINT audit_findings_message_not_blank CHECK (btrim(message) <> ''),
    evidence            jsonb NOT NULL CONSTRAINT audit_findings_evidence_present
                        CHECK (jsonb_typeof(evidence) = 'object' AND evidence <> '{}'::jsonb),   -- no finding without evidence
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_findings_id_client_key UNIQUE (id, client_id),
    CONSTRAINT audit_findings_run_key UNIQUE (run_id, finding_key),
    CONSTRAINT audit_findings_amount_two_decimals CHECK (amount IS NULL OR amount = round(amount, 2)),
    CONSTRAINT audit_findings_disallowance_two_decimals CHECK (disallowance_amount IS NULL OR disallowance_amount = round(disallowance_amount, 2)),
    CONSTRAINT audit_findings_disallowance_nonneg CHECK (disallowance_amount IS NULL OR disallowance_amount >= 0),
    CONSTRAINT audit_findings_run_fk FOREIGN KEY (run_id, client_id) REFERENCES audit_runs (id, client_id)
);
CREATE INDEX audit_findings_run_check_idx ON audit_findings (run_id, check_id);
CREATE INDEX audit_findings_subject_idx ON audit_findings (subject_id);

-- =====================================================================================================
-- Working papers: one per run + check. Population, sample (reproducible), exceptions with decisions, notes; immutable once signed off.
-- =====================================================================================================
CREATE TABLE audit_working_papers (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    run_id              uuid NOT NULL,
    check_id            text NOT NULL REFERENCES audit_checks (check_id),
    status              text NOT NULL DEFAULT 'open' CONSTRAINT audit_working_papers_status_check CHECK (status IN ('open', 'in_review', 'signed_off')),
    population_count    integer NOT NULL DEFAULT 0 CONSTRAINT audit_working_papers_population_nonneg CHECK (population_count >= 0),
    population_digest   text CONSTRAINT audit_working_papers_digest_format CHECK (population_digest IS NULL OR population_digest ~ '^[0-9a-f]{64}$'),
    population_amount   numeric(18, 4),
    sample_method       text NOT NULL DEFAULT 'none' CONSTRAINT audit_working_papers_method_check CHECK (sample_method IN ('none', 'random', 'systematic', 'value')),
    sample_seed         bigint,
    sample_params       jsonb NOT NULL DEFAULT '{}'::jsonb CONSTRAINT audit_working_papers_params_object CHECK (jsonb_typeof(sample_params) = 'object'),
    sample_ids          jsonb NOT NULL DEFAULT '[]'::jsonb CONSTRAINT audit_working_papers_sample_array CHECK (jsonb_typeof(sample_ids) = 'array'),
    conclusion          text,           -- the reviewer's own words; never written by the AI
    created_by          text NOT NULL CONSTRAINT audit_working_papers_created_by_not_blank CHECK (btrim(created_by) <> ''),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    signed_off_by       text,
    signed_off_at       timestamptz,
    CONSTRAINT audit_working_papers_id_client_key UNIQUE (id, client_id),
    CONSTRAINT audit_working_papers_run_check_key UNIQUE (run_id, check_id),
    CONSTRAINT audit_working_papers_amount_two_decimals CHECK (population_amount IS NULL OR population_amount = round(population_amount, 2)),
    -- a sample is reproducible: any method other than 'none' records its seed (the same seed + population gives the same sample)
    CONSTRAINT audit_working_papers_sample_reproducible CHECK (sample_method = 'none' OR sample_seed IS NOT NULL),
    CONSTRAINT audit_working_papers_signoff_complete CHECK (status <> 'signed_off'
        OR (signed_off_by IS NOT NULL AND btrim(signed_off_by) <> '' AND signed_off_at IS NOT NULL AND btrim(coalesce(conclusion, '')) <> '')),
    CONSTRAINT audit_working_papers_run_fk FOREIGN KEY (run_id, client_id) REFERENCES audit_runs (id, client_id),
    CONSTRAINT audit_working_papers_financial_year_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

CREATE TABLE audit_paper_items (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL,
    paper_id      uuid NOT NULL,
    finding_id    uuid NOT NULL,
    status        text NOT NULL DEFAULT 'open' CONSTRAINT audit_paper_items_status_check CHECK (status IN ('open', 'cleared', 'confirmed')),
    reviewer_note text,
    decided_by    text,
    decided_at    timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_paper_items_paper_finding_key UNIQUE (paper_id, finding_id),
    -- clearing or confirming an exception is a decision: who, when and why
    CONSTRAINT audit_paper_items_decision_complete CHECK (status = 'open'
        OR (decided_by IS NOT NULL AND btrim(decided_by) <> '' AND decided_at IS NOT NULL AND btrim(coalesce(reviewer_note, '')) <> '')),
    CONSTRAINT audit_paper_items_paper_fk FOREIGN KEY (paper_id, client_id) REFERENCES audit_working_papers (id, client_id),
    CONSTRAINT audit_paper_items_finding_fk FOREIGN KEY (finding_id, client_id) REFERENCES audit_findings (id, client_id)
);

CREATE TABLE audit_paper_notes (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id  uuid NOT NULL,
    paper_id   uuid NOT NULL,
    note       text NOT NULL CONSTRAINT audit_paper_notes_note_not_blank CHECK (btrim(note) <> ''),
    created_by text NOT NULL CONSTRAINT audit_paper_notes_created_by_not_blank CHECK (btrim(created_by) <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_paper_notes_paper_fk FOREIGN KEY (paper_id, client_id) REFERENCES audit_working_papers (id, client_id)
);
CREATE INDEX audit_paper_notes_paper_idx ON audit_paper_notes (paper_id);

-- AI summary of exceptions: plain language, a suggestion only, stored with the gateway call that produced it
CREATE TABLE audit_ai_summaries (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL,
    run_id        uuid NOT NULL,
    paper_id      uuid,
    llm_call_id   uuid NOT NULL,
    summary_text  text NOT NULL CONSTRAINT audit_ai_summaries_text_not_blank CHECK (btrim(summary_text) <> ''),
    is_suggestion boolean NOT NULL DEFAULT true CONSTRAINT audit_ai_summaries_suggestion_only CHECK (is_suggestion),
    created_by    text NOT NULL CONSTRAINT audit_ai_summaries_created_by_not_blank CHECK (btrim(created_by) <> ''),
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_ai_summaries_run_fk FOREIGN KEY (run_id, client_id) REFERENCES audit_runs (id, client_id),
    CONSTRAINT audit_ai_summaries_paper_fk FOREIGN KEY (paper_id, client_id) REFERENCES audit_working_papers (id, client_id),
    CONSTRAINT audit_ai_summaries_call_fk FOREIGN KEY (llm_call_id, client_id) REFERENCES llm_calls (id, client_id)
);
-- the gateway log must accept the new purpose (0018 allowed two)
ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_purpose_check;
ALTER TABLE llm_calls ADD CONSTRAINT llm_calls_purpose_check
    CHECK (purpose IN ('invoice_extraction', 'narration_suggestion', 'audit_summary'));

-- =====================================================================================================
-- Tax audit form data (Form 3CD / Form 26): a set per client + year + form, entries derived from a run or typed by hand
-- =====================================================================================================
CREATE TABLE audit_form_sets (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    form_key          text NOT NULL REFERENCES audit_form_defs (form_key),
    status            text NOT NULL DEFAULT 'draft' CONSTRAINT audit_form_sets_status_check CHECK (status IN ('draft', 'finalised')),
    created_by        text NOT NULL CONSTRAINT audit_form_sets_created_by_not_blank CHECK (btrim(created_by) <> ''),
    created_at        timestamptz NOT NULL DEFAULT now(),
    finalised_by      text,
    finalised_at      timestamptz,
    CONSTRAINT audit_form_sets_id_client_key UNIQUE (id, client_id),
    CONSTRAINT audit_form_sets_year_form_key UNIQUE (client_id, financial_year_id, form_key),
    CONSTRAINT audit_form_sets_final_complete CHECK (status <> 'finalised' OR (finalised_by IS NOT NULL AND finalised_at IS NOT NULL)),
    CONSTRAINT audit_form_sets_financial_year_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

CREATE TABLE audit_form_entries (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL,
    form_set_id  uuid NOT NULL,
    clause_no    text NOT NULL CONSTRAINT audit_form_entries_clause_not_blank CHECK (btrim(clause_no) <> ''),
    field_key    text NOT NULL CONSTRAINT audit_form_entries_field_not_blank CHECK (btrim(field_key) <> ''),
    value        jsonb NOT NULL,          -- amounts as strings; derived values come from the engine, manual ones from the accountant
    origin       text NOT NULL CONSTRAINT audit_form_entries_origin_check CHECK (origin IN ('derived', 'manual')),
    run_id       uuid,
    entered_by   text NOT NULL CONSTRAINT audit_form_entries_entered_by_not_blank CHECK (btrim(entered_by) <> ''),
    entered_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_form_entries_key UNIQUE (form_set_id, clause_no, field_key),
    CONSTRAINT audit_form_entries_derived_has_run CHECK (origin = 'manual' OR run_id IS NOT NULL),
    CONSTRAINT audit_form_entries_set_fk FOREIGN KEY (form_set_id, client_id) REFERENCES audit_form_sets (id, client_id),
    CONSTRAINT audit_form_entries_run_fk FOREIGN KEY (run_id, client_id) REFERENCES audit_runs (id, client_id)
);

-- =====================================================================================================
-- Guards
-- =====================================================================================================
-- runs, findings, AI summaries and paper notes: insert only (notes also only while the paper is not signed off)
CREATE FUNCTION audit_insert_only_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION '% is insert only: audit evidence is never changed or deleted', TG_TABLE_NAME;
END $$;
CREATE TRIGGER audit_runs_guard BEFORE UPDATE OR DELETE ON audit_runs FOR EACH ROW EXECUTE FUNCTION audit_insert_only_guard();
CREATE TRIGGER audit_findings_guard BEFORE UPDATE OR DELETE ON audit_findings FOR EACH ROW EXECUTE FUNCTION audit_insert_only_guard();
CREATE TRIGGER audit_ai_summaries_guard BEFORE UPDATE OR DELETE ON audit_ai_summaries FOR EACH ROW EXECUTE FUNCTION audit_insert_only_guard();
CREATE TRIGGER audit_paper_notes_update_guard BEFORE UPDATE OR DELETE ON audit_paper_notes FOR EACH ROW EXECUTE FUNCTION audit_insert_only_guard();

-- a finding belongs to the run of the paper and to the paper's check; no exception can be added to a signed-off paper
CREATE FUNCTION audit_paper_item_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    p audit_working_papers%ROWTYPE;
    f_run uuid;
    f_check text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a working paper item cannot be deleted';
    END IF;
    SELECT * INTO p FROM audit_working_papers WHERE id = NEW.paper_id;
    IF p.status = 'signed_off' THEN
        RAISE EXCEPTION 'this working paper is signed off: its items cannot be added or changed';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT run_id, check_id INTO f_run, f_check FROM audit_findings WHERE id = NEW.finding_id;
        IF f_run IS DISTINCT FROM p.run_id OR f_check IS DISTINCT FROM p.check_id THEN
            RAISE EXCEPTION 'the finding does not belong to the run and check of this working paper';
        END IF;
    ELSIF NEW.paper_id <> OLD.paper_id OR NEW.finding_id <> OLD.finding_id OR NEW.client_id <> OLD.client_id THEN
        RAISE EXCEPTION 'the identity of a working paper item cannot be changed';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER audit_paper_items_guard BEFORE INSERT OR UPDATE OR DELETE ON audit_paper_items
    FOR EACH ROW EXECUTE FUNCTION audit_paper_item_guard();

CREATE FUNCTION audit_paper_note_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM audit_working_papers WHERE id = NEW.paper_id AND status = 'signed_off') THEN
        RAISE EXCEPTION 'this working paper is signed off: notes cannot be added';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER audit_paper_notes_insert_guard BEFORE INSERT ON audit_paper_notes FOR EACH ROW EXECUTE FUNCTION audit_paper_note_guard();

-- working papers: never deleted; identity never changes; signed off is terminal and needs every exception decided
CREATE FUNCTION audit_working_papers_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a working paper cannot be deleted';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'open' THEN
            RAISE EXCEPTION 'a working paper is created open';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'signed_off' THEN
        RAISE EXCEPTION 'this working paper is signed off and cannot be changed';
    END IF;
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.run_id <> OLD.run_id OR NEW.check_id <> OLD.check_id
       OR NEW.financial_year_id <> OLD.financial_year_id OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'the identity of a working paper cannot be changed';
    END IF;
    IF NEW.status <> OLD.status AND NOT ((OLD.status = 'open' AND NEW.status = 'in_review')
                                         OR (OLD.status = 'in_review' AND NEW.status IN ('open', 'signed_off'))) THEN
        RAISE EXCEPTION 'a working paper cannot move from % to %', OLD.status, NEW.status;
    END IF;
    IF NEW.status = 'signed_off' AND EXISTS (SELECT 1 FROM audit_paper_items WHERE paper_id = OLD.id AND status = 'open') THEN
        RAISE EXCEPTION 'a working paper with open exceptions cannot be signed off';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER audit_working_papers_guard BEFORE INSERT OR UPDATE OR DELETE ON audit_working_papers
    FOR EACH ROW EXECUTE FUNCTION audit_working_papers_guard();

-- form sets: never deleted, identity fixed, finalised is terminal; entries change only while the set is a draft
CREATE FUNCTION audit_form_sets_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a form set cannot be deleted';
    END IF;
    IF OLD.status = 'finalised' THEN
        RAISE EXCEPTION 'this form set is finalised and cannot be changed';
    END IF;
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.financial_year_id <> OLD.financial_year_id OR NEW.form_key <> OLD.form_key THEN
        RAISE EXCEPTION 'the identity of a form set cannot be changed';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER audit_form_sets_guard BEFORE UPDATE OR DELETE ON audit_form_sets FOR EACH ROW EXECUTE FUNCTION audit_form_sets_guard();

CREATE FUNCTION audit_form_entries_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    v_set uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_set := OLD.form_set_id;
    ELSE
        v_set := NEW.form_set_id;
    END IF;
    IF EXISTS (SELECT 1 FROM audit_form_sets WHERE id = v_set AND status = 'finalised') THEN
        RAISE EXCEPTION 'this form set is finalised: its entries cannot be added, changed or removed';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER audit_form_entries_guard BEFORE INSERT OR UPDATE OR DELETE ON audit_form_entries
    FOR EACH ROW EXECUTE FUNCTION audit_form_entries_guard();

-- related-party flags are history: deactivate, never delete
CREATE FUNCTION audit_related_parties_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a related-party flag cannot be deleted (set it inactive)';
    END IF;
    IF NEW.ledger_id <> OLD.ledger_id OR NEW.client_id <> OLD.client_id THEN
        RAISE EXCEPTION 'the ledger of a related-party flag cannot be changed';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER audit_related_parties_guard BEFORE UPDATE OR DELETE ON audit_related_parties
    FOR EACH ROW EXECUTE FUNCTION audit_related_parties_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE audit_rule_limits     ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_checks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_form_defs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_form_clauses    ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_holidays        ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_related_parties ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_runs            ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_findings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_working_papers  ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_paper_items     ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_paper_notes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_ai_summaries    ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_form_sets       ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_form_entries    ENABLE ROW LEVEL SECURITY;

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
