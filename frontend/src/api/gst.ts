// Typed client for docs/PHASE3_API_CONTRACT.md (package F). Same conventions as ../api.ts:
// amounts are decimal strings, reads send no actor, writes send X-User. No tax is calculated here.

import { API_BASE, getUser } from '../api'
import { mapApiError } from '../lib/apiError'

export type Amount = string
export type RuleWorst = 'pending' | 'secondary_verified' | 'verified'
export interface RuleStatus {
  worst: RuleWorst
  tables: Record<string, string>
  pending_sources: string[]
}
export interface Heads {
  igst: Amount
  cgst: Amount
  sgst: Amount
  cess: Amount
}
export type Query = Record<string, string | number | boolean | undefined | null>

export type RegistrationType = 'regular' | 'composition'
export interface Registration {
  id: string
  gstin: string
  state_code: string
  state_name: string
  registration_type: RegistrationType
  return_frequency: 'monthly' | 'qrmp'
  composition_category: 'manufacturer' | 'trader' | 'restaurant' | 'service_provider' | null
  trade_name: string | null
  effective_from: string
  effective_to: string | null
  is_active: boolean
  ledger_roles: Record<string, { ledger_id: string; ledger_name: string }>
}
export interface RegistrationBody {
  gstin?: string
  registration_type: RegistrationType
  return_frequency?: 'monthly' | 'qrmp'
  composition_category?: Registration['composition_category']
  trade_name?: string
  effective_from: string
  effective_to?: string | null
  is_active?: boolean
}
export interface GstinCheck {
  valid: boolean
  errors: { rule_id: string; message: string }[]
  state_code: string
  state_name: string
  pan: string
  expected_check_char: string | null
}
export interface GstItem {
  id: string
  name: string
  item_kind: 'goods' | 'service'
  hsn_sac: string
  uqc: string
  sales_ledger_id: string | null
  purchase_ledger_id: string | null
  default_itc_category_key: string | null
  default_rcm_category_key: string | null
  is_active: boolean
}
export type GstItemBody = Omit<GstItem, 'id'>
export interface RateLookup {
  rule_id: string
  rule_key: string
  treatment: 'taxable' | 'exempt' | 'nil_rated' | 'non_gst'
  rate: string
  cess_rate: string
  cess_specific_amount: string
  cess_uqc: string | null
  is_default: boolean
  is_example: boolean
  verification_status: string
  source_reference: string
}
export type RuleTable =
  | 'state-codes'
  | 'uqc'
  | 'rate-slabs'
  | 'rcm-categories'
  | 'blocked-credit-categories'
  | 'itc-conditions'
  | 'composition-rules'
  | 'thresholds'

// ---- invoice mode ----
export interface GstItemIn {
  item_id: string | null
  description: string
  hsn_sac: string
  uqc: string | null
  quantity: string
  unit_rate: string
  discount: string
  ledger_id: string
  rcm_category_key: string | null
  itc_category_key: string | null
  itc_exception_claimed: boolean
  itc_exception_note: string | null
}
export interface GstIn {
  gst_registration_id: string
  document_kind: 'tax_invoice' | 'bill_of_supply' | 'self_invoice'
  supply_category: string
  place_of_supply: string
  invoice_date: string
  counterparty_gstin: string | null
  original_invoice_no?: string | null
  original_invoice_date?: string | null
  note_reason?: string | null
  items: GstItemIn[]
}
export interface GstVoucherBody {
  voucher_type: string
  voucher_date: string
  narration: string
  reference_no?: string | null
  party_ledger_id?: string | null
  gst: GstIn
}
export interface GstItemOut {
  item_line_no: number
  gross_amount: Amount
  taxable_value: Amount
  treatment: string
  gst_rate: string
  cess_rate: string
  cgst: Amount
  sgst: Amount
  igst: Amount
  cess: Amount
  rate_rule_id: string | null
  rate_is_default: boolean
  rcm: boolean
  tax_in_cost: boolean
}
export interface GstOut {
  invoice_value: Amount
  invoice_round_off: Amount
  has_rcm: boolean
  engine_version?: string
  warnings: { rule_id: string; message: string; item_line_no: number | null }[]
  items: GstItemOut[]
}
export interface GstPreview {
  lines: { ledger_id: string; ledger_name: string; debit: Amount; credit: Amount; gst_role: string }[]
  gst: GstOut
  errors: { rule_id: string; message: string; line_no: number | null; details?: { item_line_no?: number } }[]
}

