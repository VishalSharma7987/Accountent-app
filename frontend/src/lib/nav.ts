// Sidebar navigation config. To add a group later (GST, TDS, Audit, Final accounts),
// append ONE entry to NAV_GROUPS and add its route in App.tsx. Only link routes that exist.
export interface NavItem {
  to: string
  label: string
  /** match the path exactly (needed where one route is a prefix of another) */
  end?: boolean
}
export interface NavGroup {
  id: string
  label: string
  icon: string // short text glyph, shown in the narrow sidebar
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'masters',
    label: 'Masters',
    icon: 'M',
    items: [
      { to: '/clients', label: 'Clients' },
      { to: '/ledgers', label: 'Ledgers' },
      { to: '/parties', label: 'Parties' },
      { to: '/periods', label: 'Periods' },
    ],
  },
  {
    id: 'transactions',
    label: 'Transactions',
    icon: 'T',
    items: [
      { to: '/vouchers/new', label: 'New voucher', end: true },
      { to: '/vouchers', label: 'Vouchers', end: true },
      { to: '/import', label: 'Excel import' },
    ],
  },
  {
    id: 'banking',
    label: 'Banking',
    icon: 'B',
    items: [
      { to: '/bank', label: 'Bank statements' },
      { to: '/reconciliation', label: 'Reconciliation' },
      { to: '/brs', label: 'BRS report' },
      { to: '/cash-book', label: 'Cash / Bank book' },
    ],
  },
  {
    id: 'receivables',
    label: 'Receivables & Payables',
    icon: 'R',
    items: [
      { to: '/opening-bills', label: 'Opening bills' },
      { to: '/outstanding', label: 'Outstanding / ageing' },
      { to: '/msme', label: 'MSME dues' },
    ],
  },
  {
    id: 'reports',
    label: 'Reports',
    icon: 'P',
    items: [
      { to: '/statement', label: 'Ledger statement' },
      { to: '/trial-balance', label: 'Trial Balance' },
    ],
  },
  {
    id: 'gst',
    label: 'GST',
    icon: 'G',
    items: [
      { to: '/gst/registrations', label: 'Registrations' },
      { to: '/gst/items', label: 'Item master (HSN)' },
      { to: '/gst/invoice', label: 'GST invoice' },
      { to: '/gst/itc', label: 'ITC register' },
      { to: '/gst/2b', label: 'GSTR-2B reconciliation' },
      { to: '/gst/gstr1', label: 'GSTR-1 working' },
      { to: '/gst/gstr3b', label: 'GSTR-3B working' },
      { to: '/gst/tie-out', label: 'Tie-out' },
      { to: '/gst/composition', label: 'Composition' },
      { to: '/gst/workings', label: 'Saved workings' },
      { to: '/gst/rules', label: 'GST rules' },
    ],
  },
  {
    id: 'tds',
    label: 'TDS',
    icon: 'D',
    items: [
      { to: '/tds/deductees', label: 'Deductees and masters' },
      { to: '/tds/entry', label: 'Voucher with TDS' },
      { to: '/tds/register', label: 'TDS register' },
      { to: '/tds/challans', label: 'Challans and interest' },
      { to: '/tds/returns', label: 'Returns and certificates' },
      { to: '/tds/26as', label: '26AS reconciliation' },
      { to: '/tds/rules', label: 'TDS rules' },
    ],
  },
  {
    id: 'inventory',
    label: 'Inventory',
    icon: 'I',
    items: [
      { to: '/inventory/masters', label: 'Godowns, items, opening' },
      { to: '/inventory/policy', label: 'Valuation policy' },
      { to: '/inventory/journals', label: 'Stock journals' },
      { to: '/inventory/register', label: 'Stock register' },
      { to: '/inventory/closing-stock', label: 'Closing stock (NRV)' },
    ],
  },
  {
    id: 'final',
    label: 'Final accounts',
    icon: 'F',
    items: [
      { to: '/final/setup', label: 'Setup: ledgers, partners' },
      { to: '/final/adjustments', label: 'Year-end adjustments' },
      { to: '/final/assets', label: 'Fixed assets and depreciation' },
      { to: '/final/closing-stock', label: 'Closing stock approval' },
      { to: '/final/statements', label: 'Trading, P&L, Balance Sheet' },
      { to: '/final/sch3', label: 'Schedule III (company)' },
      { to: '/final/cash-flow', label: 'Cash Flow Statement' },
      { to: '/final/export', label: 'Export (Excel / PDF)' },
      { to: '/final/close', label: 'Year-end close' },
    ],
  },
]

function matches(item: NavItem, path: string): boolean {
  if (item.end) return path === item.to
  return path === item.to || path.startsWith(item.to + '/')
}

/** The item for a path; the longest matching route wins. A voucher detail page (/vouchers/:id) counts as Vouchers. */
export function findNav(path: string, groups: NavGroup[] = NAV_GROUPS): { group: NavGroup; item: NavItem } | null {
  let best: { group: NavGroup; item: NavItem } | null = null
  for (const group of groups)
    for (const item of group.items) {
      const hit = matches(item, path) || (item.to === '/vouchers' && path.startsWith('/vouchers/') && path !== '/vouchers/new')
      if (hit && (!best || item.to.length > best.item.to.length)) best = { group, item }
    }
  return best
}

/** Open groups after a header click. */
export function toggleGroup(open: string[], id: string): string[] {
  return open.includes(id) ? open.filter((g) => g !== id) : [...open, id]
}
