-- 0005: party master and bill-wise allocation (Phase 2, steps 2.1-2.3).
-- Schema-agnostic (see 0003). Money: numeric(18,4) + CHECK (x = round(x, 2)) (see 0004).
-- RLS enabled with NO policies on every table; API roles hold nothing (default privileges closed in 0004).

-- =====================================================================================================
-- parties: extra master data of a debtor / creditor ledger (one row per party ledger)
-- =====================================================================================================
CREATE TABLE parties (
    ledger_id   uuid PRIMARY KEY,
    client_id   uuid NOT NULL,
    gstin       text CONSTRAINT parties_gstin_format
                CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
    pan         text CONSTRAINT parties_pan_format CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
    state_code  text CONSTRAINT parties_state_code_format CHECK (state_code ~ '^[0-9]{2}$'),
    credit_days integer NOT NULL DEFAULT 0 CONSTRAINT parties_credit_days_nonneg CHECK (credit_days >= 0),
    msme_category text NOT NULL DEFAULT 'none' CONSTRAINT parties_msme_category_check
                CHECK (msme_category IN ('none', 'micro', 'small', 'medium')),
    udyam_no    text CONSTRAINT parties_udyam_format CHECK (udyam_no ~ '^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$'),
    msme_written_agreement boolean NOT NULL DEFAULT false,  -- a written agreement on the credit period exists (MSMED Act s.15)
    bill_wise   boolean NOT NULL DEFAULT true,               -- party lines must be allocated to bills (rule B-01)
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT parties_ledger_client_key UNIQUE (ledger_id, client_id),
    CONSTRAINT parties_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT parties_msme_needs_udyam CHECK (msme_category = 'none' OR udyam_no IS NOT NULL),
    CONSTRAINT parties_pan_inside_gstin CHECK (gstin IS NULL OR pan IS NULL OR substr(gstin, 3, 10) = pan),
    CONSTRAINT parties_state_matches_gstin CHECK (gstin IS NULL OR state_code IS NULL OR substr(gstin, 1, 2) = state_code)
);
CREATE INDEX parties_client_idx ON parties (client_id);

-- a party ledger must sit under Sundry Debtors or Sundry Creditors (directly or through custom sub-groups)
CREATE FUNCTION parties_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.ledger_id <> OLD.ledger_id OR NEW.client_id <> OLD.client_id) THEN
        RAISE EXCEPTION 'ledger_id and client_id of a party cannot be changed';
    END IF;
    IF NOT EXISTS (
        WITH RECURSIVE chain AS (
            SELECT g.id, g.code, g.parent_id FROM ledgers l JOIN account_groups g ON g.id = l.group_id
             WHERE l.id = NEW.ledger_id
            UNION ALL
            SELECT p.id, p.code, p.parent_id FROM account_groups p JOIN chain c ON c.parent_id = p.id
        )
        SELECT 1 FROM chain WHERE code IN ('sundry_debtors', 'sundry_creditors')
    ) THEN
        RAISE EXCEPTION 'a party must be a ledger under Sundry Debtors or Sundry Creditors';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER parties_guard
    BEFORE INSERT OR UPDATE ON parties
    FOR EACH ROW EXECUTE FUNCTION parties_guard();

-- =====================================================================================================
-- opening_bills: the open bills a party ledger starts a financial year with
-- =====================================================================================================
CREATE TABLE opening_bills (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    party_ledger_id   uuid NOT NULL,
    bill_ref          text NOT NULL CONSTRAINT opening_bills_ref_not_blank CHECK (btrim(bill_ref) <> ''),
    bill_date         date NOT NULL,
    due_date          date NOT NULL,
    debit             numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT opening_bills_debit_nonneg CHECK (debit >= 0),
    credit            numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT opening_bills_credit_nonneg CHECK (credit >= 0),
    CONSTRAINT opening_bills_debit_two_decimals CHECK (debit = round(debit, 2)),
    CONSTRAINT opening_bills_credit_two_decimals CHECK (credit = round(credit, 2)),
    CONSTRAINT opening_bills_exactly_one_side CHECK ((debit > 0) <> (credit > 0)),
    CONSTRAINT opening_bills_due_not_before_bill CHECK (due_date >= bill_date),
    CONSTRAINT opening_bills_party_fk FOREIGN KEY (party_ledger_id, client_id)
        REFERENCES parties (ledger_id, client_id),
    CONSTRAINT opening_bills_financial_year_fk FOREIGN KEY (financial_year_id, client_id)
        REFERENCES financial_years (id, client_id)
);
CREATE UNIQUE INDEX opening_bills_ref_key ON opening_bills (client_id, party_ledger_id, lower(btrim(bill_ref)));
CREATE INDEX opening_bills_year_idx ON opening_bills (financial_year_id, party_ledger_id);

