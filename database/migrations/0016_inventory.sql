-- 0016: inventory, trading (Phase 5, step 5.0). Schema-agnostic (see 0003). (0015 is reserved for Phase 4.1.)
-- Money: numeric(18,4) + round(.., 2) check (0004). Quantities follow the same pattern: numeric(18,4) + CHECK (qty = round(qty, 3)), so the
-- database rejects 1.0005 instead of rounding it (rule S-02); values read back have 4 decimals and are quantized to 3 in Python.
-- RLS on every table, no policies. Functions pin their search_path; function privileges are closed at the end.
--
-- Design in one paragraph: a stock item is a gst_items row (goods) plus one stock_items row (SKU + default godown). Stock moves ONLY
-- from (a) posted invoice item lines (voucher_item_lines.item_id) of Sales / Purchase / Credit Note / Debit Note vouchers and (b) posted
-- stock journals (transfer between godowns, write-off). Movements are append-only rows written by the service at posting; a movement
-- stores quantity and, for a purchase only, its cost. The cost of everything that goes OUT (and of returns) is never stored: the pure
-- engine computes it from the policy (FIFO / weighted average periodic / moving) every time a report is built. Nothing here posts an
-- accounting entry: accounting stays periodic and closing stock goes to the final accounts in Phase 6.

-- =====================================================================================================
-- godowns
-- =====================================================================================================
CREATE TABLE godowns (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   uuid NOT NULL REFERENCES clients (id),
    name        text NOT NULL CONSTRAINT godowns_name_not_blank CHECK (btrim(name) <> ''),
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT godowns_id_client_key UNIQUE (id, client_id)
);
CREATE UNIQUE INDEX godowns_client_name_key ON godowns (client_id, lower(btrim(name)));

-- =====================================================================================================
-- inventory_settings: the client's policy PER financial year (no row = policy not set: S-04, never a silent default)
-- =====================================================================================================
CREATE TABLE inventory_settings (
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    valuation_method    text NOT NULL CONSTRAINT inventory_settings_method_check
                        CHECK (valuation_method IN ('fifo', 'wa_periodic', 'wa_moving')),
    negative_stock_mode text NOT NULL DEFAULT 'block' CONSTRAINT inventory_settings_negative_check
                        CHECK (negative_stock_mode IN ('block', 'warn')),   -- 'block' is the safe default named in the API contract
    set_by              text NOT NULL,
    set_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, financial_year_id),
    CONSTRAINT inventory_settings_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- =====================================================================================================
-- stock_items: the inventory side of a gst_items goods row (name, HSN and unit (uqc) live in gst_items; invoice item lines already point there)
-- =====================================================================================================
CREATE TABLE stock_items (
    item_id             uuid PRIMARY KEY,
    client_id           uuid NOT NULL,
    sku                 text NOT NULL CONSTRAINT stock_items_sku_not_blank CHECK (btrim(sku) <> ''),
    default_godown_id   uuid NOT NULL,
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stock_items_id_client_key UNIQUE (item_id, client_id),
    CONSTRAINT stock_items_item_fk FOREIGN KEY (item_id, client_id) REFERENCES gst_items (id, client_id),
    CONSTRAINT stock_items_godown_fk FOREIGN KEY (default_godown_id, client_id) REFERENCES godowns (id, client_id)
);
CREATE UNIQUE INDEX stock_items_client_sku_key ON stock_items (client_id, lower(btrim(sku)));
CREATE INDEX stock_items_client_idx ON stock_items (client_id);

-- =====================================================================================================
-- stock_opening: opening quantity and value per item + godown + financial year
-- =====================================================================================================
CREATE TABLE stock_opening (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    item_id             uuid NOT NULL,
    godown_id           uuid NOT NULL,
    quantity            numeric(18, 4) NOT NULL CONSTRAINT stock_opening_qty_nonneg CHECK (quantity >= 0),
    value               numeric(18, 4) NOT NULL CONSTRAINT stock_opening_value_nonneg CHECK (value >= 0),
    entered_by          text NOT NULL,
    entered_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stock_opening_value_two_decimals CHECK (value = round(value, 2)),
    CONSTRAINT stock_opening_qty_three_decimals CHECK (quantity = round(quantity, 3)),
    CONSTRAINT stock_opening_value_needs_qty CHECK (quantity > 0 OR value = 0),
    CONSTRAINT stock_opening_key UNIQUE (client_id, financial_year_id, item_id, godown_id),
    CONSTRAINT stock_opening_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT stock_opening_item_fk FOREIGN KEY (item_id, client_id) REFERENCES stock_items (item_id, client_id),
    CONSTRAINT stock_opening_godown_fk FOREIGN KEY (godown_id, client_id) REFERENCES godowns (id, client_id)
);

