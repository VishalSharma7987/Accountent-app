-- 0003: accounting core (Phase 1, step 1.1).
-- Schema-agnostic: the connection's search_path decides the schema. Every function below is created with
-- SET search_path FROM CURRENT, which pins the schema it was installed into (and keeps the advisors quiet).
--
-- Defence in depth: the application enforces these rules too (backend/app/engine, services).
-- Row-level security is enabled on every table with NO policies: deny all to the Supabase API roles.
-- Only the backend's direct Postgres connection reads and writes these tables.

-- =====================================================================================================
-- clients
-- =====================================================================================================
CREATE TABLE clients (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name          text NOT NULL CONSTRAINT clients_name_not_blank CHECK (btrim(name) <> ''),
    legal_name    text,
    entity_type   text NOT NULL CONSTRAINT clients_entity_type_check
                  CHECK (entity_type IN ('proprietorship', 'partnership', 'llp', 'company')),
    business_type text NOT NULL CONSTRAINT clients_business_type_check
                  CHECK (business_type IN ('trading', 'service', 'manufacturing')),
    pan           text,
    state_code    text,
    gst_type      text NOT NULL CONSTRAINT clients_gst_type_check
                  CHECK (gst_type IN ('regular', 'composition', 'unregistered')),
    books_begin_date date,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================================================
-- financial_years: 1 April - 31 March
-- =====================================================================================================
CREATE TABLE financial_years (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id  uuid NOT NULL REFERENCES clients (id),
    start_date date NOT NULL,
    end_date   date NOT NULL,
    CONSTRAINT financial_years_client_start_key UNIQUE (client_id, start_date),
    CONSTRAINT financial_years_id_client_key UNIQUE (id, client_id),
    CONSTRAINT financial_years_start_is_1_april
        CHECK (extract(month FROM start_date) = 4 AND extract(day FROM start_date) = 1),
    CONSTRAINT financial_years_end_is_start_plus_1y_minus_1d
        CHECK (end_date = (start_date + interval '1 year' - interval '1 day')::date)
);

-- =====================================================================================================
-- periods: lockable date ranges inside a financial year
-- =====================================================================================================
CREATE TABLE periods (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    period_start      date NOT NULL,
    period_end        date NOT NULL,
    status            text NOT NULL DEFAULT 'open' CONSTRAINT periods_status_check
                      CHECK (status IN ('open', 'locked')),
    locked_at         timestamptz,
    locked_by         text,
    CONSTRAINT periods_financial_year_fk FOREIGN KEY (financial_year_id, client_id)
        REFERENCES financial_years (id, client_id),
    CONSTRAINT periods_year_start_key UNIQUE (financial_year_id, period_start),
    CONSTRAINT periods_end_not_before_start CHECK (period_end >= period_start)
);

CREATE FUNCTION periods_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    fy financial_years%ROWTYPE;
BEGIN
    -- serialise concurrent inserts for the same year so two overlapping periods cannot both pass
    PERFORM pg_advisory_xact_lock(hashtext(NEW.financial_year_id::text));

    SELECT * INTO fy FROM financial_years WHERE id = NEW.financial_year_id;
    IF FOUND AND (NEW.period_start < fy.start_date OR NEW.period_end > fy.end_date) THEN
        RAISE EXCEPTION 'period % to % is outside its financial year % to %',
            NEW.period_start, NEW.period_end, fy.start_date, fy.end_date
            USING ERRCODE = 'check_violation';
    END IF;

    IF EXISTS (
        SELECT 1 FROM periods p
        WHERE p.financial_year_id = NEW.financial_year_id
          AND p.id <> NEW.id
          AND p.period_start <= NEW.period_end
          AND p.period_end >= NEW.period_start
    ) THEN
        RAISE EXCEPTION 'period % to % overlaps another period of the same financial year',
            NEW.period_start, NEW.period_end
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER periods_guard
    BEFORE INSERT OR UPDATE OF financial_year_id, period_start, period_end ON periods
    FOR EACH ROW EXECUTE FUNCTION periods_guard();

-- =====================================================================================================
-- account_groups: client_id NULL = system group (seeded); otherwise a client's custom sub-group
-- =====================================================================================================
CREATE TABLE account_groups (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid REFERENCES clients (id),
    code      text NOT NULL CONSTRAINT account_groups_code_not_blank CHECK (btrim(code) <> ''),
    name      text NOT NULL CONSTRAINT account_groups_name_not_blank CHECK (btrim(name) <> ''),
    parent_id uuid REFERENCES account_groups (id),
    nature    text NOT NULL CONSTRAINT account_groups_nature_check
              CHECK (nature IN ('asset', 'liability', 'income', 'expense')),
    report    text NOT NULL CONSTRAINT account_groups_report_check
              CHECK (report IN ('balance_sheet', 'trading', 'profit_loss')),
    is_system boolean NOT NULL DEFAULT false,
    CONSTRAINT account_groups_system_flag CHECK (is_system = (client_id IS NULL)),
    CONSTRAINT account_groups_custom_needs_parent CHECK (client_id IS NULL OR parent_id IS NOT NULL),
    CONSTRAINT account_groups_not_own_parent CHECK (parent_id IS DISTINCT FROM id)
);
-- unique per scope: system groups together, and each client's own groups
CREATE UNIQUE INDEX account_groups_system_code_key ON account_groups (code) WHERE client_id IS NULL;
CREATE UNIQUE INDEX account_groups_system_name_key ON account_groups (lower(name)) WHERE client_id IS NULL;
CREATE UNIQUE INDEX account_groups_client_code_key ON account_groups (client_id, code) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX account_groups_client_name_key ON account_groups (client_id, lower(name)) WHERE client_id IS NOT NULL;
CREATE INDEX account_groups_parent_idx ON account_groups (parent_id);

CREATE FUNCTION account_groups_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    parent account_groups%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.client_id IS NULL THEN
            RAISE EXCEPTION 'system groups cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.client_id IS NULL THEN
            RAISE EXCEPTION 'system groups cannot be edited';
        END IF;
        -- a custom group keeps its place in the tree for good, so nature/report always equal its parent's
        IF NEW.client_id IS DISTINCT FROM OLD.client_id OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
           OR NEW.nature <> OLD.nature OR NEW.report <> OLD.report OR NEW.is_system <> OLD.is_system THEN
            RAISE EXCEPTION 'only the name and code of a custom group can be changed';
        END IF;
    END IF;

    IF NEW.parent_id IS NOT NULL THEN
        SELECT * INTO parent FROM account_groups WHERE id = NEW.parent_id;
        IF NEW.client_id IS NULL AND parent.client_id IS NOT NULL THEN
            RAISE EXCEPTION 'a system group cannot have a client group as parent';
        END IF;
        IF NEW.client_id IS NOT NULL AND parent.client_id IS NOT NULL AND parent.client_id <> NEW.client_id THEN
            RAISE EXCEPTION 'a group parent must be a system group or a group of the same client';
        END IF;
        IF NEW.client_id IS NOT NULL AND (NEW.nature <> parent.nature OR NEW.report <> parent.report) THEN
            RAISE EXCEPTION 'a custom group must have the same nature and report as its parent group';
        END IF;
    END IF;

    IF NEW.client_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM account_groups s
        WHERE s.client_id IS NULL AND (lower(s.name) = lower(NEW.name) OR s.code = NEW.code)
    ) THEN
        RAISE EXCEPTION 'a custom group cannot reuse the name or code of a system group';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER account_groups_guard
    BEFORE INSERT OR UPDATE OR DELETE ON account_groups
    FOR EACH ROW EXECUTE FUNCTION account_groups_guard();

