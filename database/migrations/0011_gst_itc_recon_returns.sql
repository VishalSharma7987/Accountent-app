-- 0011: ITC register, GSTR-2B / IMS import, books <-> 2B links, return workings (Phase 3, step 3.0).
-- Schema-agnostic (see 0003). Money: numeric(18,4) + round check (0004). RLS on, no policies.
-- Posted vouchers stay immutable (0003). What changes AFTER posting (ITC status, evidence, reversal) lives in these tables,
-- never in the voucher: itc_entries keeps identity and amounts fixed (guard) and every status change is an append-only event.

-- =====================================================================================================
-- itc_entries: one row per posted purchase / debit note / credit note item line that carries GST (created by the posting hook)
-- =====================================================================================================
CREATE TABLE itc_entries (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    gst_registration_id uuid NOT NULL,
    voucher_id          uuid NOT NULL,
    item_line_no        integer NOT NULL,
    doc_type            text NOT NULL CONSTRAINT itc_entries_doc_type_check CHECK (doc_type IN ('invoice', 'debit_note', 'credit_note')),
    source              text NOT NULL CONSTRAINT itc_entries_source_check CHECK (source IN ('regular', 'rcm')),
    supplier_ledger_id  uuid,
    supplier_gstin      text,
    supplier_invoice_no text,
    supplier_invoice_date date NOT NULL,
    igst                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_entries_igst_nonneg CHECK (igst >= 0),
    cgst                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_entries_cgst_nonneg CHECK (cgst >= 0),
    sgst                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_entries_sgst_nonneg CHECK (sgst >= 0),
    cess                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_entries_cess_nonneg CHECK (cess >= 0),
    -- current status (mutable, every change also written to itc_status_events)
    status              text NOT NULL CONSTRAINT itc_entries_status_check
                        CHECK (status IN ('eligible', 'blocked', 'pending', 'reversed')),
    pending_reason      text CONSTRAINT itc_entries_pending_reason_check
                        CHECK (pending_reason IN ('not_in_2b', 'evidence_missing', 'ims_pending', 'ims_rejected')),
    blocked_category_key text,
    -- Section 16 evidence (mutable until the credit is claimed)
    tax_document_held   boolean NOT NULL DEFAULT false,
    goods_services_received boolean NOT NULL DEFAULT false,
    received_date       date,
    supplier_tax_paid   text NOT NULL DEFAULT 'unknown' CONSTRAINT itc_entries_supplier_tax_paid_check
                        CHECK (supplier_tax_paid IN ('unknown', 'in_2b', 'not_in_2b', 'manual_confirmed')),
    evidence_note       text,
    evidence_by         text,
    evidence_at         timestamptz,
    claim_deadline      date,                -- Section 16(4) date computed by the engine (rule data: gst_itc_conditions)
    claimed_in_period   date,                -- first day of the month (or quarter start) of the GSTR-3B in which it was claimed
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT itc_entries_id_client_key UNIQUE (id, client_id),
    CONSTRAINT itc_entries_line_key UNIQUE (voucher_id, item_line_no),
    CONSTRAINT itc_entries_igst_two_decimals CHECK (igst = round(igst, 2)),
    CONSTRAINT itc_entries_cgst_two_decimals CHECK (cgst = round(cgst, 2)),
    CONSTRAINT itc_entries_sgst_two_decimals CHECK (sgst = round(sgst, 2)),
    CONSTRAINT itc_entries_cess_two_decimals CHECK (cess = round(cess, 2)),
    CONSTRAINT itc_entries_pending_reason_rule CHECK ((status = 'pending') = (pending_reason IS NOT NULL)),
    CONSTRAINT itc_entries_blocked_rule CHECK ((status = 'blocked') = (blocked_category_key IS NOT NULL) OR status = 'reversed'),
    CONSTRAINT itc_entries_claimed_period_first_day CHECK (claimed_in_period IS NULL OR extract(day FROM claimed_in_period) = 1),
    CONSTRAINT itc_entries_claim_needs_eligible CHECK (claimed_in_period IS NULL OR status IN ('eligible', 'reversed')),
    CONSTRAINT itc_entries_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id),
    CONSTRAINT itc_entries_line_fk FOREIGN KEY (voucher_id, item_line_no) REFERENCES voucher_item_lines (voucher_id, item_line_no),
    CONSTRAINT itc_entries_registration_fk FOREIGN KEY (gst_registration_id, client_id)
        REFERENCES gst_registrations (id, client_id),
    CONSTRAINT itc_entries_supplier_fk FOREIGN KEY (supplier_ledger_id, client_id) REFERENCES ledgers (id, client_id)
);
CREATE INDEX itc_entries_client_status_idx ON itc_entries (client_id, status);
CREATE INDEX itc_entries_supplier_idx ON itc_entries (client_id, supplier_ledger_id, supplier_invoice_date);

