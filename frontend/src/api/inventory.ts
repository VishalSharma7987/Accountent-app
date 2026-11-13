// Typed client for docs/PHASE5_API_CONTRACT.md (package F). Same conventions as ./gst.ts and ./tds.ts:
// amounts and quantities are decimal strings, reads send no actor, writes send X-User.
// Nothing is valued or costed here: every cost, closing value and write-down comes from the server.

import { API_BASE, getUser } from '../api'
import { mapApiError } from '../lib/apiError'
import type { Amount, Query } from './gst'

export type { Amount, Query }
export { downloadFile } from './tds'

export type ValuationMethod = 'fifo' | 'wa_periodic' | 'wa_moving'
export type NegativeMode = 'block' | 'warn'
export type JournalType = 'transfer' | 'write_off'
export type JournalStatus = 'draft' | 'approved' | 'posted' | 'reversed'
export type ReasonCode = 'damage' | 'expiry' | 'theft' | 'loss' | 'sample' | 'other'

export interface Godown {
  id: string
  name: string
  is_active: boolean
}
export interface StockItem {
  item_id: string
  sku: string
  name: string
  hsn_sac: string
  uqc: string
  default_godown_id: string | null
  default_godown_name: string | null
  is_active: boolean
  has_entries: boolean
  opening_qty?: string
  opening_value?: Amount
}
export interface StockItemBody {
  sku: string
  default_godown_id: string
  is_active?: boolean
}
export interface Policy {
  financial_year_id: string
  valuation_method: ValuationMethod
  negative_stock_mode: NegativeMode
  set_by: string | null
  set_at: string | null
}
export interface PolicyBody {
  valuation_method: ValuationMethod
  negative_stock_mode: NegativeMode
}
export interface OpeningRow {
  item_id: string
  sku?: string
  name?: string
  godown_id: string
  godown_name?: string
  quantity: string
  value: Amount
  unit_cost?: string
}
export interface Opening {
  rows: OpeningRow[]
  total_value: Amount
  ledger_opening_value: Amount | null
  difference: Amount | null
}

export interface JournalLine {
  line_no?: number
  item_id: string
  item_name?: string
  from_godown_id: string
  to_godown_id: string | null
  quantity: string
}
export interface Journal {
  id: string
  journal_type: JournalType
  journal_number: string | null
  journal_date: string
  narration: string
  reason_code: ReasonCode | null
  reason_note: string | null
  status: JournalStatus
  financial_year_id: string
  lines: JournalLine[]
  created_by: string | null
  approved_by: string | null
  posted_by: string | null
  reversed_by: string | null
  reverse_reason: string | null
}
export interface JournalBody {
  journal_type: JournalType
  journal_date: string
  narration: string
  reason_code?: ReasonCode | null
  reason_note?: string | null
  lines: { item_id: string; from_godown_id: string; to_godown_id: string | null; quantity: string }[]
}
export interface JournalFilter {
  financial_year_id: string
  journal_type?: JournalType | ''
  status?: JournalStatus | ''
  from?: string
  to?: string
}

export interface StockIssue {
  rule_id: string
  message: string
  line_no?: number | null
  item_id?: string | null
  severity?: 'error' | 'warning'
}
export interface PolicyRef {
  valuation_method: ValuationMethod
  negative_stock_mode: NegativeMode
}
export interface RegisterRow {
  item_id: string
  sku: string
  name: string
  uqc: string
  opening_qty: string
  opening_value: Amount | null
  inward_qty: string
  inward_value: Amount | null
  outward_qty: string
  outward_value: Amount | null
  closing_qty: string
  closing_value: Amount | null
  by_godown: { godown_id: string; closing_qty: string }[]
}
export interface StockRegister {
  policy: PolicyRef | null
  from: string
  to: string
  rows: RegisterRow[]
  totals: { opening_value: Amount; inward_value: Amount; outward_value: Amount; closing_value: Amount }
  errors: StockIssue[]
  warnings: StockIssue[]
  engine_version?: string
}
export interface RegisterQuery {
  financial_year_id: string
  from?: string
  to?: string
  item_id?: string
  godown_id?: string
}
export interface ItemLedgerRow {
  date: string
  seq: number
  kind: string
  voucher_number?: string | null
  journal_number?: string | null
  godown_id: string
  in_qty: string
  in_value: Amount | null
  out_qty: string
  out_value: Amount | null
  balance_qty: string
  balance_value: Amount | null
}
export interface NrvRow {
  item_id: string
  name?: string
  as_on_date?: string
  nrv_per_unit: Amount | null
  basis_note: string
  entered_by?: string | null
  entered_at?: string | null
}
export interface ClosingRow {
  item_id: string
  sku: string
  name: string
  closing_qty: string
  cost_value: Amount
  nrv_per_unit: Amount | null
  nrv_value: Amount | null
  write_down: Amount
  carrying_value: Amount
}
export interface ClosingStock {
  policy: PolicyRef | null
  as_on: string
  rows: ClosingRow[]
  totals: { cost_value: Amount; write_down: Amount; carrying_value: Amount }
  items_without_nrv: string[]
  errors: StockIssue[]
  warnings: StockIssue[]
}

