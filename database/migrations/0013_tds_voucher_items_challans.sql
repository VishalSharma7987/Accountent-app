-- 0013: TDS on vouchers (register source), challans and challan allocations (Phase 4, step 4.0). Schema-agnostic (see 0003).
-- Money: numeric(18,4) + round check (0004). RLS on, no policies.
-- A voucher that deducts (or collects) tax has, besides its ordinary voucher_lines (the tax line is written by the engine from the
-- tds_ledger_roles map, never typed): one tds_voucher_items row per deduction, holding the engine's whole working. Rows are written only
-- while the voucher is a draft (the Phase 3 guard function gst_voucher_child_guard works for any table with a voucher_id) and are immutable
-- afterwards. The TDS register is this table joined to POSTED vouchers; a reversed voucher drops out of the register and the threshold totals.
-- What changes AFTER posting (deposit, matching) lives in the challan tables, never in the voucher.

-- =====================================================================================================
-- tds_voucher_items
-- =====================================================================================================
CREATE TABLE tds_voucher_items (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    voucher_id          uuid NOT NULL,
    item_no             integer NOT NULL CONSTRAINT tds_voucher_items_no_positive CHECK (item_no > 0),
    kind                text NOT NULL CONSTRAINT tds_voucher_items_kind_check CHECK (kind IN ('tds', 'tcs')),
    deductee_ledger_id  uuid NOT NULL,                  -- the party: deductee (TDS) or collectee (TCS)
    nature_key          text NOT NULL REFERENCES tds_natures (nature_key),
    act                 text NOT NULL CONSTRAINT tds_voucher_items_act_check CHECK (act IN ('it_act_1961', 'it_act_2025')),
    section_ref         text NOT NULL CONSTRAINT tds_voucher_items_section_not_blank CHECK (btrim(section_ref) <> ''),   -- snapshot of the section applied
    table_ref           text,
    rate_rule_id        uuid REFERENCES tds_rates (id),  -- the rule row applied (audit trail)
    financial_year_id   uuid NOT NULL,
    event_date          date NOT NULL,                  -- the earlier of payment date and credit date: decides the Act, the rate and the due dates
    credit_date         date,
    payment_date        date,
    payment_amount      numeric(18, 4) NOT NULL CONSTRAINT tds_voucher_items_payment_nonneg CHECK (payment_amount >= 0),   -- this voucher's amount on which the nature applies
    cumulative_before   numeric(18, 4) NOT NULL CONSTRAINT tds_voucher_items_cum_before_nonneg CHECK (cumulative_before >= 0),   -- same deductee + nature + FY, posted vouchers before this one
    cumulative_after    numeric(18, 4) NOT NULL,
    threshold_crossed   boolean NOT NULL DEFAULT false,  -- this item is the one that crossed a threshold (catch-up on the earlier amounts when mode is whole_amount)
    taxable_base        numeric(18, 4) NOT NULL CONSTRAINT tds_voucher_items_base_nonneg CHECK (taxable_base >= 0),   -- amount the rate is applied to (may exceed payment_amount on a catch-up)
    rate_applied        numeric(7, 4) NOT NULL CONSTRAINT tds_voucher_items_rate_range CHECK (rate_applied >= 0 AND rate_applied <= 100),
    rate_reason         text NOT NULL CONSTRAINT tds_voucher_items_reason_check CHECK (rate_reason IN
                        ('normal', 'no_pan', 'lower_certificate', 'nil_certificate', 'below_threshold', 'manual_salary')),
    lower_cert_id       uuid,
    tax_already_on_base numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_voucher_items_already_nonneg CHECK (tax_already_on_base >= 0),   -- tax deducted earlier on the part of the base that is re-based
    tds_amount          numeric(18, 4) NOT NULL CONSTRAINT tds_voucher_items_amount_nonneg CHECK (tds_amount >= 0),   -- tax of THIS voucher (the credit line)
    tds_line_no         integer,                        -- the voucher line (Cr TDS payable / TCS payable for the party's deduction)
    engine_version      text NOT NULL,
    note                text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_voucher_items_key UNIQUE (voucher_id, item_no),
    CONSTRAINT tds_voucher_items_id_client_key UNIQUE (id, client_id),
    CONSTRAINT tds_voucher_items_payment_two_decimals CHECK (payment_amount = round(payment_amount, 2)),
    CONSTRAINT tds_voucher_items_cum_before_two_decimals CHECK (cumulative_before = round(cumulative_before, 2)),
    CONSTRAINT tds_voucher_items_cum_after_two_decimals CHECK (cumulative_after = round(cumulative_after, 2)),
    CONSTRAINT tds_voucher_items_base_two_decimals CHECK (taxable_base = round(taxable_base, 2)),
    CONSTRAINT tds_voucher_items_already_two_decimals CHECK (tax_already_on_base = round(tax_already_on_base, 2)),
    CONSTRAINT tds_voucher_items_amount_two_decimals CHECK (tds_amount = round(tds_amount, 2)),
    CONSTRAINT tds_voucher_items_dates CHECK (credit_date IS NOT NULL OR payment_date IS NOT NULL),
    CONSTRAINT tds_voucher_items_event_is_earlier CHECK (event_date = least(coalesce(credit_date, payment_date), coalesce(payment_date, credit_date))),
    CONSTRAINT tds_voucher_items_cum_order CHECK (cumulative_after >= cumulative_before),
    CONSTRAINT tds_voucher_items_cert_reason CHECK ((rate_reason IN ('lower_certificate', 'nil_certificate')) = (lower_cert_id IS NOT NULL)),
    CONSTRAINT tds_voucher_items_zero_has_no_line CHECK ((tds_amount > 0) = (tds_line_no IS NOT NULL)),
    CONSTRAINT tds_voucher_items_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id) ON DELETE CASCADE,
    CONSTRAINT tds_voucher_items_line_fk FOREIGN KEY (voucher_id, tds_line_no) REFERENCES voucher_lines (voucher_id, line_no) ON DELETE CASCADE,
    CONSTRAINT tds_voucher_items_deductee_fk FOREIGN KEY (deductee_ledger_id, client_id) REFERENCES tds_deductees (ledger_id, client_id),
    CONSTRAINT tds_voucher_items_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT tds_voucher_items_cert_fk FOREIGN KEY (lower_cert_id, client_id) REFERENCES tds_lower_deduction_certs (id, client_id)
);
CREATE INDEX tds_voucher_items_deductee_idx ON tds_voucher_items (client_id, deductee_ledger_id, financial_year_id, nature_key);
CREATE INDEX tds_voucher_items_event_idx ON tds_voucher_items (client_id, event_date);