-- =====================================================================================================
-- ledgers
-- =====================================================================================================
CREATE TABLE ledgers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id  uuid NOT NULL REFERENCES clients (id),
    group_id   uuid NOT NULL REFERENCES account_groups (id),
    name       text NOT NULL CONSTRAINT ledgers_name_not_blank CHECK (btrim(name) <> ''),
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ledgers_id_client_key UNIQUE (id, client_id)
);
CREATE UNIQUE INDEX ledgers_client_name_key ON ledgers (client_id, lower(name));
CREATE INDEX ledgers_client_idx ON ledgers (client_id);
CREATE INDEX ledgers_group_idx ON ledgers (group_id);

CREATE FUNCTION ledgers_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    g_client uuid;
BEGIN
    SELECT client_id INTO g_client FROM account_groups WHERE id = NEW.group_id;
    IF FOUND AND g_client IS NOT NULL AND g_client <> NEW.client_id THEN
        RAISE EXCEPTION 'a ledger can only use a system group or a group of its own client';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER ledgers_guard
    BEFORE INSERT OR UPDATE OF group_id, client_id ON ledgers
    FOR EACH ROW EXECUTE FUNCTION ledgers_guard();

-- =====================================================================================================
-- opening_balances
-- =====================================================================================================
CREATE TABLE opening_balances (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    ledger_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    debit             numeric(18, 2) NOT NULL DEFAULT 0 CONSTRAINT opening_balances_debit_nonneg CHECK (debit >= 0),
    credit            numeric(18, 2) NOT NULL DEFAULT 0 CONSTRAINT opening_balances_credit_nonneg CHECK (credit >= 0),
    CONSTRAINT opening_balances_one_side CHECK (NOT (debit > 0 AND credit > 0)),
    CONSTRAINT opening_balances_ledger_year_key UNIQUE (ledger_id, financial_year_id),
    CONSTRAINT opening_balances_ledger_fk FOREIGN KEY (ledger_id, client_id)
        REFERENCES ledgers (id, client_id),
    CONSTRAINT opening_balances_financial_year_fk FOREIGN KEY (financial_year_id, client_id)
        REFERENCES financial_years (id, client_id)
);
CREATE INDEX opening_balances_year_idx ON opening_balances (financial_year_id);

