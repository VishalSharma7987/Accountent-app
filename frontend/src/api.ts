// Typed client for docs/API_CONTRACT.md. The base path is /api (Vite proxy strips it in dev).
// Reads send no actor; every write sends header X-User (kept in localStorage).

import { ApiFailure, mapApiError } from './lib/apiError'
import type {
  AuditEntry,
  ClientDetail,
  ClientSummary,
  CreateClientBody,
  CreatedClient,
  DryRun,
  GroupNode,
  ImportCommit,
  LedgerRow,
  LedgerStatement,
  OpeningBalances,
  Period,
  TrialBalance,
  Voucher,
  VoucherFilters,
  VoucherIn,
  VoucherList,
} from './types'

// Deployed: VITE_API_URL is the backend root (e.g. https://accountent-app.onrender.com).
// Local dev: unset, so calls go to /api and the Vite proxy forwards them to the backend.
export const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '') || '/api'
const USER_KEY = 'ledgermind.user'

export function getUser(): string {
  try {
    return localStorage.getItem(USER_KEY) ?? ''
  } catch {
    return ''
  }
}
export function setUser(name: string): void {
  try {
    localStorage.setItem(USER_KEY, name)
  } catch {
    /* storage unavailable: the field simply is not remembered */
  }
}

type Query = Record<string, string | number | boolean | undefined | null>

function url(path: string, query?: Query): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const text = qs.toString()
  return `${API_BASE}${path}${text ? `?${text}` : ''}`
}

interface Options {
  query?: Query
  body?: unknown
  form?: FormData
  write?: boolean
}

async function request<T>(method: string, path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (opts.write) headers['X-User'] = getUser()
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let response: Response
  try {
    response = await fetch(url(path, opts.query), { method, headers, body })
  } catch {
    throw mapApiError(0, null)
  }
  if (response.status === 204) return undefined as T
  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    parsed = null
  }
  if (!response.ok) throw mapApiError(response.status, parsed)
  return parsed as T
}

const get = <T>(path: string, query?: Query) => request<T>('GET', path, { query })
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, { body: body ?? {}, write: true })

export const api = {
  // clients
  createClient: (body: CreateClientBody) => post<CreatedClient>('/clients', body),
  listClients: () => get<ClientSummary[]>('/clients'),
  getClient: (id: string) => get<ClientDetail>(`/clients/${id}`),
  // groups and ledgers
  listGroups: (clientId: string) => get<GroupNode[]>(`/clients/${clientId}/groups`),
  listLedgers: (clientId: string, asOn?: string) => get<LedgerRow[]>(`/clients/${clientId}/ledgers`, { as_on: asOn }),
  createLedger: (clientId: string, body: { name: string; group_code: string }) =>
    post<{ ledger_id: string }>(`/clients/${clientId}/ledgers`, body),
  deactivateLedger: (clientId: string, ledgerId: string) =>
    post<{ ok: boolean }>(`/clients/${clientId}/ledgers/${ledgerId}/deactivate`),
  getOpeningBalances: (clientId: string, fyId: string) =>
    get<OpeningBalances>(`/clients/${clientId}/financial-years/${fyId}/opening-balances`),
  setOpeningBalance: (clientId: string, fyId: string, ledgerId: string, body: { debit?: string; credit?: string }) =>
    request<{ ok: boolean }>('PUT', `/clients/${clientId}/financial-years/${fyId}/opening-balances/${ledgerId}`, {
      body,
      write: true,
    }),
  // vouchers
  createVoucher: (clientId: string, body: VoucherIn) =>
    post<{ voucher_id: string }>(`/clients/${clientId}/vouchers`, body),
  listVouchers: (clientId: string, filters: VoucherFilters = {}) =>
    get<VoucherList>(`/clients/${clientId}/vouchers`, { ...filters }),
  getVoucher: (id: string) => get<Voucher>(`/vouchers/${id}`),
  updateVoucher: (id: string, body: VoucherIn) =>
    request<{ voucher_id: string }>('PUT', `/vouchers/${id}`, { body, write: true }),
  deleteVoucher: (id: string) => request<void>('DELETE', `/vouchers/${id}`, { write: true }),
  approveVoucher: (id: string) => post<{ ok: boolean }>(`/vouchers/${id}/approve`),
  returnToDraft: (id: string) => post<{ ok: boolean }>(`/vouchers/${id}/return-to-draft`),
  postVoucher: (id: string) => post<{ voucher_number: string }>(`/vouchers/${id}/post`),
  reverseVoucher: (id: string, body: { reversal_date: string; reason: string }) =>
    post<{ reversal_voucher_id: string }>(`/vouchers/${id}/reverse`, body),
  // periods
  listPeriods: (clientId: string, fyId?: string) => get<Period[]>(`/clients/${clientId}/periods`, { fy_id: fyId }),
  lockPeriod: (clientId: string, periodId: string) => post<{ ok: boolean }>(`/clients/${clientId}/periods/${periodId}/lock`),
  unlockPeriod: (clientId: string, periodId: string, reason: string) =>
    post<{ ok: boolean }>(`/clients/${clientId}/periods/${periodId}/unlock`, { reason }),
  // reports
  ledgerStatement: (clientId: string, ledgerId: string, from: string, to: string) =>
    get<LedgerStatement>(`/clients/${clientId}/reports/ledger-statement`, { ledger_id: ledgerId, from, to }),
  trialBalance: (clientId: string, asOn: string, hideZero = false) =>
    get<TrialBalance>(`/clients/${clientId}/reports/trial-balance`, { as_on: asOn, hide_zero: hideZero }),
  auditLog: (clientId: string, entity?: string, entityId?: string, limit?: number) =>
    get<AuditEntry[]>(`/clients/${clientId}/audit-log`, { entity, entity_id: entityId, limit }),
  // Excel import
  importTemplateUrl: (clientId: string) => url(`/clients/${clientId}/imports/vouchers/template`),
  importDryRun: (clientId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DryRun>('POST', `/clients/${clientId}/imports/vouchers/dry-run`, { form, write: true })
  },
  importCommit: (clientId: string, file: File, refIds: string[]) => {
    const form = new FormData()
    form.append('file', file)
    form.append('ref_ids', refIds.join(','))
    return request<ImportCommit>('POST', `/clients/${clientId}/imports/vouchers/commit`, { form, write: true })
  },
}

export { ApiFailure }
