// Pure display helpers for the Phase 2 screens. They add and compare amounts exactly (integer paise) so the
// screen can show "allocated X of Y" and running ticks; they decide nothing: the server enforces every rule.

import { formatBalance, fromPaise, toPaise } from './money'
import type {
  AllocationIn,
  AllocationKind,
  AllocationOut,
  BankMapping,
  Balance,
  BookItem,
  BucketKey,
  OpeningBillIn,
  VoucherType,
} from '../types'

// ---- allocation editor ----

export interface AllocRow {
  kind: AllocationKind
  bill_ref: string
  amount: string
  due_date: string
}

export const ALLOC_KINDS: { value: AllocationKind; label: string }[] = [
  { value: 'new_ref', label: 'New Ref' },
  { value: 'against_ref', label: 'Against Ref' },
  { value: 'advance', label: 'Advance' },
  { value: 'on_account', label: 'On Account' },
]

export const blankAllocRow = (kind: AllocationKind = 'new_ref'): AllocRow => ({ kind, bill_ref: '', amount: '', due_date: '' })

/** The amount of a voucher line as typed: the debit or the credit, whichever is filled ('' when neither). */
export function lineAmountText(debit: string, credit: string): string {
  const d = toPaise(debit) ?? 0n
  return d !== 0n ? debit.trim() : (toPaise(credit) ?? 0n) !== 0n ? credit.trim() : ''
}
export function lineSide(debit: string, credit: string): 'Dr' | 'Cr' | null {
  if ((toPaise(debit) ?? 0n) !== 0n) return 'Dr'
  if ((toPaise(credit) ?? 0n) !== 0n) return 'Cr'
  return null
}

export type AllocState = 'none' | 'partial' | 'full' | 'over' | 'unreadable'
export interface AllocProgress {
  allocated: string
  total: string
  remaining: string // line amount minus allocated; negative when over-allocated
  state: AllocState
}

/** "allocated X of Y" for one line. */
export function allocationProgress(lineAmount: string, rows: { amount: string }[]): AllocProgress {
  const total = toPaise(lineAmount)
  let allocated = 0n
  let bad = total === null
  for (const r of rows) {
    const p = toPaise(r.amount)
    if (p === null) bad = true
    else allocated += p
  }
  const t = total ?? 0n
  let state: AllocState
  if (bad) state = 'unreadable'
  else if (allocated === 0n) state = 'none'
  else if (allocated === t) state = 'full'
  else if (allocated > t) state = 'over'
  else state = 'partial'
  return { allocated: fromPaise(allocated), total: fromPaise(t), remaining: fromPaise(t - allocated), state }
}

/** Voucher types whose party line gets one New Ref row prefilled, and on which side of the line. */
const PREFILL_SIDE: Partial<Record<VoucherType, 'Dr' | 'Cr'>> = { sales: 'Dr', purchase: 'Cr' }

/** The visible default for a Sales/Purchase party line: one New Ref named from the voucher Reference No, whole line amount. */
export function prefillRows(type: VoucherType, side: 'Dr' | 'Cr' | null, reference: string, amount: string): AllocRow[] {
  if (side === null || PREFILL_SIDE[type] !== side) return []
  if ((toPaise(amount) ?? 0n) === 0n) return []
  return [{ kind: 'new_ref', bill_ref: reference.trim(), amount: amount.trim(), due_date: '' }]
}

/** Keep an untouched prefilled row in step when the line amount or the Reference No is edited. Any other rows are left alone. */
export function followPrefill(
  rows: AllocRow[],
  before: { amount: string; reference: string },
  after: { amount: string; reference: string },
): AllocRow[] {
  if (rows.length !== 1) return rows
  const r = rows[0]
  if (r.kind !== 'new_ref') return rows
  const sameAmount = r.amount.trim() === before.amount.trim()
  const sameRef = r.bill_ref.trim() === before.reference.trim()
  if (!sameAmount && !sameRef) return rows
  return [{ ...r, amount: sameAmount ? after.amount.trim() : r.amount, bill_ref: sameRef ? after.reference.trim() : r.bill_ref }]
}

/** Rows to send to the API: no bill ref on On Account, due date only where the user typed one. */
export function toAllocationIn(rows: AllocRow[]): AllocationIn[] {
  return rows.map((r) => {
    const out: AllocationIn = { kind: r.kind, amount: r.amount.trim() }
    if (r.kind !== 'on_account') out.bill_ref = r.bill_ref.trim()
    if (r.due_date && (r.kind === 'new_ref' || r.kind === 'advance')) out.due_date = r.due_date
    return out
  })
}

export function fromAllocationOut(list: AllocationOut[] | undefined): AllocRow[] {
  return (list ?? []).map((a) => ({
    kind: a.kind,
    bill_ref: a.bill_ref ?? '',
    amount: a.amount,
    due_date: a.due_date ?? '',
  }))
}

// ---- outstanding / ageing ----

export const BUCKETS: { key: BucketKey; label: string }[] = [
  { key: 'not_due', label: 'Not due' },
  { key: '0-30', label: '0-30' },
  { key: '31-60', label: '31-60' },
  { key: '61-90', label: '61-90' },
  { key: '90+', label: '90+' },
]
export function bucketLabel(key: string): string {
  return BUCKETS.find((b) => b.key === key)?.label ?? key
}

// ---- parties ----

export type PartyArea = 'gstin' | 'pan' | 'state_code' | 'credit_days' | 'msme' | 'bill_wise' | 'general'

