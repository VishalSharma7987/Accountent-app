// Typed client for docs/PHASE4_API_CONTRACT.md (package F). Same conventions as ./gst.ts:
// amounts are decimal strings, reads send no actor, writes send X-User. No tax is calculated here.

import { API_BASE, getUser } from '../api'
import { mapApiError } from '../lib/apiError'
import type { VoucherLineIn } from '../types'
import type { Amount, Query, RuleStatus } from './gst'

export type { Amount, Query, RuleStatus }

export type PanStatus = 'valid' | 'missing' | 'invalid' | 'applied_for'
export type ReturnKind = 'salary' | 'non_salary_resident' | 'tcs'
export type ChallanKind = 'tds' | 'tcs'

export interface Cert {
  id: string
  certificate_no: string
  nature_key: string | null
  rate: string
  max_amount: Amount
  valid_from: string
  valid_to: string
  amount_used: Amount
  amount_left: Amount
  is_active: boolean
}
export interface CertBody {
  certificate_no: string
  nature_key?: string | null
  rate: string
  max_amount: Amount
  valid_from: string
  valid_to: string
  note?: string
}
export interface Deductee {
  ledger_id: string
  ledger_name: string
  pan: string | null
  pan_status: PanStatus
  deductee_type: string
  default_nature_key: string | null
  is_active: boolean
  lower_certs: Cert[]
  pan_warning: string | null
}
export interface DeducteeBody {
  pan?: string | null
  pan_status: PanStatus
  deductee_type: string
  default_nature_key?: string | null
  is_active?: boolean
}
export interface TdsProfile {
  tan: string | null
  fy_flags: { financial_year_id: string; prev_year_turnover_over_threshold: boolean; note: string | null }[]
}
export interface LedgerRole {
  role: string
  nature_key: string | null
  ledger_id: string
  ledger_name?: string
}

export interface RuleTableOut {
  on: string
  status: { overall: string; counts: Record<string, number> }
  rows: Record<string, unknown>[]
}
export type RuleTableName = 'natures' | 'section-map' | 'rates' | 'provisions' | 'due-dates' | 'interest-rules' | 'forms'
export interface SectionMapRow {
  nature_key: string
  description: string
  sec_1961: string | null
  sec_2025: string | null
  table_ref_2025: string | null
  payment_code_2025: string | null
  status: string
}

// ---- deduction on vouchers ----
export interface TdsItemIn {
  deductee_ledger_id: string
  nature_key: string
  amount: Amount
  credit_date: string | null
  payment_date: string | null
  lower_cert_id: string | null
  manual_tax: Amount | null
}
export interface TdsBlock {
  items: TdsItemIn[]
}
export interface TdsVoucherBody {
  voucher_type: string
  voucher_date: string
  narration: string
  reference_no?: string | null
  party_ledger_id?: string | null
  lines: VoucherLineIn[]
  tds: TdsBlock
}
export interface TdsWarning {
  rule_id: string
  message: string
}
export interface TdsItemOut {
  item_no: number
  deductee_ledger_id: string
  deductee_name: string
  nature_key: string
  act: string
  section_ref: string
  table_ref: string | null
  event_date: string
  payment_amount: Amount
  cumulative_before: Amount
  cumulative_after: Amount
  threshold_crossed: boolean
  taxable_base: Amount
  rate_applied: string
  rate_reason: string
  lower_cert_id: string | null
  tax_already_on_base: Amount
  tds_amount: Amount
  tds_line_no: number | null
  verification_status: string
  warnings: TdsWarning[]
}
export interface TdsOut {
  engine_version?: string
  items: TdsItemOut[]
}
export interface TdsPreview {
  lines: { ledger_id: string; ledger_name: string; debit: Amount; credit: Amount; tds_role?: string | null }[]
  tds: TdsOut
  errors: { rule_id: string; message: string; line_no: number | null }[]
  rule_status?: RuleStatus
}
export interface ThresholdPosition {
  financial_year_id: string
  cumulative_amount: Amount
  tax_deducted: Amount
  single_threshold: Amount | null
  annual_threshold: Amount | null
  headroom: Amount | null
}
export interface RegisterRow {
  item_id: string
  voucher_id: string
  voucher_number: string | null
  voucher_date: string
  deductee_ledger_id: string
  deductee_name: string
  pan: string | null
  nature_key: string
  section_ref: string
  event_date: string
  payment_amount: Amount
  taxable_base: Amount
  rate_applied: string
  rate_reason: string
  tds_amount: Amount
  deposited: Amount
  balance: Amount
  due_date: string
  deposited_on: string | null
  days_late: number | null
}
export interface Register {
  rows: RegisterRow[]
  totals: Record<string, unknown>
  rule_status?: RuleStatus
}
export interface RegisterFilter {
  financial_year_id: string
  quarter?: number | ''
  nature_key?: string
  deductee_ledger_id?: string
  deposit_status?: 'all' | 'deposited' | 'short' | 'undeposited'
}
export interface ByDeducteeRow {
  deductee_name: string
  nature_key: string
  cumulative_amount: Amount
  tax_deducted: Amount
  threshold: Amount | null
  threshold_crossed_on: string | null
}

