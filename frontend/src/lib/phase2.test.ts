import { describe, expect, it } from 'vitest'
import {
  allocationProgress,
  bucketLabel,
  cashBankLedgers,
  cleanMapping,
  blankMapping,
  followPrefill,
  fromAllocationOut,
  groupByArea,
  lineAmountText,
  lineSide,
  mappingProblems,
  matchBody,
  openingBillsTotal,
  partyArea,
  prefillRows,
  tickTotals,
  toAllocationIn,
  toggleId,
} from './phase2'

describe('allocation progress', () => {
  it('nothing allocated', () => {
    expect(allocationProgress('11800.00', [])).toEqual({ allocated: '0.00', total: '11800.00', remaining: '11800.00', state: 'none' })
  })
  it('partly allocated', () => {
    expect(allocationProgress('10000.00', [{ amount: '2500.50' }, { amount: '1000' }])).toEqual({
      allocated: '3500.50',
      total: '10000.00',
      remaining: '6499.50',
      state: 'partial',
    })
  })
  it('exactly allocated (no float drift: 0.10 + 0.20 = 0.30)', () => {
    expect(allocationProgress('0.30', [{ amount: '0.10' }, { amount: '0.20' }]).state).toBe('full')
  })
  it('over-allocated shows a negative remainder', () => {
    expect(allocationProgress('100.00', [{ amount: '100.01' }])).toEqual({ allocated: '100.01', total: '100.00', remaining: '-0.01', state: 'over' })
  })
  it('unreadable amount is flagged', () => {
    expect(allocationProgress('100.00', [{ amount: '12.345' }]).state).toBe('unreadable')
  })
})

describe('line amount and side', () => {
  it('picks the filled column', () => {
    expect(lineAmountText('5000', '')).toBe('5000')
    expect(lineAmountText('', '7,000.00'.replace(',', ''))).toBe('7000.00')
    expect(lineAmountText('', '')).toBe('')
    expect(lineSide('5000', '')).toBe('Dr')
    expect(lineSide('', '7000')).toBe('Cr')
    expect(lineSide('', '')).toBeNull()
  })
})

describe('prefill', () => {
  it('Sales debtor Dr line: one New Ref from the reference with the whole amount', () => {
    expect(prefillRows('sales', 'Dr', ' INV-12 ', '11800.00')).toEqual([{ kind: 'new_ref', bill_ref: 'INV-12', amount: '11800.00', due_date: '' }])
  })
  it('Purchase creditor Cr line prefills; Dr side does not', () => {
    expect(prefillRows('purchase', 'Cr', 'B-7', '500.00')).toHaveLength(1)
    expect(prefillRows('purchase', 'Dr', 'B-7', '500.00')).toEqual([])
  })
  it('receipt / journal / zero amount do not prefill', () => {
    expect(prefillRows('receipt', 'Cr', 'X', '500.00')).toEqual([])
    expect(prefillRows('journal', 'Dr', 'X', '500.00')).toEqual([])
    expect(prefillRows('sales', 'Dr', 'X', '')).toEqual([])
  })
  it('an untouched prefilled row follows the amount and the reference', () => {
    const rows = prefillRows('sales', 'Dr', 'A1', '100.00')
    const next = followPrefill(rows, { amount: '100.00', reference: 'A1' }, { amount: '250.00', reference: 'A2' })
    expect(next).toEqual([{ kind: 'new_ref', bill_ref: 'A2', amount: '250.00', due_date: '' }])
  })
  it('a row the user changed keeps their value', () => {
    const rows = [{ kind: 'new_ref' as const, bill_ref: 'MINE', amount: '60.00', due_date: '' }]
    expect(followPrefill(rows, { amount: '100.00', reference: 'A1' }, { amount: '250.00', reference: 'A2' })).toEqual(rows)
  })
  it('several rows are never touched', () => {
    const rows = [
      { kind: 'new_ref' as const, bill_ref: 'A1', amount: '100.00', due_date: '' },
      { kind: 'on_account' as const, bill_ref: '', amount: '5.00', due_date: '' },
    ]
    expect(followPrefill(rows, { amount: '100.00', reference: 'A1' }, { amount: '9.00', reference: 'Z' })).toBe(rows)
  })
})

