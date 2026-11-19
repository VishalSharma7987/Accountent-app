// Pure helpers for the Final accounts screens. Nothing here computes an amount, depreciation or profit:
// the server does (CLAUDE.md principle 1). These only shape forms, validate typed text, and label what the server returned.
import type { AdjType, AdjustmentBody, ClassRow, Finding, RuleStatusRow, Sch3Ledger, TermsRow } from '../api/final'
import { cleanTyped, toPaise } from '../lib/money'

export const FINAL_ENTITY_NOTE = 'Partners and partnership adjustments apply to partnership and LLP clients only.'

export interface AdjMeta {
  value: AdjType
  label: string
  /** the accountant types the amount */
  amount: boolean
  /** debit and credit ledger are both chosen (F-02) */
  twoLedgers: boolean
  party?: 'debtor' | 'drawings'
  rate?: boolean
  partner?: boolean
  months?: boolean
  firmOnly?: boolean
  hint: string
}

export const ADJ_TYPES: AdjMeta[] = [
  { value: 'outstanding_expense', label: 'Outstanding expense', amount: true, twoLedgers: true, hint: 'Debit the expense ledger, credit the outstanding-expense liability ledger.' },
  { value: 'prepaid_expense', label: 'Prepaid expense', amount: true, twoLedgers: true, hint: 'Debit the prepaid-expense asset ledger, credit the expense ledger.' },
  { value: 'accrued_income', label: 'Accrued income', amount: true, twoLedgers: true, hint: 'Debit the accrued-income asset ledger, credit the income ledger.' },
  { value: 'income_in_advance', label: 'Income received in advance', amount: true, twoLedgers: true, hint: 'Debit the income ledger, credit the income-in-advance liability ledger.' },
  { value: 'provision', label: 'Provision for expense', amount: true, twoLedgers: true, hint: 'Debit the expense ledger, credit the provision ledger (Provisions group).' },
  { value: 'bad_debt', label: 'Bad debts written off', amount: true, twoLedgers: false, party: 'debtor', hint: 'Debit Bad debts, credit the debtor. The debtor must owe at least this amount on the date.' },
  { value: 'provision_doubtful_debts', label: 'Provision for doubtful debts', amount: false, twoLedgers: false, rate: true, hint: 'The server computes the change in the provision from the rate and the closing debtors. Do not type an amount.' },
  { value: 'interest_on_capital', label: 'Interest on capital', amount: false, twoLedgers: false, partner: true, firmOnly: true, hint: 'Computed by the server from the deed rate and the capital balance. Do not type an amount.' },
  { value: 'interest_on_drawings', label: 'Interest on drawings', amount: false, twoLedgers: false, partner: true, party: 'drawings', firmOnly: true, hint: 'Computed by the server from the deed rate and each drawing. Choose the partner and the drawings ledger.' },
  { value: 'partner_remuneration', label: 'Partners remuneration', amount: false, twoLedgers: false, partner: true, months: true, firmOnly: true, hint: 'Annual remuneration from the deed, for the months chosen (default 12). Computed by the server.' },
]

export function adjMeta(t: AdjType | ''): AdjMeta | undefined {
  return ADJ_TYPES.find((a) => a.value === t)
}

export interface AdjForm {
  adj_type: AdjType | ''
  as_on_date: string
  basis_note: string
  amount: string
  debit_ledger_id: string
  credit_ledger_id: string
  party_ledger_id: string
  rate_percent: string
  partner_id: string
  months: string
  auto_reverse_on: string
  duplicate_reason: string
}
export const EMPTY_ADJ: AdjForm = {
  adj_type: '',
  as_on_date: '',
  basis_note: '',
  amount: '',
  debit_ledger_id: '',
  credit_ledger_id: '',
  party_ledger_id: '',
  rate_percent: '',
  partner_id: '',
  months: '',
  auto_reverse_on: '',
  duplicate_reason: '',
}

const RATE = /^\d{1,3}(\.\d{1,4})?$/

