import { useMemo, useState, type FormEvent } from 'react'
import { api } from '../api'
import { useClient } from '../context'
import { BalanceText, ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import type { GroupNode, LedgerRow } from '../types'

function flattenGroups(nodes: GroupNode[], depth = 0): { code: string; label: string }[] {
  return nodes.flatMap((n) => [{ code: n.code, label: `${'  '.repeat(depth)}${n.name}` }, ...flattenGroups(n.children, depth + 1)])
}

/** Ledgers grouped by their group path, in the order the API returns the groups. */
function byGroup(ledgers: LedgerRow[]): { path: string; rows: LedgerRow[] }[] {
  const order: string[] = []
  const map = new Map<string, LedgerRow[]>()
  for (const l of ledgers) {
    const key = l.group_path.join(' > ')
    if (!map.has(key)) {
      map.set(key, [])
      order.push(key)
    }
    map.get(key)!.push(l)
  }
  return order.map((path) => ({ path, rows: map.get(path)! }))
}

export default function Ledgers() {
  const { clientId, client } = useClient()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const groups = useLoad(clientId ? () => api.listGroups(clientId) : null, `groups:${clientId}`)
  const [name, setName] = useState('')
  const [groupCode, setGroupCode] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const groupOptions = useMemo(() => flattenGroups(groups.data ?? []), [groups.data])
  const grouped = useMemo(
    () => byGroup((ledgers.data ?? []).filter((l) => showInactive || l.is_active)),
    [ledgers.data, showInactive],
  )

  if (!clientId) return <Page title="Ledgers">Select a client first.</Page>

  const create = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setNotice('')
    try {
      await api.createLedger(clientId, { name, group_code: groupCode || groupOptions[0]?.code })
      setName('')
      setNotice('Ledger created.')
      ledgers.reload()
    } catch (err) {
      setError(asFailure(err))
    }
  }

  const deactivate = async (l: LedgerRow) => {
    if (!window.confirm(`Deactivate ledger '${l.name}'?`)) return
    setError(null)
    setNotice('')
    try {
      await api.deactivateLedger(clientId, l.id)
      setNotice(`'${l.name}' deactivated.`)
      ledgers.reload()
    } catch (err) {
      setError(asFailure(err))
    }
  }

  return (
    <Page
      title={`Ledgers — ${client?.name ?? ''}`}
      actions={
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> show inactive
        </label>
      }
    >
      <form onSubmit={create} className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="New ledger name">
          <input className={input} required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Group">
          <select className={input} value={groupCode || groupOptions[0]?.code || ''} onChange={(e) => setGroupCode(e.target.value)}>
            {groupOptions.map((g) => (
              <option key={g.code} value={g.code}>
                {g.label}
              </option>
            ))}
          </select>
        </Field>
        <button className={btnPrimary}>Add ledger</button>
      </form>
      <ErrorBox error={error ?? ledgers.error ?? groups.error} />
      {notice && <Notice>{notice}</Notice>}
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Ledger</th>
            <th className={thR + ' w-52'}>Closing balance</th>
            <th className={th + ' w-28'}></th>
          </tr>
        </thead>
        <tbody>
          {grouped.map((g) => (
            <GroupBlock key={g.path} path={g.path} rows={g.rows} onDeactivate={deactivate} />
          ))}
        </tbody>
      </table>
    </Page>
  )
}

function GroupBlock({ path, rows, onDeactivate }: { path: string; rows: LedgerRow[]; onDeactivate: (l: LedgerRow) => void }) {
  return (
    <>
      <tr>
        <td colSpan={3} className="bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600">
          {path}
        </td>
      </tr>
      {rows.map((l) => (
        <tr key={l.id} className={l.is_active ? '' : 'text-slate-400'}>
          <td className={td + ' pl-6'}>
            {l.name} {!l.is_active && <span className="text-xs">(inactive)</span>}
          </td>
          <td className={tdR}>
            <BalanceText balance={l.balance} />
          </td>
          <td className={td}>
            {l.is_active && (
              <button className={btn + ' ' + btnDanger} onClick={() => onDeactivate(l)}>
                Deactivate
              </button>
            )}
          </td>
        </tr>
      ))}
    </>
  )
}
