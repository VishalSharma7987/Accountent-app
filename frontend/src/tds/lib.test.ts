import { describe, expect, test } from 'vitest'
import { blankTdsItem, buildLines, countPending, dueClass, fyLabel, itemProblems, mergeProposal, panBadge, previewBody } from './lib'

const item = (over = {}) => ({ ...blankTdsItem(), deductee_ledger_id: 'd1', nature_key: 'contractor', amount: '50000.00', payment_date: '2026-05-10', ...over })
const base = { voucher_type: 'payment', voucher_date: '2026-05-10', narration: 'Contract', reference_no: null, party_ledger_id: 'd1' }

describe('tds lib', () => {
  test('fyLabel', () => {
    expect(fyLabel({ start_date: '2026-04-01' })).toBe('2026-27')
    expect(fyLabel({ start_date: '2099-04-01' })).toBe('2099-00')
  })
  test('itemProblems lists what is missing, never fills a default', () => {
    expect(itemProblems(blankTdsItem())).toHaveLength(4)
    expect(itemProblems(item())).toEqual([])
    expect(itemProblems(item({ payment_date: null }))).toEqual(['Enter the credit date or the payment date'])
    expect(itemProblems(item({ amount: '10.005' }))).toEqual(['Enter the amount (max 2 decimals)'])
  })
  test('buildLines: payment is Dr party / Cr bank for the gross; purchase is Dr expense / Cr party', () => {
    const items = [item(), item({ deductee_ledger_id: 'd2', amount: '1000.50' })]
    expect(buildLines('payment', items, 'bank')).toEqual([
      { ledger_id: 'd1', debit: '50000.00' },
      { ledger_id: 'd2', debit: '1000.50' },
      { ledger_id: 'bank', credit: '51000.50' },
    ])
    expect(buildLines('purchase', [item()], 'exp')).toEqual([
      { ledger_id: 'exp', debit: '50000.00' },
      { ledger_id: 'd1', credit: '50000.00' },
    ])
  })
  test('previewBody is null until ready and carries no tax amount (T-05)', () => {
    expect(previewBody(base, [blankTdsItem()], 'bank')).toBeNull()
    expect(previewBody(base, [item()], '')).toBeNull()
    const body = previewBody(base, [item()], 'bank')
    expect(body?.tds.items[0].manual_tax).toBeNull()
    expect(JSON.stringify(body)).not.toContain('tds_amount')
  })
  test('mergeProposal adds proposed paise to existing, exactly', () => {
    expect(
      mergeProposal(
        [
          { item_id: 'a', challan_id: 'c1', amount: '10.10' },
          { item_id: 'b', challan_id: 'c2', amount: '5.00' },
        ],
        'c1',
        [{ item_id: 'a', amount: '0.20' }],
      ),
    ).toEqual([{ item_id: 'a', amount: '10.30' }])
  })
  test('badges: missing PAN is red, unknown status never green; due status colours', () => {
    expect(panBadge('missing').cls).toContain('red')
    expect(panBadge('zzz').cls).not.toContain('green')
    expect(dueClass('overdue')).toContain('red')
  })
  test('countPending reads verification_status or status', () => {
    expect(countPending([{ verification_status: 'pending' }, { status: 'pending' }, { status: 'verified' }])).toBe(2)
  })
})