describe('allocation payload', () => {
  it('drops bill ref on On Account and due date on Against Ref', () => {
    expect(
      toAllocationIn([
        { kind: 'new_ref', bill_ref: ' INV-1 ', amount: '100.00 ', due_date: '2026-05-10' },
        { kind: 'against_ref', bill_ref: 'INV-0', amount: '50', due_date: '2026-05-10' },
        { kind: 'on_account', bill_ref: 'junk', amount: '10', due_date: '' },
      ]),
    ).toEqual([
      { kind: 'new_ref', amount: '100.00', bill_ref: 'INV-1', due_date: '2026-05-10' },
      { kind: 'against_ref', amount: '50', bill_ref: 'INV-0' },
      { kind: 'on_account', amount: '10' },
    ])
  })
  it('reads a saved voucher back', () => {
    expect(fromAllocationOut([{ kind: 'new_ref', amount: '100.00', bill_ref: 'A', due_date: '2026-05-10' }])).toEqual([
      { kind: 'new_ref', bill_ref: 'A', amount: '100.00', due_date: '2026-05-10' },
    ])
    expect(fromAllocationOut(undefined)).toEqual([])
  })
})

describe('buckets', () => {
  it('labels', () => {
    expect(bucketLabel('not_due')).toBe('Not due')
    expect(bucketLabel('90+')).toBe('90+')
    expect(bucketLabel('31-60')).toBe('31-60')
  })
})

describe('party rule areas', () => {
  it('maps P rules to form areas', () => {
    expect(partyArea('P-01')).toBe('gstin')
    expect(partyArea('P-03')).toBe('gstin')
    expect(partyArea('P-02')).toBe('pan')
    expect(partyArea('P-04')).toBe('state_code')
    expect(partyArea('P-05')).toBe('msme')
    expect(partyArea('P-06')).toBe('credit_days')
    expect(partyArea('P-09')).toBe('msme_activity')
    expect(partyArea('P-10')).toBe('udyam_date')
    expect(partyArea('P-11')).toBe('agreed_days')
    expect(partyArea('P-08')).toBe('bill_wise')
    expect(partyArea('P-07')).toBe('general')
  })
  it('groups errors', () => {
    const g = groupByArea([{ rule_id: 'P-01' }, { rule_id: 'P-03' }, { rule_id: 'P-06' }])
    expect(g.gstin).toHaveLength(2)
    expect(g.credit_days).toHaveLength(1)
    expect(g.pan).toBeUndefined()
  })
})

describe('opening bills total', () => {
  it('Dr minus Cr with side', () => {
    expect(openingBillsTotal([{ amount: '1000.00', side: 'Dr' }, { amount: '250.25', side: 'Cr' }])).toEqual({ amount: '749.75', side: 'Dr' })
    expect(openingBillsTotal([{ amount: '100', side: 'Cr' }])).toEqual({ amount: '100.00', side: 'Cr' })
    expect(openingBillsTotal([{ amount: '100', side: 'Cr' }, { amount: '100.00', side: 'Dr' }])).toEqual({ amount: '0.00', side: null })
    expect(openingBillsTotal([])).toEqual({ amount: '0.00', side: null })
  })
})

