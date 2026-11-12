// Amounts are decimal STRINGS end to end ("12500.00"). Nothing here uses floating point.
// Used for DISPLAY only: the server is the only place that decides what an amount means.

const PLAIN = /^-?\d+(\.\d+)?$/

/** Strip thousands separators and spaces a user may type; does not validate. */
export function cleanTyped(text: string): string {
  return text.replace(/[,\s]/g, '')
}

/** Indian digit grouping with 2 decimals: "10000" -> "10,000.00", "123456789.5" -> "12,34,56,789.50". */
export function formatInr(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return ''
  const text = cleanTyped(amount)
  if (!PLAIN.test(text)) return amount // not a number: show it as typed
  const negative = text.startsWith('-')
  const body = negative ? text.slice(1) : text
  const [whole, fraction = ''] = body.split('.')
  const head = whole.slice(0, -3)
  const tail = whole.slice(-3)
  const groups = head ? head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + tail : tail
  const decimals = (fraction + '00').slice(0, Math.max(2, fraction.length))
  return `${negative ? '-' : ''}${groups}.${decimals}`
}

/** A balance as the API returns it: amount + side ("Dr" | "Cr" | null for nil). */
export function formatBalance(balance: { amount: string; side: 'Dr' | 'Cr' | null }): string {
  return balance.side ? `${formatInr(balance.amount)} ${balance.side}` : formatInr(balance.amount)
}

/** Parse a typed amount to integer paise (BigInt), or null when it is not a plain number of at most 2 decimals. */
export function toPaise(text: string): bigint | null {
  const cleaned = cleanTyped(text)
  if (cleaned === '') return 0n
  if (!/^-?\d+(\.\d{0,2})?$/.test(cleaned)) return null
  const negative = cleaned.startsWith('-')
  const [whole, fraction = ''] = (negative ? cleaned.slice(1) : cleaned).split('.')
  const value = BigInt(whole) * 100n + BigInt((fraction + '00').slice(0, 2))
  return negative ? -value : value
}

export function fromPaise(paise: bigint): string {
  const negative = paise < 0n
  const abs = negative ? -paise : paise
  const whole = abs / 100n
  const fraction = (abs % 100n).toString().padStart(2, '0')
  return `${negative ? '-' : ''}${whole}.${fraction}`
}

export interface Sum {
  total: string // "0.00" when nothing readable
  invalid: boolean // true when some entry is not a plain amount (the total ignores it)
}

/** Add decimal strings exactly (integer paise). Blank entries count as zero. */
export function sumAmounts(values: string[]): Sum {
  let total = 0n
  let invalid = false
  for (const v of values) {
    const paise = toPaise(v)
    if (paise === null) invalid = true
    else total += paise
  }
  return { total: fromPaise(total), invalid }
}

/** a - b as a decimal string, exact. Unreadable inputs count as zero. */
export function subtractAmounts(a: string, b: string): string {
  return fromPaise((toPaise(a) ?? 0n) - (toPaise(b) ?? 0n))
}

export function isNilAmount(amount: string): boolean {
  return (toPaise(amount) ?? 1n) === 0n
}
