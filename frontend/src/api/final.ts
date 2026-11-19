// Typed client for docs/PHASE6_API_CONTRACT.md (package UI). Same conventions as ./gst.ts, ./tds.ts, ./inventory.ts:
// amounts are decimal strings, reads send no actor, writes send X-User.
// Nothing is calculated here: every amount, depreciation, profit and finding comes from the server.

import { API_BASE, getUser } from '../api'
import { mapApiError } from '../lib/apiError'
import type { Amount, Query } from './gst'

export type { Amount, Query }
export { downloadFile } from './tds'

export type Severity = 'error' | 'warning'
export interface Finding {
  rule_id: string
  message: string
  severity: Severity
  ledger_id?: string | null
}
/** One law row used by a statement; `pending` is shown on screen and printed on exports. */
export interface RuleStatusRow {
  rule?: string
  block_key?: string
  act?: string
  verification_status?: string
  [k: string]: unknown
}

// ---- setup, partners ----
export interface LedgerRoleRow {
  role: string
  ledger_id: string
  ledger_name: string
  created?: boolean
}
export interface Partner {
  id: string
  name: string
  capital_ledger_id: string
  current_ledger_id: string | null
  is_active: boolean
}
export interface PartnerBody {
  name: string
  capital_ledger_id: string
  current_ledger_id?: string | null
  is_active?: boolean
}
export interface TermsRow {
  partner_id: string
  name?: string
  profit_share_percent: string
  interest_on_capital_rate: string | null
  interest_on_drawings_rate: string | null
  remuneration_annual: Amount | null
  deed_reference: string | null
}
export interface Terms {
  rows: TermsRow[]
  share_total: string
  share_ok: boolean
}

// ---- adjustments ----
export type AdjType =
  | 'outstanding_expense'
  | 'prepaid_expense'
  | 'accrued_income'
  | 'income_in_advance'
  | 'provision'
  | 'bad_debt'
  | 'provision_doubtful_debts'
  | 'interest_on_capital'
  | 'interest_on_drawings'
  | 'partner_remuneration'
export interface AdjustmentBody {
  adj_type: AdjType
  as_on_date: string
  basis_note: string
  amount?: string | null
  debit_ledger_id?: string | null
  credit_ledger_id?: string | null
  party_ledger_id?: string | null
  rate_percent?: string | null
  partner_id?: string | null
  months?: number | null
  auto_reverse_on?: string | null
  duplicate_reason?: string | null
}
export interface AdjLine {
  ledger_id: string
  ledger_name: string
  debit: Amount
  credit: Amount
}
export interface AdjPreview {
  amount: Amount
  lines: AdjLine[]
  narration: string
  params: Record<string, unknown>
  findings: Finding[]
}
export interface AdjCreated {
  adjustment_id: string
  voucher_id: string
  auto_reverse_voucher_id: string | null
  amount: Amount
  lines: AdjLine[]
}
export interface AdjustmentRow {
  id: string
  adj_type: AdjType
  as_on_date: string
  amount: Amount
  basis_note: string
  params: Record<string, unknown>
  voucher_id: string
  voucher_status: string
  voucher_number: string | null
  auto_reverse_voucher_id: string | null
}