-- =====================================================================================================
-- stock_journals (+ lines, + gapless numbers): transfer between godowns, write-off (damage etc.). No ledger lines: not an accounting voucher.
-- Lifecycle draft -> approved -> posted -> reversed (the same discipline as vouchers). A reversal does not create a second journal: the
-- journal becomes 'reversed' (reason stored) and the service appends mirror movements (kind reversal_in / reversal_out).
-- =====================================================================================================
CREATE TABLE stock_journals (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    journal_type        text NOT NULL CONSTRAINT stock_journals_type_check CHECK (journal_type IN ('transfer', 'write_off')),
    journal_number      text,
    journal_date        date NOT NULL,
    narration           text NOT NULL CONSTRAINT stock_journals_narration_not_blank CHECK (btrim(narration) <> ''),
    reason_code         text CONSTRAINT stock_journals_reason_check CHECK (reason_code IN ('damage', 'expiry', 'theft', 'loss', 'sample', 'other')),
    reason_note         text,
    status              text NOT NULL DEFAULT 'draft' CONSTRAINT stock_journals_status_check
                        CHECK (status IN ('draft', 'approved', 'posted', 'reversed')),
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    approved_by         text,
    approved_at         timestamptz,
    posted_by           text,
    posted_at           timestamptz,
    reversed_by         text,
    reversed_at         timestamptz,
    reverse_reason      text,
    CONSTRAINT stock_journals_id_client_key UNIQUE (id, client_id),
    CONSTRAINT stock_journals_number_key UNIQUE (client_id, financial_year_id, journal_number),
    CONSTRAINT stock_journals_number_when_posted CHECK ((status IN ('posted', 'reversed')) = (journal_number IS NOT NULL)),
    CONSTRAINT stock_journals_approved_by CHECK (status = 'draft' OR approved_by IS NOT NULL),
    CONSTRAINT stock_journals_posted_by CHECK (status IN ('draft', 'approved') OR posted_by IS NOT NULL),
    CONSTRAINT stock_journals_reversed_fields CHECK ((status = 'reversed') = (reversed_by IS NOT NULL AND btrim(coalesce(reverse_reason, '')) <> '')),
    CONSTRAINT stock_journals_writeoff_reason CHECK (
        (journal_type = 'write_off' AND reason_code IS NOT NULL AND btrim(coalesce(reason_note, '')) <> '')
        OR (journal_type = 'transfer' AND reason_code IS NULL)),
    CONSTRAINT stock_journals_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);
CREATE INDEX stock_journals_client_date_idx ON stock_journals (client_id, journal_date);

CREATE TABLE stock_journal_lines (
    journal_id      uuid NOT NULL,
    client_id       uuid NOT NULL,
    line_no         integer NOT NULL CONSTRAINT stock_journal_lines_no_positive CHECK (line_no > 0),
    item_id         uuid NOT NULL,
    from_godown_id  uuid NOT NULL,        -- transfer: source; write-off: the godown the goods leave
    to_godown_id    uuid,                 -- transfer only
    quantity        numeric(18, 4) NOT NULL CONSTRAINT stock_journal_lines_qty_pos CHECK (quantity > 0),
    PRIMARY KEY (journal_id, line_no),
    CONSTRAINT stock_journal_lines_qty_three_decimals CHECK (quantity = round(quantity, 3)),
    CONSTRAINT stock_journal_lines_godowns_differ CHECK (to_godown_id IS NULL OR to_godown_id <> from_godown_id),
    CONSTRAINT stock_journal_lines_journal_fk FOREIGN KEY (journal_id, client_id) REFERENCES stock_journals (id, client_id) ON DELETE CASCADE,
    CONSTRAINT stock_journal_lines_item_fk FOREIGN KEY (item_id, client_id) REFERENCES stock_items (item_id, client_id),
    CONSTRAINT stock_journal_lines_from_fk FOREIGN KEY (from_godown_id, client_id) REFERENCES godowns (id, client_id),
    CONSTRAINT stock_journal_lines_to_fk FOREIGN KEY (to_godown_id, client_id) REFERENCES godowns (id, client_id)
);

