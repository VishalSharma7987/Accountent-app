// Shapes of docs/API_CONTRACT.md. Amounts are strings with 2 decimals; dates are YYYY-MM-DD; ids are UUID strings.

export type Side = 'Dr' | 'Cr' | null
export interface Balance {
  amount: string
  side: Side
}

export type EntityType = 'proprietorship' | 'partnership' | 'llp' | 'company'
export type BusinessType = 'trading' | 'service' | 'manufacturing'
export type GstType = 'regular' | 'composition' | 'unregistered'
export type VoucherType =
  | 'contra'
  | 'payment'
  | 'receipt'
  | 'sales'
  | 'purchase'
  | 'credit_note'
  | 'debit_note'
  | 'journal'
export type VoucherStatus = 'draft' | 'approved' | 'posted' | 'reversed'

export const VOUCHER_TYPES: { value: VoucherType; label: string }[] = [
  { value: 'payment', label: 'Payment' },
  { value: 'receipt', label: 'Receipt' },
  { value: 'contra', label: 'Contra' },
  { value: 'sales', label: 'Sales' },
  { value: 'purchase', label: 'Purchase' },
  { value: 'credit_note', label: 'Credit Note' },
  { value: 'debit_note', label: 'Debit Note' },
  { value: 'journal', label: 'Journal' },
]

export interface ClientSummary {
  id: string
  name: string
  legal_name: string | null
  entity_type: EntityType
  business_type: BusinessType
  gst_type: GstType
  is_active: boolean
}
export interface FinancialYear {
  id: string
  start_date: string
  end_date: string
}
export interface ClientDetail extends ClientSummary {
  pan?: string | null
  state_code?: string | null
  books_begin_date?: string | null
  financial_years: FinancialYear[]
}
export interface CreateClientBody {
  name: string
  legal_name?: string
  entity_type: EntityType
  business_type: BusinessType
  gst_type: GstType
  pan?: string
  state_code?: string
  books_begin_date?: string
  fy_start: string
  proprietor_name?: string
  partners?: string[]
}
export interface CreatedClient {
  client_id: string
  financial_year_id: string
  ledger_ids: Record<string, string>
}

export interface GroupNode {
  code: string
  name: string
  nature: string
  report: string
  is_system: boolean
  children: GroupNode[]
}

export interface LedgerRow {
  id: string
  name: string
  group_code: string
  group_name: string
  group_path: string[]
  is_active: boolean
  balance: Balance
}

export interface OpeningRow {
  ledger_id: string
  ledger_name: string
  debit: string
  credit: string
}
export interface OpeningBalances {
  rows: OpeningRow[]
  total_debit: string
  total_credit: string
  difference: Balance
  is_balanced: boolean
}

export interface VoucherLineIn {
  ledger_id: string
  debit?: string | null
  credit?: string | null
  allocations?: AllocationIn[] // Phase 2: only lines of bill-wise party ledgers
}
export interface VoucherIn {
  voucher_type: VoucherType
  voucher_date: string
  narration: string
  reference_no?: string | null
  party_ledger_id?: string | null
  duplicate_override_reason?: string | null
  lines: VoucherLineIn[]
}
export interface VoucherLineOut {
  line_no: number
  ledger_id: string
  ledger_name: string
  debit: string
  credit: string
  allocations?: AllocationOut[]
}
export interface Voucher {
  id: string
  client_id: string
  financial_year_id: string
  voucher_type: VoucherType
  voucher_number: string | null
  voucher_date: string
  narration: string
  reference_no: string | null
  party_ledger_id: string | null
  status: VoucherStatus
  reverses_voucher_id: string | null
  reversed_by_voucher_id: string | null
  duplicate_override_reason: string | null
  created_by: string
  approved_by: string | null
  posted_by: string | null
  lines: VoucherLineOut[]
}
export interface VoucherListItem {
  id: string
  voucher_number: string | null
  voucher_type: VoucherType
  voucher_date: string
  narration: string
  reference_no: string | null
  status: VoucherStatus
  total: string
}
export interface VoucherList {
  items: VoucherListItem[]
  total_count: number
}
export interface VoucherFilters {
  from?: string
  to?: string
  type?: string
  status?: string
  ledger_id?: string
  limit?: number
  offset?: number
}

