-- 0010: invoice-mode vouchers (Phase 3, step 3.0). Schema-agnostic (see 0003). Money: numeric(18,4) + round check (0004).
-- A Sales / Purchase / Credit Note / Debit Note voucher in "invoice mode" has, besides its ordinary voucher_lines (written by the engine,
-- never typed): one voucher_gst header row, one or more voucher_item_lines (items, qty, rate, discount, taxable value, tax amounts),
-- and voucher_gst_line_roles saying which voucher_line is the party / taxable / tax / RCM / round-off line.
-- All three tables are written only while the voucher is a draft (same guard as voucher_lines) and are immutable afterwards.
-- The tax amounts are cross-checked by the database itself (CHECK constraints below) against the half-up rounding of taxable value x rate.

-- =====================================================================================================
-- voucher_gst: header
-- =====================================================================================================
CREATE TABLE voucher_gst (
    voucher_id          uuid PRIMARY KEY,
    client_id           uuid NOT NULL,
    gst_registration_id uuid NOT NULL,
    document_kind       text NOT NULL CONSTRAINT voucher_gst_document_kind_check
                        CHECK (document_kind IN ('tax_invoice', 'bill_of_supply', 'self_invoice')),   -- self_invoice: RCM purchase from an unregistered supplier
    supply_category     text NOT NULL CONSTRAINT voucher_gst_supply_category_check CHECK (supply_category IN (
                        'b2b', 'b2c', 'sez_with_payment', 'sez_without_payment', 'export_with_payment', 'export_without_payment',
                        'deemed_export', 'unregistered_supplier', 'composition_supplier', 'import_of_service')),
    counterparty_gstin  text CONSTRAINT voucher_gst_gstin_format
                        CHECK (counterparty_gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),   -- snapshot at voucher time
    counterparty_state_code text REFERENCES gst_state_codes (code),
    place_of_supply     text NOT NULL REFERENCES gst_state_codes (code),
    invoice_date        date NOT NULL,           -- Sales: = voucher date. Purchase: the supplier's invoice date (reference_no = supplier's invoice no)
    original_invoice_no   text,                  -- Credit / Debit Note: the invoice being corrected
    original_invoice_date date,
    note_reason         text CONSTRAINT voucher_gst_note_reason_check CHECK (note_reason IN (
                        'sales_return', 'post_sale_discount', 'deficiency_in_services', 'correction_in_invoice',
                        'change_in_pos', 'provisional_assessment', 'others')),
    has_rcm             boolean NOT NULL DEFAULT false,
    invoice_round_off   numeric(18, 4) NOT NULL DEFAULT 0,     -- signed; posted to the round_off ledger
    invoice_value       numeric(18, 4) NOT NULL CONSTRAINT voucher_gst_value_nonneg CHECK (invoice_value >= 0),
    engine_version      text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT voucher_gst_round_off_two_decimals CHECK (invoice_round_off = round(invoice_round_off, 2)),
    CONSTRAINT voucher_gst_round_off_sane CHECK (abs(invoice_round_off) < 1),
    CONSTRAINT voucher_gst_value_two_decimals CHECK (invoice_value = round(invoice_value, 2)),
    CONSTRAINT voucher_gst_note_fields CHECK ((original_invoice_no IS NULL) = (original_invoice_date IS NULL)),
    CONSTRAINT voucher_gst_note_date_order CHECK (original_invoice_date IS NULL OR original_invoice_date <= invoice_date),
    CONSTRAINT voucher_gst_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id) ON DELETE CASCADE,
    CONSTRAINT voucher_gst_registration_fk FOREIGN KEY (gst_registration_id, client_id)
        REFERENCES gst_registrations (id, client_id)
);
CREATE INDEX voucher_gst_registration_idx ON voucher_gst (gst_registration_id, invoice_date);
CREATE INDEX voucher_gst_client_idx ON voucher_gst (client_id);