-- =====================================================================================================
-- vouchers: draft -> approved -> posted -> reversed
-- =====================================================================================================
CREATE TABLE vouchers (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id                 uuid NOT NULL,
    financial_year_id         uuid NOT NULL,
    voucher_type              text NOT NULL CONSTRAINT vouchers_type_check CHECK (voucher_type IN
                              ('contra', 'payment', 'receipt', 'sales', 'purchase', 'credit_note', 'debit_note', 'journal')),
    voucher_number            text,
    voucher_date              date NOT NULL,
    narration                 text NOT NULL CONSTRAINT vouchers_narration_not_blank CHECK (btrim(narration) <> ''),
    reference_no              text,
    party_ledger_id           uuid,
    status                    text NOT NULL DEFAULT 'draft' CONSTRAINT vouchers_status_check
                              CHECK (status IN ('draft', 'approved', 'posted', 'reversed')),
    reverses_voucher_id       uuid,
    reversed_by_voucher_id    uuid,
    duplicate_override_reason text,
    created_by                text NOT NULL,
    created_at                timestamptz NOT NULL DEFAULT now(),
    approved_by               text,
    approved_at               timestamptz,
    posted_by                 text,
    posted_at                 timestamptz,
    CONSTRAINT vouchers_id_client_key UNIQUE (id, client_id),
    CONSTRAINT vouchers_number_key UNIQUE (client_id, financial_year_id, voucher_type, voucher_number),
    -- the voucher number exists exactly from posting onwards (drafts have an internal id only)
    CONSTRAINT vouchers_number_required_when_posted
        CHECK (status NOT IN ('posted', 'reversed') OR voucher_number IS NOT NULL),
    CONSTRAINT vouchers_no_number_before_posting
        CHECK (status IN ('posted', 'reversed') OR voucher_number IS NULL),
    CONSTRAINT vouchers_reversed_has_reversal CHECK ((status = 'reversed') = (reversed_by_voucher_id IS NOT NULL)),
    CONSTRAINT vouchers_not_own_reversal
        CHECK (reverses_voucher_id IS DISTINCT FROM id AND reversed_by_voucher_id IS DISTINCT FROM id),
    CONSTRAINT vouchers_financial_year_fk FOREIGN KEY (financial_year_id, client_id)
        REFERENCES financial_years (id, client_id),
    CONSTRAINT vouchers_party_ledger_fk FOREIGN KEY (party_ledger_id, client_id)
        REFERENCES ledgers (id, client_id),
    CONSTRAINT vouchers_reverses_fk FOREIGN KEY (reverses_voucher_id, client_id)
        REFERENCES vouchers (id, client_id),
    CONSTRAINT vouchers_reversed_by_fk FOREIGN KEY (reversed_by_voucher_id, client_id)
        REFERENCES vouchers (id, client_id)
);
-- a voucher can be reversed only once, and a reversal voucher reverses exactly one voucher
CREATE UNIQUE INDEX vouchers_reverses_once_key ON vouchers (reverses_voucher_id) WHERE reverses_voucher_id IS NOT NULL;
CREATE UNIQUE INDEX vouchers_reversed_by_once_key ON vouchers (reversed_by_voucher_id) WHERE reversed_by_voucher_id IS NOT NULL;
CREATE INDEX vouchers_client_date_idx ON vouchers (client_id, voucher_date);
CREATE INDEX vouchers_year_idx ON vouchers (financial_year_id);
CREATE INDEX vouchers_party_ledger_idx ON vouchers (party_ledger_id);

