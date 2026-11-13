import { useState } from 'react'
import { api } from '../api'
import { tdsApi, type Cert, type Deductee, type DeducteeBody, type LedgerRole, type PanStatus } from '../api/tds'
import { ErrorBox, Field, LedgerPicker, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR, Amount } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient, Row, Tabs, useFy } from './common'
import { useNatures } from './hooks'
import { DEDUCTEE_TYPES, LEDGER_ROLES, PAN_STATUSES, fyLabel, panBadge } from './lib'

type Tab = 'deductees' | 'roles' | 'profile'

/** Masters for TDS: deductees (PAN, certificates), ledger roles, TAN and the 194Q buyer flag. */
export default function Deductees() {
  const { clientId } = useClient()
  const [tab, setTab] = useState<Tab>('deductees')
  if (!clientId) return <Page title="TDS masters"><NoClient /></Page>
  return (
    <Page title="TDS masters">
      <Tabs
        tabs={[
          { key: 'deductees', label: 'Deductees and certificates' },
          { key: 'roles', label: 'Ledger roles' },
          { key: 'profile', label: 'TAN and 194Q flag' },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'deductees' && <DeducteeTab clientId={clientId} />}
      {tab === 'roles' && <RolesTab clientId={clientId} />}
      {tab === 'profile' && <ProfileTab clientId={clientId} />}
    </Page>
  )
}

const blankBody = (): DeducteeBody => ({ pan: '', pan_status: 'valid', deductee_type: 'individual', default_nature_key: null, is_active: true })

function DeducteeTab({ clientId }: { clientId: string }) {
  const [q, setQ] = useState('')
  const list = useLoad(() => tdsApi.listDeductees(clientId, q), `tds-ded:${clientId}:${q}`)
  const ledgers = useLoad(() => api.listLedgers(clientId), `ledgers:${clientId}`)
  const natures = useNatures()
  const [ledgerId, setLedgerId] = useState('')
  const [body, setBody] = useState<DeducteeBody>(blankBody())
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState('')

  const edit = (d: Deductee) => {
    setLedgerId(d.ledger_id)
    setBody({ pan: d.pan ?? '', pan_status: d.pan_status, deductee_type: d.deductee_type, default_nature_key: d.default_nature_key, is_active: d.is_active })
  }
  const save = async () => {
    setError(null)
    setNotice('')
    try {
      await tdsApi.putDeductee(clientId, ledgerId, { ...body, pan: body.pan_status === 'valid' || body.pan_status === 'invalid' ? (body.pan ?? '').toUpperCase() : null, default_nature_key: body.default_nature_key || null })
      setNotice('Saved.')
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }

  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
        <Row>
          <Field label="Party ledger">
            <div className="w-64">
              <LedgerPicker ledgers={ledgers.data ?? []} value={ledgerId} onChange={setLedgerId} placeholder="Supplier / contractor" />
            </div>
          </Field>
          <Field label="PAN status">
            <select className={input} value={body.pan_status} onChange={(e) => setBody({ ...body, pan_status: e.target.value as PanStatus })}>
              {PAN_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="PAN">
            <input className={`${input} w-32 uppercase`} maxLength={10} disabled={body.pan_status === 'missing' || body.pan_status === 'applied_for'} value={body.pan ?? ''} onChange={(e) => setBody({ ...body, pan: e.target.value })} />
          </Field>
          <Field label="Deductee type">
            <select className={input} value={body.deductee_type} onChange={(e) => setBody({ ...body, deductee_type: e.target.value })}>
              {DEDUCTEE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Usual nature (optional)">
            <select className={input} value={body.default_nature_key ?? ''} onChange={(e) => setBody({ ...body, default_nature_key: e.target.value || null })}>
              <option value="">(none)</option>
              {natures.options.map((n) => (
                <option key={n.key} value={n.key}>
                  {n.label}
                </option>
              ))}
            </select>
          </Field>
          <label className="flex items-center gap-1 pb-1 text-sm">
            <input type="checkbox" checked={body.is_active ?? true} onChange={(e) => setBody({ ...body, is_active: e.target.checked })} /> Active
          </label>
          <button className={btnPrimary} disabled={!ledgerId} onClick={save}>
            Save deductee
          </button>
        </Row>
        <ErrorBox error={error} />
        {notice && <Notice>{notice}</Notice>}
      </div>
      <Field label="Search deductees">
        <input className={`${input} w-64`} value={q} onChange={(e) => setQ(e.target.value)} />
      </Field>
      <ErrorBox error={list.error} />
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Deductee</th>
            <th className={th}>PAN</th>
            <th className={th}>Status</th>
            <th className={th}>Type</th>
            <th className={th}>Usual nature</th>
            <th className={th}>Certificates</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((d) => {
            const b = panBadge(d.pan_status)
            return (
              <FragmentRow key={d.ledger_id}>
                <tr className={d.is_active ? '' : 'text-slate-400'}>
                  <td className={td}>{d.ledger_name}</td>
                  <td className={`${td} font-mono`}>{d.pan ?? '-'}</td>
                  <td className={td}>
                    <span className={`rounded border px-2 py-0.5 text-xs ${b.cls}`}>{b.label}</span>
                    {d.pan_warning && <div className="text-xs text-amber-800">{d.pan_warning}</div>}
                  </td>
                  <td className={td}>{d.deductee_type}</td>
                  <td className={td}>{d.default_nature_key ?? '-'}</td>
                  <td className={td}>{d.lower_certs.length}</td>
                  <td className={td}>
                    <button className={btn} onClick={() => edit(d)}>
                      Edit
                    </button>{' '}
                    <button className={btn} onClick={() => setOpen(open === d.ledger_id ? '' : d.ledger_id)}>
                      Certificates
                    </button>
                  </td>
                </tr>
                {open === d.ledger_id && (
                  <tr>
                    <td colSpan={7} className="bg-slate-50 p-2">
                      <Certs clientId={clientId} deductee={d} natures={natures.options} onChanged={list.reload} />
                    </td>
                  </tr>
                )}
              </FragmentRow>
            )
          })}
          {list.data?.length === 0 && (
            <tr>
              <td colSpan={7} className={`${td} text-slate-500`}>
                No deductees yet. Choose a party ledger above and save its PAN details.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function FragmentRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

function Certs({ clientId, deductee, natures, onChanged }: { clientId: string; deductee: Deductee; natures: { key: string; label: string }[]; onChanged: () => void }) {
  const certs = useLoad(() => tdsApi.listCerts(clientId, deductee.ledger_id), `tds-certs:${deductee.ledger_id}`)
  const [f, setF] = useState({ certificate_no: '', nature_key: '', rate: '', max_amount: '', valid_from: '', valid_to: '', note: '' })
  const [error, setError] = useState<ApiFailure | null>(null)
  const add = async () => {
    setError(null)
    try {
      await tdsApi.addCert(clientId, deductee.ledger_id, { ...f, nature_key: f.nature_key || null })
      setF({ certificate_no: '', nature_key: '', rate: '', max_amount: '', valid_from: '', valid_to: '', note: '' })
      certs.reload()
      onChanged()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const toggle = async (c: Cert) => {
    setError(null)
    try {
      await tdsApi.updateCert(clientId, deductee.ledger_id, c.id, { is_active: !c.is_active })
      certs.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold">Lower / nil deduction certificates of {deductee.ledger_name}</div>
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Certificate no</th>
            <th className={th}>Nature</th>
            <th className={thR}>Rate %</th>
            <th className={thR}>Limit</th>
            <th className={thR}>Used</th>
            <th className={thR}>Left</th>
            <th className={th}>Valid</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(certs.data ?? []).map((c) => (
            <tr key={c.id} className={c.is_active ? '' : 'text-slate-400'}>
              <td className={td}>{c.certificate_no}</td>
              <td className={td}>{c.nature_key ?? 'any'}</td>
              <td className={tdR}>{c.rate}</td>
              <td className={tdR}><Amount value={c.max_amount} /></td>
              <td className={tdR}><Amount value={c.amount_used} /></td>
              <td className={tdR}><Amount value={c.amount_left} /></td>
              <td className={td}>
                {c.valid_from} to {c.valid_to}
              </td>
              <td className={td}>
                <button className={btn} onClick={() => toggle(c)}>
                  {c.is_active ? 'Deactivate' : 'Activate'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Row>
        <Field label="Certificate no">
          <input className={`${input} w-32`} value={f.certificate_no} onChange={(e) => setF({ ...f, certificate_no: e.target.value })} />
        </Field>
        <Field label="Nature">
          <select className={input} value={f.nature_key} onChange={(e) => setF({ ...f, nature_key: e.target.value })}>
            <option value="">(any)</option>
            {natures.map((n) => (
              <option key={n.key} value={n.key}>
                {n.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Rate % (0 = nil)">
          <input className={`${input} w-20 text-right`} value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} />
        </Field>
        <Field label="Limit (amount)">
          <input className={`${input} w-28 text-right`} value={f.max_amount} onChange={(e) => setF({ ...f, max_amount: e.target.value })} />
        </Field>
        <Field label="Valid from">
          <input type="date" className={input} value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} />
        </Field>
        <Field label="Valid to">
          <input type="date" className={input} value={f.valid_to} onChange={(e) => setF({ ...f, valid_to: e.target.value })} />
        </Field>
        <button className={btn} onClick={add}>
          Add certificate
        </button>
      </Row>
      <ErrorBox error={error} />
    </div>
  )
}

function RolesTab({ clientId }: { clientId: string }) {
  const roles = useLoad(() => tdsApi.getRoles(clientId), `tds-roles:${clientId}`)
  const ledgers = useLoad(() => api.listLedgers(clientId), `ledgers:${clientId}`)
  const natures = useNatures()
  const [rows, setRows] = useState<LedgerRole[] | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const current = rows ?? roles.data?.roles ?? []
  const nameOf = (id: string) => ledgers.data?.find((l) => l.id === id)?.name ?? ''
  const set = (i: number, patch: Partial<LedgerRole>) => setRows(current.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  const save = async () => {
    setError(null)
    setNotice('')
    try {
      await tdsApi.putRoles(clientId, current.filter((r) => r.ledger_id))
      setRows(null)
      roles.reload()
      setNotice('Saved. All roles were replaced by this list.')
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-600">A role without a nature is the default for every nature. Payable ledgers sit under Duties & Taxes; interest and late fee under Indirect Expenses. The server checks the group.</p>
      <ErrorBox error={roles.error} />
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Role</th>
            <th className={th}>Nature (blank = default)</th>
            <th className={th}>Ledger</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {current.map((r, i) => (
            <tr key={i}>
              <td className={td}>
                <select className={input} value={r.role} onChange={(e) => set(i, { role: e.target.value })}>
                  {LEDGER_ROLES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </td>
              <td className={td}>
                <select className={input} value={r.nature_key ?? ''} onChange={(e) => set(i, { nature_key: e.target.value || null })}>
                  <option value="">(default)</option>
                  {natures.options.map((n) => (
                    <option key={n.key} value={n.key}>
                      {n.label}
                    </option>
                  ))}
                </select>
              </td>
              <td className={td}>
                <div className="w-64">
                  <LedgerPicker ledgers={ledgers.data ?? []} value={r.ledger_id} onChange={(id) => set(i, { ledger_id: id, ledger_name: nameOf(id) })} />
                </div>
              </td>
              <td className={td}>
                <button className={btn} onClick={() => setRows(current.filter((_, k) => k !== i))}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Row>
        <button className={btn} onClick={() => setRows([...current, { role: 'tds_payable', nature_key: null, ledger_id: '' }])}>
          Add role
        </button>
        <button className={btnPrimary} onClick={save}>
          Save roles
        </button>
      </Row>
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
    </div>
  )
}

function ProfileTab({ clientId }: { clientId: string }) {
  const profile = useLoad(() => tdsApi.getProfile(clientId), `tds-profile:${clientId}`)
  const { years } = useFy()
  const [tan, setTan] = useState<string | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const shownTan = tan ?? profile.data?.tan ?? ''
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
      profile.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-3">
      <Row>
        <Field label="TAN of the deductor (AAAA99999A)">
          <input className={`${input} w-40 uppercase`} maxLength={10} value={shownTan} onChange={(e) => setTan(e.target.value.toUpperCase())} />
        </Field>
        <button className={btnPrimary} onClick={() => run(() => tdsApi.putProfile(clientId, shownTan), 'TAN saved.')}>
          Save TAN
        </button>
      </Row>
      <div className="text-sm font-semibold">194Q buyer flag by financial year</div>
      <p className="text-xs text-slate-600">Tick only when the buyer's turnover in the previous year was over the threshold. A year with no entry blocks 194Q deduction; nothing is assumed.</p>
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Financial year</th>
            <th className={th}>Previous-year turnover over threshold</th>
            <th className={th}>Recorded</th>
          </tr>
        </thead>
        <tbody>
          {years.map((y) => {
            const flag = profile.data?.fy_flags.find((f) => f.financial_year_id === y.id)
            return (
              <tr key={y.id}>
                <td className={td}>{fyLabel(y)}</td>
                <td className={td}>
                  <button className={btn} onClick={() => run(() => tdsApi.putFyFlag(clientId, y.id, { prev_year_turnover_over_threshold: !(flag?.prev_year_turnover_over_threshold ?? false) }), 'Flag saved.')}>
                    {flag ? (flag.prev_year_turnover_over_threshold ? 'Yes (click to change to No)' : 'No (click to change to Yes)') : 'Record: Yes'}
                  </button>
                </td>
                <td className={td}>{flag ? 'Yes' : 'Not recorded'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <ErrorBox error={error ?? profile.error} />
      {notice && <Notice>{notice}</Notice>}
    </div>
  )
}