/** Which part of the party form a P-0x rule error belongs to (so the message is shown next to it). */
export function partyArea(ruleId: string): PartyArea {
  switch (ruleId) {
    case 'P-01':
    case 'P-03':
      return 'gstin'
    case 'P-02':
      return 'pan'
    case 'P-04':
      return 'state_code'
    case 'P-05':
      return 'msme'
    case 'P-06':
      return 'credit_days'
    case 'P-08':
      return 'bill_wise'
    default:
      return 'general'
  }
}

export function groupByArea<T extends { rule_id: string }>(errors: T[]): Partial<Record<PartyArea, T[]>> {
  const out: Partial<Record<PartyArea, T[]>> = {}
  for (const e of errors) (out[partyArea(e.rule_id)] ??= []).push(e)
  return out
}

// ---- opening bills ----

/** Signed total of the rows as typed (Dr +, Cr -) for display next to the server's figure. Unreadable amounts count as zero. */
export function openingBillsTotal(rows: Pick<OpeningBillIn, 'amount' | 'side'>[]): Balance {
  let t = 0n
  for (const r of rows) {
    const p = toPaise(r.amount) ?? 0n
    t += r.side === 'Dr' ? p : -p
  }
  if (t === 0n) return { amount: '0.00', side: null }
  return { amount: fromPaise(t < 0n ? -t : t), side: t < 0n ? 'Cr' : 'Dr' }
}

// ---- bank format mapping ----

export const DATE_FORMATS = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%Y-%m-%d', '%d-%b-%Y', '%d %b %Y', '%m/%d/%Y']

export const blankMapping = (): BankMapping => ({
  header_row: 1,
  date_col: '',
  date_format: '%d/%m/%Y',
  description_col: '',
  reference_col: '',
  debit_col: '',
  credit_col: '',
  amount_col: '',
  drcr_col: '',
  balance_col: '',
  opening_balance: '',
})

const has = (v: string | null | undefined) => (v ?? '').trim() !== ''

/** Form completeness only (the server parses and validates the file): what the user must still fill in. */
export function mappingProblems(m: BankMapping): string[] {
  const out: string[] = []
  if (!Number.isInteger(m.header_row) || m.header_row < 1) out.push('Header row must be 1 or more.')
  if (!has(m.date_col)) out.push('Date column is required.')
  if (!has(m.date_format)) out.push('Date format is required.')
  if (!has(m.description_col)) out.push('Description column is required.')
  const split = has(m.debit_col) && has(m.credit_col)
  const single = has(m.amount_col) && has(m.drcr_col)
  const partialSplit = has(m.debit_col) !== has(m.credit_col)
  const partialSingle = has(m.amount_col) !== has(m.drcr_col)
  if (split && single) out.push('Use either Debit + Credit columns or Amount + Dr/Cr column, not both.')
  else if (!split && !single) out.push('Give Debit + Credit columns, or an Amount column with a Dr/Cr column.')
  if (partialSplit && !single) out.push('Debit and Credit columns go together.')
  if (partialSingle && !split) out.push('Amount and Dr/Cr columns go together.')
  return out
}

/** Empty boxes are left out so the server sees only what the user filled. */
export function cleanMapping(m: BankMapping): BankMapping {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(m)) {
    if (typeof v === 'string') {
      if (v.trim() !== '') out[k] = v.trim()
    } else if (v !== null && v !== undefined) out[k] = v
  }
  return out as unknown as BankMapping
}

// ---- reconciliation ----

export interface BankTick {
  debit: string
  credit: string
}
export interface TickTotals {
  bank: string // credits - debits of the ticked bank lines (deposits positive)
  book: string // Dr - Cr of the ticked book items (deposits positive)
  difference: string // bank - book
  ties: boolean // both sides ticked and the nets are equal
}

/** Running totals of ticked rows. Bank credit = deposit = book Dr (docs/PHASE2_PLAN.md). Display only; the server decides. */
export function tickTotals(bank: BankTick[], book: BankTick[]): TickTotals {
  let b = 0n
  for (const x of bank) b += (toPaise(x.credit) ?? 0n) - (toPaise(x.debit) ?? 0n)
  let k = 0n
  for (const x of book) k += (toPaise(x.debit) ?? 0n) - (toPaise(x.credit) ?? 0n)
  return {
    bank: fromPaise(b),
    book: fromPaise(k),
    difference: fromPaise(b - k),
    ties: bank.length > 0 && book.length > 0 && b === k,
  }
}

export function bookItemId(item: Pick<BookItem, 'voucher_line_id' | 'opening_item_id'>): string {
  return item.voucher_line_id ?? item.opening_item_id ?? ''
}

export function toggleId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]
}

/** Split the ticked book items into voucher-line ids and opening-item ids as the match endpoint wants them. */
export function matchBody(bankLineIds: string[], book: BookItem[], tickedBookIds: string[]) {
  const voucher_line_ids: string[] = []
  const opening_item_ids: string[] = []
  for (const item of book) {
    const id = bookItemId(item)
    if (!tickedBookIds.includes(id)) continue
    if (item.voucher_line_id) voucher_line_ids.push(item.voucher_line_id)
    else if (item.opening_item_id) opening_item_ids.push(item.opening_item_id)
  }
  return { bank_line_ids: bankLineIds, voucher_line_ids, opening_item_ids }
}

export function balanceOrNil(b: Balance | null | undefined): string {
  return b ? formatBalance(b) : ''
}

// ---- ledger pickers ----

const CASH_BANK_GROUPS = ['Cash-in-hand', 'Bank Accounts']
export function cashBankLedgers<T extends { is_active: boolean; group_name: string }>(ledgers: T[], onlyBank = false): T[] {
  return ledgers.filter((l) => l.is_active && (onlyBank ? l.group_name === 'Bank Accounts' : CASH_BANK_GROUPS.includes(l.group_name)))
}