// ---- challans ----
export interface AllocIn {
  item_id: string
  amount: Amount
}
export interface ChallanBody {
  kind: ChallanKind
  financial_year_id: string
  quarter: number
  bsr_code: string
  deposit_date: string
  challan_serial_no: string
  tax_amount: Amount
  interest_amount?: Amount
  fee_amount?: Amount
  other_amount?: Amount
  payment_voucher_id?: string | null
  note?: string
  allocations?: AllocIn[]
}
export interface ChallanRow {
  id: string
  bsr_code: string
  deposit_date: string
  challan_serial_no: string
  tax_amount: Amount
  interest_amount: Amount
  fee_amount: Amount
  other_amount: Amount
  total_amount: Amount
  allocated: Amount
  unallocated: Amount
  status: string
  allocations?: { item_id: string; amount: Amount; deductee_name?: string; section_ref?: string }[]
}
export interface MatchRow {
  item_id: string
  deductee_name: string
  section_ref: string
  tds_amount: Amount
  allocated: Amount
  balance: Amount
  due_date: string
  deposited_on: string | null
  days_late: number | null
  interest_late_deposit: Amount
}
export interface Matching {
  rows: MatchRow[]
  unallocated_challans: ChallanRow[]
  totals: Record<string, unknown>
}
export interface InterestRow {
  item_id: string
  deductee_name: string
  tds_amount: Amount
  deductible_on: string
  deducted_on: string
  months_late_deduction: number
  interest_late_deduction: Amount
  deposited_on: string | null
  due_date: string
  months_late_deposit: number
  interest_late_deposit: Amount
  rule_status?: RuleStatus
}
export interface Interest {
  rows: InterestRow[]
  totals: Record<string, unknown>
}
export interface DueEvent {
  event: string
  kind: string
  quarter: number | null
  period: string
  due_date: string
  status: 'done' | 'due' | 'overdue'
  amount_due: Amount | null
}

// ---- returns and certificates ----
export interface ReturnWorking {
  form_no: string
  form_status: string
  tan: string | null
  period: string
  deductee_rows: Record<string, unknown>[]
  challan_rows: Record<string, unknown>[]
  totals: Record<string, unknown>
  errors: { rule_id: string; message: string }[]
  warnings: { rule_id: string; message: string }[]
  rule_status?: RuleStatus
}
export interface SavedReturnWorking {
  id: string
  version: number
  [k: string]: unknown
}
export interface CertificateData {
  form_no: string
  deductor: { name: string; tan: string | null; pan: string | null }
  deductee: { name: string; pan: string | null }
  items: Record<string, unknown>[]
  challans: Record<string, unknown>[]
  total_deducted: Amount
  total_deposited: Amount
}
export interface CertificateQuery {
  deductee_ledger_id: string
  financial_year_id: string
  quarter: number
  certificate_kind: string
}
export interface SavedCertificate {
  id: string
  version: number
  [k: string]: unknown
}

