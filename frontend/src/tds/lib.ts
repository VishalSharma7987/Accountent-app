// Pure helpers for the TDS screens. Nothing here computes tax: the server does (T-05).
import type { DueEvent, MatchRow, TdsItemIn, TdsVoucherBody } from '../api/tds'
import { sumAmounts, toPaise } from '../lib/money'
import type { FinancialYear, VoucherLineIn } from '../types'

export const QUARTERS = [
  { value: 1, label: 'Q1 (Apr-Jun)' },
  { value: 2, label: 'Q2 (Jul-Sep)' },
  { value: 3, label: 'Q3 (Oct-Dec)' },
  { value: 4, label: 'Q4 (Jan-Mar)' },
]

export const PAN_STATUSES = [
  { value: 'valid', label: 'Valid PAN' },
  { value: 'missing', label: 'PAN missing' },
  { value: 'invalid', label: 'PAN invalid' },
  { value: 'applied_for', label: 'Applied for' },
]
export const DEDUCTEE_TYPES = ['individual', 'huf', 'company', 'firm', 'llp', 'aop', 'society', 'trust', 'local_authority', 'other']
export const LEDGER_ROLES = [
  { value: 'tds_payable', label: 'TDS payable' },
  { value: 'tcs_payable', label: 'TCS payable' },
  { value: 'tds_receivable', label: 'TDS receivable' },
  { value: 'tcs_receivable', label: 'TCS receivable' },
  { value: 'interest', label: 'Interest on TDS' },
  { value: 'late_fee', label: 'Late fee' },
]
export const CERT_KINDS = [
  { value: 'form_16a', label: 'Form 16A (TDS other than salary)' },
  { value: 'form_27d', label: 'Form 27D (TCS)' },
]

/** "2026-04-01" -> "2026-27" (Indian financial year label). */
export function fyLabel(fy: Pick<FinancialYear, 'start_date'>): string {
  const start = Number(fy.start_date.slice(0, 4))
  return `${start}-${String((start + 1) % 100).padStart(2, '0')}`
}

export function newestFirst<T extends { start_date: string }>(years: T[]): T[] {
  return [...years].sort((a, b) => b.start_date.localeCompare(a.start_date))
}

export function panBadge(status: string): { label: string; cls: string } {
  if (status === 'valid') return { label: 'PAN valid', cls: 'bg-green-100 text-green-900 border-green-400' }
  if (status === 'applied_for') return { label: 'PAN applied for', cls: 'bg-yellow-50 text-yellow-900 border-yellow-300' }
  // missing, invalid and anything unknown: the higher rate applies, so it is shown in red
  return { label: status === 'invalid' ? 'PAN invalid' : 'PAN missing', cls: 'bg-red-100 text-red-900 border-red-400' }
}

export function dueClass(status: DueEvent['status'] | string): string {
  if (status === 'overdue') return 'bg-red-100 text-red-900'
  if (status === 'done') return 'bg-green-100 text-green-900'
  return 'bg-amber-50 text-amber-900'
}

export const blankTdsItem = (): TdsItemIn => ({
  deductee_ledger_id: '',
  nature_key: '',
  amount: '',
  credit_date: null,
  payment_date: null,
  lower_cert_id: null,
  manual_tax: null,
})

const hasInput = (i: TdsItemIn) => !!(i.deductee_ledger_id || i.nature_key || i.amount || i.credit_date || i.payment_date || i.manual_tax)

/** Why a typed item cannot be previewed yet (empty list = ready). The server still decides everything else. */
export function itemProblems(i: TdsItemIn): string[] {
  const out: string[] = []
  if (!i.deductee_ledger_id) out.push('Choose the deductee')
  if (!i.nature_key) out.push('Choose the nature of payment')
  const paise = toPaise(i.amount)
  if (!i.amount || paise === null || paise <= 0n) out.push('Enter the amount (max 2 decimals)')
  if (!i.credit_date && !i.payment_date) out.push('Enter the credit date or the payment date')
  return out
}

/** Gross voucher lines the caller types; the tax line is added by the server (read-only). */
export function buildLines(type: string, items: TdsItemIn[], counterLedgerId: string): VoucherLineIn[] {
  const total = sumAmounts(items.map((i) => i.amount)).total
  const party = items.map((i) => (type === 'payment' ? { ledger_id: i.deductee_ledger_id, debit: i.amount } : { ledger_id: i.deductee_ledger_id, credit: i.amount }))
  const counter = type === 'payment' ? { ledger_id: counterLedgerId, credit: total } : { ledger_id: counterLedgerId, debit: total }
  return type === 'payment' ? [...party, counter] : [counter, ...party]
}

export function previewBody(
  base: { voucher_type: string; voucher_date: string; narration: string; reference_no: string | null; party_ledger_id: string | null },
  items: TdsItemIn[],
  counterLedgerId: string,
): TdsVoucherBody | null {
  const typed = items.filter(hasInput)
  if (typed.length === 0 || !counterLedgerId || !base.voucher_date) return null
  if (typed.some((i) => itemProblems(i).length > 0)) return null
  const clean = typed.map((i) => ({ ...i, manual_tax: i.manual_tax || null }))
  return { ...base, lines: buildLines(base.voucher_type, clean, counterLedgerId), tds: { items: clean } }
}

/** Add the proposed amounts of one challan to what it already allocates, exactly (integer paise). */
export function mergeProposal(
  proposed: { item_id: string; challan_id: string; amount: string }[],
  challanId: string,
  existing: { item_id: string; amount: string }[],
): { item_id: string; amount: string }[] {
  const byItem = new Map<string, bigint>()
  for (const e of existing) byItem.set(e.item_id, (byItem.get(e.item_id) ?? 0n) + (toPaise(e.amount) ?? 0n))
  for (const p of proposed) if (p.challan_id === challanId) byItem.set(p.item_id, (byItem.get(p.item_id) ?? 0n) + (toPaise(p.amount) ?? 0n))
  return [...byItem.entries()].map(([item_id, paise]) => ({ item_id, amount: `${paise / 100n}.${String(paise % 100n).padStart(2, '0')}` }))
}

export function shortRows(rows: MatchRow[]): MatchRow[] {
  return rows.filter((r) => (toPaise(r.balance) ?? 0n) > 0n)
}

export function countPending(rows: { verification_status?: unknown; status?: unknown }[]): number {
  return rows.filter((r) => (r.verification_status ?? r.status) === 'pending').length
}

export function certLabel(kind: string): string {
  return CERT_KINDS.find((k) => k.value === kind)?.label ?? kind
}
