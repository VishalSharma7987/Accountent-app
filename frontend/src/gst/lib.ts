// Pure display helpers for the GST screens. No tax is computed here: the server decides every figure.
import type { GstIn, GstItemIn, GstVoucherBody, Registration, ReturnQuery, RuleWorst } from '../api/gst'

export const LEDGER_ROLES: { key: string; label: string }[] = [
  { key: 'output_cgst', label: 'Output CGST' },
  { key: 'output_sgst', label: 'Output SGST / UTGST' },
  { key: 'output_igst', label: 'Output IGST' },
  { key: 'output_cess', label: 'Output Cess' },
  { key: 'input_cgst', label: 'Input CGST' },
  { key: 'input_sgst', label: 'Input SGST / UTGST' },
  { key: 'input_igst', label: 'Input IGST' },
  { key: 'input_cess', label: 'Input Cess' },
  { key: 'rcm_cgst', label: 'RCM payable CGST' },
  { key: 'rcm_sgst', label: 'RCM payable SGST / UTGST' },
  { key: 'rcm_igst', label: 'RCM payable IGST' },
  { key: 'rcm_cess', label: 'RCM payable Cess' },
  { key: 'round_off', label: 'Round off' },
  { key: 'itc_reversal', label: 'ITC reversal (expense)' },
  { key: 'composition_tax_expense', label: 'Composition tax expense' },
  { key: 'composition_tax_payable', label: 'Composition tax payable' },
]

export const SUPPLY_CATEGORIES: { value: string; label: string }[] = [
  { value: 'b2b', label: 'B2B (registered)' },
  { value: 'b2c', label: 'B2C (unregistered)' },
  { value: 'sez_with_payment', label: 'SEZ with payment' },
  { value: 'sez_without_payment', label: 'SEZ without payment' },
  { value: 'export_with_payment', label: 'Export with payment' },
  { value: 'export_without_payment', label: 'Export without payment (LUT)' },
  { value: 'deemed_export', label: 'Deemed export' },
  { value: 'unregistered_supplier', label: 'Purchase from unregistered supplier' },
  { value: 'composition_supplier', label: 'Purchase from composition supplier' },
  { value: 'import_of_service', label: 'Import of service' },
]

export const RULE_BADGE: Record<RuleWorst, { label: string; cls: string }> = {
  pending: { label: 'Rules pending verification', cls: 'bg-amber-100 text-amber-900 border-amber-400' },
  secondary_verified: { label: 'Rules verified from a secondary source', cls: 'bg-yellow-50 text-yellow-900 border-yellow-300' },
  verified: { label: 'Rules verified', cls: 'bg-green-100 text-green-900 border-green-400' },
}

export function ruleBadge(worst: RuleWorst | string | undefined | null): { label: string; cls: string } {
  if (worst && worst in RULE_BADGE) return RULE_BADGE[worst as RuleWorst]
  // an unknown or missing status is shown as pending, never as verified
  return RULE_BADGE.pending
}

const AMOUNT = /^-?\d+\.\d{2}$/
export function isAmountText(v: unknown): v is string {
  return typeof v === 'string' && AMOUNT.test(v)
}

/** "2026-05" -> "2026-04-01" (Indian financial-year quarters: Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar). */
export function quarterStart(month: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(month)
  if (!m) return ''
  const year = Number(m[1])
  const mon = Number(m[2])
  const first = mon >= 4 ? 4 + Math.floor((mon - 4) / 3) * 3 : 1
  return `${year}-${String(first).padStart(2, '0')}-01`
}

export const isMonth = (v: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(v)

/** Quarterly for QRMP and composition registrations (period_start = first month of the quarter), else monthly. */
export function isQuarterly(reg: Pick<Registration, 'registration_type' | 'return_frequency'> | undefined): boolean {
  return !!reg && (reg.registration_type === 'composition' || reg.return_frequency === 'qrmp')
}

/** Build the return query from a typed month ("YYYY-MM") and the registration. */
export function returnQuery(reg: Registration | undefined, month: string): ReturnQuery | null {
  if (!reg || !isMonth(month)) return null
  return isQuarterly(reg)
    ? { registration_id: reg.id, period_start: quarterStart(month), period_kind: 'quarter' }
    : { registration_id: reg.id, period_start: `${month}-01`, period_kind: 'month' }
}

export function titleCase(key: string): string {
  const text = key.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export type Shape = { kind: 'scalar' } | { kind: 'rows'; columns: string[] } | { kind: 'record' } | { kind: 'empty' }

/** How the generic table viewer draws a value: array of records, one record, or a plain value. */
export function shapeOf(value: unknown): Shape {
  if (Array.isArray(value)) {
    if (value.length === 0) return { kind: 'empty' }
    const cols: string[] = []
    for (const row of value) {
      if (row && typeof row === 'object' && !Array.isArray(row)) {
        for (const k of Object.keys(row)) if (!cols.includes(k)) cols.push(k)
      } else return { kind: 'scalar' }
    }
    return { kind: 'rows', columns: cols }
  }
  if (value && typeof value === 'object') return Object.keys(value).length ? { kind: 'record' } : { kind: 'empty' }
  return { kind: 'scalar' }
}

export const CLASS_LABEL: Record<string, string> = {
  matched: 'Matched',
  value_mismatch: 'Value mismatch',
  gstin_mismatch: 'GSTIN mismatch',
  period_mismatch: 'Period mismatch',
  only_in_books: 'Only in books',
  only_in_2b: 'Only in 2B',
  ambiguous: 'Ambiguous',
}

/** Roles a registration still has no ledger for (drives the "map ledgers" warning). */
export function missingRoles(reg: Pick<Registration, 'ledger_roles' | 'registration_type'>): string[] {
  const needed =
    reg.registration_type === 'composition'
      ? ['composition_tax_expense', 'composition_tax_payable']
      : LEDGER_ROLES.map((r) => r.key).filter((k) => !k.startsWith('composition_'))
  return needed.filter((k) => !reg.ledger_roles[k])
}

export const blankGstItem = (): GstItemIn => ({
  item_id: null,
  description: '',
  hsn_sac: '',
  uqc: null,
  quantity: '1',
  unit_rate: '',
  discount: '0',
  ledger_id: '',
  rcm_category_key: null,
  itc_category_key: null,
  itc_exception_claimed: false,
  itc_exception_note: null,
})

/** An item row is ready for the server preview when the typed numbers are plain and a ledger and HSN are chosen. */
export function itemReady(i: GstItemIn): boolean {
  return i.ledger_id !== '' && i.hsn_sac.trim() !== '' && /^\d+(\.\d{1,3})?$/.test(i.quantity) && /^\d+(\.\d{1,4})?$/.test(i.unit_rate)
}

/** Only item rows the user has started are sent; null while nothing can be previewed yet. */
export function previewBody(base: Omit<GstVoucherBody, 'gst'>, gst: GstIn): GstVoucherBody | null {
  if (!gst.gst_registration_id || !gst.place_of_supply) return null
  const items = gst.items.filter(itemReady)
  if (items.length === 0 || items.length !== gst.items.filter((i) => i.description || i.hsn_sac || i.unit_rate || i.ledger_id).length) return null
  return { ...base, gst: { ...gst, items } }
}
