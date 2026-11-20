import { useState } from 'react'
import { api } from '../api'
import { aiApi } from '../api/ai'
import { LedgerSelect } from '../final/common'
import { ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, td, th, thR, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import type { LedgerRow } from '../types'
import { NoClient, Tabs } from './common'

type Tab = 'parties' | 'lines'

/** Saved party and line mappings used when a document is turned into a draft. A mapping is only ever created by a person. */
export default function Mappings() {
  const { clientId } = useClient()
  const [tab, setTab] = useState<Tab>('parties')
  const [q, setQ] = useState('')
  const ledgers = useLoad<LedgerRow[]>(clientId ? () => api.listLedgers(clientId) : null, `ai-map-ledgers:${clientId}`)
  if (!clientId)
    return (
      <Page title="Mappings">
        <NoClient />
      </Page>
    )
  return (
    <Page title="Mappings">
      <div className="flex items-end gap-3">
        <Tabs<Tab> tabs={[['parties', 'Party mappings'], ['lines', 'Line mappings']]} value={tab} onChange={setTab} />
        <Field label="Search">
          <input className={input} value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
      </div>
      <ErrorBox error={ledgers.error} />
      {tab === 'parties' ? <Parties clientId={clientId} q={q} ledgers={ledgers.data ?? []} /> : <Lines clientId={clientId} q={q} ledgers={ledgers.data ?? []} />}
    </Page>
  )
}

function useSave() {
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<void>, done: string) => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  return { error, notice, busy, run }
}

function Parties({ clientId, q, ledgers }: { clientId: string; q: string; ledgers: LedgerRow[] }) {
  const list = useLoad(() => aiApi.listPartyMappings(clientId, q), `ai-pmap:${clientId}:${q}`)
  const [kind, setKind] = useState<'gstin' | 'name'>('gstin')
  const [key, setKey] = useState('')
  const [ledger, setLedger] = useState('')
  const [replace, setReplace] = useState(false)
  const s = useSave()
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Match by">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value as 'gstin' | 'name')}>
            <option value="gstin">GSTIN</option>
            <option value="name">Name</option>
          </select>
        </Field>
        <Field label={kind === 'gstin' ? 'GSTIN' : 'Name as printed'}>
          <input className={input} value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>
        <Field label="Party ledger">
          <LedgerSelect ledgers={ledgers} value={ledger} onChange={setLedger} groups={['sundry_debtors', 'sundry_creditors']} blank="(choose party ledger)" />
        </Field>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          replace an existing mapping for this key
        </label>
        <button className={btnPrimary} disabled={s.busy || !key.trim() || !ledger} onClick={() => s.run(async () => { await aiApi.putPartyMapping(clientId, { match_kind: kind, match_key: key.trim(), party_ledger_id: ledger, replace }); setKey(''); list.reload() }, 'Mapping saved.')}>
          Save mapping
        </button>
      </div>
      <ErrorBox error={s.error ?? list.error} />
      {s.notice && <Notice>{s.notice}</Notice>}
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Match by</th>
            <th className={th}>Key</th>
            <th className={th}>Party ledger</th>
            <th className={thR}>Used</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((m) => (
            <tr key={m.id}>
              <td className={td}>{m.match_kind}</td>
              <td className={td}>{m.match_key}</td>
              <td className={td}>{m.party_ledger_name}</td>
              <td className={tdR}>{m.use_count}</td>
              <td className={td}>
                <button className={btn} onClick={() => { setKind(m.match_kind); setKey(m.match_key); setLedger(m.party_ledger_id); setReplace(true) }}>
                  Edit
                </button>{' '}
                <button className={btnDanger} disabled={s.busy} onClick={() => s.run(async () => { await aiApi.deletePartyMapping(clientId, m.id); list.reload() }, 'Mapping deleted.')}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={5}>
                No party mappings yet. They are saved when you accept a queue item.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function Lines({ clientId, q, ledgers }: { clientId: string; q: string; ledgers: LedgerRow[] }) {
  const list = useLoad(() => aiApi.listLineMappings(clientId, q), `ai-lmap:${clientId}:${q}`)
  const [kind, setKind] = useState<'hsn_sac' | 'description'>('hsn_sac')
  const [key, setKey] = useState('')
  const [ledger, setLedger] = useState('')
  const [party, setParty] = useState('')
  const [replace, setReplace] = useState(false)
  const s = useSave()
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Match by">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value as 'hsn_sac' | 'description')}>
            <option value="hsn_sac">HSN / SAC</option>
            <option value="description">Description</option>
          </select>
        </Field>
        <Field label={kind === 'hsn_sac' ? 'HSN / SAC' : 'Description as printed'}>
          <input className={input} value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>
        <Field label="Expense / income ledger">
          <LedgerSelect ledgers={ledgers} value={ledger} onChange={setLedger} blank="(choose ledger)" />
        </Field>
        <Field label="Only for party (optional)">
          <LedgerSelect ledgers={ledgers} value={party} onChange={setParty} groups={['sundry_debtors', 'sundry_creditors']} blank="(any party)" />
        </Field>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          replace an existing mapping
        </label>
        <button className={btnPrimary} disabled={s.busy || !key.trim() || !ledger} onClick={() => s.run(async () => { await aiApi.putLineMapping(clientId, { match_kind: kind, match_key: key.trim(), ledger_id: ledger, party_ledger_id: party || null, replace }); setKey(''); list.reload() }, 'Mapping saved.')}>
          Save mapping
        </button>
      </div>
      <ErrorBox error={s.error ?? list.error} />
      {s.notice && <Notice>{s.notice}</Notice>}
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Match by</th>
            <th className={th}>Key</th>
            <th className={th}>Ledger</th>
            <th className={th}>Party</th>
            <th className={th}>Item</th>
            <th className={thR}>Used</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((m) => (
            <tr key={m.id}>
              <td className={td}>{m.match_kind}</td>
              <td className={td}>{m.match_key}</td>
              <td className={td}>{m.ledger_name}</td>
              <td className={td}>{m.party_ledger_name ?? 'any'}</td>
              <td className={td}>{m.item_name ?? ''}</td>
              <td className={tdR}>{m.use_count}</td>
              <td className={td}>
                <button className={btn} onClick={() => { setKind(m.match_kind); setKey(m.match_key); setLedger(m.ledger_id); setParty(m.party_ledger_id ?? ''); setReplace(true) }}>
                  Edit
                </button>{' '}
                <button className={btnDanger} disabled={s.busy} onClick={() => s.run(async () => { await aiApi.deleteLineMapping(clientId, m.id); list.reload() }, 'Mapping deleted.')}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={7}>
                No line mappings yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