CREATE TABLE stock_journal_sequences (
    client_id         uuid NOT NULL,
    financial_year_id uuid NOT NULL,
    last_number       integer NOT NULL DEFAULT 0 CONSTRAINT stock_journal_sequences_nonneg CHECK (last_number >= 0),
    PRIMARY KEY (client_id, financial_year_id),
    CONSTRAINT stock_journal_sequences_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id)
);

-- =====================================================================================================
-- stock_movements: append only. quantity > 0; direction says in / out. value is stored for a purchase only (its cost: taxable value plus
-- the tax that is part of the cost); for every other kind it is NULL and the engine computes the cost.
--   purchase / sales_return / transfer_in / reversal_in         -> direction 'in'
--   sale / purchase_return / transfer_out / write_off / reversal_out -> direction 'out'
--   sales_return, purchase_return, reversal_in, reversal_out carry ref_movement_id (the movement they correct / return).
-- =====================================================================================================
CREATE TABLE stock_movements (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    seq                 bigint GENERATED ALWAYS AS IDENTITY UNIQUE,   -- tie-break for the same date: order of posting
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    item_id             uuid NOT NULL,
    godown_id           uuid NOT NULL,
    movement_date       date NOT NULL,
    kind                text NOT NULL CONSTRAINT stock_movements_kind_check CHECK (kind IN (
                        'purchase', 'sale', 'sales_return', 'purchase_return', 'transfer_in', 'transfer_out', 'write_off',
                        'reversal_in', 'reversal_out')),
    direction           text NOT NULL CONSTRAINT stock_movements_direction_check CHECK (direction IN ('in', 'out')),
    quantity            numeric(18, 4) NOT NULL CONSTRAINT stock_movements_qty_pos CHECK (quantity > 0),
    value               numeric(18, 4) CONSTRAINT stock_movements_value_nonneg CHECK (value >= 0),
    voucher_id          uuid,
    item_line_no        integer,
    journal_id          uuid,
    journal_line_no     integer,
    ref_movement_id     uuid,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stock_movements_id_client_key UNIQUE (id, client_id),
    CONSTRAINT stock_movements_value_two_decimals CHECK (value = round(value, 2)),
    CONSTRAINT stock_movements_qty_three_decimals CHECK (quantity = round(quantity, 3)),
    CONSTRAINT stock_movements_direction_matches_kind CHECK (
        (kind IN ('purchase', 'sales_return', 'transfer_in', 'reversal_in') AND direction = 'in')
        OR (kind IN ('sale', 'purchase_return', 'transfer_out', 'write_off', 'reversal_out') AND direction = 'out')),
    CONSTRAINT stock_movements_value_only_for_purchase CHECK ((kind = 'purchase') = (value IS NOT NULL)),
    CONSTRAINT stock_movements_one_source CHECK ((voucher_id IS NOT NULL) <> (journal_id IS NOT NULL)),
    CONSTRAINT stock_movements_voucher_line_pair CHECK ((voucher_id IS NULL) OR ((item_line_no IS NULL) = (kind IN ('reversal_in', 'reversal_out')))),
    CONSTRAINT stock_movements_journal_line_pair CHECK ((journal_id IS NULL) OR ((journal_line_no IS NULL) = (kind IN ('reversal_in', 'reversal_out')))),
    CONSTRAINT stock_movements_kind_source CHECK (
        (kind IN ('purchase', 'sale', 'sales_return', 'purchase_return') AND voucher_id IS NOT NULL)
        OR (kind IN ('transfer_in', 'transfer_out', 'write_off') AND journal_id IS NOT NULL)
        OR kind IN ('reversal_in', 'reversal_out')),
    CONSTRAINT stock_movements_ref_rule CHECK ((kind IN ('sales_return', 'purchase_return', 'reversal_in', 'reversal_out')) = (ref_movement_id IS NOT NULL)),
    CONSTRAINT stock_movements_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT stock_movements_item_fk FOREIGN KEY (item_id, client_id) REFERENCES stock_items (item_id, client_id),
    CONSTRAINT stock_movements_godown_fk FOREIGN KEY (godown_id, client_id) REFERENCES godowns (id, client_id),
    CONSTRAINT stock_movements_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id),
    CONSTRAINT stock_movements_voucher_line_fk FOREIGN KEY (voucher_id, item_line_no) REFERENCES voucher_item_lines (voucher_id, item_line_no),
    CONSTRAINT stock_movements_journal_fk FOREIGN KEY (journal_id, client_id) REFERENCES stock_journals (id, client_id),
    CONSTRAINT stock_movements_journal_line_fk FOREIGN KEY (journal_id, journal_line_no) REFERENCES stock_journal_lines (journal_id, line_no),
    CONSTRAINT stock_movements_ref_fk FOREIGN KEY (ref_movement_id, client_id) REFERENCES stock_movements (id, client_id)
);
CREATE INDEX stock_movements_item_idx ON stock_movements (client_id, item_id, movement_date, seq);
CREATE INDEX stock_movements_fy_idx ON stock_movements (client_id, financial_year_id);
CREATE INDEX stock_movements_voucher_idx ON stock_movements (voucher_id) WHERE voucher_id IS NOT NULL;
-- one movement per invoice item line, one per journal line and kind (a transfer line has an out and an in)
CREATE UNIQUE INDEX stock_movements_voucher_line_key ON stock_movements (voucher_id, item_line_no) WHERE item_line_no IS NOT NULL;
CREATE UNIQUE INDEX stock_movements_journal_line_key ON stock_movements (journal_id, journal_line_no, kind) WHERE journal_line_no IS NOT NULL;
-- a movement can be reversed once
CREATE UNIQUE INDEX stock_movements_reversed_once_key ON stock_movements (ref_movement_id) WHERE kind IN ('reversal_in', 'reversal_out');