-- append-only history of every status / evidence change
CREATE TABLE itc_status_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL,
    itc_entry_id uuid NOT NULL,
    from_status  text,
    to_status    text NOT NULL,
    reason       text NOT NULL CONSTRAINT itc_status_events_reason_not_blank CHECK (btrim(reason) <> ''),
    actor        text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT itc_status_events_entry_fk FOREIGN KEY (itc_entry_id, client_id) REFERENCES itc_entries (id, client_id)
);
CREATE INDEX itc_status_events_entry_idx ON itc_status_events (itc_entry_id, created_at);

-- ITC reversals (180-day rule, late-identified blocked credit, ...) and their re-claim. The reversal / re-claim are DRAFT journal vouchers
-- made by the service (never posted by the tool); status follows the voucher.
CREATE TABLE itc_reversals (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id            uuid NOT NULL,
    itc_entry_id         uuid NOT NULL,
    reason               text NOT NULL CONSTRAINT itc_reversals_reason_check
                         CHECK (reason IN ('payment_180_days', 'blocked_identified_late', 'other')),
    as_on_date           date NOT NULL,        -- the date the unpaid test was run
    unpaid_fraction_note text,                 -- how the unpaid share was worked out (shown to the accountant)
    igst                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_igst_nonneg CHECK (igst >= 0),
    cgst                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_cgst_nonneg CHECK (cgst >= 0),
    sgst                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_sgst_nonneg CHECK (sgst >= 0),
    cess                 numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_cess_nonneg CHECK (cess >= 0),
    reclaimed_igst       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_r_igst_nonneg CHECK (reclaimed_igst >= 0),
    reclaimed_cgst       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_r_cgst_nonneg CHECK (reclaimed_cgst >= 0),
    reclaimed_sgst       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_r_sgst_nonneg CHECK (reclaimed_sgst >= 0),
    reclaimed_cess       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT itc_reversals_r_cess_nonneg CHECK (reclaimed_cess >= 0),
    reversal_voucher_id  uuid,                 -- the draft Journal (Dr ITC reversal, Cr Input tax); set when created
    reclaim_voucher_id   uuid,                 -- the draft Journal (Dr Input tax, Cr ITC reversal) on payment
    reclaimed_on         date,
    status               text NOT NULL DEFAULT 'proposed' CONSTRAINT itc_reversals_status_check
                         CHECK (status IN ('proposed', 'drafted', 'reversed', 'reclaim_drafted', 'reclaimed', 'cancelled')),
    created_by           text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT itc_reversals_igst_two CHECK (igst = round(igst, 2)),
    CONSTRAINT itc_reversals_cgst_two CHECK (cgst = round(cgst, 2)),
    CONSTRAINT itc_reversals_sgst_two CHECK (sgst = round(sgst, 2)),
    CONSTRAINT itc_reversals_cess_two CHECK (cess = round(cess, 2)),
    CONSTRAINT itc_reversals_r_igst_two CHECK (reclaimed_igst = round(reclaimed_igst, 2)),
    CONSTRAINT itc_reversals_r_cgst_two CHECK (reclaimed_cgst = round(reclaimed_cgst, 2)),
    CONSTRAINT itc_reversals_r_sgst_two CHECK (reclaimed_sgst = round(reclaimed_sgst, 2)),
    CONSTRAINT itc_reversals_r_cess_two CHECK (reclaimed_cess = round(reclaimed_cess, 2)),
    CONSTRAINT itc_reversals_something CHECK (igst + cgst + sgst + cess > 0),
    CONSTRAINT itc_reversals_reclaim_le_reversal CHECK (
        reclaimed_igst <= igst AND reclaimed_cgst <= cgst AND reclaimed_sgst <= sgst AND reclaimed_cess <= cess),
    CONSTRAINT itc_reversals_entry_fk FOREIGN KEY (itc_entry_id, client_id) REFERENCES itc_entries (id, client_id),
    CONSTRAINT itc_reversals_voucher_fk FOREIGN KEY (reversal_voucher_id, client_id) REFERENCES vouchers (id, client_id),
    CONSTRAINT itc_reversals_reclaim_voucher_fk FOREIGN KEY (reclaim_voucher_id, client_id) REFERENCES vouchers (id, client_id)
);
CREATE INDEX itc_reversals_entry_idx ON itc_reversals (itc_entry_id);

