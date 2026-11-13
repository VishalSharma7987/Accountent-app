import { describe, expect, test } from 'vitest'
import type { GstIn } from '../api/gst'
import {
  blankTdsItem,
  buildLines,
  countPending,
  deductorAnswerLabel,
  dueClass,
  fyLabel,
  invoicePreviewBody,
  isPartialCertificate,
  itemProblems,
  mergeProposal,
  panBadge,
  previewBody,
  rateCells,
  selectableNatures,
} from './lib'

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

describe('Phase 4.1 helpers', () => {
  test('selectableNatures hides the nature the system picks (ex-194-IB)', () => {
    expect(selectableNatures([{ key: 'rent_land_building' }, { key: 'rent_194ib' }, { key: 'contractor' }]).map((n) => n.key)).toEqual(['rent_land_building', 'contractor'])
  })
  test('rateCells and isPartialCertificate: certificate 0.5 but effective 1.25 is a partial certificate', () => {
    expect(rateCells({ certificate_rate: '0.5', effective_rate: '1.25' })).toEqual({ certificate: '0.5', effective: '1.25' })
    expect(isPartialCertificate({ certificate_rate: '0.5', effective_rate: '1.25' })).toBe(true)
    expect(isPartialCertificate({ certificate_rate: '0.5', effective_rate: '0.5' })).toBe(false)
    expect(isPartialCertificate({ certificate_rate: null, effective_rate: '2' })).toBe(false)
    expect(rateCells({ certificate_rate: null, effective_rate: null })).toEqual({ certificate: '', effective: '' })
  })
  test('deductorAnswerLabel never assumes an answer', () => {
    const profile = [{ financial_year_id: 'fy1', individual_huf_not_tax_audited: true }, { financial_year_id: 'fy2', individual_huf_not_tax_audited: false }]
    expect(deductorAnswerLabel(profile, 'fy1')).toMatch(/^Yes/)
    expect(deductorAnswerLabel(profile, 'fy2')).toMatch(/^No/)
    expect(deductorAnswerLabel(profile, 'fy3')).toBe('Not recorded')
    expect(deductorAnswerLabel(undefined, 'fy1')).toBe('Not recorded')
  })
  test('invoicePreviewBody sends the GST block with no lines and no tax amount', () => {
    const gst: GstIn = { gst_registration_id: 'r', document_kind: 'tax_invoice', supply_category: 'b2b', place_of_supply: '27', invoice_date: '2026-05-10', counterparty_gstin: null, items: [] }
    const body = invoicePreviewBody({ ...base, voucher_type: 'purchase' }, [item()], gst)
    expect(body?.lines).toEqual([])
    expect(body?.gst).toBe(gst)
    expect(body?.tds.items[0]).not.toHaveProperty('tds_amount')
    expect(invoicePreviewBody({ ...base, voucher_type: 'purchase' }, [blankTdsItem()], gst)).toBeNull()
  })
})