-- =====================================================================================================
-- bill_allocations: how each party line of a voucher settles or creates bills (Tally semantics)
--   new_ref      creates a bill on the party's natural side (debtor Dr / creditor Cr); needs due_date
--   against_ref  settles (part of) an existing bill, or - in a reversal voucher - undoes an earlier allocation
--   advance      creates a bill on the opposite side (receipt from a debtor / payment to a creditor in advance)
--   on_account   unallocated amount, no bill reference
-- Written only while the voucher is a draft; immutable afterwards (like voucher_lines).
-- =====================================================================================================
CREATE TABLE bill_allocations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL,
    voucher_id      uuid NOT NULL,
    line_no         integer NOT NULL,
    party_ledger_id uuid NOT NULL,
    kind            text NOT NULL CONSTRAINT bill_allocations_kind_check
                    CHECK (kind IN ('new_ref', 'against_ref', 'advance', 'on_account')),
    bill_ref        text,
    due_date        date,
    debit           numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT bill_allocations_debit_nonneg CHECK (debit >= 0),
    credit          numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT bill_allocations_credit_nonneg CHECK (credit >= 0),
    CONSTRAINT bill_allocations_debit_two_decimals CHECK (debit = round(debit, 2)),
    CONSTRAINT bill_allocations_credit_two_decimals CHECK (credit = round(credit, 2)),
    CONSTRAINT bill_allocations_exactly_one_side CHECK ((debit > 0) <> (credit > 0)),
    CONSTRAINT bill_allocations_ref_rule CHECK (
        (kind = 'on_account' AND bill_ref IS NULL)
        OR (kind <> 'on_account' AND bill_ref IS NOT NULL AND btrim(bill_ref) <> '')),
    CONSTRAINT bill_allocations_due_rule CHECK (
        (kind = 'new_ref' AND due_date IS NOT NULL) OR (kind <> 'new_ref' AND due_date IS NULL)),
    CONSTRAINT bill_allocations_line_fk FOREIGN KEY (voucher_id, line_no)
        REFERENCES voucher_lines (voucher_id, line_no) ON DELETE CASCADE,
    CONSTRAINT bill_allocations_voucher_fk FOREIGN KEY (voucher_id, client_id)
        REFERENCES vouchers (id, client_id),
    CONSTRAINT bill_allocations_party_fk FOREIGN KEY (party_ledger_id, client_id)
        REFERENCES parties (ledger_id, client_id)
);
-- a bill reference is created once per party (new_ref or advance); reversals use against_ref
CREATE UNIQUE INDEX bill_allocations_new_ref_key
    ON bill_allocations (client_id, party_ledger_id, lower(btrim(bill_ref))) WHERE kind IN ('new_ref', 'advance');
CREATE INDEX bill_allocations_party_ref_idx ON bill_allocations (client_id, party_ledger_id, lower(btrim(bill_ref)));
CREATE INDEX bill_allocations_voucher_idx ON bill_allocations (voucher_id, line_no);

CREATE FUNCTION bill_allocations_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    s text;
    ln voucher_lines%ROWTYPE;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO s FROM vouchers WHERE id = NEW.voucher_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION 'bill allocations can only be changed while the voucher is draft (status is %)', s;
        END IF;
        SELECT * INTO ln FROM voucher_lines WHERE voucher_id = NEW.voucher_id AND line_no = NEW.line_no;
        IF FOUND THEN
            IF ln.ledger_id <> NEW.party_ledger_id THEN
                RAISE EXCEPTION 'allocation party ledger must be the ledger of voucher line %', NEW.line_no;
            END IF;
            IF (ln.debit > 0) <> (NEW.debit > 0) THEN
                RAISE EXCEPTION 'allocation side must match the side (Dr/Cr) of voucher line %', NEW.line_no;
            END IF;
        END IF;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO s FROM vouchers WHERE id = OLD.voucher_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION 'bill allocations can only be changed while the voucher is draft (status is %)', s;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER bill_allocations_guard
    BEFORE INSERT OR UPDATE OR DELETE ON bill_allocations
    FOR EACH ROW EXECUTE FUNCTION bill_allocations_guard();

-- Posting check (rule B-01 as a second line of defence): every line of a bill-wise party must be allocated in full.
CREATE FUNCTION vouchers_allocation_check() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT vl.line_no, vl.debit + vl.credit AS line_amount,
               COALESCE((SELECT sum(a.debit + a.credit) FROM bill_allocations a
                          WHERE a.voucher_id = vl.voucher_id AND a.line_no = vl.line_no), 0) AS allocated
          FROM voucher_lines vl
          JOIN parties p ON p.ledger_id = vl.ledger_id AND p.bill_wise
         WHERE vl.voucher_id = NEW.id
    LOOP
        IF r.line_amount <> r.allocated THEN
            RAISE EXCEPTION 'posting: line % of voucher % is allocated % of %', r.line_no, NEW.id, r.allocated, r.line_amount
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER vouchers_allocation_check
    AFTER INSERT OR UPDATE ON vouchers
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.status = 'posted')
    EXECUTE FUNCTION vouchers_allocation_check();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE parties           ENABLE ROW LEVEL SECURITY;
ALTER TABLE opening_bills     ENABLE ROW LEVEL SECURITY;
ALTER TABLE bill_allocations  ENABLE ROW LEVEL SECURITY;

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
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM %I', s, r);
        END IF;
    END LOOP;
END $$;
