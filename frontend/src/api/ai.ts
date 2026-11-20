// Typed client for docs/PHASE7_API_CONTRACT.md (package UI7). Same conventions as ./gst.ts and ./final.ts:
// amounts are decimal strings, reads send no actor, writes send X-User. Nothing is calculated here:
// every finding, status and recomputed value comes from the server.
// Package F routes (approval queue, narration) were not committed when this was written: they follow the contract
// (docs/PHASE7_API_CONTRACT.md, sections Approval queue and Narration suggestions) and are marked UNVERIFIED below.

import { getUser } from '../api'
import { mapApiError } from '../lib/apiError'
import { url, type Query } from './final'

export type { Query }

export type FindingSeverity = 'error' | 'review' | 'warning' | 'info'
export interface DocFinding {
  rule_id: string
  severity: FindingSeverity
  message: string
  field_path?: string | null
  printed?: string | null
  computed?: string | null
}
type Ok = { ok: boolean }

// ---- documents ----
export interface DocumentCreated {
  id: string
  sha256: string
  size_bytes: number
  content_type: string
  doc_type: string
  status: string
  page_count: number | null
}
export interface DocumentRow {
  id: string
  doc_type: string
  original_filename: string
  size_bytes: number
  status: string
  uploaded_by: string
  uploaded_at: string
  linked_voucher_ids: string[]
}
export interface TextSummary {
  page_no: number
  method: string
  engine_version: string
  mean_confidence: string | null
  char_count: number
}
export interface ExtractionVersion {
  id: string
  version: number
  source: string
  status: string
  created_at: string
  superseded: boolean
}
export interface DocumentDetail extends DocumentRow {
  content_type: string
  sha256: string
  page_count: number | null
  status_note: string | null
  financial_year_id: string | null
  texts: TextSummary[]
  extractions: ExtractionVersion[]
  queue_item_id: string | null
}
export interface PageText {
  page_no: number
  method: string
  text: string
  blocks: Record<string, unknown>[] | null
}
export type ReadMethod = 'auto' | 'pdf_text' | 'tesseract' | 'paddleocr'
export interface ReadTextResult {
  pages: { page_no: number; method: string; char_count: number; mean_confidence: string | null }[]
}

// ---- AI settings and call log ----
export interface AiSettings {
  llm_enabled: boolean
  data_class: string
  enabled_by: string | null
  enabled_at: string | null
  note: string | null
  model: string | null
  model_configured: boolean
  key_configured: boolean
}
export interface LlmCall {
  id: string
  purpose: string
  provider: string
  model: string | null
  prompt_version: string
  status: string
  masking_applied: boolean
  masking_report: { data_class?: string; counts?: Record<string, number> } | null
  tokens_in: number | null
  tokens_out: number | null
  latency_ms: number | null
  document_id: string | null
  created_by: string
  created_at: string
}
export interface LlmCallDetail extends LlmCall {
  prompt_masked: string | null
  response_raw: string | null
  error_message: string | null
}

// ---- extraction ----
export type ExPayload = Record<string, unknown>
export interface ExtractResult {
  status: 'ok' | 'blocked' | 'invalid' | 'error'
  extraction_id: string | null
  llm_call_id: string | null
  findings: DocFinding[]
  message: string
}
export interface ExtractionOut {
  id: string
  document_id: string
  version: number
  source: string
  status: string
  schema_version: string
  payload: ExPayload
  invalid_reason: string | null
  llm_call_id: string | null
  superseded: boolean
}
export interface CheckResult {
  findings: DocFinding[]
  recomputed: Record<string, unknown>
  direction: string | null
  place_of_supply: string | null
}
export interface BuildDraftResult {
  queue_item_id: string
  status: string
  findings: DocFinding[]
  draft_voucher_id: string | null
}