CREATE FUNCTION vouchers_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'a voucher must be created as draft (got %)', NEW.status;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'only a draft voucher can be deleted (status is %)', OLD.status;
        END IF;
        RETURN OLD;
    END IF;

    -- UPDATE
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id THEN
        RAISE EXCEPTION 'id and client_id of a voucher cannot be changed';
    END IF;

    IF OLD.status = 'reversed' THEN
        RAISE EXCEPTION 'a reversed voucher cannot be changed';

    ELSIF OLD.status = 'posted' THEN
        IF NEW.status <> 'reversed' THEN
            RAISE EXCEPTION 'a posted voucher can only change to reversed (not %)', NEW.status;
        END IF;
        IF (to_jsonb(NEW) - 'status' - 'reversed_by_voucher_id')
           <> (to_jsonb(OLD) - 'status' - 'reversed_by_voucher_id') THEN
            RAISE EXCEPTION 'a posted voucher can only change status and reversed_by_voucher_id';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM vouchers r
            WHERE r.id = NEW.reversed_by_voucher_id AND r.client_id = NEW.client_id
              AND r.reverses_voucher_id = NEW.id AND r.status = 'posted'
        ) THEN
            RAISE EXCEPTION 'a voucher can be marked reversed only by a posted reversal voucher that reverses it';
        END IF;

    ELSIF OLD.status = 'approved' THEN
        IF NEW.status = 'draft' THEN
            IF (to_jsonb(NEW) - 'status' - 'approved_by' - 'approved_at')
               <> (to_jsonb(OLD) - 'status' - 'approved_by' - 'approved_at') THEN
                RAISE EXCEPTION 'moving an approved voucher back to draft can only change status and approval fields';
            END IF;
        ELSIF NEW.status = 'posted' THEN
            IF (to_jsonb(NEW) - 'status' - 'voucher_number' - 'posted_by' - 'posted_at')
               <> (to_jsonb(OLD) - 'status' - 'voucher_number' - 'posted_by' - 'posted_at') THEN
                RAISE EXCEPTION 'posting can only change status, voucher_number, posted_by and posted_at';
            END IF;
        ELSE
            RAISE EXCEPTION 'an approved voucher can only move to draft or posted (not %)', NEW.status;
        END IF;

    ELSE -- draft
        IF NEW.status NOT IN ('draft', 'approved') THEN
            RAISE EXCEPTION 'a draft voucher can only move to approved (not %)', NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER vouchers_guard
    BEFORE INSERT OR UPDATE OR DELETE ON vouchers
    FOR EACH ROW EXECUTE FUNCTION vouchers_guard();

-- Posting checks, deferred to commit so lines can be written in the same transaction:
-- at least 2 lines, total debit = total credit, voucher date inside its financial year.
CREATE FUNCTION vouchers_posting_check() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    n_lines integer;
    total_dr numeric(18, 2);
    total_cr numeric(18, 2);
    fy financial_years%ROWTYPE;
BEGIN
    SELECT count(*), COALESCE(sum(debit), 0), COALESCE(sum(credit), 0)
      INTO n_lines, total_dr, total_cr
      FROM voucher_lines WHERE voucher_id = NEW.id;
    IF n_lines < 2 THEN
        RAISE EXCEPTION 'posting: voucher % has % line(s); at least 2 are required', NEW.id, n_lines
            USING ERRCODE = 'check_violation';
    END IF;
    IF total_dr <> total_cr THEN
        RAISE EXCEPTION 'posting: voucher % is not balanced (debit % vs credit %)', NEW.id, total_dr, total_cr
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT * INTO fy FROM financial_years WHERE id = NEW.financial_year_id;
    IF NEW.voucher_date < fy.start_date OR NEW.voucher_date > fy.end_date THEN
        RAISE EXCEPTION 'posting: voucher date % is outside its financial year % to %',
            NEW.voucher_date, fy.start_date, fy.end_date
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER vouchers_posting_check
    AFTER INSERT OR UPDATE ON vouchers
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.status = 'posted')
    EXECUTE FUNCTION vouchers_posting_check();