// ---- ITC ----
export type ItcStatus = 'eligible' | 'blocked' | 'pending' | 'reversed'
export type SupplierTaxPaid = 'unknown' | 'in_2b' | 'not_in_2b' | 'manual_confirmed'
export interface ItcEntry extends Heads {
  id: string
  voucher_id: string
  voucher_number: string | null
  item_line_no: number
  doc_type: string
  source: 'regular' | 'rcm'
  supplier_ledger_id: string
  supplier_name: string
  supplier_gstin: string | null
  supplier_invoice_no: string
  supplier_invoice_date: string
  status: ItcStatus
  pending_reason: string | null
  blocked_category_key: string | null
  tax_document_held: boolean
  goods_services_received: boolean
  received_date: string | null
  supplier_tax_paid: SupplierTaxPaid
  evidence_note: string | null
  claim_deadline: string | null
  claimed_in_period: string | null
  days_since_invoice: number
  unpaid_share: ({ fraction: string } & Heads) | null
}
export interface ItcList {
  entries: ItcEntry[]
  totals: Record<ItcStatus, Heads>
  rule_status?: RuleStatus
}
export interface ItcEvent {
  from_status: string | null
  to_status: string
  reason: string
  actor: string
  created_at: string
}
export interface ExposureItem extends Heads {
  itc_entry_id: string
  voucher_number: string | null
  supplier_name: string
  supplier_invoice_no: string
  invoice_date: string
  days: number
  due_on_day: number
  outstanding: Amount
  already_reversed: boolean
}
export interface Exposure {
  as_on: string
  rule_status?: RuleStatus
  items: ExposureItem[]
  approaching: ExposureItem[]
  total: Heads
}
export interface ItcReversal {
  id: string
  itc_entry_id: string
  reason: string
  as_on_date: string
  amounts: Heads | null
  reversal_voucher_id: string | null
  reclaim_voucher_id: string | null
  status: string
}
export interface Balance {
  amount: Amount
  side: 'Dr' | 'Cr' | null
}
export interface RegisterTie {
  input_ledgers: Record<string, Balance>
  itc_register: Record<string, Amount>
  difference: Record<string, Amount>
  ties: boolean
  notes: string[]
}

// ---- 2B ----
export interface Import2b {
  id: string
  kind: 'gstr2b' | 'ims'
  period: string
  file_name: string
  generated_on: string | null
  document_count: number
  created_at: string
}
export interface Doc2b extends Heads {
  id: string
  section: string
  supplier_gstin: string
  supplier_name: string | null
  doc_type: string
  doc_no: string
  doc_date: string
  taxable_value: Amount
  itc_available: string | boolean | null
  itc_reason: string | null
  ims_status: string | null
  supplier_return_period: string | null
}
export type ReconClass = 'matched' | 'value_mismatch' | 'gstin_mismatch' | 'period_mismatch' | 'only_in_books' | 'only_in_2b' | 'ambiguous'
export interface ReconBooks extends Heads {
  voucher_id: string
  voucher_number: string | null
  supplier_gstin: string | null
  supplier_invoice_no: string
  invoice_date: string
  taxable_value: Amount
  itc_status: string
}
export interface ReconDoc extends Heads {
  document_id: string
  supplier_gstin: string
  doc_no: string
  doc_date: string
  taxable_value: Amount
  itc_available: string | boolean | null
  ims_status: string | null
}
export interface ReconRow {
  class: ReconClass
  books: ReconBooks | null
  doc_2b: ReconDoc | null
  differences: { field: string; books: Amount; doc_2b: Amount; difference: Amount }[]
  note: string
  link_id: string | null
}
export interface Recon {
  period: string
  tolerance: Amount
  summary: Record<string, number>
  rows: ReconRow[]
  totals: Record<'books' | 'doc_2b' | 'difference', Record<string, Amount>>
}

