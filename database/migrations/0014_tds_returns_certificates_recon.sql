-- 0014: TDS / TCS return workings, certificates, 26AS / AIS import and reconciliation (Phase 4, step 4.0). Schema-agnostic (see 0003).
-- Money: numeric(18,4) + round check (0004). RLS on, no policies.

-- quarterly statement working (data only: the official file formats are not built in Phase 4; see PHASE4_LEGAL_VALUES.md)
CREATE TABLE tds_return_workings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL REFERENCES clients (id),
    financial_year_id   uuid NOT NULL,
    quarter             integer NOT NULL CONSTRAINT tds_return_workings_quarter_check CHECK (quarter BETWEEN 1 AND 4),
    return_kind         text NOT NULL CONSTRAINT tds_return_workings_kind_check
                        CHECK (return_kind IN ('salary', 'non_salary_resident', 'tcs')),
    form_no             text NOT NULL CONSTRAINT tds_return_workings_form_not_blank CHECK (btrim(form_no) <> ''),   -- snapshot from tds_forms on the quarter-end date (24Q / 26Q / 27EQ or 138 / 140 / 143)
    form_status         text NOT NULL CONSTRAINT tds_return_workings_form_status_check
                        CHECK (form_status IN ('verified', 'secondary_verified', 'pending')),
    version             integer NOT NULL CONSTRAINT tds_return_workings_version_pos CHECK (version > 0),
    status              text NOT NULL DEFAULT 'draft' CONSTRAINT tds_return_workings_status_check CHECK (status IN ('draft', 'final')),
    data                jsonb NOT NULL,          -- deductee-wise / challan-wise working exactly as shown / exported (amounts as 2-decimal strings)
    data_hash           text NOT NULL,
    rule_statuses       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_return_workings_key UNIQUE (client_id, financial_year_id, quarter, return_kind, version),
    CONSTRAINT tds_return_workings_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- what was actually filed (receipt / token number typed by the accountant)
