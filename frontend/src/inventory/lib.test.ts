import { describe, expect, test } from 'vitest'
import { blankJournalLine, isMoney, isQuantity, journalActions, journalBody, journalProblems, nrvRows, hasWriteDown, type JournalDraft } from './lib'

const draft = (over: Partial<JournalDraft> = {}): JournalDraft => ({
  journal_type: 'transfer',
  journal_date: '2026-06-01',
  narration: 'Move to shop',
  reason_code: '',
  reason_note: '',
  lines: [{ item_id: 'i1', from_godown_id: 'g1', to_godown_id: 'g2', quantity: '5' }],
  ...over,
})

describe('S-02 quantity typing', () => {
  test('S02_three_decimals_ok_four_rejected', () => {
    expect(isQuantity('10')).toBe(true)
    expect(isQuantity('10.125')).toBe(true)
    expect(isQuantity('10.1255')).toBe(false)
    expect(isQuantity('0')).toBe(false)
    expect(isQuantity('0', true)).toBe(true)
    expect(isQuantity('-1')).toBe(false)
    expect(isQuantity('1e3')).toBe(false)
  })
  test('money_two_decimals', () => {
    expect(isMoney('10.5')).toBe(true)
    expect(isMoney('10.005')).toBe(false)
  })
})

describe('stock journal draft', () => {
  test('S10_valid_transfer_has_no_problems', () => {
    expect(journalProblems(draft())).toEqual([])
  })
  test('S10_same_godown_and_blank_fields_reported', () => {
    const p = journalProblems(draft({ narration: '', lines: [{ item_id: 'i1', from_godown_id: 'g1', to_godown_id: 'g1', quantity: '0' }] }))
    expect(p).toEqual(['Narration is required.', 'Line 1: from and to godown are the same.', 'Line 1: quantity must be above zero with at most 3 decimals.'])
  })
  test('S10_write_off_needs_reason_and_note_for_other', () => {
    const base = draft({ journal_type: 'write_off', lines: [{ item_id: 'i1', from_godown_id: 'g1', to_godown_id: '', quantity: '2' }] })
    expect(journalProblems(base)).toEqual(['Choose the write-off reason.'])
    expect(journalProblems({ ...base, reason_code: 'other' })).toEqual(['Reason "Other" needs a note.'])
    expect(journalProblems({ ...base, reason_code: 'damage' })).toEqual([])
  })
  test('write_off_body_has_no_to_godown_and_no_money', () => {
    const b = journalBody(draft({ journal_type: 'write_off', reason_code: 'damage', lines: [{ item_id: 'i1', from_godown_id: 'g1', to_godown_id: 'g2', quantity: ' 2 ' }] }))
    expect(b).toEqual({
      journal_type: 'write_off',
      journal_date: '2026-06-01',
      narration: 'Move to shop',
      reason_code: 'damage',
      reason_note: null,
      lines: [{ item_id: 'i1', from_godown_id: 'g1', to_godown_id: null, quantity: '2' }],
    })
  })
  test('blank_line_is_empty', () => {
    expect(blankJournalLine().quantity).toBe('')
  })
  test('journal_actions_follow_status', () => {
    expect(journalActions('draft')).toEqual(['edit', 'delete', 'approve'])
    expect(journalActions('approved')).toEqual(['post'])
    expect(journalActions('posted')).toEqual(['reverse'])
    expect(journalActions('reversed')).toEqual([])
  })
})

describe('S-15 NRV rows', () => {
  test('blank_deletes_value_needs_note', () => {
    const r = nrvRows({ a: { nrv: '', note: '' }, b: { nrv: '1,250.50', note: 'quote' }, c: { nrv: '9', note: ' ' }, d: { nrv: '1.234', note: 'x' } })
    expect(r.rows[0]).toEqual({ item_id: 'a', nrv_per_unit: null, basis_note: '' })
    expect(r.rows[1]).toEqual({ item_id: 'b', nrv_per_unit: '1250.50', basis_note: 'quote' })
    expect(r.problems).toEqual(['NRV 9 needs a basis note.', 'NRV "1.234" must be a number with at most 2 decimals.'])
  })
  test('write_down_flag', () => {
    expect(hasWriteDown([{ write_down: '0.00' }])).toBe(false)
    expect(hasWriteDown([{ write_down: '0.00' }, { write_down: '150.00' }])).toBe(true)
  })
})
