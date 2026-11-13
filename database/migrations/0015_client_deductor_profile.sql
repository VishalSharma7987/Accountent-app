-- 0015: facts about the DEDUCTOR (the client) that decide which TDS section applies, per financial year (Phase 4.1). Schema-agnostic (see 0003).
-- RLS enabled with NO policies; API roles hold nothing (0004). No function is created here.
--
-- Rent: the section follows the person who PAYS the rent, not the landlord. A client that is an individual or HUF not liable to tax audit
-- in the preceding year deducts under ex-194-IB (2%, Rs 50,000 a month); every other client under the ordinary rent rule (ex-194-I).
-- The answer can change from year to year, so it is kept per financial year like tds_client_fy_flags (0012). The accountant enters it;
-- the tool never guesses it (engine rule T-19: no entry for the year = refused).
CREATE TABLE tds_deductor_fy_profile (
    client_id           uuid NOT NULL REFERENCES clients (id),
    financial_year_id   uuid NOT NULL,
    individual_huf_not_tax_audited boolean NOT NULL,    -- the client is an individual / HUF NOT liable to tax audit in the preceding year
    note                text,
    entered_by          text NOT NULL,
    entered_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, financial_year_id),
    CONSTRAINT tds_deductor_fy_profile_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);
ALTER TABLE tds_deductor_fy_profile ENABLE ROW LEVEL SECURITY;

-- The PAN status of the deductee when the item was worked. A threshold crossing later brings the earlier payments in at the rate that
-- applied to each one (engine rule T-07), so the status of that day must be kept. NULL on rows written before this column existed:
-- the engine then uses the deductee's present status.
ALTER TABLE tds_voucher_items ADD COLUMN pan_status_at_event text
    CONSTRAINT tds_voucher_items_pan_status_check CHECK (pan_status_at_event IN ('valid', 'missing', 'invalid', 'applied_for'));