describe('bank mapping form', () => {
  const ok = { ...blankMapping(), date_col: 'Txn Date', description_col: 'Narration', debit_col: 'Withdrawal', credit_col: 'Deposit' }
  it('blank form lists what is missing', () => {
    const p = mappingProblems(blankMapping())
    expect(p).toContain('Date column is required.')
    expect(p).toContain('Description column is required.')
    expect(p).toContain('Give Debit + Credit columns, or an Amount column with a Dr/Cr column.')
  })
  it('debit + credit is complete', () => {
    expect(mappingProblems(ok)).toEqual([])
  })
  it('amount + dr/cr is complete', () => {
    expect(mappingProblems({ ...ok, debit_col: '', credit_col: '', amount_col: 'Amt', drcr_col: 'Type' })).toEqual([])
  })
  it('half a pair and both styles are refused', () => {
    expect(mappingProblems({ ...ok, credit_col: '' })).toContain('Debit and Credit columns go together.')
    expect(mappingProblems({ ...ok, amount_col: 'Amt', drcr_col: 'Type' })).toContain('Use either Debit + Credit columns or Amount + Dr/Cr column, not both.')
  })
  it('clean mapping leaves out empty boxes', () => {
    expect(cleanMapping(ok)).toEqual({
      header_row: 1,
      date_col: 'Txn Date',
      date_format: '%d/%m/%Y',
      description_col: 'Narration',
      debit_col: 'Withdrawal',
      credit_col: 'Deposit',
    })
  })
})

describe('reconciliation ticks', () => {
  it('bank credit 5000 ties with book Dr 5000', () => {
    expect(tickTotals([{ debit: '0.00', credit: '5000.00' }], [{ debit: '5000.00', credit: '0.00' }])).toEqual({
      bank: '5000.00',
      book: '5000.00',
      difference: '0.00',
      ties: true,
    })
  })
  it('many to one: cheques 3000.10 + 1999.90 paid, one bank debit 5000.00', () => {
    const t = tickTotals([{ debit: '5000.00', credit: '0.00' }], [{ debit: '0.00', credit: '3000.10' }, { debit: '0.00', credit: '1999.90' }])
    expect(t).toEqual({ bank: '-5000.00', book: '-5000.00', difference: '0.00', ties: true })
  })
  it('difference is bank minus book', () => {
    const t = tickTotals([{ debit: '0.00', credit: '100.00' }], [{ debit: '99.99', credit: '0.00' }])
    expect(t).toEqual({ bank: '100.00', book: '99.99', difference: '0.01', ties: false })
  })
  it('opposite direction does not tie', () => {
    expect(tickTotals([{ debit: '0.00', credit: '100.00' }], [{ debit: '0.00', credit: '100.00' }]).ties).toBe(false)
  })
  it('nothing ticked on one side never ties', () => {
    expect(tickTotals([], []).ties).toBe(false)
    expect(tickTotals([{ debit: '0.00', credit: '0.00' }], []).ties).toBe(false)
  })
})

describe('match body', () => {
  const book = [
    { voucher_line_id: 'v1', date: '2026-04-01', voucher_number: 'R/1', narration: null, reference_no: null, debit: '1.00', credit: '0.00' },
    { opening_item_id: 'o1', date: '2026-04-01', voucher_number: null, narration: null, reference_no: null, debit: '2.00', credit: '0.00' },
    { voucher_line_id: 'v2', date: '2026-04-02', voucher_number: 'R/2', narration: null, reference_no: null, debit: '3.00', credit: '0.00' },
  ]
  it('splits ids by kind', () => {
    expect(matchBody(['b1'], book, ['o1', 'v1'])).toEqual({ bank_line_ids: ['b1'], voucher_line_ids: ['v1'], opening_item_ids: ['o1'] })
  })
  it('toggles', () => {
    expect(toggleId(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggleId(['a', 'b'], 'a')).toEqual(['b'])
  })
})

describe('cash and bank ledgers', () => {
  const list = [
    { id: 1, is_active: true, group_name: 'Bank Accounts' },
    { id: 2, is_active: true, group_name: 'Cash-in-hand' },
    { id: 3, is_active: false, group_name: 'Bank Accounts' },
    { id: 4, is_active: true, group_name: 'Sundry Debtors' },
  ]
  it('cash and bank, active only', () => {
    expect(cashBankLedgers(list).map((l) => l.id)).toEqual([1, 2])
  })
  it('bank only', () => {
    expect(cashBankLedgers(list, true).map((l) => l.id)).toEqual([1])
  })
})
