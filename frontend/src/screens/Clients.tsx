import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { useClient } from '../context'
import { ErrorBox, Field, Notice, Page, BalanceText, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import type { BusinessType, CreateClientBody, EntityType, GstType } from '../types'

const ENTITIES: EntityType[] = ['proprietorship', 'partnership', 'llp', 'company']
const BUSINESSES: BusinessType[] = ['trading', 'service', 'manufacturing']
const GST: GstType[] = ['regular', 'composition', 'unregistered']

function thisFyStart(): string {
  const now = new Date()
  const year = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1
  return `${year}-04-01`
}

function CreateClient({ onCreated }: { onCreated: (clientId: string) => void }) {
  const [form, setForm] = useState({
    name: '',
    legal_name: '',
    entity_type: 'proprietorship' as EntityType,
    business_type: 'trading' as BusinessType,
    gst_type: 'regular' as GstType,
    pan: '',
    state_code: '',
    fy_start: thisFyStart(),
    proprietor_name: '',
    partners: '',
  })
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const isFirm = form.entity_type === 'partnership' || form.entity_type === 'llp'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const body: CreateClientBody = {
      name: form.name,
      entity_type: form.entity_type,
      business_type: form.business_type,
      gst_type: form.gst_type,
      fy_start: form.fy_start,
    }
    if (form.legal_name) body.legal_name = form.legal_name
    if (form.pan) body.pan = form.pan
    if (form.state_code) body.state_code = form.state_code
    if (form.entity_type === 'proprietorship') body.proprietor_name = form.proprietor_name
    if (isFirm) body.partners = form.partners.split('\n').map((p) => p.trim()).filter(Boolean)
    try {
      const created = await api.createClient(body)
      onCreated(created.client_id)
      set({ name: '', legal_name: '', pan: '', state_code: '', proprietor_name: '', partners: '' })
    } catch (err) {
      setError(asFailure(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <h2 className="text-sm font-semibold">New client</h2>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Field label="Name *">
          <input className={input} required value={form.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="Legal name">
          <input className={input} value={form.legal_name} onChange={(e) => set({ legal_name: e.target.value })} />
        </Field>
        <Field label="Entity type">
          <select className={input} value={form.entity_type} onChange={(e) => set({ entity_type: e.target.value as EntityType })}>
            {ENTITIES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </Field>
        <Field label="Business type">
          <select className={input} value={form.business_type} onChange={(e) => set({ business_type: e.target.value as BusinessType })}>
            {BUSINESSES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </Field>
        <Field label="GST type">
          <select className={input} value={form.gst_type} onChange={(e) => set({ gst_type: e.target.value as GstType })}>
            {GST.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </Field>
        <Field label="Financial year starts (1 April)">
          <input className={input} type="date" required value={form.fy_start} onChange={(e) => set({ fy_start: e.target.value })} />
        </Field>
        <Field label="PAN">
          <input className={input} value={form.pan} onChange={(e) => set({ pan: e.target.value })} />
        </Field>
        <Field label="State code">
          <input className={input} value={form.state_code} onChange={(e) => set({ state_code: e.target.value })} />
        </Field>
        {form.entity_type === 'proprietorship' && (
          <Field label="Proprietor name *">
            <input className={input} required value={form.proprietor_name} onChange={(e) => set({ proprietor_name: e.target.value })} />
          </Field>
        )}
        {isFirm && (
          <Field label="Partners (one per line) *">
            <textarea className={input} rows={3} required value={form.partners} onChange={(e) => set({ partners: e.target.value })} />
          </Field>
        )}
      </div>
      <ErrorBox error={error} />
      <button className={btnPrimary} disabled={busy}>
        Create client
      </button>
    </form>
  )
}

function OpeningBalancesGrid({ clientId, fyId }: { clientId: string; fyId: string }) {
  const ledgers = useLoad(() => api.listLedgers(clientId), `ledgers:${clientId}`)
  const openings = useLoad(() => api.getOpeningBalances(clientId, fyId), `open:${clientId}:${fyId}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [saved, setSaved] = useState('')
  const stored = new Map((openings.data?.rows ?? []).map((r) => [r.ledger_id, r]))

  const save = async (ledgerId: string, debit: string, credit: string) => {
    const old = stored.get(ledgerId)
    if ((old?.debit ?? '') === debit && (old?.credit ?? '') === credit) return
    setError(null)
    try {
      await api.setOpeningBalance(clientId, fyId, ledgerId, { debit, credit })
      setSaved('Saved')
      openings.reload()
    } catch (err) {
      setError(asFailure(err))
      setSaved('')
    }
  }

  const check = openings.data
  return (
    <div className="space-y-2">
      <ErrorBox error={error ?? ledgers.error ?? openings.error} />
      {saved && <Notice>{saved}</Notice>}
      {check && (
        <div
          className={`rounded border px-3 py-2 text-sm ${check.is_balanced ? 'border-green-300 bg-green-50' : 'border-red-400 bg-red-50 text-red-800'}`}
        >
          Total Debit <b className="tabular-nums">{check.total_debit}</b> · Total Credit <b className="tabular-nums">{check.total_credit}</b> ·
          Difference <BalanceText balance={check.difference} danger={!check.is_balanced} />
          {!check.is_balanced && ' — posting stays blocked until the difference is nil.'}
        </div>
      )}
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className={th}>Ledger</th>
            <th className={th}>Group</th>
            <th className={thR + ' w-40'}>Debit</th>
            <th className={thR + ' w-40'}>Credit</th>
          </tr>
        </thead>
        <tbody>
          {(ledgers.data ?? []).map((l) => (
            <OpeningRowInput
              key={l.id + (stored.get(l.id)?.debit ?? '') + (stored.get(l.id)?.credit ?? '')}
              name={l.name}
              group={l.group_path.join(' > ')}
              debit={stored.get(l.id)?.debit ?? ''}
              credit={stored.get(l.id)?.credit ?? ''}
              onSave={(d, c) => save(l.id, d, c)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OpeningRowInput({
  name,
  group,
  debit,
  credit,
  onSave,
}: {
  name: string
  group: string
  debit: string
  credit: string
  onSave: (debit: string, credit: string) => void
}) {
  const [d, setD] = useState(debit)
  const [c, setC] = useState(credit)
  const commit = () => onSave(d, c)
  return (
    <tr>
      <td className={td}>{name}</td>
      <td className={td + ' text-slate-500'}>{group}</td>
      <td className={tdR}>
        <input className={input + ' w-full text-right'} value={d} onChange={(e) => setD(e.target.value)} onBlur={commit} aria-label={`${name} debit`} />
      </td>
      <td className={tdR}>
        <input className={input + ' w-full text-right'} value={c} onChange={(e) => setC(e.target.value)} onBlur={commit} aria-label={`${name} credit`} />
      </td>
    </tr>
  )
}

export default function Clients() {
  const { clients, clientId, setClientId, reloadClients, client } = useClient()
  const [fyId, setFyId] = useState('')
  const years = client?.financial_years ?? []
  const chosenYear = fyId && years.some((y) => y.id === fyId) ? fyId : (years[years.length - 1]?.id ?? '')

  return (
    <Page title="Clients">
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Entity</th>
            <th className={th}>Business</th>
            <th className={th}>GST</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {clients.map((c) => (
            <tr key={c.id} className={c.id === clientId ? 'bg-blue-50' : ''}>
              <td className={td}>{c.name}</td>
              <td className={td}>{c.entity_type}</td>
              <td className={td}>{c.business_type}</td>
              <td className={td}>{c.gst_type}</td>
              <td className={td}>
                <button className={btn} onClick={() => setClientId(c.id)} disabled={c.id === clientId}>
                  {c.id === clientId ? 'Selected' : 'Select'}
                </button>
              </td>
            </tr>
          ))}
          {clients.length === 0 && (
            <tr>
              <td className={td} colSpan={5}>
                No clients yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <CreateClient
        onCreated={(id) => {
          reloadClients()
          setClientId(id)
        }}
      />

      {client && (
        <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
          <div className="flex items-end gap-3">
            <h2 className="text-sm font-semibold">Opening balances — {client.name}</h2>
            <Field label="Financial year">
              <select className={input} value={chosenYear} onChange={(e) => setFyId(e.target.value)}>
                {years.map((y) => (
                  <option key={y.id} value={y.id}>
                    {y.start_date} to {y.end_date}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {chosenYear && <OpeningBalancesGrid key={chosenYear} clientId={client.id} fyId={chosenYear} />}
        </div>
      )}
    </Page>
  )
}