export interface Period {
  id: string
  financial_year_id: string
  start: string
  end: string
  status: 'open' | 'locked'
  locked_at: string | null
  locked_by: string | null
}
export interface BlockingVoucher {
  voucher_id: string
  voucher_type: VoucherType
  voucher_date: string
  status: VoucherStatus
  narration: string
}

export interface StatementRow {
  kind: 'opening' | 'entry' | 'closing'
  date: string
  voucher_number: string | null
  voucher_type: string | null
  narration: string | null
  particulars: string
  debit: string
  credit: string
  balance: Balance
}
export interface LedgerStatement {
  ledger_id: string
  ledger_name: string
  from_date: string
  to_date: string
  opening: Balance
  closing: Balance
  total_debit: string
  total_credit: string
  rows: StatementRow[]
}

export interface TrialBalanceRow {
  group_path: string[]
  ledger_id: string
  ledger_name: string
  debit: string
  credit: string
}
export interface TrialBalanceSection {
  group_code: string
  group_name: string
  debit: string
  credit: string
  rows: TrialBalanceRow[]
}
export interface TrialBalance {
  as_on: string
  sections: TrialBalanceSection[]
  total_debit: string
  total_credit: string
  difference: Balance
  is_balanced: boolean
}

export interface AuditEntry {
  id: number
  actor: string
  action: string
  entity: string
  entity_id: string
  old_data: unknown
  new_data: unknown
  created_at: string
}

export interface ImportError {
  rule_id: string
  message: string
  line_no: number | null
  row: number | null
}
export interface ImportVoucher {
  ref_id: string
  first_row: number
  status: 'ok' | 'error'
  errors: ImportError[]
  allocations: ImportAllocation[]
}
export interface ImportAllocation {
  line_no: number
  row: number
  kind: 'new_ref' | 'against_ref' | 'advance' | 'on_account'
  bill_ref: string | null
  amount: string
  due_date: string | null
  auto: boolean // New Ref built by the importer from the voucher's reference_no (not in the sheet)
}
export interface DryRun {
  vouchers: ImportVoucher[]
  ok_count: number
  error_count: number
}
export interface ImportCommit {
  created: { ref_id: string; voucher_id: string; allocations: ImportAllocation[] }[]
  skipped: { ref_id: string; reason: string }[]
}

// ---- Phase 2 (docs/PHASE2_API_CONTRACT.md) ----

export type PartyNature = 'debtor' | 'creditor'
export type MsmeCategory = 'none' | 'micro' | 'small' | 'medium'
export interface Party {
  ledger_id: string
  ledger_name: string
  nature: PartyNature
  gstin: string | null
  pan: string | null
  state_code: string | null
  credit_days: number | null
  msme_category: MsmeCategory
  udyam_no: string | null
  msme_written_agreement: boolean
  bill_wise: boolean
}
export type PartyBody = Omit<Party, 'ledger_id' | 'ledger_name' | 'nature'>

export type AllocationKind = 'new_ref' | 'against_ref' | 'advance' | 'on_account'
export interface AllocationIn {
  kind: AllocationKind
  amount: string
  bill_ref?: string | null
  due_date?: string | null
}
export interface AllocationOut extends AllocationIn {
  due_date: string | null
}

export interface OpeningBillIn {
  bill_ref: string
  bill_date: string
  due_date?: string | null
  amount: string
  side: 'Dr' | 'Cr'
}
export interface OpeningBillOut extends OpeningBillIn {
  due_date: string | null
}
export interface OpeningBills {
  bills: OpeningBillOut[]
  total: Balance
  ledger_opening: Balance
  difference: Balance
  is_balanced: boolean
}

export interface OpenBill {
  party_ledger_id: string
  party_name: string
  bill_ref: string | null
  kind: 'bill' | 'advance' | 'on_account'
  bill_date: string
  due_date: string
  original: Balance
  outstanding: Balance
}