-- =====================================================================================================
-- voucher_stock_lines: per invoice item line, written with the draft (draft-only guard below)
--   Sales / Purchase: optional row = godown other than the item's default.
--   Credit Note / Debit Note: a row = the goods physically came back / went back (stock moves); no row = value-only note, no stock effect.
--   original_movement_id: required on a Credit / Debit Note row (the sale / purchase movement being returned): rule S-12.
-- =====================================================================================================
CREATE TABLE voucher_stock_lines (
    voucher_id           uuid NOT NULL,
    client_id            uuid NOT NULL,
    item_line_no         integer NOT NULL,
    godown_id            uuid NOT NULL,
    original_movement_id uuid,
    PRIMARY KEY (voucher_id, item_line_no),
    CONSTRAINT voucher_stock_lines_voucher_fk FOREIGN KEY (voucher_id, client_id) REFERENCES vouchers (id, client_id) ON DELETE CASCADE,
    CONSTRAINT voucher_stock_lines_line_fk FOREIGN KEY (voucher_id, item_line_no)
        REFERENCES voucher_item_lines (voucher_id, item_line_no) ON DELETE CASCADE,
    CONSTRAINT voucher_stock_lines_godown_fk FOREIGN KEY (godown_id, client_id) REFERENCES godowns (id, client_id),
    CONSTRAINT voucher_stock_lines_original_fk FOREIGN KEY (original_movement_id, client_id) REFERENCES stock_movements (id, client_id)
);