// ---- invoice integration (voucher item line) ----
export interface ItemStockIn {
  godown_id: string | null
  original_movement_id: string | null
}
export interface Returnable {
  movement_id: string
  kind: string
  voucher_number: string | null
  date: string
  quantity: string
  already_returned: string
  returnable: string
}
export interface StockPreview {
  movements: { item_id: string; godown_id: string; kind: string; quantity: string; cost: Amount | null }[]
  errors: StockIssue[]
  warnings: StockIssue[]
}

// ---- transport ----
function url(path: string, query?: Query): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const text = qs.toString()
  return `${API_BASE}${path}${text ? `?${text}` : ''}`
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; write?: boolean } = {}): Promise<T> {
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

export const inventoryApi = {
  // masters
  listGodowns: (cl: string) => get<Godown[]>(`${c(cl)}/godowns`),
  addGodown: (cl: string, name: string) => post<{ id: string }>(`${c(cl)}/godowns`, { name }),
  updateGodown: (cl: string, id: string, b: { name?: string; is_active?: boolean }) => put<{ ok: boolean }>(`${c(cl)}/godowns/${id}`, b),
  listStockItems: (cl: string, q: { q?: string; active?: boolean; financial_year_id?: string } = {}) => get<StockItem[]>(`${c(cl)}/stock-items`, q),
  putStockItem: (cl: string, itemId: string, b: StockItemBody) => put<{ ok: boolean }>(`${c(cl)}/stock-items/${itemId}`, b),
  getPolicy: (cl: string, fy: string) => get<Policy>(`${c(cl)}/inventory/policy`, { financial_year_id: fy }),
  /** The contract names the year only on GET; the same financial_year_id query parameter is sent on PUT. */
  putPolicy: (cl: string, fy: string, b: PolicyBody) =>
    request<{ ok: boolean }>('PUT', `${c(cl)}/inventory/policy`, { query: { financial_year_id: fy }, body: b, write: true }),
  copyPolicy: (cl: string, b: { from_financial_year_id: string; to_financial_year_id: string }) => post<{ ok: boolean }>(`${c(cl)}/inventory/policy/copy`, b),
  getOpening: (cl: string, fy: string) => get<Opening>(`${c(cl)}/inventory/opening`, { financial_year_id: fy }),
  putOpening: (cl: string, fy: string, rows: { item_id: string; godown_id: string; quantity: string; value: Amount }[]) =>
    put<{ ok: boolean; total_value: Amount }>(`${c(cl)}/inventory/opening/${fy}`, { rows }),
  // stock journals
  listJournals: (cl: string, f: JournalFilter) => get<Journal[]>(`${c(cl)}/stock-journals`, { ...f }),
  createJournal: (cl: string, b: JournalBody) => post<Journal>(`${c(cl)}/stock-journals`, b),
  updateJournal: (cl: string, id: string, b: JournalBody) => put<Journal>(`${c(cl)}/stock-journals/${id}`, b),
  deleteJournal: (cl: string, id: string) => del<void>(`${c(cl)}/stock-journals/${id}`),
  approveJournal: (cl: string, id: string) => post<Journal>(`${c(cl)}/stock-journals/${id}/approve`),
  postJournal: (cl: string, id: string) => post<Journal>(`${c(cl)}/stock-journals/${id}/post`),
  reverseJournal: (cl: string, id: string, reason: string) => post<Journal>(`${c(cl)}/stock-journals/${id}/reverse`, { reason }),
  // reports and NRV
  stockRegister: (cl: string, q: RegisterQuery) => get<StockRegister>(`${c(cl)}/inventory/stock-register`, { ...q }),
  itemLedger: (cl: string, itemId: string, q: { financial_year_id: string; from?: string; to?: string }) =>
    get<{ rows: ItemLedgerRow[] }>(`${c(cl)}/stock-items/${itemId}/ledger`, q),
  closingStock: (cl: string, q: { financial_year_id: string; as_on?: string }) => get<ClosingStock>(`${c(cl)}/inventory/closing-stock`, { ...q }),
  getNrv: (cl: string, fy: string, asOn?: string) => get<{ rows: NrvRow[] }>(`${c(cl)}/inventory/nrv/${fy}`, { as_on: asOn }),
  putNrv: (cl: string, fy: string, b: { as_on_date: string; rows: { item_id: string; nrv_per_unit: Amount | null; basis_note: string }[] }) =>
    put<{ ok: boolean }>(`${c(cl)}/inventory/nrv/${fy}`, b),
  registerExportPath: (cl: string) => `${c(cl)}/inventory/stock-register/export`,
  closingExportPath: (cl: string) => `${c(cl)}/inventory/closing-stock/export`,
  // invoice integration
  returnable: (cl: string, itemId: string, on?: string) => get<Returnable[]>(`${c(cl)}/stock-items/${itemId}/returnable`, { on }),
}
