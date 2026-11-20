// Pure helpers for the Documents & AI screens. No accounting maths: statuses and findings come from the server,
// these only sort, label and shape what the server sent.
import type { Acknowledge, DocFinding, ExPayload, LlmCall, QueueHistory } from '../api/ai'
import type { GroupNode } from '../types'

export const DOC_TYPES: { value: string; label: string }[] = [
  { value: 'purchase_invoice', label: 'Purchase invoice' },
  { value: 'sales_invoice', label: 'Sales invoice' },
  { value: 'bank_statement', label: 'Bank statement' },
  { value: 'tally_xml', label: 'Tally XML' },
]
export const QUEUE_STATUSES = ['pending', 'in_review', 'accepted', 'rejected'] as const
export const DATA_CLASSES: { value: string; label: string }[] = [
  { value: 'synthetic', label: 'Synthetic (test data)' },
  { value: 'anonymised', label: 'Anonymised' },
  { value: 'real_acknowledged', label: 'Real client data (acknowledged)' },
]

export function docTypeLabel(value: string): string {
  return DOC_TYPES.find((d) => d.value === value)?.label ?? value
}
export function statusLabel(status: string): string {
  const t = status.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** File size for display (not money). */
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** error and review findings block acceptance (BLOCKING in engine/doc_types.py); warnings need an acknowledgement; info is shown. */
export function isBlocking(f: Pick<DocFinding, 'severity'>): boolean {
  return f.severity === 'error' || f.severity === 'review'
}
export function splitDocFindings(findings: DocFinding[] | undefined | null) {
  const list = findings ?? []
  return {
    blocking: list.filter(isBlocking),
    warnings: list.filter((f) => f.severity === 'warning'),
    info: list.filter((f) => f.severity === 'info'),
  }
}
export function hasBlocking(findings: DocFinding[] | undefined | null): boolean {
  return (findings ?? []).some(isBlocking)
}
export function findingKey(f: Pick<DocFinding, 'rule_id' | 'field_path'>): string {
  return `${f.rule_id}|${f.field_path ?? ''}`
}
/** Warnings not yet acknowledged by the person (acknowledged = set of findingKey). */
export function unacknowledgedWarnings(findings: DocFinding[] | undefined | null, acknowledged: ReadonlySet<string>): DocFinding[] {
  return (findings ?? []).filter((f) => f.severity === 'warning' && !acknowledged.has(findingKey(f)))
}
export function acknowledgements(findings: DocFinding[] | undefined | null, acknowledged: ReadonlySet<string>): Acknowledge[] {
  return (findings ?? []).filter((f) => f.severity === 'warning' && acknowledged.has(findingKey(f))).map((f) => ({ rule_id: f.rule_id, field_path: f.field_path ?? null }))
}
/** Accept is allowed only when the server shows no blocking finding and every warning is acknowledged. */
export function canAccept(findings: DocFinding[] | undefined | null, acknowledged: ReadonlySet<string>, status: string): boolean {
  if (status === 'accepted' || status === 'rejected') return false
  return !hasBlocking(findings) && unacknowledgedWarnings(findings, acknowledged).length === 0
}
export function findingsAt(findings: DocFinding[] | undefined | null, path: string): DocFinding[] {
  return (findings ?? []).filter((f) => f.field_path === path)
}
export function severityRank(f: Pick<DocFinding, 'severity'>): number {
  return { error: 0, review: 1, warning: 2, info: 3 }[f.severity] ?? 4
}
export function sortFindings(findings: DocFinding[]): DocFinding[] {
  return [...findings].sort((a, b) => severityRank(a) - severityRank(b) || a.rule_id.localeCompare(b.rule_id))
}
/** Group findings by rule id for the extraction screen. */
export function groupByRule(findings: DocFinding[]): { rule_id: string; items: DocFinding[] }[] {
  const map = new Map<string, DocFinding[]>()
  for (const f of sortFindings(findings)) map.set(f.rule_id, [...(map.get(f.rule_id) ?? []), f])
  return [...map.entries()].map(([rule_id, items]) => ({ rule_id, items }))
}

// ---- editable payload fields ----
export interface FieldRow {
  path: string
  label: string
  value: string
  /** a boxed extraction field ({value, page, ...}) or a plain value (Tally proposal) */
  boxed: boolean
}
const SKIP_KEYS = new Set(['notes', 'source', 'guid', 'total_display', 'tally_voucher_type'])

export function labelOf(path: string): string {
  const m = /^lines\[(\d+)\]\.(.+)$/.exec(path)
  const base = (m ? m[2] : path.replace(/^totals\./, '')).replace(/_/g, ' ')
  const text = base.charAt(0).toUpperCase() + base.slice(1)
  if (m) return `Line ${Number(m[1]) + 1} ${text.toLowerCase()}`
  return path.startsWith('totals.') ? text : text
}
function isBoxed(v: unknown): v is { value: string | null } {
  return !!v && typeof v === 'object' && !Array.isArray(v) && 'value' in (v as object)
}
function leaf(path: string, v: unknown, out: FieldRow[]) {
  if (isBoxed(v)) out.push({ path, label: labelOf(path), value: v.value ?? '', boxed: true })
  else if (v === null || typeof v === 'string' || typeof v === 'number') out.push({ path, label: labelOf(path), value: v === null ? '' : String(v), boxed: false })
}
/** Every editable field of an extraction payload or a Tally proposal, in screen order. Paths follow the engine: lines[0].taxable_value. */
export function flattenPayload(payload: ExPayload | null | undefined): FieldRow[] {
  const out: FieldRow[] = []
  if (!payload) return out
  for (const [key, v] of Object.entries(payload)) {
    if (SKIP_KEYS.has(key) || key === 'currency') continue
    if (key === 'lines' && Array.isArray(v)) {
      v.forEach((line, i) => {
        if (line && typeof line === 'object') for (const [k, lv] of Object.entries(line as object)) leaf(`lines[${i}].${k}`, lv, out)
      })
    } else if (key === 'totals' && v && typeof v === 'object') {
      for (const [k, tv] of Object.entries(v as object)) leaf(`totals.${k}`, tv, out)
    } else leaf(key, v, out)
  }
  return out
}
/** Fields whose value differs from the original: only these are sent as edits. */
export function changedEdits(original: FieldRow[], edited: Record<string, string>): { field_path: string; value: string | null }[] {
  const base = new Map(original.map((r) => [r.path, r.value]))
  return Object.entries(edited)
    .filter(([path, v]) => (base.get(path) ?? '') !== v)
    .map(([field_path, v]) => ({ field_path, value: v.trim() === '' ? null : v.trim() }))
}

// ---- the model-call log ----
/** Calls and tokens used, counted from the call log. The server exposes no limit figure, so none is shown. */
export function usageFromCalls(calls: LlmCall[]): { calls: number; ok: number; failed: number; tokens_in: number; tokens_out: number } {
  let ok = 0
  let failed = 0
  let tin = 0
  let tout = 0
  for (const c of calls) {
    if (c.status === 'ok') ok += 1
    else failed += 1
    tin += c.tokens_in ?? 0
    tout += c.tokens_out ?? 0
  }
  return { calls: calls.length, ok, failed, tokens_in: tin, tokens_out: tout }
}
export function maskingSummary(report: LlmCall['masking_report']): string {
  const counts = report?.counts ?? {}
  const parts = Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${k}`)
  return parts.length ? parts.join(', ') : 'nothing masked'
}

/** A voucher detail route for a linked voucher. */
export function voucherHref(id: string): string {
  return `/vouchers/${id}`
}

/** Today minus nothing: first and last day of an Indian financial year starting in April of `startYear`. */
export function fyRange(startYear: number): { from: string; to: string } {
  return { from: `${startYear}-04-01`, to: `${startYear + 1}-03-31` }
}

// ---- manual extraction form (the accountant types what the document says) ----
export const HEADER_FIELDS: [string, string][] = [
  ['document_kind', 'Document kind (e.g. tax_invoice, credit_note)'],
  ['supplier_name', 'Supplier name'],
  ['supplier_gstin', 'Supplier GSTIN'],
  ['buyer_name', 'Buyer name'],
  ['buyer_gstin', 'Buyer GSTIN'],
  ['invoice_no', 'Invoice no'],
  ['invoice_date', 'Invoice date (YYYY-MM-DD)'],
  ['place_of_supply', 'Place of supply'],
  ['original_invoice_no', 'Original invoice no (credit / debit notes)'],
]
export const LINE_FIELDS: [string, string][] = [
  ['description', 'Description'],
  ['hsn_sac', 'HSN/SAC'],
  ['quantity', 'Qty'],
  ['unit', 'Unit'],
  ['unit_rate', 'Rate'],
  ['discount', 'Discount'],
  ['taxable_value', 'Taxable value'],
  ['gst_rate', 'GST %'],
  ['cgst', 'CGST'],
  ['sgst', 'SGST'],
  ['igst', 'IGST'],
  ['cess', 'Cess'],
]
export const TOTAL_FIELDS: [string, string][] = [
  ['taxable_total', 'Taxable total'],
  ['cgst_total', 'CGST total'],
  ['sgst_total', 'SGST total'],
  ['igst_total', 'IGST total'],
  ['cess_total', 'Cess total'],
  ['round_off', 'Round off'],
  ['grand_total', 'Grand total'],
]
function boxed(v: string | undefined) {
  const t = (v ?? '').trim()
  return { value: t === '' ? null : t, page: null, bbox: null, confidence: null }
}
/** The extraction payload exactly as typed (strings as printed); the server checks and recomputes everything. */
export function buildInvoicePayload(header: Record<string, string>, lines: Record<string, string>[], totals: Record<string, string>): ExPayload {
  const pick = (names: [string, string][], src: Record<string, string>) => Object.fromEntries(names.map(([k]) => [k, boxed(src[k])]))
  return {
    ...pick(HEADER_FIELDS, header),
    lines: lines.map((l) => pick(LINE_FIELDS, l)),
    totals: pick(TOTAL_FIELDS, totals),
    currency: 'INR',
    notes: [],
  }
}

// ---- approval queue: credit / debit note pseudo fields ----
/** Edit paths that are not in the extraction: the server keeps them in `_note` (engine NOTE_REASONS; the date is YYYY-MM-DD). */
export const NOTE_REASONS = ['sales_return', 'post_sale_discount', 'deficiency_in_services', 'correction_in_invoice', 'change_in_pos', 'provisional_assessment', 'others']
const NOTE_PATHS: [string, string][] = [
  ['note_reason', `Credit / debit note reason (${NOTE_REASONS.join(', ')})`],
  ['original_invoice_date', 'Original invoice date (YYYY-MM-DD)'],
]
/** The two editable rows of a credit / debit note invoice item (shown for notes, or when a finding points at them). */
export function noteFieldRows(payload: ExPayload | null | undefined, kind: string, findings: DocFinding[] | undefined | null): FieldRow[] {
  if (kind !== 'invoice' || !payload) return []
  const docKind = (payload.document_kind as { value?: string | null } | undefined)?.value ?? ''
  const pointed = (findings ?? []).some((f) => NOTE_PATHS.some(([p]) => p === f.field_path))
  if (!/credit_note|debit_note/.test(docKind) && !pointed) return []
  const note = (payload._note && typeof payload._note === 'object' ? payload._note : {}) as Record<string, unknown>
  return NOTE_PATHS.map(([path, label]) => ({ path, label, value: typeof note[path] === 'string' ? (note[path] as string) : '', boxed: false }))
}

/** Findings carried in the details of a queue_blocked error: blocking ones (`findings`) or the warnings still to acknowledge. */
export function blockedFindings(details: unknown): DocFinding[] {
  const d = (details && typeof details === 'object' ? details : {}) as { findings?: DocFinding[]; unacknowledged?: DocFinding[] }
  return [...(d.findings ?? []), ...(d.unacknowledged ?? [])]
}

export function historyLine(h: QueueHistory): string {
  return [h.at ? h.at.slice(0, 19).replace('T', ' ') : '', h.actor, statusLabel(h.action.replace(/^queue_item_/, ''))].filter(Boolean).join(' ')
}

// ---- Tally group picker ----
export interface GroupChoice {
  id: string
  code: string
  label: string
}
/** All groups of the tree in display order, children labelled with their parent: "Current Assets > Bank Accounts". */
export function flattenGroups(nodes: GroupNode[], parents: string[] = []): GroupChoice[] {
  return nodes.flatMap((n) => [{ id: n.id, code: n.code, label: [...parents, n.name].join(' > ') }, ...flattenGroups(n.children, [...parents, n.name])])
}
