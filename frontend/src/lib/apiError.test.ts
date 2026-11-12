import { describe, expect, it } from 'vitest'
import { errorsForLine, mapApiError, voucherLevelErrors } from './apiError'

describe('mapApiError', () => {
  it('maps the voucher rule errors list', () => {
    const f = mapApiError(422, {
      errors: [
        { rule_id: 'V-04', message: 'Debit 10,000.00 and Credit 9,000.00 are not equal (difference 1,000.00)', line_no: null },
        { rule_id: 'V-05', message: "Line 2: ledger 'Cash' is inactive.", line_no: 2 },
      ],
    })
    expect(f.status).toBe(422)
    expect(f.code).toBe('rule_violation')
    expect(f.ruleErrors).toHaveLength(2)
    expect(f.message).toContain('are not equal')
    expect(voucherLevelErrors(f.ruleErrors).map((e) => e.rule_id)).toEqual(['V-04'])
    expect(errorsForLine(f.ruleErrors, 2).map((e) => e.rule_id)).toEqual(['V-05'])
    expect(errorsForLine(f.ruleErrors, 1)).toEqual([])
  })
  it('maps a ServiceError body with details', () => {
    const f = mapApiError(409, { code: 'period_has_open_vouchers', message: 'cannot be locked', details: [{ voucher_id: 'x' }] })
    expect(f).toMatchObject({ status: 409, code: 'period_has_open_vouchers', message: 'cannot be locked' })
    expect(f.details).toEqual([{ voucher_id: 'x' }])
    expect(f.ruleErrors).toEqual([])
  })
  it('maps FastAPI request validation errors', () => {
    const f = mapApiError(422, { detail: [{ loc: ['body', 'lines', 0, 'debit'], msg: 'Input should be a valid string' }] })
    expect(f.code).toBe('invalid_request')
    expect(f.message).toBe('lines > 0 > debit: Input should be a valid string')
  })
  it('falls back to readable text', () => {
    expect(mapApiError(500, null).message).toBe('Request failed (HTTP 500).')
    expect(mapApiError(0, null).message).toBe('The server is not reachable.')
    expect(mapApiError(404, { detail: 'Not Found' }).message).toBe('Not Found')
  })
})
