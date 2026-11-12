// Typed client for docs/API_CONTRACT.md. The base path is /api (Vite proxy strips it in dev).
// Reads send no actor; every write sends header X-User (kept in localStorage).

import { ApiFailure, mapApiError } from './lib/apiError'
import type {
  AgeingReport,
  AutoMatchResult,
  BankFormat,
  BankMapping,
  BankOnlyDraftsResult,
  Brs,
  CashBook,
  MatchBody,
  MsmeDue,
  OpenBill,
  OpeningBillIn,
  OpeningBills,
  OutstandingReport,
  Party,
  PartyBody,
  PartyNature,
  StatementImported,
  StatementLine,
  StatementPreview,
  StatementSummary,
  Unmatched,
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

  // ---- Phase 2 (docs/PHASE2_API_CONTRACT.md) ----
  listParties: (clientId: string, nature?: PartyNature) => get<Party[]>(`/clients/${clientId}/parties`, { nature }),
  saveParty: (clientId: string, ledgerId: string, body: PartyBody) =>
    request<{ ok: boolean }>('PUT', `/clients/${clientId}/parties/${ledgerId}`, { body, write: true }),
  getOpeningBills: (clientId: string, fyId: string, ledgerId: string) =>
    get<OpeningBills>(`/clients/${clientId}/financial-years/${fyId}/opening-bills/${ledgerId}`),
  saveOpeningBills: (clientId: string, fyId: string, ledgerId: string, bills: OpeningBillIn[]) =>
    request<{ ok: boolean }>('PUT', `/clients/${clientId}/financial-years/${fyId}/opening-bills/${ledgerId}`, {
      body: { bills },
      write: true,
    }),
  openBills: (clientId: string, partyLedgerId: string, asOn: string) =>
    get<OpenBill[]>(`/clients/${clientId}/open-bills`, { party_ledger_id: partyLedgerId, as_on: asOn }),
  outstanding: (clientId: string, kind: 'receivable' | 'payable', asOn: string) =>
    get<OutstandingReport>(`/clients/${clientId}/reports/outstanding`, { kind, as_on: asOn }),
  ageing: (clientId: string, kind: 'receivable' | 'payable', asOn: string) =>
    get<AgeingReport>(`/clients/${clientId}/reports/ageing`, { kind, as_on: asOn }),
  cashBook: (clientId: string, ledgerId: string, from: string, to: string) =>
    get<CashBook>(`/clients/${clientId}/reports/cash-book`, { ledger_id: ledgerId, from, to }),
  msmeDue: (clientId: string, asOn: string) => get<MsmeDue>(`/clients/${clientId}/reports/msme-due`, { as_on: asOn }),
  listBankFormats: (clientId: string) => get<BankFormat[]>(`/clients/${clientId}/bank-formats`),
  createBankFormat: (clientId: string, name: string, mapping: BankMapping) =>
    post<{ format_id: string }>(`/clients/${clientId}/bank-formats`, { name, mapping }),
  previewStatement: (clientId: string, file: File, formatId: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('format_id', formatId)
    return request<StatementPreview>('POST', `/clients/${clientId}/bank-statements/preview`, { form, write: true })
  },
  importStatement: (clientId: string, file: File, bankLedgerId: string, formatId: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('bank_ledger_id', bankLedgerId)
    form.append('format_id', formatId)
    return request<StatementImported>('POST', `/clients/${clientId}/bank-statements`, { form, write: true })
  },
  listStatements: (clientId: string, bankLedgerId?: string) =>
    get<StatementSummary[]>(`/clients/${clientId}/bank-statements`, { bank_ledger_id: bankLedgerId }),
  statementLines: (statementId: string) => get<StatementLine[]>(`/bank-statements/${statementId}/lines`),
  deleteStatement: (statementId: string) => request<void>('DELETE', `/bank-statements/${statementId}`, { write: true }),
  unmatched: (clientId: string, bankLedgerId: string, asOn: string) =>
    get<Unmatched>(`/clients/${clientId}/reconciliation/${bankLedgerId}/unmatched`, { as_on: asOn }),
  autoMatch: (clientId: string, bankLedgerId: string, asOn: string) =>
    post<AutoMatchResult>(`/clients/${clientId}/reconciliation/${bankLedgerId}/auto-match`, { as_on: asOn }),
  createMatch: (clientId: string, bankLedgerId: string, body: MatchBody) =>
    post<{ match_id: string }>(`/clients/${clientId}/reconciliation/${bankLedgerId}/matches`, body),
  deleteMatch: (clientId: string, matchId: string) =>
    request<void>('DELETE', `/clients/${clientId}/reconciliation/matches/${matchId}`, { write: true }),
  brs: (clientId: string, bankLedgerId: string, asOn: string) =>
    get<Brs>(`/clients/${clientId}/reconciliation/${bankLedgerId}/brs`, { as_on: asOn }),
  bankOnlyDrafts: (clientId: string, bankLedgerId: string, items: { bank_line_id: string; counter_ledger_id: string }[]) =>
    post<BankOnlyDraftsResult>(`/clients/${clientId}/reconciliation/${bankLedgerId}/bank-only-drafts`, { items }),
}

export { ApiFailure }