-- =====================================================================================================
-- voucher_item_lines: items with qty, rate, discount, taxable value and the engine's tax
--   gross_amount  = round_half_up(quantity x unit_rate, 2)          (database re-checks with round())
--   taxable_value = gross_amount - discount
--   intra-state: cgst = sgst = round_half_up(taxable x rate / 200, 2), igst = 0;  inter-state: igst = round_half_up(taxable x rate / 100, 2)
--   cess_amount   = round_half_up(taxable x cess_rate / 100, 2) + cess_specific_amount
-- =====================================================================================================
CREATE TABLE voucher_item_lines (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id            uuid NOT NULL,
    voucher_id           uuid NOT NULL,
    item_line_no         integer NOT NULL CONSTRAINT voucher_item_lines_no_positive CHECK (item_line_no > 0),
    item_id              uuid,
    description          text NOT NULL CONSTRAINT voucher_item_lines_description_not_blank CHECK (btrim(description) <> ''),
    hsn_sac              text NOT NULL CONSTRAINT voucher_item_lines_hsn_format CHECK (hsn_sac ~ '^[0-9]{4}([0-9]{2}([0-9]{2})?)?$'),
    uqc                  text REFERENCES gst_uqc (code),
    quantity             numeric(18, 3) NOT NULL CONSTRAINT voucher_item_lines_qty_pos CHECK (quantity > 0),
    unit_rate            numeric(18, 4) NOT NULL CONSTRAINT voucher_item_lines_rate_nonneg CHECK (unit_rate >= 0),
    gross_amount         numeric(18, 4) NOT NULL,
    discount             numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_discount_nonneg CHECK (discount >= 0),
    taxable_value        numeric(18, 4) NOT NULL,
    ledger_id            uuid NOT NULL,          -- the Sales / Purchase / expense / asset ledger this line posts to
    treatment            text NOT NULL CONSTRAINT voucher_item_lines_treatment_check
                         CHECK (treatment IN ('taxable', 'zero_rated', 'exempt', 'nil_rated', 'non_gst')),
    gst_rate             numeric(7, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_gst_rate_range CHECK (gst_rate >= 0 AND gst_rate <= 100),
    cess_rate            numeric(7, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_cess_rate_range CHECK (cess_rate >= 0 AND cess_rate <= 1000),
    cess_specific_amount numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_cess_spec_nonneg CHECK (cess_specific_amount >= 0),
    cgst                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_cgst_nonneg CHECK (cgst >= 0),
    sgst                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_sgst_nonneg CHECK (sgst >= 0),
    igst                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_igst_nonneg CHECK (igst >= 0),
    cess                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT voucher_item_lines_cess_nonneg CHECK (cess >= 0),
    rate_rule_id         uuid REFERENCES gst_rate_rules (id),    -- the rule row applied (audit trail); NULL when treatment is fixed by the document (export/SEZ LUT)
    rate_is_default      boolean NOT NULL DEFAULT false,         -- the 'default' rule was used: warn the accountant
    rcm                  boolean NOT NULL DEFAULT false,
    rcm_category_key     text,
    tax_in_cost          boolean NOT NULL DEFAULT false,         -- blocked credit: the tax is part of the cost (no input-tax line)
    itc_category_key     text,                                   -- Section 17(5) key tagged by the accountant (purchase only)
    itc_exception_claimed boolean NOT NULL DEFAULT false,
    itc_exception_note   text,
    CONSTRAINT voucher_item_lines_voucher_no_key UNIQUE (voucher_id, item_line_no),
    CONSTRAINT voucher_item_lines_rate_two_decimals CHECK (unit_rate = round(unit_rate, 2)),
    CONSTRAINT voucher_item_lines_gross_two_decimals CHECK (gross_amount = round(gross_amount, 2)),
    CONSTRAINT voucher_item_lines_discount_two_decimals CHECK (discount = round(discount, 2)),
    CONSTRAINT voucher_item_lines_taxable_two_decimals CHECK (taxable_value = round(taxable_value, 2)),
    CONSTRAINT voucher_item_lines_cess_spec_two_decimals CHECK (cess_specific_amount = round(cess_specific_amount, 2)),
    CONSTRAINT voucher_item_lines_cgst_two_decimals CHECK (cgst = round(cgst, 2)),
    CONSTRAINT voucher_item_lines_sgst_two_decimals CHECK (sgst = round(sgst, 2)),
    CONSTRAINT voucher_item_lines_igst_two_decimals CHECK (igst = round(igst, 2)),
    CONSTRAINT voucher_item_lines_cess_two_decimals CHECK (cess = round(cess, 2)),
    -- numeric round() rounds halves away from zero = ROUND_HALF_UP for these non-negative values: a second, independent check of the engine
    CONSTRAINT voucher_item_lines_gross_formula CHECK (gross_amount = round(quantity * unit_rate, 2)),
    CONSTRAINT voucher_item_lines_discount_le_gross CHECK (discount <= gross_amount),
    CONSTRAINT voucher_item_lines_taxable_formula CHECK (taxable_value = gross_amount - discount),
    CONSTRAINT voucher_item_lines_tax_formula CHECK (
        (igst = 0 AND cgst = round(taxable_value * gst_rate / 200, 2) AND sgst = cgst)
        OR (cgst = 0 AND sgst = 0 AND igst = round(taxable_value * gst_rate / 100, 2))),
    CONSTRAINT voucher_item_lines_cess_formula CHECK (cess = round(taxable_value * cess_rate / 100, 2) + cess_specific_amount),
    CONSTRAINT voucher_item_lines_no_tax_unless_taxable CHECK (
        treatment = 'taxable' OR (gst_rate = 0 AND cess_rate = 0 AND cess_specific_amount = 0 AND cgst = 0 AND sgst = 0 AND igst = 0 AND cess = 0)),
    CONSTRAINT voucher_item_lines_rcm_needs_category CHECK (rcm = (rcm_category_key IS NOT NULL)),
    CONSTRAINT voucher_item_lines_exception_needs_category CHECK (NOT itc_exception_claimed OR itc_category_key IS NOT NULL),
    CONSTRAINT voucher_item_lines_exception_note CHECK (NOT itc_exception_claimed OR btrim(COALESCE(itc_exception_note, '')) <> ''),
    CONSTRAINT voucher_item_lines_cost_needs_category CHECK (NOT tax_in_cost OR (itc_category_key IS NOT NULL AND NOT itc_exception_claimed)),
    CONSTRAINT voucher_item_lines_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id) ON DELETE CASCADE,
    CONSTRAINT voucher_item_lines_header_fk FOREIGN KEY (voucher_id) REFERENCES voucher_gst (voucher_id) ON DELETE CASCADE,
    CONSTRAINT voucher_item_lines_item_fk FOREIGN KEY (item_id, client_id) REFERENCES gst_items (id, client_id),
    CONSTRAINT voucher_item_lines_ledger_fk FOREIGN KEY (ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE INDEX voucher_item_lines_voucher_idx ON voucher_item_lines (voucher_id);
CREATE INDEX voucher_item_lines_hsn_idx ON voucher_item_lines (client_id, hsn_sac);

-- =====================================================================================================
-- voucher_gst_line_roles: which voucher line plays which role in an invoice-mode voucher
-- =====================================================================================================
CREATE TABLE voucher_gst_line_roles (
    voucher_id   uuid NOT NULL,
    line_no      integer NOT NULL,
    role         text NOT NULL CONSTRAINT voucher_gst_line_roles_role_check CHECK (role IN (
                 'party', 'taxable', 'tax_cgst', 'tax_sgst', 'tax_igst', 'tax_cess',
                 'rcm_cgst', 'rcm_sgst', 'rcm_igst', 'rcm_cess', 'round_off')),
    item_line_no integer,
    PRIMARY KEY (voucher_id, line_no),
    CONSTRAINT voucher_gst_line_roles_line_fk FOREIGN KEY (voucher_id, line_no)
        REFERENCES voucher_lines (voucher_id, line_no) ON DELETE CASCADE,
    CONSTRAINT voucher_gst_line_roles_item_fk FOREIGN KEY (voucher_id, item_line_no)
        REFERENCES voucher_item_lines (voucher_id, item_line_no) ON DELETE CASCADE,
    CONSTRAINT voucher_gst_line_roles_item_rule CHECK ((role = 'taxable') = (item_line_no IS NOT NULL))
);

-- =====================================================================================================
-- Draft-only guard for the three tables above (same rule as voucher_lines_guard in 0003)
-- =====================================================================================================
CREATE FUNCTION gst_voucher_child_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    s text;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO s FROM vouchers WHERE id = NEW.voucher_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION '% can only be changed while the voucher is draft (status is %)', TG_TABLE_NAME, s;
        END IF;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO s FROM vouchers WHERE id = OLD.voucher_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION '% can only be changed while the voucher is draft (status is %)', TG_TABLE_NAME, s;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER voucher_gst_guard
    BEFORE INSERT OR UPDATE OR DELETE ON voucher_gst
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();
CREATE TRIGGER voucher_item_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON voucher_item_lines
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();
CREATE TRIGGER voucher_gst_line_roles_guard
    BEFORE INSERT OR UPDATE OR DELETE ON voucher_gst_line_roles
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE voucher_gst            ENABLE ROW LEVEL SECURITY;
ALTER TABLE voucher_item_lines     ENABLE ROW LEVEL SECURITY;
ALTER TABLE voucher_gst_line_roles ENABLE ROW LEVEL SECURITY;

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