export type BucketKey = 'not_due' | '0-30' | '31-60' | '61-90' | '90+'
export type Buckets = Record<BucketKey, string>
export interface OutstandingBill {
  bill_ref: string | null
  kind: 'bill' | 'advance' | 'on_account'
  bill_date: string
  due_date: string
  original: Balance
  outstanding: Balance
  days_past_due: number
  bucket: BucketKey
}
export interface OutstandingParty {
  party_ledger_id: string
  party_name: string
  bills: OutstandingBill[]
  total: Balance
  ledger_balance: Balance
  ties: boolean
}
export interface OutstandingReport {
  kind: 'receivable' | 'payable'
  as_on: string
  parties: OutstandingParty[]
  buckets: Buckets
  total: Balance
  ties: boolean
}
export interface AgeingRow extends Buckets {
  party_ledger_id: string
  party_name: string
  total: string
}
export interface AgeingReport {
  rows: AgeingRow[]
  totals: Buckets & { total?: string }
}

export interface CashBookEntry {
  voucher_id: string
  voucher_number: string | null
  voucher_type: string
  narration: string
  counter_ledgers: string[]
  receipt: string
  payment: string
}
export interface CashBookDay {
  date: string
  receipts: string
  payments: string
  closing: Balance
  entries: CashBookEntry[]
}
export interface CashBook {
  ledger_name: string
  opening: Balance
  days: CashBookDay[]
  total_receipts: string
  total_payments: string
  closing: Balance
}

export interface MsmeDueItem {
  party_ledger_id: string
  party_name: string
  bill_ref: string | null
  bill_date: string
  legal_days: number
  legal_due_date: string
  days_overdue: number
  outstanding: string
}
export interface MsmeDue {
  as_on: string
  rule_status: 'pending' | 'verified'
  rule_source: string | null
  items: MsmeDueItem[]
  total_outstanding: string
}

export interface BankMapping {
  header_row: number
  date_col: string
  date_format: string
  description_col: string
  reference_col?: string | null
  debit_col?: string | null
  credit_col?: string | null
  amount_col?: string | null
  drcr_col?: string | null
  balance_col?: string | null
  opening_balance_cell?: string | null
  opening_balance?: string | null
}
export interface BankFormat {
  id: string
  name: string
  mapping: BankMapping
}
export interface StatementPreview {
  rows: Record<string, unknown>[]
  count: number
  opening_balance: string | null
  closing_balance: string | null
  problems: { row: number | null; message: string }[]
}
export interface StatementSummary {
  id: string
  file_name: string
  period_from: string
  period_to: string
  opening_balance: string
  closing_balance: string
  line_count: number
  matched_count: number
}
export interface StatementImported {
  statement_id: string
  lines: number
  opening_balance: string
  closing_balance: string
}
export interface StatementLine {
  id: string
  line_no: number
  txn_date: string
  description: string
  reference: string | null
  debit: string
  credit: string
  balance: string | null
  match_id: string | null
}

export interface BankItem {
  line_id: string
  txn_date: string
  description: string
  reference: string | null
  debit: string
  credit: string
}
export interface BookItem {
  voucher_line_id?: string | null
  opening_item_id?: string | null
  date: string
  voucher_number: string | null
  narration: string | null
  reference_no: string | null
  debit: string
  credit: string
}
export interface MatchSuggestion {
  bank_line_ids: string[]
  book_item_ids: string[]
  reason: string
}
export interface Unmatched {
  bank: BankItem[]
  book: BookItem[]
  suggestions: MatchSuggestion[]
}
export interface AutoMatchResult {
  matched_groups: number
  matched_bank_lines: number
  matched_book_items: number
  suggestions_left: number
}
export interface MatchBody {
  bank_line_ids: string[]
  voucher_line_ids: string[]
  opening_item_ids: string[]
  note?: string
}
export interface BrsItem {
  date: string
  reference: string | null
  description: string | null
  amount: string
}
export interface Brs {
  as_on: string
  balance_per_books: Balance
  issued_not_presented: BrsItem[]
  deposited_not_cleared: BrsItem[]
  bank_only_credits: BrsItem[]
  bank_only_debits: BrsItem[]
  computed_bank_balance: Balance
  balance_per_bank: Balance
  difference: Balance
  ties: boolean
}
export interface BankOnlyDraftsResult {
  created: { bank_line_id: string; voucher_id: string }[]
}