-- =====================================================================================================
-- stock_nrv_entries: net realisable value per unit, entered per item at period end (AS 2). Editable (audited by the service).
-- =====================================================================================================
CREATE TABLE stock_nrv_entries (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           uuid NOT NULL,
    financial_year_id   uuid NOT NULL,
    item_id             uuid NOT NULL,
    as_on_date          date NOT NULL,
    nrv_per_unit        numeric(18, 4) NOT NULL CONSTRAINT stock_nrv_entries_nrv_nonneg CHECK (nrv_per_unit >= 0),
    basis_note          text NOT NULL CONSTRAINT stock_nrv_entries_basis_not_blank CHECK (btrim(basis_note) <> ''),
    entered_by          text NOT NULL,
    entered_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stock_nrv_entries_two_decimals CHECK (nrv_per_unit = round(nrv_per_unit, 2)),
    CONSTRAINT stock_nrv_entries_key UNIQUE (client_id, item_id, as_on_date),
    CONSTRAINT stock_nrv_entries_fy_fk FOREIGN KEY (financial_year_id, client_id) REFERENCES financial_years (id, client_id),
    CONSTRAINT stock_nrv_entries_item_fk FOREIGN KEY (item_id, client_id) REFERENCES stock_items (item_id, client_id)
);

-- =====================================================================================================
-- Guards
-- =====================================================================================================

-- stock items are goods only
CREATE FUNCTION stock_items_goods_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    k text;
BEGIN
    SELECT item_kind INTO k FROM gst_items WHERE id = NEW.item_id;
    IF k IS DISTINCT FROM 'goods' THEN
        RAISE EXCEPTION 'only a goods item can be a stock item';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER stock_items_goods_guard
    BEFORE INSERT OR UPDATE ON stock_items
    FOR EACH ROW EXECUTE FUNCTION stock_items_goods_guard();

-- the unit and the kind of an item that holds stock cannot change (quantities would silently change meaning)
CREATE FUNCTION gst_items_stock_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF (NEW.uqc IS DISTINCT FROM OLD.uqc OR NEW.item_kind <> OLD.item_kind)
       AND EXISTS (SELECT 1 FROM stock_items WHERE item_id = OLD.id)
       AND (EXISTS (SELECT 1 FROM stock_movements WHERE item_id = OLD.id)
            OR EXISTS (SELECT 1 FROM stock_opening WHERE item_id = OLD.id)) THEN
        RAISE EXCEPTION 'the unit or kind of an item with stock entries cannot be changed';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER gst_items_stock_guard
    BEFORE UPDATE ON gst_items
    FOR EACH ROW EXECUTE FUNCTION gst_items_stock_guard();

-- the valuation method of a year cannot change once the year has a movement; a policy row with movements cannot be deleted
CREATE FUNCTION inventory_settings_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM stock_movements WHERE client_id = OLD.client_id AND financial_year_id = OLD.financial_year_id) THEN
            RAISE EXCEPTION 'the inventory policy of a year with stock movements cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.client_id <> OLD.client_id OR NEW.financial_year_id <> OLD.financial_year_id THEN
        RAISE EXCEPTION 'the key of an inventory policy cannot be changed';
    END IF;
    IF NEW.valuation_method <> OLD.valuation_method
       AND EXISTS (SELECT 1 FROM stock_movements WHERE client_id = OLD.client_id AND financial_year_id = OLD.financial_year_id) THEN
        RAISE EXCEPTION 'the valuation method cannot be changed once the year has stock movements';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER inventory_settings_guard
    BEFORE UPDATE OR DELETE ON inventory_settings
    FOR EACH ROW EXECUTE FUNCTION inventory_settings_guard();

-- stock_journals: draft only on insert; strict status path; posted rows are frozen except posted -> reversed
CREATE FUNCTION stock_journals_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'a stock journal is created as a draft';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'a % stock journal cannot be deleted', OLD.status;
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.financial_year_id <> OLD.financial_year_id
       OR NEW.journal_type <> OLD.journal_type OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'the identity of a stock journal cannot be changed';
    END IF;
    IF OLD.status = 'reversed' THEN
        RAISE EXCEPTION 'a reversed stock journal cannot be changed';
    END IF;
    IF OLD.status = 'posted' THEN
        IF NEW.status <> 'reversed' THEN
            RAISE EXCEPTION 'a posted stock journal can only be reversed';
        END IF;
        IF (to_jsonb(NEW) - 'status' - 'reversed_by' - 'reversed_at' - 'reverse_reason')
           <> (to_jsonb(OLD) - 'status' - 'reversed_by' - 'reversed_at' - 'reverse_reason') THEN
            RAISE EXCEPTION 'only the reversal fields of a posted stock journal can change';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'draft' AND NEW.status NOT IN ('draft', 'approved') THEN
        RAISE EXCEPTION 'a draft stock journal must be approved before posting';
    END IF;
    IF OLD.status = 'approved' AND NEW.status NOT IN ('approved', 'draft', 'posted') THEN
        RAISE EXCEPTION 'an approved stock journal can only be posted or sent back to draft';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER stock_journals_guard
    BEFORE INSERT OR UPDATE OR DELETE ON stock_journals
    FOR EACH ROW EXECUTE FUNCTION stock_journals_guard();

