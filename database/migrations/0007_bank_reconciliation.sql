-- 0007: bank statements (stored SEPARATELY from the books) and reconciliation (Phase 2, steps 2.5-2.6).
-- Schema-agnostic (see 0003). Money: numeric(18,4) + CHECK (x = round(x, 2)) (see 0004). RLS on, no policies.

-- needed so match items can point at a voucher line with a same-client guarantee
ALTER TABLE voucher_lines ADD CONSTRAINT voucher_lines_id_client_key UNIQUE (id, client_id);

-- saved column mapping per bank format
CREATE TABLE bank_formats (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id  uuid NOT NULL REFERENCES clients (id),
    name       text NOT NULL CONSTRAINT bank_formats_name_not_blank CHECK (btrim(name) <> ''),
    mapping    jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT bank_formats_id_client_key UNIQUE (id, client_id)
);
CREATE UNIQUE INDEX bank_formats_name_key ON bank_formats (client_id, lower(btrim(name)));

CREATE TABLE bank_statements (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL,
    bank_ledger_id  uuid NOT NULL,
    format_id       uuid,
    file_name       text NOT NULL,
    file_sha256     text NOT NULL,
    period_from     date NOT NULL,
    period_to       date NOT NULL,
    opening_balance numeric(18, 4) NOT NULL CONSTRAINT bank_statements_opening_two_decimals CHECK (opening_balance = round(opening_balance, 2)),
    closing_balance numeric(18, 4) NOT NULL CONSTRAINT bank_statements_closing_two_decimals CHECK (closing_balance = round(closing_balance, 2)),
    imported_by     text NOT NULL,
    imported_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT bank_statements_id_client_key UNIQUE (id, client_id),
    CONSTRAINT bank_statements_period_ok CHECK (period_to >= period_from),
    CONSTRAINT bank_statements_file_key UNIQUE (client_id, bank_ledger_id, file_sha256),
    CONSTRAINT bank_statements_ledger_fk FOREIGN KEY (bank_ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT bank_statements_format_fk FOREIGN KEY (format_id, client_id) REFERENCES bank_formats (id, client_id)
);
CREATE INDEX bank_statements_ledger_idx ON bank_statements (client_id, bank_ledger_id, period_from);

-- debit = money going OUT of the bank (withdrawal), credit = money coming IN (deposit): the bank's own wording;
-- in the books the sides are the mirror image (bank deposit = Dr to the bank ledger).
CREATE TABLE bank_statement_lines (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    uuid NOT NULL,
    statement_id uuid NOT NULL,
    line_no      integer NOT NULL CONSTRAINT bank_statement_lines_line_no_positive CHECK (line_no > 0),
    txn_date     date NOT NULL,
    description  text NOT NULL DEFAULT '',
    reference    text,                      -- cheque no / UTR / reference as read from the statement
    debit        numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT bank_statement_lines_debit_nonneg CHECK (debit >= 0),
    credit       numeric(18, 4) NOT NULL DEFAULT 0 CONSTRAINT bank_statement_lines_credit_nonneg CHECK (credit >= 0),
    balance      numeric(18, 4),            -- running balance printed on the statement, when it has one
    CONSTRAINT bank_statement_lines_debit_two_decimals CHECK (debit = round(debit, 2)),
    CONSTRAINT bank_statement_lines_credit_two_decimals CHECK (credit = round(credit, 2)),
    CONSTRAINT bank_statement_lines_balance_two_decimals CHECK (balance IS NULL OR balance = round(balance, 2)),
    CONSTRAINT bank_statement_lines_exactly_one_side CHECK ((debit > 0) <> (credit > 0)),
    CONSTRAINT bank_statement_lines_id_client_key UNIQUE (id, client_id),
    CONSTRAINT bank_statement_lines_line_key UNIQUE (statement_id, line_no),
    CONSTRAINT bank_statement_lines_statement_fk FOREIGN KEY (statement_id, client_id)
        REFERENCES bank_statements (id, client_id)
);
CREATE INDEX bank_statement_lines_date_idx ON bank_statement_lines (client_id, txn_date);

-- imported lines are never edited (deleting a whole statement is allowed while nothing is matched: the match FK refuses it)
CREATE FUNCTION bank_statement_lines_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'imported bank statement lines cannot be edited';
END $$;

CREATE TRIGGER bank_statement_lines_guard
    BEFORE UPDATE ON bank_statement_lines
    FOR EACH ROW EXECUTE FUNCTION bank_statement_lines_guard();

-- items on the book side that were already outstanding when the books began (cheques issued / deposited before 1 April)
CREATE TABLE bank_opening_items (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    bank_ledger_id    uuid NOT NULL,
    kind              text NOT NULL CONSTRAINT bank_opening_items_kind_check
                      CHECK (kind IN ('issued_not_presented', 'deposited_not_cleared')),
    reference         text,
    item_date         date NOT NULL,
    amount            numeric(18, 4) NOT NULL CONSTRAINT bank_opening_items_amount_pos CHECK (amount > 0),
    CONSTRAINT bank_opening_items_two_decimals CHECK (amount = round(amount, 2)),
    CONSTRAINT bank_opening_items_id_client_key UNIQUE (id, client_id),
    CONSTRAINT bank_opening_items_ledger_fk FOREIGN KEY (bank_ledger_id, client_id) REFERENCES ledgers (id, client_id),
    CONSTRAINT bank_opening_items_year_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- a bank-only line for which the accountant asked for a DRAFT voucher (never posted by the tool)
CREATE TABLE bank_line_drafts (
    bank_line_id uuid PRIMARY KEY,
    client_id    uuid NOT NULL,
    voucher_id   uuid NOT NULL,
    created_by   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT bank_line_drafts_line_fk FOREIGN KEY (bank_line_id, client_id) REFERENCES bank_statement_lines (id, client_id),
    CONSTRAINT bank_line_drafts_voucher_fk FOREIGN KEY (voucher_id, client_id)
        REFERENCES vouchers (id, client_id) ON DELETE CASCADE
);

-- reconciliation: a match groups bank lines with book items (voucher lines on the bank ledger / opening items).
-- One-to-many in either direction: the service requires the signed totals of both sides to be equal (rule R-04).
-- Un-matching deletes the rows (the audit log keeps what was matched).
CREATE TABLE recon_matches (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id      uuid NOT NULL,
    bank_ledger_id uuid NOT NULL,
    method         text NOT NULL CONSTRAINT recon_matches_method_check CHECK (method IN ('auto', 'manual')),
    note           text,
    created_by     text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recon_matches_id_client_key UNIQUE (id, client_id),
    CONSTRAINT recon_matches_ledger_fk FOREIGN KEY (bank_ledger_id, client_id) REFERENCES ledgers (id, client_id)
);

CREATE TABLE recon_match_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       uuid NOT NULL,
    match_id        uuid NOT NULL,
    bank_line_id    uuid,
    voucher_line_id uuid,
    opening_item_id uuid,
    CONSTRAINT recon_match_items_exactly_one CHECK (
        (bank_line_id IS NOT NULL)::int + (voucher_line_id IS NOT NULL)::int + (opening_item_id IS NOT NULL)::int = 1),
    CONSTRAINT recon_match_items_match_fk FOREIGN KEY (match_id, client_id)
        REFERENCES recon_matches (id, client_id) ON DELETE CASCADE,
    CONSTRAINT recon_match_items_bank_line_fk FOREIGN KEY (bank_line_id, client_id)
        REFERENCES bank_statement_lines (id, client_id),
    CONSTRAINT recon_match_items_voucher_line_fk FOREIGN KEY (voucher_line_id, client_id)
        REFERENCES voucher_lines (id, client_id),
    CONSTRAINT recon_match_items_opening_fk FOREIGN KEY (opening_item_id, client_id)
        REFERENCES bank_opening_items (id, client_id)
);
-- every item is in at most one match
CREATE UNIQUE INDEX recon_match_items_bank_key ON recon_match_items (bank_line_id) WHERE bank_line_id IS NOT NULL;
CREATE UNIQUE INDEX recon_match_items_voucher_key ON recon_match_items (voucher_line_id) WHERE voucher_line_id IS NOT NULL;
CREATE UNIQUE INDEX recon_match_items_opening_key ON recon_match_items (opening_item_id) WHERE opening_item_id IS NOT NULL;
CREATE INDEX recon_match_items_match_idx ON recon_match_items (match_id);

ALTER TABLE bank_formats          ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_statements       ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_statement_lines  ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_opening_items    ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_line_drafts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE recon_matches         ENABLE ROW LEVEL SECURITY;
ALTER TABLE recon_match_items     ENABLE ROW LEVEL SECURITY;

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
