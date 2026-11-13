import { describe, expect, test } from 'vitest'
import type { Registration } from '../api/gst'
import { blankGstItem, isAmountText, previewBody, isQuarterly, missingRoles, quarterStart, returnQuery, ruleBadge, shapeOf } from './lib'

const reg = (over: Partial<Registration>): Registration => ({
  id: 'r1',
  gstin: '27AAAAA0000A1Z5',
  state_code: '27',
  state_name: 'Maharashtra',
  registration_type: 'regular',
  return_frequency: 'monthly',
  composition_category: null,
  trade_name: null,
  effective_from: '2026-04-01',
  effective_to: null,
  is_active: true,
  ledger_roles: {},
  ...over,
})

describe('gst lib', () => {
  test('quarterStart follows Indian financial-year quarters', () => {
    expect(quarterStart('2026-04')).toBe('2026-04-01')
    expect(quarterStart('2026-06')).toBe('2026-04-01')
    expect(quarterStart('2026-07')).toBe('2026-07-01')
    expect(quarterStart('2026-12')).toBe('2026-10-01')
    expect(quarterStart('2027-02')).toBe('2027-01-01')
    expect(quarterStart('bad')).toBe('')
  })
  test('returnQuery: monthly vs quarterly, and bad input', () => {
    expect(returnQuery(reg({}), '2026-05')).toEqual({ registration_id: 'r1', period_start: '2026-05-01', period_kind: 'month' })
    expect(returnQuery(reg({ return_frequency: 'qrmp' }), '2026-05')).toEqual({
      registration_id: 'r1',
      period_start: '2026-04-01',
      period_kind: 'quarter',
    })
    expect(returnQuery(reg({ registration_type: 'composition' }), '2026-11')?.period_kind).toBe('quarter')
    expect(returnQuery(reg({}), '2026-13')).toBeNull()
    expect(returnQuery(undefined, '2026-05')).toBeNull()
    expect(isQuarterly(undefined)).toBe(false)
  })
  test('ruleBadge never shows an unknown status as verified', () => {
    expect(ruleBadge('verified').label).toBe('Rules verified')
    expect(ruleBadge('pending').cls).toContain('amber')
    expect(ruleBadge('whatever').cls).toContain('amber')
    expect(ruleBadge(undefined).cls).toContain('amber')
  })
  test('isAmountText accepts only 2-decimal strings', () => {
    expect(isAmountText('100.00')).toBe(true)
    expect(isAmountText('-5.50')).toBe(true)
    expect(isAmountText('18.0000')).toBe(false)
    expect(isAmountText(5)).toBe(false)
  })
  test('shapeOf', () => {
    expect(shapeOf([])).toEqual({ kind: 'empty' })
    expect(shapeOf([{ a: 1 }, { a: 2, b: 3 }])).toEqual({ kind: 'rows', columns: ['a', 'b'] })
    expect(shapeOf({ a: 1 })).toEqual({ kind: 'record' })
    expect(shapeOf('x')).toEqual({ kind: 'scalar' })
    expect(shapeOf([1, 2])).toEqual({ kind: 'scalar' })
  })
  test('missingRoles lists unmapped roles', () => {
    const regular = missingRoles(reg({ ledger_roles: { output_cgst: { ledger_id: 'l', ledger_name: 'n' } } }))
    expect(regular).not.toContain('output_cgst')
    expect(regular).toContain('output_sgst')
    expect(regular).not.toContain('composition_tax_payable')
    expect(missingRoles(reg({ registration_type: 'composition' }))).toEqual(['composition_tax_expense', 'composition_tax_payable'])
  })
  test('previewBody waits for a complete item and sends no tax fields', () => {
    const base = { voucher_type: 'sales', voucher_date: '2026-05-01', narration: 'n' }
    const gst = {
      gst_registration_id: 'r1',
      document_kind: 'tax_invoice' as const,
      supply_category: 'b2b',
      place_of_supply: '27',
      invoice_date: '2026-05-01',
      counterparty_gstin: null,
      items: [{ ...blankGstItem(), hsn_sac: '9983', unit_rate: '1000.00', ledger_id: 'l1' }],
    }
    const body = previewBody(base, gst)
    expect(body?.gst.items).toHaveLength(1)
    expect(Object.keys(body?.gst.items[0] ?? {})).not.toContain('cgst')
    expect(previewBody(base, { ...gst, place_of_supply: '' })).toBeNull()
    expect(previewBody(base, { ...gst, items: [{ ...gst.items[0], unit_rate: '10.' }] })).toBeNull()
    expect(previewBody(base, { ...gst, items: [blankGstItem()] })).toBeNull()
  })
})