-- stock_journal_lines: changeable only while the journal is a draft; to_godown_id must fit the journal type
CREATE FUNCTION stock_journal_lines_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    s text;
    t text;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status, journal_type INTO s, t FROM stock_journals WHERE id = NEW.journal_id FOR SHARE;
        IF FOUND THEN
            IF s <> 'draft' THEN
                RAISE EXCEPTION 'stock journal lines can only be changed while the journal is draft (status is %)', s;
            END IF;
            IF t = 'transfer' AND NEW.to_godown_id IS NULL THEN
                RAISE EXCEPTION 'a transfer line needs a destination godown';
            END IF;
            IF t = 'write_off' AND NEW.to_godown_id IS NOT NULL THEN
                RAISE EXCEPTION 'a write-off line has no destination godown';
            END IF;
        END IF;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO s FROM stock_journals WHERE id = OLD.journal_id FOR SHARE;
        IF FOUND AND s <> 'draft' THEN
            RAISE EXCEPTION 'stock journal lines can only be changed while the journal is draft (status is %)', s;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER stock_journal_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON stock_journal_lines
    FOR EACH ROW EXECUTE FUNCTION stock_journal_lines_guard();

-- gapless journal numbers: one at a time, never deleted
CREATE FUNCTION stock_journal_sequences_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'stock journal number sequences cannot be deleted';
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.last_number NOT IN (0, 1) THEN
            RAISE EXCEPTION 'a new stock journal number sequence must start at 0 or 1 (got %)', NEW.last_number;
        END IF;
    ELSE
        IF NEW.client_id <> OLD.client_id OR NEW.financial_year_id <> OLD.financial_year_id THEN
            RAISE EXCEPTION 'the key of a stock journal number sequence cannot be changed';
        END IF;
        IF NEW.last_number <> OLD.last_number + 1 THEN
            RAISE EXCEPTION 'stock journal numbers are issued one at a time (% -> %)', OLD.last_number, NEW.last_number;
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER stock_journal_sequences_guard
    BEFORE INSERT OR UPDATE OR DELETE ON stock_journal_sequences
    FOR EACH ROW EXECUTE FUNCTION stock_journal_sequences_guard();

-- voucher_stock_lines: draft only (the Phase 3 guard works for any table with a voucher_id column)
CREATE TRIGGER voucher_stock_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON voucher_stock_lines
    FOR EACH ROW EXECUTE FUNCTION gst_voucher_child_guard();