// ---- fixed assets ----
export interface Asset {
  id: string
  asset_no: string
  name: string
  asset_ledger_id: string
  accumulated_dep_ledger_id: string | null
  is_depreciable: boolean
  it_block_key: string | null
  sched2_class_key: string | null
  useful_life_years: string | null
  residual_value: Amount | null
  book_method: string | null
  is_active: boolean
  cost: Amount
  additions: Amount
  disposed: boolean
}
export interface AssetBody {
  asset_no: string
  name: string
  asset_ledger_id: string
  accumulated_dep_ledger_id?: string | null
  is_depreciable: boolean
  it_block_key?: string | null
  sched2_class_key?: string | null
  useful_life_years?: string | null
  life_override_reason?: string | null
  residual_value?: string | null
  book_method?: string | null
  is_active?: boolean
}
export interface AssetRules {
  it_blocks: { block_key: string; description: string; rate: string; act: string; verification_status: string; source_reference: string | null }[]
  sched2_classes: { class_key: string; description: string; useful_life_years: string; max_residual_percent: string; verification_status: string }[]
  half_rate_days: number | string
  half_rate_percent: string
}
export type EventKind = 'opening' | 'purchase' | 'addition' | 'disposal'
export interface AssetEvent {
  id: string
  kind: EventKind
  event_date: string
  put_to_use_date: string | null
  amount: Amount
  accumulated_dep_bf: Amount | null
  voucher_id: string | null
  note: string | null
}
export interface EventBody {
  kind: EventKind
  event_date: string
  put_to_use_date?: string | null
  amount?: string | null
  accumulated_dep_bf?: string | null
  voucher_id?: string | null
  note?: string | null
}
export interface RegisterRow {
  asset_id: string
  asset_no: string
  name: string
  ledger?: string
  opening_cost: Amount
  additions: Amount
  disposals: Amount
  closing_cost: Amount
  opening_accumulated: Amount
  depreciation_for_year: Amount
  disposal_accumulated: Amount
  closing_accumulated: Amount
  net_block: Amount
  put_to_use_dates?: string[]
}
export interface Register {
  rows: RegisterRow[]
  totals: Record<string, Amount>
}
export interface DepLine {
  asset_id: string
  asset_no: string
  method: string
  cost: Amount
  opening_accumulated: Amount
  wdv_rate_percent: string | null
  days_used: number | string
  days_in_year: number | string
  depreciation: Amount
  closing_accumulated: Amount
  rule_status: Record<string, unknown> | string | null
}
export interface DepPreview {
  lines: DepLine[]
  total: Amount
  journal_lines: AdjLine[]
  disposal_workings: { asset_id: string; proceeds: Amount; book_value: Amount; profit_or_loss: Amount }[]
  findings: Finding[]
  rule_status?: RuleStatusRow[]
  engine_version?: string
}
export interface DepRun {
  run_id: string
  voucher_id: string
  voucher_status: string
  total: Amount
  created_at: string
}
export interface ItBlock {
  block_key: string
  description: string
  rate: string
  rate_act: string
  rate_verification: string
  opening_wdv: Amount
  additions_full: Amount
  additions_half: Amount
  disposals: Amount
  depreciation: Amount
  closing_wdv: Amount
  flags: string[]
  assets: { asset_id: string; asset_no: string; cost: Amount; put_to_use_date: string; days: number | string; half: boolean }[]
}
export interface ItWorking {
  blocks: ItBlock[]
  total_depreciation: Amount
  status: 'draft' | 'final'
  findings: Finding[]
  rule_status?: RuleStatusRow[]
  engine_version?: string
}

// ---- closing stock and statements ----
export type StockSource = 'inventory_report' | 'manual' | 'none'
export interface ClosingStockApproved {
  as_on_date: string
  source: StockSource
  inventory_method: string | null
  cost_value: Amount
  write_down: Amount
  carrying_value: Amount
  basis_note: string | null
  approved_by: string | null
  approved_at: string | null
  detail?: unknown
}
export interface ClosingStock {
  approved: ClosingStockApproved | null
  proposal: Record<string, unknown> | null
}
export interface ClosingStockBody {
  source: StockSource
  as_on_date: string
  cost_value?: string | null
  write_down?: string | null
  basis_note?: string | null
}
export interface Drill {
  ledger_id: string
  ledger_name: string
  amount: Amount
}
export interface Line {
  code: string
  label: string
  amount: Amount
  previous_amount: Amount | null
  note_no: string | number | null
  level: number
  is_total: boolean
  drill: Drill[]
}
export interface Note {
  note_no: string | number
  title: string
  lines: Line[]
}
export interface Statement {
  key: string
  format: string
  title: string
  from_date: string
  to_date: string
  left: Line[]
  right: Line[]
  totals: Record<string, Amount | null>
  notes: Note[]
  findings: Finding[]
  engine_version: string
  rule_status: RuleStatusRow[]
  rule_status_summary?: Record<string, unknown>
  basis: Record<string, string | null>
  previous_source?: string
}
export interface LedgerPosition {
  ledger_id: string
  name: string
  group_code: string
  opening: Amount
  debit_total: Amount
  credit_total: Amount
  closing: Amount
}

