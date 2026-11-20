import { describe, expect, test } from 'vitest'
import { buildRunParams, entryValueText, evidenceText, findingLinks, isSignedOff, sampleLine } from './lib'

describe('audit lib', () => {
  test('blank parameters are left out', () => {
    expect(buildRunParams({ duplicate_window_days: '', late_posting_days: ' ' })).toBeUndefined()
  })
  test('parameters are typed for the server', () => {
    expect(buildRunParams({ duplicate_window_days: '10', variance_min_amount: '1,00,000.00', doc_required_types: 'purchase, payment' })).toEqual({
      duplicate_window_days: 10,
      variance_min_amount: '100000.00',
      doc_required_types: ['purchase', 'payment'],
    })
  })
  test('voucher and ledger links', () => {
    const f = { subject_kind: 'voucher', subject_id: 'v1', evidence: { voucher_ids: ['v1', 'v2'], party_ledger_id: 'L1' } }
    expect(findingLinks(f, '2026-04-01', '2027-03-31')).toEqual([
      { label: 'Voucher 1', to: '/vouchers/v1' },
      { label: 'Voucher 2', to: '/vouchers/v2' },
      { label: 'Ledger statement', to: '/statement?ledger=L1&from=2026-04-01&to=2027-03-31' },
    ])
    expect(findingLinks({ subject_kind: 'period', subject_id: null, evidence: {} }, 'a', 'b')).toEqual([])
  })
  test('evidence amounts are shown in Indian format', () => {
    expect(evidenceText('1234567.50')).toBe('12,34,567.50')
    expect(evidenceText(['a', 'b'])).toBe('a, b')
  })
  test('sign-off and sample line', () => {
    expect(isSignedOff('signed_off')).toBe(true)
    expect(isSignedOff('in_review')).toBe(false)
    expect(sampleLine({ method: 'random', seed: 7, params: { size: 3 }, ids: ['a', 'b', 'c'] })).toBe('Method random, seed 7, size 3, 3 item(s)')
    expect(entryValueText(['x', 'y'])).toBe('2 finding(s)')
  })
})