-- =====================================================================================================
-- GSTR-2B / IMS import (files from the portal; stored separately from the books, never edited)
-- =====================================================================================================
CREATE TABLE gstr2b_imports (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    gst_registration_id uuid NOT NULL,
    kind                text NOT NULL CONSTRAINT gstr2b_imports_kind_check CHECK (kind IN ('gstr2b', 'ims')),
    return_period       date NOT NULL CONSTRAINT gstr2b_imports_period_first_day CHECK (extract(day FROM return_period) = 1),
    source_format       text NOT NULL CONSTRAINT gstr2b_imports_format_check CHECK (source_format IN ('json', 'excel')),
    file_name           text NOT NULL,
    file_hash           text NOT NULL CONSTRAINT gstr2b_imports_hash_format CHECK (file_hash ~ '^[0-9a-f]{64}$'),
    generated_on        date,
    document_count      integer NOT NULL CONSTRAINT gstr2b_imports_count_nonneg CHECK (document_count >= 0),
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gstr2b_imports_id_client_key UNIQUE (id, client_id),
    CONSTRAINT gstr2b_imports_hash_key UNIQUE (client_id, file_hash),
    CONSTRAINT gstr2b_imports_registration_fk FOREIGN KEY (gst_registration_id, client_id)
        REFERENCES gst_registrations (id, client_id)
);
CREATE INDEX gstr2b_imports_period_idx ON gstr2b_imports (gst_registration_id, return_period);

CREATE TABLE gstr2b_documents (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    import_id           uuid NOT NULL,
    row_no              integer NOT NULL CONSTRAINT gstr2b_documents_row_positive CHECK (row_no > 0),
    section             text NOT NULL CONSTRAINT gstr2b_documents_section_check
                        CHECK (section IN ('b2b', 'b2ba', 'cdnr', 'cdnra', 'isd', 'impg', 'impgsez', 'other')),
    supplier_gstin      text,
    supplier_name       text,
    doc_type            text NOT NULL CONSTRAINT gstr2b_documents_doc_type_check
                        CHECK (doc_type IN ('invoice', 'debit_note', 'credit_note', 'bill_of_entry', 'isd_credit')),
    doc_no              text NOT NULL CONSTRAINT gstr2b_documents_doc_no_not_blank CHECK (btrim(doc_no) <> ''),
    doc_date            date NOT NULL,
    place_of_supply     text,
    reverse_charge      boolean NOT NULL DEFAULT false,
    taxable_value       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT gstr2b_documents_taxable_nonneg CHECK (taxable_value >= 0),
    igst                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT gstr2b_documents_igst_nonneg CHECK (igst >= 0),
    cgst                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT gstr2b_documents_cgst_nonneg CHECK (cgst >= 0),
    sgst                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT gstr2b_documents_sgst_nonneg CHECK (sgst >= 0),
    cess                numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT gstr2b_documents_cess_nonneg CHECK (cess >= 0),
    doc_value           numeric(18, 4) CONSTRAINT gstr2b_documents_value_nonneg CHECK (doc_value >= 0),
    itc_available       text NOT NULL DEFAULT 'yes' CONSTRAINT gstr2b_documents_itc_available_check
                        CHECK (itc_available IN ('yes', 'no', 'temporary')),
    itc_reason          text,
    supplier_return_period date,            -- the supplier's GSTR-1 / IFF period as shown on the document
    supplier_filing_date date,
    ims_status          text NOT NULL DEFAULT 'none' CONSTRAINT gstr2b_documents_ims_status_check
                        CHECK (ims_status IN ('none', 'accepted', 'rejected', 'pending', 'deemed_accepted')),
    CONSTRAINT gstr2b_documents_taxable_two CHECK (taxable_value = round(taxable_value, 2)),
    CONSTRAINT gstr2b_documents_igst_two CHECK (igst = round(igst, 2)),
    CONSTRAINT gstr2b_documents_cgst_two CHECK (cgst = round(cgst, 2)),
    CONSTRAINT gstr2b_documents_sgst_two CHECK (sgst = round(sgst, 2)),
    CONSTRAINT gstr2b_documents_cess_two CHECK (cess = round(cess, 2)),
    CONSTRAINT gstr2b_documents_value_two CHECK (doc_value IS NULL OR doc_value = round(doc_value, 2)),
    CONSTRAINT gstr2b_documents_id_client_key UNIQUE (id, client_id),
    CONSTRAINT gstr2b_documents_row_key UNIQUE (import_id, row_no),
    CONSTRAINT gstr2b_documents_import_fk FOREIGN KEY (import_id, client_id)
        REFERENCES gstr2b_imports (id, client_id) ON DELETE CASCADE
);
CREATE INDEX gstr2b_documents_supplier_idx ON gstr2b_documents (client_id, supplier_gstin, doc_date);