// ---- Schedule III ----
export type CfClass = 'operating' | 'investing' | 'financing' | 'cash_equivalent' | 'non_cash' | 'equity_profit'
export interface Sch3Line {
  format_key: string
  line_code: string
  label: string
  section: string
  cf_class?: string | null
  verification_status?: string
}
export interface Sch3Ledger {
  ledger_id: string
  name: string
  group_code: string
  nature?: string
  has_activity?: boolean
  line_code: string | null
  source: 'ledger' | 'group_firm' | 'group_default' | 'none'
  cf_class: string | null
}
export interface Sch3Classification {
  lines: Sch3Line[]
  ledgers: Sch3Ledger[]
  unclassified: string[]
  defaults: string[]
  rule_status?: RuleStatusRow[]
}
export interface ClassRow {
  ledger_id: string
  line_code?: string | null
  cf_class?: CfClass | null
  note?: string | null
}
export interface Sch3Notes {
  notes: Note[]
  findings: Finding[]
  engine_version: string
  rule_status: RuleStatusRow[]
  basis: Record<string, string | null>
}

// ---- year-end close (package F, per contract) ----
export interface CloseItem {
  rule_id: string
  ok: boolean
  message: string
  details?: unknown
}
export interface CloseCheck {
  ready: boolean
  items: CloseItem[]
  net_profit: Amount
  appropriation_preview: { ledger_id: string; name: string; amount: Amount }[]
  vouchers_preview: { step: string; voucher_date: string; reference_no: string; lines: AdjLine[] }[]
  carry_preview: { ledger_count: number; total_debit: Amount; total_credit: Amount; bills_count: number; stock_items: number; it_blocks: number }
  next_financial_year: { id: string | null; exists: boolean }
}
export interface CloseStatus {
  status: 'open' | 'closed' | 'reopened'
  close_id: string | null
  closed_by: string | null
  closed_at: string | null
  net_profit: Amount | null
  voucher_ids: Record<string, string> | null
  carried: Record<string, unknown> | null
  reopened_by: string | null
  reopened_at: string | null
  reopen_reason: string | null
}
export interface CloseDone {
  close_id: string
  voucher_ids: Record<string, string>
  net_profit: Amount
  carried: Record<string, unknown>
}

// ---- transport ----
export function url(path: string, query?: Query): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const text = qs.toString()
  return `${API_BASE}${path}${text ? `?${text}` : ''}`
}

interface Opts {
  query?: Query
  body?: unknown
  write?: boolean
}

async function request<T>(method: string, path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (opts.write) headers['X-User'] = getUser()
  let body: BodyInit | undefined
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let response: Response
  try {
    response = await fetch(url(path, opts.query), { method, headers, body })
  } catch {
    throw mapApiError(0, null)
  }
  if (response.status === 204) return undefined as T
  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    parsed = null
  }
  if (!response.ok) throw mapApiError(response.status, parsed)
  return parsed as T
}
const get = <T>(path: string, query?: Query) => request<T>('GET', path, { query })
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, { body: body ?? {}, write: true })
const put = <T>(path: string, body: unknown) => request<T>('PUT', path, { body, write: true })
const del = <T>(path: string) => request<T>('DELETE', path, { write: true })

const c = (id: string) => `/clients/${id}`
type Ok = { ok: boolean }

