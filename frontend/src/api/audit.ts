// Typed client for docs/PHASE8_API_CONTRACT.md (package UI8). Same conventions as ./ai.ts and ./final.ts:
// amounts are decimal strings, reads send no actor, writes send X-User. Nothing is calculated here:
// every finding, count, sample and status comes from the server.
// Checked against backend/app/api/audit_{checks,holidays,papers,related,sampling,summary,tax}.py and their schemas.
// All of them except the catalogue (/audit/checks, /audit/rules) are client scoped: /clients/{id}/audit/...

import { getUser } from '../api'
import { mapApiError } from '../lib/apiError'
import { downloadFile, url, type Query } from './final'

export type { Query }
export { downloadFile }

export type AuditSeverity = 'error' | 'review' | 'warning' | 'info'
type Ok = { ok: boolean }

// ---- catalogue and rules ----
export interface CheckInfo {
  check_id: string
  title: string
  description: string
  rule_text: string
  severity: AuditSeverity
  category: string
  evidence_query: string
  rule_key: string | null
  active: boolean
}
export interface LimitRule {
  rule_key: string
  law: string
  section_ref: string
  amount: string
  breach_when: string
  disallow_percent: string | null
  effective_from: string
  effective_to: string | null
  source_reference: string
  verification_status: string
  notes: string | null
}

// ---- runs ----
export interface RunParams {
  duplicate_window_days?: number
  doc_required_types?: string[]
  doc_min_amount?: string
  round_unit?: string
  round_min_amount?: string
  late_posting_days?: number
  variance_min_amount?: string
  variance_band_percent?: string
}
export interface RunBody {
  financial_year_id: string
  from_date?: string
  to_date?: string
  check_ids?: string[]
  params?: RunParams
}
export interface CheckSummary {
  findings?: number
  population?: number
  notes?: string[]
  error?: string
}
export interface RunSummary {
  by_check?: Record<string, CheckSummary>
  by_severity?: Record<string, number>
  [k: string]: unknown
}
export interface RunCreated {
  id: string
  status: string
  finding_count: number
  summary: RunSummary
  error?: string | null
}
export interface RunRow {
  id: string
  financial_year_id: string
  from_date: string
  to_date: string
  check_ids: string[]
  finding_count: number
  status: string
  created_by: string
  created_at: string
}
export interface RunDetail extends RunRow {
  params: Record<string, unknown>
  rules_used: Record<string, unknown>[]
  engine_version: string
  summary: RunSummary
  error_message?: string | null
}
export interface AuditFinding {
  id: string
  run_id: string
  check_id: string
  finding_key: string
  severity: AuditSeverity
  subject_kind: string
  subject_id: string | null
  subject_ref: string
  finding_date: string | null
  amount: string | null
  disallowance_amount: string | null
  message: string
  evidence: Record<string, unknown>
  rule_status?: string | null
}
export interface ReportCheck {
  check_id: string
  title: string
  severity: AuditSeverity | null
  population: number
  findings: AuditFinding[]
  notes: string[]
  error?: string
}
export interface RunReport {
  run: Record<string, unknown> & { id: string; from_date: string; to_date: string }
  rules_pending: { rule_key: string; law: string; section_ref: string; line: string }[]
  checks: ReportCheck[]
  totals: { findings: number; by_severity: Record<string, number>; disallowance_amount: string }
}

// ---- holidays, related parties ----
export interface Holiday {
  id: string
  holiday_date: string
  name: string
  kind: string
  note: string | null
}
export interface HolidayBody {
  holiday_date: string
  name: string
  kind?: string
  note?: string
}
export interface RelatedFlag {
  id: string
  ledger_id: string
  ledger_name: string
  relationship: string
  active: boolean
  flagged_by: string
  flagged_at: string
  note: string | null
}