CREATE FUNCTION gstr2b_documents_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'imported GSTR-2B / IMS documents cannot be edited';
END $$;

CREATE TRIGGER gstr2b_documents_guard
    BEFORE UPDATE ON gstr2b_documents
    FOR EACH ROW EXECUTE FUNCTION gstr2b_documents_guard();

-- a manual or confirmed link between a purchase voucher of the books and a 2B document (one to one).
-- Automatic matches are computed on demand by the pure engine; only a decision the accountant makes is stored here.
CREATE TABLE gstr2b_links (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id            uuid NOT NULL,
    gst_registration_id  uuid NOT NULL,
    document_id          uuid NOT NULL,
    voucher_id           uuid NOT NULL,
    link_kind            text NOT NULL CONSTRAINT gstr2b_links_kind_check CHECK (link_kind IN ('manual', 'accepted_difference')),
    note                 text NOT NULL CONSTRAINT gstr2b_links_note_not_blank CHECK (btrim(note) <> ''),
    created_by           text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gstr2b_links_document_fk FOREIGN KEY (document_id, client_id) REFERENCES gstr2b_documents (id, client_id),
    CONSTRAINT gstr2b_links_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id),
    CONSTRAINT gstr2b_links_registration_fk FOREIGN KEY (gst_registration_id, client_id)
        REFERENCES gst_registrations (id, client_id)
);
CREATE UNIQUE INDEX gstr2b_links_document_key ON gstr2b_links (document_id);
CREATE UNIQUE INDEX gstr2b_links_voucher_key ON gstr2b_links (voucher_id);

-- =====================================================================================================
-- Return workings (GSTR-1, GSTR-3B, composition) and the figures actually filed (typed in or imported by the accountant)
-- =====================================================================================================
CREATE TABLE gst_return_workings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    gst_registration_id uuid NOT NULL,
    return_type         text NOT NULL CONSTRAINT gst_return_workings_type_check
                        CHECK (return_type IN ('gstr1', 'gstr3b', 'cmp08', 'gstr4')),
    period_kind         text NOT NULL CONSTRAINT gst_return_workings_kind_check CHECK (period_kind IN ('month', 'quarter', 'year')),
    period_start        date NOT NULL CONSTRAINT gst_return_workings_start_first_day CHECK (extract(day FROM period_start) = 1),
    period_end          date NOT NULL,
    version             integer NOT NULL CONSTRAINT gst_return_workings_version_pos CHECK (version > 0),
    status              text NOT NULL DEFAULT 'draft' CONSTRAINT gst_return_workings_status_check CHECK (status IN ('draft', 'final')),
    data                jsonb NOT NULL,          -- table-wise working exactly as shown / exported (amounts as 2-decimal strings)
    data_hash           text NOT NULL,
    rule_statuses       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- worst verification_status of the rules used, per rule table
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gst_return_workings_period CHECK (period_end >= period_start),
    CONSTRAINT gst_return_workings_key UNIQUE (gst_registration_id, return_type, period_start, version),
    CONSTRAINT gst_return_workings_registration_fk FOREIGN KEY (gst_registration_id, client_id)
        REFERENCES gst_registrations (id, client_id)
);