// ---- 26AS ----
export type Source26 = 'form_26as' | 'ais' | 'tis'
export type ReconClass = 'matched' | 'amount_mismatch' | 'only_in_books' | 'only_in_26as' | 'date_mismatch'
export interface ImportResult {
  import_id: string
  rows: number
  totals: { amount_paid: Amount; tax_deducted: Amount; tax_deposited: Amount }
}
export interface Import26 {
  id: string
  [k: string]: unknown
}
export interface ReconRow {
  class: ReconClass
  row: Record<string, unknown> | null
  books: { item_id?: string; voucher_id?: string; deductee_name: string; section_ref: string; event_date: string; payment_amount: Amount; tds_amount: Amount } | null
  difference: Amount | null
  section_mapping_status: string
}
export interface Recon26 {
  tolerance: Amount
  summary: Record<string, number>
  rows: ReconRow[]
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

interface Opts {
  query?: Query
  body?: unknown
  form?: FormData
  write?: boolean
}

async function request<T>(method: string, path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (opts.write) headers['X-User'] = getUser()
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
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
const post = <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body: body ?? {}, write: true, query })
const put = <T>(path: string, body: unknown) => request<T>('PUT', path, { body, write: true })
const del = <T>(path: string) => request<T>('DELETE', path, { write: true })

/** Save a server-built file (working data export, certificate sheet) exactly as the server made it. */
export async function downloadFile(path: string, filename: string, query?: Query): Promise<void> {
  let response: Response
  try {
    response = await fetch(url(path, query))
  } catch {
    throw mapApiError(0, null)
  }
  if (!response.ok) {
    let parsed: unknown = null
    try {
      parsed = await response.json()
    } catch {
      parsed = null
    }
    throw mapApiError(response.status, parsed)
  }
  const blob = await response.blob()
  const link = document.createElement('a')
  const href = URL.createObjectURL(blob)
  link.href = href
  link.download = filename
  link.click()
  URL.revokeObjectURL(href)
}

const c = (id: string) => `/clients/${id}/tds`