// ---- working papers and sampling ----
export type PaperStatus = 'open' | 'in_review' | 'signed_off' | string
export interface PaperRow {
  id: string
  run_id: string
  check_id: string
  status: PaperStatus
  population_count: number
  population_digest: string | null
  population_amount: string | null
  sample_method: string
  created_by: string
  created_at: string
  signed_off_by: string | null
  signed_off_at: string | null
  item_count: number
  open_count: number
}
export interface PaperCreated {
  id: string
  status: string
  population_count: number
  population_digest: string | null
  items: number
}
export interface Sample {
  method: string
  seed: number | null
  params: Record<string, unknown>
  ids: string[]
}
export interface PaperItem {
  id: string
  status: string
  reviewer_note: string | null
  decided_by: string | null
  decided_at: string | null
  finding: {
    id: string
    finding_key: string
    severity: AuditSeverity
    subject_kind: string
    subject_ref: string
    finding_date: string | null
    amount: string | null
    disallowance_amount: string | null
    message: string
    evidence: Record<string, unknown>
  }
}
export interface PaperNote {
  id: string
  note: string
  created_by: string
  created_at: string
}
export interface PaperDetail extends Omit<PaperRow, 'item_count' | 'open_count'> {
  financial_year_id: string
  sample: Sample
  conclusion: string | null
  items: PaperItem[]
  notes: PaperNote[]
}
export interface SampleBody {
  method: 'random' | 'systematic' | 'value'
  seed: number
  size?: number
  threshold?: string
  rest_size?: number
}
export interface SampleStored extends Sample {
  population_count: number
  population_digest: string | null
}

// ---- tax audit form ----
export interface FormClause {
  clause_no: string
  title: string
  derivability: string
  data_source?: string | null
  verification_status: string
  derivable_here?: boolean
}
export interface FormInfo {
  form_key: string
  title: string
  law: string
  section_ref: string
  verification_status: string
  note: string | null
  clauses: FormClause[]
}
export interface FormEntry {
  clause_no: string
  field_key: string
  /** a text value (count, 2-decimal amount, status) or, for derived clauses, a list of finding ids */
  value: unknown
  origin: 'derived' | 'manual' | string
  run_id: string | null
  entered_by: string
  entered_at: string
}
export interface FormSet {
  id: string
  financial_year_id: string
  form_key: string
  status: 'draft' | 'finalised' | string
  form: { title: string; law: string; section_ref: string; verification_status: string }
  clauses: FormClause[]
  entries: FormEntry[]
  created_by: string
  finalised_by: string | null
  finalised_at: string | null
}
export interface DeriveResult {
  entries: { clause_no: string; field_key: string; value: unknown; origin: string; run_id: string }[]
  skipped: { clause_no: string; reason: string }[]
  kept_manual: { clause_no: string; field_key: string }[]
}

// ---- AI summary ----
export interface SummaryResult {
  status: 'ok' | 'blocked' | 'error' | 'rejected' | string
  message?: string | null
  reason?: string | null
  problems?: string[]
  is_suggestion: boolean
  llm_call_id: string | null
  id?: string
  summary_text?: string
}
export interface StoredSummary {
  id: string
  run_id: string
  paper_id: string | null
  llm_call_id: string
  summary_text: string
  is_suggestion: boolean
  created_by: string
  created_at: string
}

// ---- transport ----
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
const c = (id: string) => `/clients/${id}/audit`

/** Paths of the Excel files (for downloadFile; the server builds the workbook). */
export const reportXlsxPath = (cl: string, runId: string) => `${c(cl)}/runs/${runId}/report`
export const formXlsxPath = (cl: string, setId: string) => `${c(cl)}/forms/sets/${setId}`