export type ExportStatement = 'trading' | 'profit_loss' | 'balance_sheet' | 'cash_flow' | 'appropriation'
export interface ExportQuery {
  financial_year_id: string
  format: 'xlsx' | 'pdf'
  statements: ExportStatement[]
  layout: 'vertical' | 'horizontal'
}

export const finalApi = {
  // setup
  setupLedgers: (cl: string, financial_year_id: string) => post<{ roles: LedgerRoleRow[] }>(`${c(cl)}/final/setup-ledgers`, { financial_year_id }),
  listRoles: (cl: string) => get<LedgerRoleRow[]>(`${c(cl)}/final/ledger-roles`),
  putRole: (cl: string, role: string, ledger_id: string) => put<Ok>(`${c(cl)}/final/ledger-roles/${role}`, { ledger_id }),
  // partners
  listPartners: (cl: string) => get<Partner[]>(`${c(cl)}/partners`),
  addPartner: (cl: string, b: PartnerBody) => post<{ id: string }>(`${c(cl)}/partners`, b),
  updatePartner: (cl: string, id: string, b: Partial<PartnerBody>) => put<Ok>(`${c(cl)}/partners/${id}`, b),
  getTerms: (cl: string, fy: string) => get<Terms>(`${c(cl)}/partners/terms`, { financial_year_id: fy }),
  putTerms: (cl: string, fy: string, rows: TermsRow[]) => put<Ok>(`${c(cl)}/partners/terms/${fy}`, { rows }),
  // adjustments
  previewAdjustment: (cl: string, b: AdjustmentBody) => post<AdjPreview>(`${c(cl)}/adjustments/preview`, b),
  createAdjustment: (cl: string, b: AdjustmentBody) => post<AdjCreated>(`${c(cl)}/adjustments`, b),
  listAdjustments: (cl: string, q: { financial_year_id: string; adj_type?: string }) => get<AdjustmentRow[]>(`${c(cl)}/adjustments`, q),
  deleteAdjustment: (cl: string, id: string) => del<Ok>(`${c(cl)}/adjustments/${id}`),
  // fixed assets
  listAssets: (cl: string, q: { q?: string; active?: boolean } = {}) => get<Asset[]>(`${c(cl)}/fixed-assets`, q),
  addAsset: (cl: string, b: AssetBody) => post<{ id: string }>(`${c(cl)}/fixed-assets`, b),
  updateAsset: (cl: string, id: string, b: AssetBody) => put<Ok>(`${c(cl)}/fixed-assets/${id}`, b),
  assetRules: (cl: string, as_on?: string) => get<AssetRules>(`${c(cl)}/fixed-assets/rules`, { as_on }),
  listEvents: (cl: string, id: string) => get<AssetEvent[]>(`${c(cl)}/fixed-assets/${id}/events`),
  addEvent: (cl: string, id: string, b: EventBody) => post<{ id: string }>(`${c(cl)}/fixed-assets/${id}/events`, b),
  deleteEvent: (cl: string, id: string, eventId: string) => del<Ok>(`${c(cl)}/fixed-assets/${id}/events/${eventId}`),
  register: (cl: string, fy: string) => get<Register>(`${c(cl)}/fixed-assets/register`, { financial_year_id: fy }),
  registerExportPath: (cl: string) => `${c(cl)}/fixed-assets/register/export`,
  bookPreview: (cl: string, financial_year_id: string) => post<DepPreview>(`${c(cl)}/depreciation/book/preview`, { financial_year_id }),
  bookRun: (cl: string, financial_year_id: string) => post<{ run_id: string; voucher_id: string; total: Amount }>(`${c(cl)}/depreciation/book/run`, { financial_year_id }),
  bookRuns: (cl: string, fy: string) => get<DepRun[]>(`${c(cl)}/depreciation/book/runs`, { financial_year_id: fy }),
  deleteBookRun: (cl: string, id: string) => del<Ok>(`${c(cl)}/depreciation/book/runs/${id}`),
  putItOpenings: (cl: string, fy: string, rows: { block_key: string; opening_wdv: string }[]) => put<Ok>(`${c(cl)}/depreciation/it/openings/${fy}`, { rows }),
  itWorking: (cl: string, fy: string) => get<ItWorking>(`${c(cl)}/depreciation/it/working`, { financial_year_id: fy }),
  finalizeIt: (cl: string, financial_year_id: string, acknowledged_flags?: string[]) =>
    post<Ok>(`${c(cl)}/depreciation/it/working/finalize`, { financial_year_id, acknowledged_flags }),
  itExportPath: (cl: string) => `${c(cl)}/depreciation/it/working/export`,
  // closing stock and statements
  getClosingStock: (cl: string, fy: string) => get<ClosingStock>(`${c(cl)}/final/closing-stock`, { financial_year_id: fy }),
  putClosingStock: (cl: string, fy: string, b: ClosingStockBody) => put<{ ok: boolean; carrying_value: Amount }>(`${c(cl)}/final/closing-stock/${fy}`, b),
  trading: (cl: string, q: { financial_year_id: string; as_on?: string }) => get<Statement>(`${c(cl)}/final/trading`, q),
  profitLoss: (cl: string, q: { financial_year_id: string; as_on?: string; format?: string }) => get<Statement>(`${c(cl)}/final/profit-loss`, q),
  balanceSheet: (cl: string, q: { financial_year_id: string; as_on?: string; format?: string }) => get<Statement>(`${c(cl)}/final/balance-sheet`, q),
  appropriation: (cl: string, fy: string) => get<Statement>(`${c(cl)}/final/appropriation`, { financial_year_id: fy }),
  ledgerPositions: (cl: string, q: { financial_year_id: string; as_on?: string }) => get<LedgerPosition[]>(`${c(cl)}/final/ledger-positions`, q),
  // Schedule III
  sch3Classification: (cl: string, fy: string) => get<Sch3Classification>(`${c(cl)}/final/sch3/classification`, { financial_year_id: fy }),
  putSch3Classification: (cl: string, rows: ClassRow[]) => put<Ok>(`${c(cl)}/final/sch3/classification`, { rows }),
  sch3BalanceSheet: (cl: string, q: { financial_year_id: string; as_on?: string }) => get<Statement>(`${c(cl)}/final/sch3/balance-sheet`, q),
  sch3ProfitLoss: (cl: string, fy: string) => get<Statement>(`${c(cl)}/final/sch3/profit-loss`, { financial_year_id: fy }),
  sch3Notes: (cl: string, fy: string) => get<Sch3Notes>(`${c(cl)}/final/sch3/notes`, { financial_year_id: fy }),
  // cash flow and export (package E, per contract)
  cashFlow: (cl: string, fy: string) => get<Statement>(`${c(cl)}/final/cash-flow`, { financial_year_id: fy }),
  exportPath: (cl: string) => `${c(cl)}/final/export`,
  exportQuery: (q: ExportQuery): Query => ({
    financial_year_id: q.financial_year_id,
    format: q.format,
    statements: q.statements.join(','),
    layout: q.layout,
  }),
  // year-end close (package F, per contract)
  closeCheck: (cl: string, fy: string) => get<CloseCheck>(`${c(cl)}/final/close/check`, { financial_year_id: fy }),
  close: (cl: string, financial_year_id: string, create_next_year: boolean) => post<CloseDone>(`${c(cl)}/final/close`, { financial_year_id, create_next_year }),
  closeStatus: (cl: string, fy: string) => get<CloseStatus>(`${c(cl)}/final/close`, { financial_year_id: fy }),
  reopen: (cl: string, closeId: string, reason: string) => post<{ ok: boolean; reversal_voucher_ids: string[] }>(`${c(cl)}/final/close/${closeId}/reopen`, { reason }),
}
