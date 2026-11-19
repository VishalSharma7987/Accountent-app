import app from '../App.tsx?raw'
import { describe, expect, it } from 'vitest'
import { monthStart } from '../api/gst'
import { CERT_KINDS, DEDUCTEE_TYPES, LEDGER_ROLES } from '../tds/lib'
import { NOTE_REASONS, cleanItem, returnTypeOf } from '../gst/lib'
import { detailLines, lineLabel } from './apiError'
import { NAV_GROUPS } from './nav'

// Keys below are typed from the backend (engine/tds_masters.py, engine/gst_invoice.py, migration 0012), not from the code under test.
describe('keys sent to the server match the backend', () => {
  it('TDS certificate kinds are non_salary, salary, tcs', () => {
    expect(CERT_KINDS.map((k) => k.value).sort()).toEqual(['non_salary', 'salary', 'tcs'])
  })
  it('TDS ledger role keys', () => {
    expect(LEDGER_ROLES.map((r) => r.value)).toEqual(['tds_payable', 'tcs_payable', 'tds_receivable', 'tcs_receivable', 'interest_expense', 'late_fee_expense'])
  })
  it('deductee types are the ten the database allows', () => {
    expect([...DEDUCTEE_TYPES].sort()).toEqual(['aop_boi', 'co_operative_society', 'company', 'firm', 'huf', 'individual', 'llp', 'local_authority', 'other', 'trust'])
  })
  it('credit / debit note reasons are the engine keys', () => {
    expect(NOTE_REASONS.map((r) => r.value)).toEqual(['sales_return', 'post_sale_discount', 'deficiency_in_services', 'correction_in_invoice', 'change_in_pos', 'provisional_assessment', 'others'])
  })
  it('the composition screen saves a cmp08 working', () => {
    expect(returnTypeOf('composition')).toBe('cmp08')
    expect(returnTypeOf('gstr1')).toBe('gstr1')
    expect(returnTypeOf('gstr3b')).toBe('gstr3b')
  })
})

describe('cleanItem', () => {
  it('sends a blank UQC as null (an empty UQC fails G-07) and trims the rest', () => {
    expect(cleanItem({ name: ' Consulting ', hsn_sac: ' 9983 ', uqc: '' })).toEqual({ name: 'Consulting', hsn_sac: '9983', uqc: null })
    expect(cleanItem({ name: 'Rice', hsn_sac: '1006', uqc: ' kgs ' }).uqc).toBe('KGS')
    expect(cleanItem({ name: 'x', hsn_sac: '1', uqc: null }).uqc).toBeNull()
  })
})

describe('monthStart', () => {
  it('turns YYYY-MM into the first day, leaves other text alone', () => {
    expect(monthStart('2026-04')).toBe('2026-04-01')
    expect(monthStart('2026-04-15')).toBe('2026-04-15')
    expect(monthStart('')).toBeUndefined()
    expect(monthStart(undefined)).toBeUndefined()
  })
})

describe('error helpers', () => {
  it('lineLabel names the voucher line', () => {
    expect(lineLabel({ line_no: 2 })).toBe('line 2')
    expect(lineLabel({ line_no: null })).toBe('')
  })
  it('detailLines lists row problems of a rejected file', () => {
    expect(detailLines([{ row: 3, message: 'bad date' }, { row: 0, message: 'recipient GSTIN differs' }, 'junk'])).toEqual(['Row 3: bad date', 'recipient GSTIN differs'])
    expect(detailLines(null)).toEqual([])
    expect(detailLines({ roles: ['x'] })).toEqual([])
  })
})

describe('navigation', () => {
  it('every sidebar link has a route in App.tsx', () => {
    const routes = new Set([...app.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]))
    const missing = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.to)).filter((to) => !routes.has(to))
    expect(missing).toEqual([])
  })
})