CREATE TRIGGER tds_voucher_items_guard
    BEFORE INSERT OR UPDATE OR DELETE ON tds_voucher_items
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();

-- =====================================================================================================
-- Challans (deposit of tax) and their allocation to deduction items
-- =====================================================================================================
CREATE TABLE tds_challans (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL REFERENCES clients (id),
    kind                text NOT NULL CONSTRAINT tds_challans_kind_check CHECK (kind IN ('tds', 'tcs')),
    financial_year_id   uuid NOT NULL,
    quarter             integer NOT NULL CONSTRAINT tds_challans_quarter_check CHECK (quarter BETWEEN 1 AND 4),   -- the statement quarter the challan belongs to
    bsr_code            text NOT NULL CONSTRAINT tds_challans_bsr_format CHECK (bsr_code ~ '^[0-9]{7}$'),
    deposit_date        date NOT NULL,
    challan_serial_no   text NOT NULL CONSTRAINT tds_challans_serial_format CHECK (challan_serial_no ~ '^[0-9]{1,5}$'),
    tax_amount          numeric(18, 4) NOT NULL CONSTRAINT tds_challans_tax_nonneg CHECK (tax_amount >= 0),
    interest_amount     numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_challans_interest_nonneg CHECK (interest_amount >= 0),
    fee_amount          numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_challans_fee_nonneg CHECK (fee_amount >= 0),     -- late filing fee etc.
    other_amount        numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_challans_other_nonneg CHECK (other_amount >= 0),
    total_amount        numeric(18, 4) NOT NULL,
    payment_voucher_id  uuid,                           -- the Payment voucher (bank) that paid it, when entered in the books
    status              text NOT NULL DEFAULT 'entered' CONSTRAINT tds_challans_status_check CHECK (status IN ('entered', 'locked')),   -- locked = used in a final return working
    note                text,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_challans_id_client_key UNIQUE (id, client_id),
    CONSTRAINT tds_challans_cin_key UNIQUE (client_id, bsr_code, deposit_date, challan_serial_no),
    CONSTRAINT tds_challans_tax_two_decimals CHECK (tax_amount = round(tax_amount, 2)),
    CONSTRAINT tds_challans_interest_two_decimals CHECK (interest_amount = round(interest_amount, 2)),
    CONSTRAINT tds_challans_fee_two_decimals CHECK (fee_amount = round(fee_amount, 2)),
    CONSTRAINT tds_challans_other_two_decimals CHECK (other_amount = round(other_amount, 2)),
    CONSTRAINT tds_challans_total_two_decimals CHECK (total_amount = round(total_amount, 2)),
    CONSTRAINT tds_challans_total_adds_up CHECK (total_amount = tax_amount + interest_amount + fee_amount + other_amount),
    CONSTRAINT tds_challans_total_pos CHECK (total_amount > 0),
    CONSTRAINT tds_challans_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT tds_challans_voucher_fk FOREIGN KEY (payment_voucher_id, client_id) REFERENCES vouchers (id, client_id)
);
CREATE INDEX tds_challans_client_idx ON tds_challans (client_id, financial_year_id, quarter);