export const tdsApi = {
  // masters
  getProfile: (cl: string) => get<TdsProfile>(`${c(cl)}/profile`),
  putProfile: (cl: string, tan: string) => put<{ ok: boolean }>(`${c(cl)}/profile`, { tan }),
  putFyFlag: (cl: string, fy: string, b: { prev_year_turnover_over_threshold: boolean; note?: string }) =>
    put<{ ok: boolean }>(`${c(cl)}/fy-flags/${fy}`, b),
  listDeductees: (cl: string, q?: string) => get<Deductee[]>(`${c(cl)}/deductees`, { q }),
  putDeductee: (cl: string, ledgerId: string, b: DeducteeBody) => put<{ ok: boolean }>(`${c(cl)}/deductees/${ledgerId}`, b),
  listCerts: (cl: string, ledgerId: string) => get<Cert[]>(`${c(cl)}/deductees/${ledgerId}/certificates`),
  addCert: (cl: string, ledgerId: string, b: CertBody) => post<{ id: string }>(`${c(cl)}/deductees/${ledgerId}/certificates`, b),
  updateCert: (cl: string, ledgerId: string, id: string, b: { is_active?: boolean; note?: string; valid_to?: string }) =>
    put<{ ok: boolean }>(`${c(cl)}/deductees/${ledgerId}/certificates/${id}`, b),
  getRoles: (cl: string) => get<{ roles: LedgerRole[] }>(`${c(cl)}/ledger-roles`),
  putRoles: (cl: string, roles: LedgerRole[]) =>
    put<{ ok: boolean }>(`${c(cl)}/ledger-roles`, { roles: roles.map((r) => ({ role: r.role, nature_key: r.nature_key, ledger_id: r.ledger_id })) }),
  ruleTable: (t: RuleTableName, q: { on?: string; nature_key?: string } = {}) => get<RuleTableOut>(`/tds/${t}`, q),
  // deduction on vouchers
  tdsPreview: (cl: string, b: TdsVoucherBody) => post<TdsPreview>(`/clients/${cl}/vouchers/tds-preview`, b),
  createTdsVoucher: (cl: string, b: TdsVoucherBody) => post<{ voucher_id: string }>(`/clients/${cl}/vouchers`, b),
  thresholdPosition: (cl: string, q: { deductee_ledger_id: string; nature_key: string; on?: string }) =>
    get<ThresholdPosition>(`${c(cl)}/threshold-position`, q),
  register: (cl: string, f: RegisterFilter) => get<Register>(`${c(cl)}/register`, { ...f }),
  registerByDeductee: (cl: string, fy: string) => get<{ rows: ByDeducteeRow[] } | ByDeducteeRow[]>(`${c(cl)}/register/by-deductee`, { financial_year_id: fy }),
  // challans
  createChallan: (cl: string, b: ChallanBody) => post<{ id: string }>(`${c(cl)}/challans`, b),
  listChallans: (cl: string, q: { financial_year_id: string; quarter?: number | ''; kind?: string }) => get<ChallanRow[]>(`${c(cl)}/challans`, q),
  getChallan: (cl: string, id: string) => get<ChallanRow>(`${c(cl)}/challans/${id}`),
  putAllocations: (cl: string, id: string, allocations: AllocIn[]) => put<{ ok: boolean }>(`${c(cl)}/challans/${id}/allocations`, { allocations }),
  matching: (cl: string, q: { financial_year_id: string; quarter?: number | ''; kind?: string }) => get<Matching>(`${c(cl)}/challan-matching`, q),
  autoMatch: (cl: string, b: { financial_year_id: string; quarter: number; kind: string }) =>
    post<{ proposed: { item_id: string; challan_id: string; amount: Amount }[] }>(`${c(cl)}/challan-matching/auto`, b),
  interest: (cl: string, q: { financial_year_id: string; as_on?: string }) => get<Interest>(`${c(cl)}/interest`, q),
  dueCalendar: (cl: string, fy: string) => get<DueEvent[]>(`${c(cl)}/due-calendar`, { financial_year_id: fy }),
  // returns and certificates
  returnWorking: (cl: string, q: { financial_year_id: string; quarter: number; return_kind: ReturnKind }) => get<ReturnWorking>(`${c(cl)}/return-working`, q),
  saveReturnWorking: (cl: string, b: { financial_year_id: string; quarter: number; return_kind: ReturnKind }) =>
    post<{ working_id: string; version: number }>(`${c(cl)}/return-workings`, b),
  listReturnWorkings: (cl: string, q: { financial_year_id: string; quarter?: number; return_kind?: ReturnKind }) =>
    get<SavedReturnWorking[]>(`${c(cl)}/return-workings`, q),
  finaliseWorking: (id: string) => post<unknown>(`/tds/return-workings/${id}/finalise`),
  certificatePreview: (cl: string, q: CertificateQuery) => get<CertificateData>(`${c(cl)}/certificates/preview`, { ...q }),
  saveCertificate: (cl: string, b: CertificateQuery) => post<{ id: string; version: number }>(`${c(cl)}/certificates`, b),
  listCertificates: (cl: string, q: { financial_year_id: string; quarter?: number }) => get<SavedCertificate[]>(`${c(cl)}/certificates`, q),
  updateCertificate: (cl: string, id: string, b: { certificate_no: string; issued_on: string }) => put<unknown>(`${c(cl)}/certificates/${id}`, b),
  // 26AS
  import26: (cl: string, form: FormData) => request<ImportResult>('POST', `${c(cl)}/26as/import`, { form, write: true }),
  list26Imports: (cl: string, fy: string) => get<Import26[]>(`${c(cl)}/26as/imports`, { financial_year_id: fy }),
  reconciliation: (cl: string, q: { financial_year_id: string; import_id?: string }) => get<Recon26>(`${c(cl)}/26as/reconciliation`, q),
  link: (cl: string, b: { row_id: string; item_id?: string; voucher_id?: string; link_kind: 'manual' | 'accepted_difference'; note: string }) =>
    post<{ link_id: string }>(`${c(cl)}/26as/links`, b),
  unlink: (cl: string, id: string) => del<void>(`${c(cl)}/26as/links/${id}`),
}