// ---- returns ----
export interface Working<T> {
  registration_id: string
  gstin: string
  period_kind: string
  period_start: string
  period_end: string
  generated_at: string
  rule_status: RuleStatus
  warnings: (string | { rule_id?: string; message: string })[]
  tables: T
  source_voucher_count: number
  unposted_drafts_in_period: { voucher_id: string }[]
}
export type AnyTables = Record<string, unknown>
export interface TieOut {
  rows: {
    head: string
    books_output: Amount
    gstr1_working: Amount
    gstr3b_working: Amount
    filed_gstr1: Amount | null
    filed_gstr3b: Amount | null
    d_books_gstr1: Amount
    d_gstr1_gstr3b: Amount
    d_books_filed: Amount | null
  }[]
  itc: Record<string, unknown>
  causes: { kind: string; reference: string; amount: Amount }[]
  ties: boolean
  rule_status?: RuleStatus
}
export interface WorkingRow {
  id: string
  return_type: string
  period_start: string
  version: number
  status: string
  data_hash: string
  created_by: string
  created_at: string
}

export interface ReturnQuery {
  registration_id: string
  period_start: string
  period_kind: 'month' | 'quarter'
}

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

const c = (id: string) => `/clients/${id}/gst`
const rq = (q: ReturnQuery): Query => ({ registration_id: q.registration_id, period_start: q.period_start, period_kind: q.period_kind })