CREATE TABLE tds_challan_allocations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    challan_id          uuid NOT NULL,
    item_id             uuid NOT NULL,                  -- the tds_voucher_items row the money is applied to
    amount              numeric(18, 4) NOT NULL CONSTRAINT tds_challan_alloc_amount_pos CHECK (amount > 0),
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_challan_alloc_two_decimals CHECK (amount = round(amount, 2)),
    CONSTRAINT tds_challan_alloc_key UNIQUE (challan_id, item_id),
    CONSTRAINT tds_challan_alloc_challan_fk FOREIGN KEY (challan_id, client_id) REFERENCES tds_challans (id, client_id),
    CONSTRAINT tds_challan_alloc_item_fk FOREIGN KEY (item_id, client_id) REFERENCES tds_voucher_items (id, client_id)
);
CREATE INDEX tds_challan_alloc_item_idx ON tds_challan_allocations (item_id);
-- (sum of allocations of a challan <= its tax_amount, and of an item <= its tds_amount, are checked by the service in the same transaction: rules T-23, T-24)

-- a locked challan cannot be changed or deleted; its allocations neither
CREATE FUNCTION tds_challans_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'locked' THEN
            RAISE EXCEPTION 'a locked challan cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'locked' THEN
        RAISE EXCEPTION 'a locked challan cannot be changed';
    END IF;
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.kind <> OLD.kind THEN
        RAISE EXCEPTION 'identity of a challan cannot be changed';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER tds_challans_guard
    BEFORE UPDATE OR DELETE ON tds_challans
    FOR EACH ROW EXECUTE FUNCTION tds_challans_guard();

CREATE FUNCTION tds_challan_alloc_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    s text;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO s FROM tds_challans WHERE id = NEW.challan_id FOR SHARE;
        IF FOUND AND s = 'locked' THEN
            RAISE EXCEPTION 'allocations of a locked challan cannot be changed';
        END IF;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO s FROM tds_challans WHERE id = OLD.challan_id FOR SHARE;
        IF FOUND AND s = 'locked' THEN
            RAISE EXCEPTION 'allocations of a locked challan cannot be changed';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER tds_challan_alloc_guard
    BEFORE INSERT OR UPDATE OR DELETE ON tds_challan_allocations
    FOR EACH ROW EXECUTE FUNCTION tds_challan_alloc_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE tds_voucher_items        ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_challans             ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_challan_allocations  ENABLE ROW LEVEL SECURITY;

-- =====================================================================================================
-- Close function privileges again (see 0004): functions created by 0013 must not be executable
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