CREATE TABLE gst_filed_returns (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    gst_registration_id uuid NOT NULL,
    return_type         text NOT NULL CONSTRAINT gst_filed_returns_type_check CHECK (return_type IN ('gstr1', 'gstr3b', 'cmp08', 'gstr4')),
    period_start        date NOT NULL CONSTRAINT gst_filed_returns_start_first_day CHECK (extract(day FROM period_start) = 1),
    arn                 text,
    filed_on            date,
    data                jsonb NOT NULL,          -- filed figures, table-wise (keys as in the contract), amounts as 2-decimal strings
    entered_by          text NOT NULL,
    entered_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gst_filed_returns_key UNIQUE (gst_registration_id, return_type, period_start),
    CONSTRAINT gst_filed_returns_registration_fk FOREIGN KEY (gst_registration_id, client_id)
        REFERENCES gst_registrations (id, client_id)
);

-- a final working cannot be changed or deleted; a new version is a new row
CREATE FUNCTION gst_return_workings_guard() RETURNS trigger
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
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.gst_registration_id <> OLD.gst_registration_id
       OR NEW.return_type <> OLD.return_type OR NEW.period_start <> OLD.period_start OR NEW.version <> OLD.version THEN
        RAISE EXCEPTION 'identity of a return working cannot be changed';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER gst_return_workings_guard
    BEFORE UPDATE OR DELETE ON gst_return_workings
    FOR EACH ROW EXECUTE FUNCTION gst_return_workings_guard();

-- =====================================================================================================
-- Guards of the ITC tables
-- =====================================================================================================
-- itc_entries: identity and amounts never change; only status, evidence and claim columns do; never deleted
CREATE FUNCTION itc_entries_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'an ITC entry cannot be deleted';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'pending_reason' - 'blocked_category_key' - 'tax_document_held' - 'goods_services_received'
        - 'received_date' - 'supplier_tax_paid' - 'evidence_note' - 'evidence_by' - 'evidence_at' - 'claim_deadline'
        - 'claimed_in_period' - 'updated_at')
       <> (to_jsonb(OLD) - 'status' - 'pending_reason' - 'blocked_category_key' - 'tax_document_held' - 'goods_services_received'
        - 'received_date' - 'supplier_tax_paid' - 'evidence_note' - 'evidence_by' - 'evidence_at' - 'claim_deadline'
        - 'claimed_in_period' - 'updated_at') THEN
        RAISE EXCEPTION 'only status, evidence and claim columns of an ITC entry can change';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER itc_entries_guard
    BEFORE UPDATE OR DELETE ON itc_entries
    FOR EACH ROW EXECUTE FUNCTION itc_entries_guard();

CREATE FUNCTION itc_status_events_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'itc_status_events is append-only';
END $$;

CREATE TRIGGER itc_status_events_guard
    BEFORE UPDATE OR DELETE ON itc_status_events
    FOR EACH ROW EXECUTE FUNCTION itc_status_events_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE itc_entries          ENABLE ROW LEVEL SECURITY;
ALTER TABLE itc_status_events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE itc_reversals        ENABLE ROW LEVEL SECURITY;
ALTER TABLE gstr2b_imports       ENABLE ROW LEVEL SECURITY;
ALTER TABLE gstr2b_documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE gstr2b_links         ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_return_workings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE gst_filed_returns    ENABLE ROW LEVEL SECURITY;

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