// ---- mappings ----
export interface PartyMapping {
  id: string
  match_kind: 'gstin' | 'name'
  match_key: string
  party_ledger_id: string
  party_ledger_name: string
  use_count: number
}
export interface PartyMappingBody {
  match_kind: 'gstin' | 'name'
  match_key: string
  party_ledger_id: string
  replace?: boolean
}
export interface LineMapping {
  id: string
  match_kind: 'hsn_sac' | 'description'
  match_key: string
  party_ledger_id: string | null
  party_ledger_name: string | null
  ledger_id: string
  ledger_name: string
  item_id: string | null
  item_name: string | null
  use_count: number
}
export interface LineMappingBody {
  match_kind: 'hsn_sac' | 'description'
  match_key: string
  ledger_id: string
  party_ledger_id?: string | null
  item_id?: string | null
  replace?: boolean
}

// ---- Tally ----
export interface TallySkipped {
  type: string
  date: string
  number: string | null
  reason_rule: string
  reason: string
}
export interface TallyReport {
  counts: Record<string, number>
  groups: { name: string; parent: string | null; suggested_group_code: string | null; decision: string }[]
  ledgers: {
    name: string
    parent_group: string | null
    suggested_group_code: string | null
    existing_ledger_id: string | null
    decision: string
    reason: string | null
    opening_balance_reported: string | null
  }[]
  stock_items: { name: string; unit: string | null; hsn: string | null; existing_item_id: string | null; decision: string; reason: string | null }[]
  vouchers: { by_type: Record<string, number>; drafted_later: number; skipped: TallySkipped[] }
  opening_balances_not_applied?: boolean
}
export interface TallyImportCreated {
  import_id: string
  company_name: string | null
  report: TallyReport
}
export interface TallyImportRow {
  import_id: string
  status: string
  company_name: string | null
  document_id: string
  created_by: string
  created_at: string
  counts: Record<string, number> | null
  report: TallyReport | null
}
export interface TallyMaster {
  id: string
  kind: string
  source_name: string
  source_parent: string | null
  decision: string
  reason: string | null
  target_group_id: string | null
  target_ledger_id: string | null
  target_item_id: string | null
}
export interface MasterDecisionBody {
  decision: 'confirmed' | 'create' | 'skip'
  target_group_id?: string | null
  target_ledger_id?: string | null
  target_item_id?: string | null
  accept_nature_change?: boolean
}
export interface QueueVouchersResult {
  queued: number
  drafted: number
  needs_review: number
  skipped: TallySkipped[]
}
export interface TallyExportBody {
  kind: 'masters' | 'vouchers' | 'both'
  from_date?: string | null
  to_date?: string | null
  financial_year_id?: string | null
  posted_only?: boolean
}
export interface TallyExportResult {
  export_id: string
  document_id: string
  master_count: number
  voucher_count: number
  warnings: string[]
}

// ---- approval queue (package F, UNVERIFIED: contract only) ----
export interface QueueRow {
  id: string
  kind: string
  status: string
  document_id: string | null
  document_name: string | null
  summary: { party?: string | null; reference_no?: string | null; date?: string | null; total?: string | null } | null
  blocking_count: number
  warning_count: number
  draft_voucher_id: string | null
  reviewer: string | null
  created_at: string
}
export interface DraftVoucher {
  id: string
  status: string
  voucher_type: string
  voucher_date: string
  reference_no: string | null
  narration: string | null
  lines: { ledger_id?: string; ledger_name?: string; debit?: string; credit?: string; [k: string]: unknown }[]
}
export interface QueueDetail extends QueueRow {
  document: { id: string; content_type: string; page_count: number | null; download_url: string } | null
  original: ExPayload
  current: ExPayload
  findings: DocFinding[]
  draft_voucher: DraftVoucher | null
  acknowledged: { rule_id: string; field_path: string | null }[]
  history: Record<string, unknown>[]
}
export interface FieldEdit {
  field_path: string
  value: string | null
}
export interface QueueEditResult {
  findings: DocFinding[]
  draft_voucher_id: string | null
  status: string
}
export interface Acknowledge {
  rule_id: string
  field_path: string | null
}

// ---- narration (package F, UNVERIFIED: contract only) ----
export interface NarrationSuggestion {
  line_id: string
  suggestion: { id: string; source: 'rule' | 'llm'; ledger_id: string; ledger_name: string; reason: string; confidence: string | null } | null
  ambiguous: { ledger_id: string; ledger_name: string; count: number }[]
  status: 'none' | 'suggested' | 'ambiguous' | 'llm_blocked'
}
export interface NarrationRule {
  id: string
  direction: string
  narration_key: string
  ledger_id: string
  ledger_name: string
  approved_count: number
  is_active: boolean
}

