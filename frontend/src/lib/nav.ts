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