/** Form to request body: only the fields the type uses are sent (a typed amount for a computed type would be rejected by the server). */
export function buildAdjustmentBody(f: AdjForm): { body: AdjustmentBody | null; problems: string[] } {
  const meta = adjMeta(f.adj_type)
  const problems: string[] = []
  if (!meta) return { body: null, problems: ['Choose the type of adjustment.'] }
  if (!f.as_on_date) problems.push('Enter the date of the adjustment.')
  if (f.basis_note.trim() === '') problems.push('Enter the basis note (why this adjustment is made).')
  const body: AdjustmentBody = { adj_type: meta.value, as_on_date: f.as_on_date, basis_note: f.basis_note.trim() }
  if (meta.amount) {
    const amount = cleanTyped(f.amount)
    const paise = toPaise(amount)
    if (amount === '' || paise === null) problems.push('Enter the amount with at most 2 decimals.')
    else if (paise <= 0n) problems.push('The amount must be more than zero.')
    else body.amount = amount
  }
  if (meta.twoLedgers) {
    if (!f.debit_ledger_id) problems.push('Choose the debit ledger.')
    if (!f.credit_ledger_id) problems.push('Choose the credit ledger.')
    body.debit_ledger_id = f.debit_ledger_id || null
    body.credit_ledger_id = f.credit_ledger_id || null
  }
  if (meta.party) {
    if (!f.party_ledger_id) problems.push(meta.party === 'debtor' ? 'Choose the debtor.' : 'Choose the partner drawings ledger.')
    body.party_ledger_id = f.party_ledger_id || null
  }
  if (meta.rate) {
    const rate = cleanTyped(f.rate_percent)
    if (!RATE.test(rate)) problems.push('Enter the provision rate in percent (up to 4 decimals).')
    else body.rate_percent = rate
  }
  if (meta.partner) {
    if (!f.partner_id) problems.push('Choose the partner.')
    body.partner_id = f.partner_id || null
  }
  if (meta.months && f.months.trim() !== '') {
    const m = Number(f.months)
    if (!Number.isInteger(m) || m < 1 || m > 12) problems.push('Months must be a whole number from 1 to 12.')
    else body.months = m
  }
  if (f.auto_reverse_on) body.auto_reverse_on = f.auto_reverse_on
  if (f.duplicate_reason.trim()) body.duplicate_reason = f.duplicate_reason.trim()
  return { body: problems.length === 0 ? body : null, problems }
}

export function adjLabel(t: string): string {
  return ADJ_TYPES.find((a) => a.value === t)?.label ?? t.replace(/_/g, ' ')
}

// ---- findings and rule status ----
export function splitFindings(findings: Finding[] | undefined): { errors: Finding[]; warnings: Finding[] } {
  const all = findings ?? []
  return { errors: all.filter((f) => f.severity === 'error'), warnings: all.filter((f) => f.severity !== 'error') }
}

export type RuleWorst = 'pending' | 'secondary_verified' | 'verified' | 'none'
/** The weakest verification status among the law rows used (pending beats everything: it is printed on exports). */
export function worstRuleStatus(rows: RuleStatusRow[] | undefined): RuleWorst {
  const statuses = (rows ?? []).map((r) => String(r.verification_status ?? '')).filter((s) => s !== '')
  if (statuses.length === 0) return 'none'
  if (statuses.some((s) => s === 'pending')) return 'pending'
  if (statuses.some((s) => s === 'secondary_verified')) return 'secondary_verified'
  return 'verified'
}
export function ruleStatusBadge(worst: RuleWorst): { label: string; cls: string } {
  if (worst === 'pending') return { label: 'Law rules PENDING verification', cls: 'border-amber-400 bg-amber-50 text-amber-900' }
  if (worst === 'secondary_verified') return { label: 'Law rules secondary-verified', cls: 'border-sky-300 bg-sky-50 text-sky-900' }
  if (worst === 'verified') return { label: 'Law rules verified', cls: 'border-green-300 bg-green-50 text-green-800' }
  return { label: 'No law rules used', cls: 'border-slate-300 bg-slate-50 text-slate-700' }
}
export function statusBadge(status: string | null | undefined): { label: string; cls: string } {
  if (status === 'pending') return { label: 'pending', cls: 'border-amber-400 bg-amber-50 text-amber-900' }
  if (status === 'secondary_verified') return { label: 'secondary verified', cls: 'border-sky-300 bg-sky-50 text-sky-900' }
  if (status === 'verified') return { label: 'verified', cls: 'border-green-300 bg-green-50 text-green-800' }
  return { label: status || 'unknown', cls: 'border-slate-300 bg-slate-50 text-slate-700' }
}
export function ruleRowLabel(r: RuleStatusRow): string {
  const name = String(r.rule ?? r.block_key ?? 'rule')
  return [name.replace(/_/g, ' '), r.block_key && r.rule ? String(r.block_key) : '', r.act ? String(r.act) : ''].filter(Boolean).join(' / ')
}

