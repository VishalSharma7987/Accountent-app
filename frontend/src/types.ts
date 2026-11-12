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
}
export interface DryRun {
  vouchers: ImportVoucher[]
  ok_count: number
  error_count: number
}
export interface ImportCommit {
  created: { ref_id: string; voucher_id: string }[]
  skipped: { ref_id: string; reason: string }[]
}
