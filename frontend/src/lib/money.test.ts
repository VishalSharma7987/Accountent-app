import { describe, expect, it } from 'vitest'
import { formatBalance, formatInr, fromPaise, isNilAmount, subtractAmounts, sumAmounts, toPaise } from './money'

describe('formatInr (Indian grouping)', () => {
  it.each([
    ['0', '0.00'],
    ['5', '5.00'],
    ['999.99', '999.99'],
    ['1000', '1,000.00'],
    ['10000', '10,000.00'],
    ['100000', '1,00,000.00'],
    ['1234567.89', '12,34,567.89'],
    ['123456789.5', '12,34,56,789.50'],
    ['1000000000', '1,00,00,00,000.00'],
    ['-100000', '-1,00,000.00'],
    ['99999999999999.99', '9,99,99,99,99,99,999.99'],
    ['15000.00', '15,000.00'],
  ])('%s -> %s', (given, expected) => {
    expect(formatInr(given)).toBe(expected)
  })
  it('shows blanks and non-numbers as typed', () => {
    expect(formatInr('')).toBe('')
    expect(formatInr(null)).toBe('')
    expect(formatInr('abc')).toBe('abc')
  })
  it('formats balances with their side', () => {
    expect(formatBalance({ amount: '325000.00', side: 'Dr' })).toBe('3,25,000.00 Dr')
    expect(formatBalance({ amount: '35000.00', side: 'Cr' })).toBe('35,000.00 Cr')
    expect(formatBalance({ amount: '0.00', side: null })).toBe('0.00')
  })
})

describe('exact decimal-string arithmetic (integer paise, no floats)', () => {
  it('parses typed amounts to paise', () => {
    expect(toPaise('10.5')).toBe(1050n)
    expect(toPaise('1,00,000.25')).toBe(10000025n)
    expect(toPaise('')).toBe(0n)
    expect(toPaise('-0.01')).toBe(-1n)
    expect(toPaise('10.005')).toBeNull()
    expect(toPaise('abc')).toBeNull()
  })
  it('converts paise back to strings', () => {
    expect(fromPaise(1050n)).toBe('10.50')
    expect(fromPaise(5n)).toBe('0.05')
    expect(fromPaise(-1n)).toBe('-0.01')
    expect(fromPaise(0n)).toBe('0.00')
  })
  it('adds without the floating-point trap', () => {
    expect(sumAmounts(['0.10', '0.20'])).toEqual({ total: '0.30', invalid: false })
    expect(sumAmounts(['10000', '', '2,500.50'])).toEqual({ total: '12500.50', invalid: false })
    expect(sumAmounts(['99999999999999.99', '0.01'])).toEqual({ total: '100000000000000.00', invalid: false })
  })
  it('flags unreadable entries and ignores them in the total', () => {
    expect(sumAmounts(['10', 'x', '5.005'])).toEqual({ total: '10.00', invalid: true })
  })
  it('subtracts exactly and detects nil', () => {
    expect(subtractAmounts('10000.00', '9000.00')).toBe('1000.00')
    expect(subtractAmounts('0.30', '0.10')).toBe('0.20')
    expect(subtractAmounts('1', '2.50')).toBe('-1.50')
    expect(isNilAmount('0.00')).toBe(true)
    expect(isNilAmount('0.01')).toBe(false)
  })
})
