// Display helpers for the audit screens. No audit maths: counts, findings, samples and statuses are the server's.
import type { AuditFinding, RunParams } from '../api/audit'
import { formatInr } from '../lib/money'

/** Run parameters typed in the form. Blank fields are left out so the server default applies; nothing is guessed. */
export function buildRunParams(f: Record<string, string>): RunParams | undefined {
  const out: RunParams = {}
  const text = (k: keyof RunParams) => (f[k] ?? '').trim()
  for (const k of ['duplicate_window_days', 'late_posting_days'] as const) if (text(k) !== '') out[k] = Number(text(k))
  for (const k of ['doc_min_amount', 'round_unit', 'round_min_amount', 'variance_min_amount', 'variance_band_percent'] as const)
    if (text(k) !== '') out[k] = text(k).replace(/,/g, '')
  if (text('doc_required_types') !== '')
    out.doc_required_types = text('doc_required_types')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  return Object.keys(out).length ? out : undefined
}

/** Which parameter belongs to which check (for the parameter panel). */
export const PARAM_FIELDS: { key: keyof RunParams; label: string; check: string; hint: string }[] = [
  { key: 'duplicate_window_days', label: 'Duplicate window (days)', check: 'A-02', hint: 'default 7' },
  { key: 'doc_required_types', label: 'Voucher types needing a document', check: 'A-03', hint: 'comma separated, e.g. purchase,payment' },
  { key: 'doc_min_amount', label: 'Document needed from amount', check: 'A-03', hint: 'default 0.00' },
  { key: 'round_unit', label: 'Round-amount unit', check: 'A-12', hint: 'default 1,000.00' },
  { key: 'round_min_amount', label: 'Round-amount minimum', check: 'A-12', hint: 'default 10,000.00' },
  { key: 'late_posting_days', label: 'Late posting after (days)', check: 'A-14', hint: 'default 30' },
  { key: 'variance_min_amount', label: 'Variance minimum amount', check: 'A-15', hint: 'default 1,00,000.00' },
  { key: 'variance_band_percent', label: 'Variance band (%)', check: 'A-15', hint: 'default 50.00' },
]

export interface FindingLink {
  label: string
  to: string
}

function ids(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}

/** Links from a finding to the voucher and ledger statement screens, built from what the server stored. */
export function findingLinks(f: Pick<AuditFinding, 'subject_kind' | 'subject_id' | 'evidence'>, from: string, to: string): FindingLink[] {
  const out: FindingLink[] = []
  const seen = new Set<string>()
  const add = (label: string, path: string) => {
    if (!seen.has(path)) {
      seen.add(path)
      out.push({ label, to: path })
    }
  }
  const voucherIds = [...new Set([...(f.subject_kind === 'voucher' && f.subject_id ? [f.subject_id] : []), ...ids(f.evidence?.voucher_ids)])]
  voucherIds.forEach((id, i) => add(voucherIds.length > 1 ? `Voucher ${i + 1}` : 'Voucher', `/vouchers/${id}`))
  const ledgers: string[] = []
  if (f.subject_kind === 'ledger' && f.subject_id) ledgers.push(f.subject_id)
  for (const k of ['ledger_id', 'party_ledger_id'] as const) {
    const v = f.evidence?.[k]
    if (typeof v === 'string') ledgers.push(v)
  }
  if (f.subject_kind === 'party' && f.subject_id) ledgers.push(f.subject_id)
  for (const id of ledgers) add('Ledger statement', `/statement?ledger=${id}&from=${from}&to=${to}`)
  return out
}

const AMOUNT = /^-?\d+\.\d{2}$/
/** One evidence value as text; 2-decimal amount strings in Indian format. */
export function evidenceText(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return AMOUNT.test(v) ? formatInr(v) : v
  if (Array.isArray(v)) return v.map(evidenceText).join(', ')
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${k}: ${evidenceText(x)}`)
      .join('; ')
  }
  return String(v)
}

export function evidenceRows(evidence: Record<string, unknown> | undefined): [string, string][] {
  return Object.entries(evidence ?? {}).map(([k, v]) => [k, evidenceText(v)])
}

export const isSignedOff = (status: string) => status === 'signed_off'
export const itemOpen = (status: string) => status === 'open'
export const dt = (iso: string | null | undefined) => (iso ? iso.slice(0, 19).replace('T', ' ') : '')
/** dd-mm-yyyy for dates the server sends as ISO. */
export function dmy(iso: string | null | undefined): string {
  return iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : (iso ?? '')
}

/** Text of a form entry value: finding ids as a count + list, everything else as it is. */
export function entryValueText(v: unknown): string {
  if (Array.isArray(v)) return `${v.length} finding(s)`
  return evidenceText(v)
}
export function entryFindingIds(v: unknown): string[] {
  return ids(v)
}

/** The sample parameters as one line, to show that method + seed reproduce the same ids. */
export function sampleLine(s: { method: string; seed: number | null; params: Record<string, unknown>; ids: string[] }): string {
  if (!s.method || s.method === 'none') return 'No sample drawn yet.'
  const extra = Object.entries(s.params ?? {})
    .filter(([k, v]) => k !== 'seed' && v !== null && v !== undefined)
    .map(([k, v]) => `${k} ${evidenceText(v)}`)
  return [`Method ${s.method}`, `seed ${s.seed ?? 'not recorded'}`, ...extra, `${s.ids.length} item(s)`].join(', ')
}