-- =====================================================================================================
-- voucher_lines: written only while the voucher is a draft
-- =====================================================================================================
CREATE TABLE voucher_lines (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id  uuid NOT NULL,
    voucher_id uuid NOT NULL,
    line_no    integer NOT NULL CONSTRAINT voucher_lines_line_no_positive CHECK (line_no > 0),
    ledger_id  uuid NOT NULL,
    debit      numeric(18, 2) NOT NULL DEFAULT 0 CONSTRAINT voucher_lines_debit_nonneg CHECK (debit >= 0),
    credit     numeric(18, 2) NOT NULL DEFAULT 0 CONSTRAINT voucher_lines_credit_nonneg CHECK (credit >= 0),
    CONSTRAINT voucher_lines_exactly_one_side CHECK ((debit > 0) <> (credit > 0)),
    CONSTRAINT voucher_lines_voucher_line_key UNIQUE (voucher_id, line_no),
    CONSTRAINT voucher_lines_voucher_fk FOREIGN KEY (voucher_id, client_id)
        REFERENCES vouchers (id, client_id),
    CONSTRAINT voucher_lines_ledger_fk FOREIGN KEY (ledger_id, client_id)
        REFERENCES ledgers (id, client_id)
);
CREATE INDEX voucher_lines_voucher_idx ON voucher_lines (voucher_id);
CREATE INDEX voucher_lines_ledger_idx ON voucher_lines (ledger_id);

CREATE FUNCTION voucher_lines_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    s text;
BEGIN
    -- FOR SHARE: a concurrent approve/post of the same voucher waits until this transaction ends
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO s FROM vouchers WHERE id = NEW.voucher_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION 'voucher lines can only be changed while the voucher is draft (status is %)', s;
        END IF;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO s FROM vouchers WHERE id = OLD.voucher_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION 'voucher lines can only be changed while the voucher is draft (status is %)', s;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER voucher_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON voucher_lines
    FOR EACH ROW EXECUTE FUNCTION voucher_lines_guard();

-- =====================================================================================================
-- voucher_number_sequences: gapless numbers, issued one at a time
-- =====================================================================================================
CREATE TABLE voucher_number_sequences (
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    voucher_type      text NOT NULL CONSTRAINT voucher_number_sequences_type_check CHECK (voucher_type IN
                      ('contra', 'payment', 'receipt', 'sales', 'purchase', 'credit_note', 'debit_note', 'journal')),
    last_number       integer NOT NULL DEFAULT 0 CONSTRAINT voucher_number_sequences_nonneg CHECK (last_number >= 0),
    PRIMARY KEY (client_id, financial_year_id, voucher_type),
    CONSTRAINT voucher_number_sequences_financial_year_fk FOREIGN KEY (financial_year_id, client_id)
        REFERENCES financial_years (id, client_id)
);

CREATE FUNCTION voucher_number_sequences_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'voucher number sequences cannot be deleted';
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.last_number NOT IN (0, 1) THEN
            RAISE EXCEPTION 'a new voucher number sequence must start at 0 or 1 (got %)', NEW.last_number;
        END IF;
    ELSE
        IF NEW.client_id <> OLD.client_id OR NEW.financial_year_id <> OLD.financial_year_id
           OR NEW.voucher_type <> OLD.voucher_type THEN
            RAISE EXCEPTION 'the key of a voucher number sequence cannot be changed';
        END IF;
        IF NEW.last_number <> OLD.last_number + 1 THEN
            RAISE EXCEPTION 'voucher numbers are issued one at a time: last_number must go from % to %, not %',
                OLD.last_number, OLD.last_number + 1, NEW.last_number;
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER voucher_number_sequences_guard
    BEFORE INSERT OR UPDATE OR DELETE ON voucher_number_sequences
    FOR EACH ROW EXECUTE FUNCTION voucher_number_sequences_guard();

-- =====================================================================================================
-- audit_log: append only
-- =====================================================================================================
CREATE TABLE audit_log (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id  uuid NOT NULL REFERENCES clients (id),
    actor      text NOT NULL CONSTRAINT audit_log_actor_not_blank CHECK (btrim(actor) <> ''),
    action     text NOT NULL,
    entity     text NOT NULL,
    entity_id  uuid NOT NULL,
    old_data   jsonb,
    new_data   jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_entity_idx ON audit_log (client_id, entity, entity_id, id);

CREATE FUNCTION audit_log_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (no UPDATE or DELETE)';
END $$;

CREATE TRIGGER audit_log_guard
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_guard();

-- =====================================================================================================
-- Row-level security: enabled everywhere, NO policies (deny all to the Supabase API roles)
-- =====================================================================================================
ALTER TABLE clients                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE financial_years         ENABLE ROW LEVEL SECURITY;
ALTER TABLE periods                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_groups          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledgers                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE opening_balances        ENABLE ROW LEVEL SECURITY;
ALTER TABLE vouchers                ENABLE ROW LEVEL SECURITY;
ALTER TABLE voucher_lines           ENABLE ROW LEVEL SECURITY;
ALTER TABLE voucher_number_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log               ENABLE ROW LEVEL SECURITY;