// ---- drill-down to the Ledger statement screen ----
export function drillHref(ledgerId: string, from: string, to: string): string {
  const q = new URLSearchParams({ ledger: ledgerId, from, to })
  return `/statement?${q.toString()}`
}

// ---- partner terms ----
export function termsText(v: string | null | undefined): string {
  return v ?? ''
}
/** Rows for PUT /partners/terms: blank optional values become null; the deed reference is required whenever a deed value is entered. */
export function buildTermsRows(rows: TermsRow[]): { rows: TermsRow[]; problems: string[] } {
  const problems: string[] = []
  const out = rows.map((r) => {
    const name = r.name ?? 'Partner'
    const share = cleanTyped(r.profit_share_percent)
    if (!RATE.test(share)) problems.push(`${name}: profit share must be a percent with up to 4 decimals.`)
    const ioc = nullable(r.interest_on_capital_rate)
    const iod = nullable(r.interest_on_drawings_rate)
    const rem = nullable(r.remuneration_annual)
    if (ioc !== null && !RATE.test(ioc)) problems.push(`${name}: interest on capital rate is not a valid percent.`)
    if (iod !== null && !RATE.test(iod)) problems.push(`${name}: interest on drawings rate is not a valid percent.`)
    if (rem !== null && toPaise(rem) === null) problems.push(`${name}: remuneration must be an amount with at most 2 decimals.`)
    const ref = (r.deed_reference ?? '').trim()
    if ((ioc !== null || iod !== null || rem !== null) && ref === '') problems.push(`${name}: enter the partnership deed reference for the deed values.`)
    return { partner_id: r.partner_id, profit_share_percent: share, interest_on_capital_rate: ioc, interest_on_drawings_rate: iod, remuneration_annual: rem, deed_reference: ref || null }
  })
  return { rows: out, problems }
}
function nullable(v: string | null | undefined): string | null {
  const t = cleanTyped(v ?? '')
  return t === '' ? null : t
}

// ---- Schedule III classification ----
export function classificationRows(edits: Record<string, { line_code: string; cf_class: string }>): ClassRow[] {
  return Object.entries(edits).map(([ledger_id, e]) => ({
    ledger_id,
    line_code: e.line_code || null,
    cf_class: (e.cf_class || null) as ClassRow['cf_class'],
  }))
}
export function sourceLabel(s: Sch3Ledger['source']): string {
  if (s === 'ledger') return 'set for this ledger'
  if (s === 'group_firm') return 'from its group'
  if (s === 'group_default') return 'group default (confirm)'
  return 'not classified'
}

// ---- year-end close ----
export function blockingItems<T extends { ok: boolean }>(items: T[]): T[] {
  return items.filter((i) => !i.ok)
}

export function exportFileName(clientName: string, fyLabelText: string, format: 'xlsx' | 'pdf'): string {
  const safe = `${clientName}-${fyLabelText}`.replace(/[^A-Za-z0-9._-]+/g, '_')
  return `final-accounts-${safe}.${format}`
}

export const CF_CLASSES = [
  { value: 'operating', label: 'Operating' },
  { value: 'investing', label: 'Investing' },
  { value: 'financing', label: 'Financing' },
  { value: 'cash_equivalent', label: 'Cash and cash equivalent' },
  { value: 'non_cash', label: 'Non-cash' },
  { value: 'equity_profit', label: 'Equity / profit' },
]
export const CLOSING_STOCK_SOURCES = [
  { value: 'inventory_report', label: 'From the Phase 5 closing stock report' },
  { value: 'manual', label: 'Typed (manual valuation)' },
  { value: 'none', label: 'No stock (service client)' },
]
export const EVENT_KINDS = [
  { value: 'opening', label: 'Opening balance' },
  { value: 'purchase', label: 'Purchase' },
  { value: 'addition', label: 'Addition' },
  { value: 'disposal', label: 'Disposal' },
]
