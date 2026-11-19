import { describe, expect, test } from 'vitest'
import { EMPTY_ADJ, blockingItems, buildAdjustmentBody, buildTermsRows, drillHref, exportFileName, splitFindings, worstRuleStatus } from './lib'

const base = { ...EMPTY_ADJ, as_on_date: '2027-03-31', basis_note: 'Rent for March unpaid' }

describe('adjustment body', () => {
  test('outstanding expense sends amount and both ledgers', () => {
    const r = buildAdjustmentBody({ ...base, adj_type: 'outstanding_expense', amount: '10,000.50', debit_ledger_id: 'a', credit_ledger_id: 'b' })
    expect(r.problems).toEqual([])
    expect(r.body).toMatchObject({ adj_type: 'outstanding_expense', amount: '10000.50', debit_ledger_id: 'a', credit_ledger_id: 'b' })
  })
  test('F-05 computed types never send an amount', () => {
    const r = buildAdjustmentBody({ ...base, adj_type: 'provision_doubtful_debts', amount: '999', rate_percent: '5' })
    expect(r.body?.amount).toBeUndefined()
    expect(r.body?.rate_percent).toBe('5')
  })
  test('F-01 three decimals are refused, not rounded', () => {
    const r = buildAdjustmentBody({ ...base, adj_type: 'bad_debt', amount: '10.005', party_ledger_id: 'd' })
    expect(r.body).toBeNull()
    expect(r.problems[0]).toMatch(/2 decimals/)
  })
  test('basis note and date are required', () => {
    const r = buildAdjustmentBody({ ...EMPTY_ADJ, adj_type: 'bad_debt', amount: '5', party_ledger_id: 'd' })
    expect(r.problems).toHaveLength(2)
  })
  test('F-08 months must be 1 to 12', () => {
    expect(buildAdjustmentBody({ ...base, adj_type: 'partner_remuneration', partner_id: 'p', months: '13' }).body).toBeNull()
    expect(buildAdjustmentBody({ ...base, adj_type: 'partner_remuneration', partner_id: 'p', months: '6' }).body?.months).toBe(6)
    expect(buildAdjustmentBody({ ...base, adj_type: 'partner_remuneration', partner_id: 'p' }).body?.months).toBeUndefined()
  })
  test('interest on drawings needs partner and drawings ledger', () => {
    expect(buildAdjustmentBody({ ...base, adj_type: 'interest_on_drawings', partner_id: 'p' }).problems).toEqual(['Choose the partner drawings ledger.'])
  })
})

describe('partner terms', () => {
  const row = { partner_id: 'p1', name: 'Anil', profit_share_percent: '50', interest_on_capital_rate: '', interest_on_drawings_rate: null, remuneration_annual: '', deed_reference: '' }
  test('blank optional values become null', () => {
    const r = buildTermsRows([row])
    expect(r.problems).toEqual([])
    expect(r.rows[0]).toMatchObject({ interest_on_capital_rate: null, remuneration_annual: null, deed_reference: null })
  })
  test('F-62 deed values need a deed reference', () => {
    expect(buildTermsRows([{ ...row, interest_on_capital_rate: '12' }]).problems[0]).toMatch(/deed reference/)
    expect(buildTermsRows([{ ...row, interest_on_capital_rate: '12', deed_reference: 'Deed 2020' }]).problems).toEqual([])
  })
  test('invalid percent is reported', () => {
    expect(buildTermsRows([{ ...row, profit_share_percent: '12.34567' }]).problems).toHaveLength(1)
  })
})

describe('server findings and rule status', () => {
  test('findings split by severity', () => {
    const s = splitFindings([
      { rule_id: 'F-41', message: 'a', severity: 'error' },
      { rule_id: 'F-45', message: 'b', severity: 'warning' },
    ])
    expect(s.errors).toHaveLength(1)
    expect(s.warnings[0].rule_id).toBe('F-45')
  })
  test('pending is the worst status', () => {
    expect(worstRuleStatus([{ verification_status: 'verified' }, { verification_status: 'pending' }])).toBe('pending')
    expect(worstRuleStatus([{ verification_status: 'verified' }, { verification_status: 'secondary_verified' }])).toBe('secondary_verified')
    expect(worstRuleStatus([{ verification_status: 'verified' }])).toBe('verified')
    expect(worstRuleStatus([])).toBe('none')
  })
})

describe('links and names', () => {
  test('drill-down opens the ledger statement with the year dates', () => {
    expect(drillHref('L1', '2026-04-01', '2027-03-31')).toBe('/statement?ledger=L1&from=2026-04-01&to=2027-03-31')
  })
  test('export file name is safe', () => {
    expect(exportFileName('A & B Traders', '2026-27', 'pdf')).toBe('final-accounts-A_B_Traders-2026-27.pdf')
  })
  test('close blockers are the items not ok', () => {
    expect(blockingItems([{ ok: true }, { ok: false }])).toHaveLength(1)
  })
})