CREATE TABLE tds_filed_returns (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    quarter             integer NOT NULL CONSTRAINT tds_filed_returns_quarter_check CHECK (quarter BETWEEN 1 AND 4),
    return_kind         text NOT NULL CONSTRAINT tds_filed_returns_kind_check CHECK (return_kind IN ('salary', 'non_salary_resident', 'tcs')),
    receipt_no          text,
    filed_on            date,
    data                jsonb NOT NULL,          -- filed totals as typed (amounts as 2-decimal strings)
    entered_by          text NOT NULL,
    entered_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_filed_returns_key UNIQUE (client_id, financial_year_id, quarter, return_kind),
    CONSTRAINT tds_filed_returns_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- certificate data (Form 16A / 131 for non-salary, 27D / 133 for TCS, Form 16 / 130 for salary): a stored, versioned snapshot per deductee and quarter
CREATE TABLE tds_certificates (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    certificate_kind    text NOT NULL CONSTRAINT tds_certificates_kind_check CHECK (certificate_kind IN ('non_salary', 'salary', 'tcs')),
    deductee_ledger_id  uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    quarter             integer CONSTRAINT tds_certificates_quarter_check CHECK (quarter BETWEEN 1 AND 4),   -- NULL for the annual salary certificate
    form_no             text NOT NULL CONSTRAINT tds_certificates_form_not_blank CHECK (btrim(form_no) <> ''),
    form_status         text NOT NULL CONSTRAINT tds_certificates_form_status_check CHECK (form_status IN ('verified', 'secondary_verified', 'pending')),
    version             integer NOT NULL CONSTRAINT tds_certificates_version_pos CHECK (version > 0),
    certificate_no      text,                    -- the portal's certificate number when the accountant has it
    issued_on           date,
    data                jsonb NOT NULL,          -- header, per-item table, per-challan table (amounts as 2-decimal strings)
    data_hash           text NOT NULL,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_certificates_key UNIQUE (client_id, certificate_kind, deductee_ledger_id, financial_year_id, quarter, version),
    CONSTRAINT tds_certificates_deductee_fk FOREIGN KEY (deductee_ledger_id, client_id) REFERENCES tds_deductees (ledger_id, client_id),
    CONSTRAINT tds_certificates_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- 26AS / AIS / TIS import (Excel / CSV / text as the accountant downloads it; the layout is NOT verified: PHASE4_LEGAL_VALUES.md)
CREATE TABLE tds_26as_imports (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL REFERENCES clients (id),
    financial_year_id   uuid NOT NULL,
    source              text NOT NULL CONSTRAINT tds_26as_imports_source_check CHECK (source IN ('form_26as', 'ais', 'tis', 'form_168')),
    side                text NOT NULL CONSTRAINT tds_26as_imports_side_check CHECK (side IN ('deductee', 'deductor')),   -- deductee: our client's own credit; deductor: statement of tax deducted by our client
    file_name           text NOT NULL,
    file_hash           text NOT NULL,
    row_count           integer NOT NULL CONSTRAINT tds_26as_imports_rows_nonneg CHECK (row_count >= 0),
    imported_by         text NOT NULL,
    imported_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_26as_imports_id_client_key UNIQUE (id, client_id),
    CONSTRAINT tds_26as_imports_hash_key UNIQUE (client_id, file_hash),
    CONSTRAINT tds_26as_imports_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

CREATE TABLE tds_26as_rows (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    import_id           uuid NOT NULL,
    row_no              integer NOT NULL CONSTRAINT tds_26as_rows_no_pos CHECK (row_no > 0),
    deductor_tan        text,
    deductor_name       text,
    deductee_pan        text,
    section_ref         text,                    -- as printed (e.g. '194C'); mapped to a nature by the engine, never guessed
    transaction_date    date,
    booking_date        date,
    booking_status      text,                    -- F / U / P ... as printed
    amount_paid         numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_26as_rows_paid_nonneg CHECK (amount_paid >= 0),
    tax_deducted        numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_26as_rows_deducted_nonneg CHECK (tax_deducted >= 0),
    tax_deposited       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT tds_26as_rows_deposited_nonneg CHECK (tax_deposited >= 0),
    CONSTRAINT tds_26as_rows_paid_two_decimals CHECK (amount_paid = round(amount_paid, 2)),
    CONSTRAINT tds_26as_rows_deducted_two_decimals CHECK (tax_deducted = round(tax_deducted, 2)),
    CONSTRAINT tds_26as_rows_deposited_two_decimals CHECK (tax_deposited = round(tax_deposited, 2)),
    CONSTRAINT tds_26as_rows_key UNIQUE (import_id, row_no),
    CONSTRAINT tds_26as_rows_id_client_key UNIQUE (id, client_id),
    CONSTRAINT tds_26as_rows_import_fk FOREIGN KEY (import_id, client_id) REFERENCES tds_26as_imports (id, client_id)
);
CREATE INDEX tds_26as_rows_client_idx ON tds_26as_rows (client_id, import_id);

-- match of a 26AS / AIS row to the books: a deduction item (deductor side) or a posted voucher that booked the receivable (deductee side)
CREATE TABLE tds_26as_links (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    row_id              uuid NOT NULL,
    item_id             uuid,
    voucher_id          uuid,
    link_kind           text NOT NULL CONSTRAINT tds_26as_links_kind_check CHECK (link_kind IN ('auto', 'manual', 'accepted_difference')),
    note                text,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tds_26as_links_target CHECK ((item_id IS NOT NULL) <> (voucher_id IS NOT NULL)),
    CONSTRAINT tds_26as_links_note_needed CHECK (link_kind = 'auto' OR btrim(coalesce(note, '')) <> ''),
    CONSTRAINT tds_26as_links_row_fk FOREIGN KEY (row_id, client_id) REFERENCES tds_26as_rows (id, client_id) ON DELETE CASCADE,
    CONSTRAINT tds_26as_links_item_fk FOREIGN KEY (item_id, client_id) REFERENCES tds_voucher_items (id, client_id),
    CONSTRAINT tds_26as_links_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id)
);
CREATE UNIQUE INDEX tds_26as_links_row_key ON tds_26as_links (row_id);

-- a final working cannot be changed or deleted; a new version is a new row
CREATE FUNCTION tds_return_workings_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'final' THEN
            RAISE EXCEPTION 'a final return working cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'final' THEN
        RAISE EXCEPTION 'a final return working cannot be changed';
    END IF;
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.financial_year_id <> OLD.financial_year_id
       OR NEW.quarter <> OLD.quarter OR NEW.return_kind <> OLD.return_kind OR NEW.version <> OLD.version THEN
        RAISE EXCEPTION 'identity of a return working cannot be changed';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER tds_return_workings_guard
    BEFORE UPDATE OR DELETE ON tds_return_workings
    FOR EACH ROW EXECUTE FUNCTION tds_return_workings_guard();

-- certificate snapshots are never changed (a new version is a new row)
CREATE FUNCTION tds_certificates_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a certificate snapshot cannot be deleted';
    END IF;
    IF (to_jsonb(NEW) - 'certificate_no' - 'issued_on') <> (to_jsonb(OLD) - 'certificate_no' - 'issued_on') THEN
        RAISE EXCEPTION 'only the certificate number and issue date of a certificate snapshot can change';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER tds_certificates_guard
    BEFORE UPDATE OR DELETE ON tds_certificates
    FOR EACH ROW EXECUTE FUNCTION tds_certificates_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE tds_return_workings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_filed_returns    ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_certificates     ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_26as_imports     ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_26as_rows        ENABLE ROW LEVEL SECURITY;
ALTER TABLE tds_26as_links       ENABLE ROW LEVEL SECURITY;

-- =====================================================================================================
-- Close function privileges again (see 0004): functions created by 0013 / 0014 must not be executable
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