export const gstApi = {
  // masters
  listRegistrations: (cl: string) => get<Registration[]>(`${c(cl)}/registrations`),
  createRegistration: (cl: string, b: RegistrationBody) => post<{ id: string }>(`${c(cl)}/registrations`, b),
  updateRegistration: (cl: string, id: string, b: RegistrationBody) => put<{ ok: boolean }>(`${c(cl)}/registrations/${id}`, b),
  setLedgerRoles: (cl: string, id: string, roles: Record<string, string>) =>
    put<{ ok: boolean }>(`${c(cl)}/registrations/${id}/ledger-roles`, { roles }),
  validateGstin: (gstin: string, onDate?: string) => post<GstinCheck>('/gst/validate-gstin', { gstin, on_date: onDate }),
  listItems: (cl: string, q?: string, kind?: string) => get<GstItem[]>(`${c(cl)}/items`, { q, kind }),
  createItem: (cl: string, b: GstItemBody) => post<{ id: string }>(`${c(cl)}/items`, b),
  updateItem: (cl: string, id: string, b: GstItemBody) => put<{ ok: boolean }>(`${c(cl)}/items/${id}`, b),
  rateLookup: (hsn: string, kind: 'goods' | 'services', on?: string) =>
    get<RateLookup>('/gst/rates/lookup', { hsn_sac: hsn, supply_kind: kind, on }),
  ruleTable: (t: RuleTable, on?: string) => get<unknown>(`/gst/${t}`, { on }),
  // invoice mode
  gstPreview: (cl: string, b: GstVoucherBody) => post<GstPreview>(`/clients/${cl}/vouchers/gst-preview`, b),
  createGstVoucher: (cl: string, b: GstVoucherBody) => post<{ voucher_id: string }>(`/clients/${cl}/vouchers`, b),
  // ITC
  listItc: (cl: string, q: { registration_id?: string; status?: string; period?: string; supplier_ledger_id?: string }) =>
    get<ItcList>(`${c(cl)}/itc`, q),
  itcEvidence: (
    cl: string,
    id: string,
    b: { tax_document_held: boolean; goods_services_received: boolean; received_date?: string | null; supplier_tax_paid?: SupplierTaxPaid; evidence_note?: string },
  ) => put<ItcEntry>(`${c(cl)}/itc/${id}/evidence`, b),
  itcConfirm: (cl: string, id: string, reason: string) => post<ItcEntry>(`${c(cl)}/itc/${id}/confirm`, { reason }),
  itcEvents: (cl: string, id: string) => get<ItcEvent[]>(`${c(cl)}/itc/${id}/events`),
  itcTagBlocked: (cl: string, id: string, category_key: string, note: string) =>
    post<ItcEntry>(`${c(cl)}/itc/${id}/tag-blocked`, { category_key, note }),
  exposure180: (cl: string, registrationId: string, asOn: string) =>
    get<Exposure>(`${c(cl)}/itc/exposure-180`, { registration_id: registrationId, as_on: asOn }),
  createReversals: (cl: string, registrationId: string, asOn: string, ids?: string[]) =>
    post<{ created: { reversal_id: string; itc_entry_id: string; voucher_id: string }[] }>(`${c(cl)}/itc/reversals`, {
      registration_id: registrationId,
      as_on: asOn,
      itc_entry_ids: ids,
    }),
  listReversals: (cl: string, status?: string) => get<ItcReversal[]>(`${c(cl)}/itc/reversals`, { status }),
  reclaim: (cl: string, id: string, asOn: string) => post<{ reclaim_voucher_id: string }>(`${c(cl)}/itc/reversals/${id}/reclaim`, { as_on: asOn }),
  registerTie: (cl: string, registrationId: string, asOn: string) =>
    get<RegisterTie>(`${c(cl)}/itc/register-tie`, { registration_id: registrationId, as_on: asOn }),
  // 2B
  import2b: (cl: string, file: File, registrationId: string, kind: 'gstr2b' | 'ims', period: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('registration_id', registrationId)
    form.append('kind', kind)
    form.append('period', period)
    return request<{ import_id: string; documents: number; period: string; generated_on: string | null; totals: Record<string, Amount> }>(
      'POST',
      `${c(cl)}/2b/import`,
      { form, write: true },
    )
  },
  list2bImports: (cl: string, registrationId: string) => get<Import2b[]>(`${c(cl)}/2b/imports`, { registration_id: registrationId }),
  list2bDocuments: (importId: string) => get<Doc2b[]>(`/gst/2b/imports/${importId}/documents`),
  reconciliation: (cl: string, registrationId: string, period: string) =>
    get<Recon>(`${c(cl)}/2b/reconciliation`, { registration_id: registrationId, period }),
  createLink: (cl: string, b: { document_id: string; voucher_id: string; link_kind: 'manual' | 'accepted_difference'; note: string }) =>
    post<{ link_id: string }>(`${c(cl)}/2b/links`, b),
  deleteLink: (cl: string, id: string) => request<void>('DELETE', `${c(cl)}/2b/links/${id}`, { write: true }),
  apply2b: (cl: string, registrationId: string, period: string) =>
    post<{ updated: { itc_entry_id: string; from_status: string; to_status: string }[] }>(`${c(cl)}/2b/apply`, {}, { registration_id: registrationId, period }),
  // returns
  gstr1: (cl: string, q: ReturnQuery) => get<Working<AnyTables>>(`${c(cl)}/gstr1`, rq(q)),
  gstr3b: (cl: string, q: ReturnQuery) => get<Working<AnyTables>>(`${c(cl)}/gstr3b`, rq(q)),
  tieOut: (cl: string, q: ReturnQuery) => get<TieOut>(`${c(cl)}/tie-out`, rq(q)),
  composition: (cl: string, registrationId: string, periodStart: string) =>
    get<Record<string, unknown>>(`${c(cl)}/composition`, { registration_id: registrationId, period_start: periodStart }),
  saveWorking: (cl: string, b: { registration_id: string; return_type: string; period_start: string; period_kind: string }) =>
    post<{ working_id: string; version: number }>(`${c(cl)}/workings`, b),
  finaliseWorking: (id: string) => post<{ ok: boolean }>(`/gst/workings/${id}/finalise`),
  listWorkings: (cl: string, registrationId: string, returnType?: string) =>
    get<WorkingRow[]>(`${c(cl)}/workings`, { registration_id: registrationId, return_type: returnType }),
  // file downloads (opened by the browser; the server sets X-Rule-Status)
  workingExportUrl: (id: string) => url(`/gst/workings/${id}/export.xlsx`),
  returnExportUrl: (cl: string, kind: 'gstr1' | 'gstr3b' | 'tie-out', ext: 'xlsx' | 'json', q: ReturnQuery) =>
    url(`${c(cl)}/${kind}/export.${ext}`, rq(q)),
}