// ---- transport ----
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
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, { body: body ?? {}, write: true })
const put = <T>(path: string, body: unknown) => request<T>('PUT', path, { body, write: true })
const del = <T>(path: string) => request<T>('DELETE', path, { write: true })
const c = (id: string) => `/clients/${id}`

/** The authenticated download as a Blob (the endpoint needs X-User; there is no public URL). */
export async function fetchDocumentBlob(clientId: string, documentId: string): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(url(`${c(clientId)}/documents/${documentId}/download`), { headers: { 'X-User': getUser() } })
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
  return response.blob()
}

/** Save the document under a name. */
export async function saveDocument(clientId: string, documentId: string, filename: string): Promise<void> {
  const blob = await fetchDocumentBlob(clientId, documentId)
  const link = document.createElement('a')
  const href = URL.createObjectURL(blob)
  link.href = href
  link.download = filename
  link.click()
  URL.revokeObjectURL(href)
}

export const aiApi = {
  // documents
  uploadDocument: (cl: string, file: File, doc_type: string, financial_year_id?: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('doc_type', doc_type)
    if (financial_year_id) form.append('financial_year_id', financial_year_id)
    return request<DocumentCreated>('POST', `${c(cl)}/documents`, { form, write: true })
  },
  listDocuments: (cl: string, q: { doc_type?: string; status?: string; q?: string } = {}) => get<DocumentRow[]>(`${c(cl)}/documents`, q),
  getDocument: (cl: string, id: string) => get<DocumentDetail>(`${c(cl)}/documents/${id}`),
  pageText: (cl: string, id: string, page: number, method?: string) => get<PageText>(`${c(cl)}/documents/${id}/pages/${page}/text`, { method }),
  readText: (cl: string, id: string, method: ReadMethod = 'auto') => post<ReadTextResult>(`${c(cl)}/documents/${id}/read-text`, { method }),
  linkVoucher: (cl: string, id: string, voucher_id: string) => post<{ id: string }>(`${c(cl)}/documents/${id}/links`, { voucher_id, link_kind: 'supporting' }),
  unlinkVoucher: (cl: string, id: string, voucher_id: string) => del<Ok>(`${c(cl)}/documents/${id}/links/${voucher_id}`),
  // AI settings, call log
  getSettings: (cl: string) => get<AiSettings>(`${c(cl)}/ai/settings`),
  putSettings: (cl: string, b: { llm_enabled: boolean; data_class: string; note: string | null }) => put<Ok>(`${c(cl)}/ai/settings`, b),
  listCalls: (cl: string, q: { purpose?: string; status?: string; document_id?: string; limit?: number } = {}) => get<LlmCall[]>(`${c(cl)}/ai/calls`, q),
  getCall: (cl: string, id: string) => get<LlmCallDetail>(`${c(cl)}/ai/calls/${id}`),
  // extraction
  extract: (cl: string, id: string, b: { mode: 'llm' | 'manual'; payload?: ExPayload }) => post<ExtractResult>(`${c(cl)}/documents/${id}/extract`, b),
  listExtractions: (cl: string, id: string) => get<ExtractionVersion[]>(`${c(cl)}/documents/${id}/extractions`),
  getExtraction: (cl: string, id: string) => get<ExtractionOut>(`${c(cl)}/extractions/${id}`),
  checkExtraction: (cl: string, id: string) => post<CheckResult>(`${c(cl)}/extractions/${id}/check`),
  buildDraft: (cl: string, id: string, extraction_id?: string) => post<BuildDraftResult>(`${c(cl)}/documents/${id}/build-draft`, extraction_id ? { extraction_id } : {}),
  // mappings
  listPartyMappings: (cl: string, q?: string) => get<PartyMapping[]>(`${c(cl)}/mappings/parties`, { q }),
  putPartyMapping: (cl: string, b: PartyMappingBody) => put<{ id: string }>(`${c(cl)}/mappings/parties`, b),
  deletePartyMapping: (cl: string, id: string) => del<Ok>(`${c(cl)}/mappings/parties/${id}`),
  listLineMappings: (cl: string, q?: string) => get<LineMapping[]>(`${c(cl)}/mappings/lines`, { q }),
  putLineMapping: (cl: string, b: LineMappingBody) => put<{ id: string }>(`${c(cl)}/mappings/lines`, b),
  deleteLineMapping: (cl: string, id: string) => del<Ok>(`${c(cl)}/mappings/lines/${id}`),
  // Tally
  createImport: (cl: string, document_id: string) => post<TallyImportCreated>(`${c(cl)}/tally/imports`, { document_id }),
  listImports: (cl: string) => get<TallyImportRow[]>(`${c(cl)}/tally/imports`),
  getImport: (cl: string, id: string) => get<TallyImportRow>(`${c(cl)}/tally/imports/${id}`),
  listMasters: (cl: string, q: { kind?: string; decision?: string } = {}) => get<TallyMaster[]>(`${c(cl)}/tally/masters`, q),
  decideMaster: (cl: string, id: string, b: MasterDecisionBody) => put<Ok>(`${c(cl)}/tally/masters/${id}`, b),
  confirmExact: (cl: string, importId: string) => post<{ confirmed: number }>(`${c(cl)}/tally/imports/${importId}/confirm-exact-matches`),
  applyMasters: (cl: string, importId: string) => post<{ created: Record<string, number>; skipped: unknown }>(`${c(cl)}/tally/imports/${importId}/apply-masters`),
  queueVouchers: (cl: string, importId: string, financial_year_id?: string) =>
    post<QueueVouchersResult>(`${c(cl)}/tally/imports/${importId}/queue-vouchers`, financial_year_id ? { financial_year_id } : {}),
  exportTally: (cl: string, b: TallyExportBody) => post<TallyExportResult>(`${c(cl)}/tally/export`, b),
  listExports: (cl: string) => get<Record<string, unknown>[]>(`${c(cl)}/tally/exports`),
  // approval queue (UNVERIFIED: package F)
  listQueue: (cl: string, q: { status?: string; kind?: string; has_blocking?: boolean } = {}) => get<QueueRow[]>(`${c(cl)}/queue`, q),
  getQueueItem: (cl: string, id: string) => get<QueueDetail>(`${c(cl)}/queue/${id}`),
  claim: (cl: string, id: string) => post<Ok>(`${c(cl)}/queue/${id}/claim`),
  release: (cl: string, id: string) => post<Ok>(`${c(cl)}/queue/${id}/release`),
  editFields: (cl: string, id: string, edits: FieldEdit[]) => put<QueueEditResult>(`${c(cl)}/queue/${id}/fields`, { edits }),
  accept: (cl: string, id: string, acknowledge: Acknowledge[], learn: boolean) =>
    post<{ ok: boolean; draft_voucher_id: string | null }>(`${c(cl)}/queue/${id}/accept`, { acknowledge, learn }),
  reject: (cl: string, id: string, reason: string) => post<Ok>(`${c(cl)}/queue/${id}/reject`, { reason }),
  acceptClean: (cl: string, ids: string[]) => post<{ accepted: string[]; refused: { id: string; reason: string }[] }>(`${c(cl)}/queue/accept-clean`, { ids }),
  // narration (UNVERIFIED: package F)
  suggestion: (cl: string, lineId: string) => get<NarrationSuggestion>(`${c(cl)}/bank/lines/${lineId}/suggestion`),
  acceptSuggestion: (cl: string, id: string) => post<Ok>(`${c(cl)}/bank/suggestions/${id}/accept`),
  rejectSuggestion: (cl: string, id: string) => post<Ok>(`${c(cl)}/bank/suggestions/${id}/reject`),
  listNarrationRules: (cl: string) => get<NarrationRule[]>(`${c(cl)}/ai/narration-rules`),
  setNarrationRule: (cl: string, id: string, is_active: boolean) => put<Ok>(`${c(cl)}/ai/narration-rules/${id}`, { is_active }),
}