export const auditApi = {
  listChecks: () => get<CheckInfo[]>('/audit/checks'),
  listRules: () => get<LimitRule[]>('/audit/rules'),
  // runs
  createRun: (cl: string, b: RunBody) => post<RunCreated>(`${c(cl)}/runs`, b),
  listRuns: (cl: string) => get<RunRow[]>(`${c(cl)}/runs`),
  getRun: (cl: string, id: string) => get<RunDetail>(`${c(cl)}/runs/${id}`),
  listFindings: (cl: string, id: string, q: { check_id?: string; severity?: string; subject_id?: string } = {}) =>
    get<AuditFinding[]>(`${c(cl)}/runs/${id}/findings`, q),
  getReport: (cl: string, id: string) => get<RunReport>(`${c(cl)}/runs/${id}/report`),
  // holidays
  listHolidays: (cl: string, year?: number) => get<Holiday[]>(`${c(cl)}/holidays`, { year }),
  addHoliday: (cl: string, b: HolidayBody) => post<{ id: string }>(`${c(cl)}/holidays`, b),
  deleteHoliday: (cl: string, id: string) => del<Ok>(`${c(cl)}/holidays/${id}`),
  // related parties
  listRelated: (cl: string, active?: boolean) => get<RelatedFlag[]>(`${c(cl)}/related-parties`, { active }),
  flagRelated: (cl: string, b: { ledger_id: string; relationship: string; note?: string }) => post<{ id: string }>(`${c(cl)}/related-parties`, b),
  updateRelated: (cl: string, id: string, b: { relationship?: string; active?: boolean; note?: string }) => put<Ok>(`${c(cl)}/related-parties/${id}`, b),
  // working papers
  createPaper: (cl: string, b: { run_id: string; check_id: string }) => post<PaperCreated>(`${c(cl)}/papers`, b),
  listPapers: (cl: string, q: { run_id?: string; check_id?: string; status?: string } = {}) => get<PaperRow[]>(`${c(cl)}/papers`, q),
  getPaper: (cl: string, id: string) => get<PaperDetail>(`${c(cl)}/papers/${id}`),
  decideItem: (cl: string, paper: string, item: string, b: { status: 'cleared' | 'confirmed'; reviewer_note: string }) =>
    put<Ok>(`${c(cl)}/papers/${paper}/items/${item}`, b),
  addNote: (cl: string, paper: string, note: string) => post<{ id: string }>(`${c(cl)}/papers/${paper}/notes`, { note }),
  sendToReview: (cl: string, paper: string) => post<Ok>(`${c(cl)}/papers/${paper}/review`),
  reopenPaper: (cl: string, paper: string) => post<Ok>(`${c(cl)}/papers/${paper}/reopen`),
  signOff: (cl: string, paper: string, conclusion: string) =>
    post<{ ok: boolean; signed_off_at: string }>(`${c(cl)}/papers/${paper}/sign-off`, { conclusion }),
  sample: (cl: string, paper: string, b: SampleBody) => post<SampleStored>(`${c(cl)}/papers/${paper}/sample`, b),
  // tax audit form
  getForm: (cl: string, financial_year_id: string) => get<FormInfo>(`${c(cl)}/forms`, { financial_year_id }),
  createFormSet: (cl: string, financial_year_id: string) => post<{ id: string; form_key: string; status: string }>(`${c(cl)}/forms/sets`, { financial_year_id }),
  getFormSet: (cl: string, id: string) => get<FormSet>(`${c(cl)}/forms/sets/${id}`),
  deriveForm: (cl: string, id: string, b: { run_id: string; clause_nos?: string[] }) => post<DeriveResult>(`${c(cl)}/forms/sets/${id}/derive`, b),
  enterForm: (cl: string, id: string, b: { clause_no: string; field_key: string; value: string }) => put<unknown>(`${c(cl)}/forms/sets/${id}/entries`, b),
  finaliseForm: (cl: string, id: string) => post<Ok>(`${c(cl)}/forms/sets/${id}/finalise`),
  // AI summary (suggestion only)
  summarise: (cl: string, run: string, b: { paper_id?: string; check_id?: string }) => post<SummaryResult>(`${c(cl)}/runs/${run}/summary`, b),
  listSummaries: (cl: string, run: string) => get<StoredSummary[]>(`${c(cl)}/runs/${run}/summaries`),
}