-- stock_movements: INSERT only, and only for something that has left draft; the row must agree with its source line
CREATE FUNCTION stock_movements_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    fy_start date;
    fy_end   date;
    s        text;
    vtype    text;
    il       voucher_item_lines%ROWTYPE;
    jl       stock_journal_lines%ROWTYPE;
    r        stock_movements%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'stock movements cannot be changed or deleted; reverse the voucher or journal instead';
    END IF;
    SELECT start_date, end_date INTO fy_start, fy_end FROM financial_years WHERE id = NEW.financial_year_id AND client_id = NEW.client_id;
    IF NEW.movement_date < fy_start OR NEW.movement_date > fy_end THEN
        RAISE EXCEPTION 'the movement date is outside the financial year';
    END IF;
    IF NEW.voucher_id IS NOT NULL THEN
        SELECT status, voucher_type INTO s, vtype FROM vouchers WHERE id = NEW.voucher_id AND client_id = NEW.client_id;
        IF s IS NULL OR s = 'draft' THEN
            RAISE EXCEPTION 'stock moves only from an approved or posted voucher';
        END IF;
        IF NEW.item_line_no IS NOT NULL THEN
            SELECT * INTO il FROM voucher_item_lines WHERE voucher_id = NEW.voucher_id AND item_line_no = NEW.item_line_no;
            IF il.item_id IS DISTINCT FROM NEW.item_id OR il.quantity <> NEW.quantity THEN
                RAISE EXCEPTION 'the movement does not match its invoice item line (item or quantity)';
            END IF;
            IF NOT ((NEW.kind = 'purchase' AND vtype = 'purchase') OR (NEW.kind = 'sale' AND vtype = 'sales')
                    OR (NEW.kind = 'sales_return' AND vtype = 'credit_note') OR (NEW.kind = 'purchase_return' AND vtype = 'debit_note')) THEN
                RAISE EXCEPTION 'a % movement cannot come from a % voucher', NEW.kind, vtype;
            END IF;
            IF NEW.kind = 'purchase'
               AND NEW.value <> il.taxable_value + CASE WHEN il.tax_in_cost THEN il.cgst + il.sgst + il.igst + il.cess ELSE 0 END THEN
                RAISE EXCEPTION 'the purchase cost must equal the taxable value plus the tax that is part of the cost';
            END IF;
        END IF;
    ELSE
        SELECT status INTO s FROM stock_journals WHERE id = NEW.journal_id AND client_id = NEW.client_id;
        IF s IS NULL OR s NOT IN ('approved', 'posted', 'reversed') THEN
            RAISE EXCEPTION 'stock moves only from an approved or posted stock journal';
        END IF;
        IF NEW.journal_line_no IS NOT NULL THEN
            SELECT * INTO jl FROM stock_journal_lines WHERE journal_id = NEW.journal_id AND line_no = NEW.journal_line_no;
            IF jl.item_id <> NEW.item_id OR jl.quantity <> NEW.quantity
               OR (NEW.kind IN ('transfer_out', 'write_off') AND jl.from_godown_id <> NEW.godown_id)
               OR (NEW.kind = 'transfer_in' AND jl.to_godown_id IS DISTINCT FROM NEW.godown_id) THEN
                RAISE EXCEPTION 'the movement does not match its stock journal line';
            END IF;
            IF NOT ((NEW.kind = 'write_off' AND EXISTS (SELECT 1 FROM stock_journals WHERE id = NEW.journal_id AND journal_type = 'write_off'))
                    OR (NEW.kind IN ('transfer_in', 'transfer_out') AND EXISTS (SELECT 1 FROM stock_journals WHERE id = NEW.journal_id AND journal_type = 'transfer'))) THEN
                RAISE EXCEPTION 'a % movement does not fit this journal type', NEW.kind;
            END IF;
        END IF;
    END IF;
    IF NEW.ref_movement_id IS NOT NULL THEN
        SELECT * INTO r FROM stock_movements WHERE id = NEW.ref_movement_id AND client_id = NEW.client_id;
        IF r.item_id IS DISTINCT FROM NEW.item_id THEN
            RAISE EXCEPTION 'the referenced movement is for another item';
        END IF;
        IF (NEW.kind = 'sales_return' AND r.kind <> 'sale') OR (NEW.kind = 'purchase_return' AND r.kind <> 'purchase')
           OR (NEW.kind = 'reversal_in' AND r.direction <> 'out') OR (NEW.kind = 'reversal_out' AND r.direction <> 'in') THEN
            RAISE EXCEPTION 'a % cannot refer to a % movement', NEW.kind, r.kind;
        END IF;
        IF NEW.kind IN ('reversal_in', 'reversal_out') AND (r.godown_id <> NEW.godown_id OR r.quantity <> NEW.quantity) THEN
            RAISE EXCEPTION 'a reversal movement must repeat the godown and quantity of the movement it reverses';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER stock_movements_guard
    BEFORE INSERT OR UPDATE OR DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION stock_movements_guard();

-- =====================================================================================================
-- Row-level security: enabled, NO policies
-- =====================================================================================================
ALTER TABLE godowns                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_settings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_items             ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_opening           ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_journals          ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_journal_lines     ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_journal_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_movements         ENABLE ROW LEVEL SECURITY;
ALTER TABLE voucher_stock_lines     ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_nrv_entries       ENABLE ROW LEVEL SECURITY;

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
