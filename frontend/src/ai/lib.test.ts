import { describe, expect, it } from 'vitest'
import type { DocFinding, LlmCall } from '../api/ai'
import { acknowledgements, canAccept, changedEdits, fileSize, flattenPayload, groupByRule, hasBlocking, maskingSummary, usageFromCalls } from './lib'

const f = (rule_id: string, severity: DocFinding['severity'], field_path: string | null = null): DocFinding => ({ rule_id, severity, message: 'm', field_path })

describe('findings gate acceptance (blocking = error or review)', () => {
  it('a review or error finding blocks, a warning does not', () => {
    expect(hasBlocking([f('D-10', 'warning')])).toBe(false)
    expect(hasBlocking([f('D-10', 'review')])).toBe(true)
    expect(hasBlocking([f('D-05', 'error')])).toBe(true)
  })
  it('an unacknowledged warning blocks accept until acknowledged', () => {
    const list = [f('D-12', 'warning', 'totals.grand_total')]
    expect(canAccept(list, new Set(), 'in_review')).toBe(false)
    expect(canAccept(list, new Set(['D-12|totals.grand_total']), 'in_review')).toBe(true)
    expect(acknowledgements(list, new Set(['D-12|totals.grand_total']))).toEqual([{ rule_id: 'D-12', field_path: 'totals.grand_total' }])
  })
  it('a finished item cannot be accepted again', () => {
    expect(canAccept([], new Set(), 'accepted')).toBe(false)
    expect(canAccept([], new Set(), 'rejected')).toBe(false)
    expect(canAccept([], new Set(), 'pending')).toBe(true)
  })
  it('groups by rule id, errors first', () => {
    const g = groupByRule([f('D-20', 'warning'), f('D-05', 'error'), f('D-05', 'error', 'lines[0].cgst')])
    expect(g.map((x) => x.rule_id)).toEqual(['D-05', 'D-20'])
    expect(g[0].items).toHaveLength(2)
  })
})

describe('flattenPayload', () => {
  it('uses engine field paths (lines are 0-based) and skips notes and currency', () => {
    const rows = flattenPayload({
      supplier_name: { value: 'Shree Traders', page: 1 },
      invoice_no: { value: null },
      lines: [{ description: { value: 'Rice' }, taxable_value: { value: '1000.00' } }],
      totals: { grand_total: { value: '1050.00' } },
      currency: 'INR',
      notes: ['x'],
    })
    expect(rows.map((r) => r.path)).toEqual(['supplier_name', 'invoice_no', 'lines[0].description', 'lines[0].taxable_value', 'totals.grand_total'])
    expect(rows[2].label).toBe('Line 1 description')
    expect(rows[1].value).toBe('')
  })
  it('reads a Tally proposal with plain values', () => {
    const rows = flattenPayload({ source: 'tally', voucher_type: 'Sales', total: '500.00', lines: [{ tally_ledger_name: 'Sales', debit: '0.00', credit: '500.00' }] })
    expect(rows.map((r) => r.path)).toEqual(['voucher_type', 'total', 'lines[0].tally_ledger_name', 'lines[0].debit', 'lines[0].credit'])
    expect(rows[0].boxed).toBe(false)
  })
  it('sends only changed fields, an emptied field as null', () => {
    const base = flattenPayload({ invoice_no: { value: 'A1' }, supplier_name: { value: 'X' } })
    expect(changedEdits(base, { invoice_no: 'A2', supplier_name: 'X' })).toEqual([{ field_path: 'invoice_no', value: 'A2' }])
    expect(changedEdits(base, { supplier_name: ' ' })).toEqual([{ field_path: 'supplier_name', value: null }])
  })
})

describe('display helpers', () => {
  it('file size', () => {
    expect(fileSize(512)).toBe('512 B')
    expect(fileSize(2048)).toBe('2.0 KB')
    expect(fileSize(3 * 1024 * 1024)).toBe('3.0 MB')
  })
  it('usage counts calls and tokens from the log', () => {
    const call = (status: string, tin: number | null, tout: number | null) => ({ status, tokens_in: tin, tokens_out: tout }) as LlmCall
    expect(usageFromCalls([call('ok', 100, 20), call('error', null, null), call('ok', 50, 5)])).toEqual({ calls: 3, ok: 2, failed: 1, tokens_in: 150, tokens_out: 25 })
  })
  it('masking summary shows counts only', () => {
    expect(maskingSummary({ data_class: 'real_acknowledged', counts: { PAN: 2, GSTIN: 0, AADHAAR: 1 } })).toBe('2 PAN, 1 AADHAAR')
    expect(maskingSummary(null)).toBe('nothing masked')
  })
})
