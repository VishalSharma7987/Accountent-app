import { useState } from 'react'
import { api } from '../api'
import { auditApi, type RelatedFlag } from '../api/audit'
import { ErrorBox, Field, LedgerPicker, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'
import { dt } from './lib'

export default function Related() {
  const { clientId } = useClient()
  const flags = useLoad(clientId ? () => auditApi.listRelated(clientId) : null, `audit-related:${clientId}`)
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [ledgerId, setLedgerId] = useState('')
  const [relationship, setRelationship] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  if (!clientId)
    return (
      <Page title="Related parties">
        <NoClient />
      </Page>
    )
  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      flags.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Related-party flags">
      <div className="text-sm text-slate-600">Flag the ledgers of related parties for check A-18. Flags are never deleted: set them inactive instead.</div>
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
        <Field label="Ledger">
          <div className="w-64">
            <LedgerPicker ledgers={ledgers.data ?? []} value={ledgerId} onChange={setLedgerId} />
          </div>
        </Field>
        <Field label="Relationship">
          <input className={input} value={relationship} onChange={(e) => setRelationship(e.target.value)} />
        </Field>
        <Field label="Note">
          <input className={input + ' w-64'} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <button
          className={btnPrimary}
          disabled={!ledgerId || !relationship.trim()}
          onClick={() =>
            run(async () => {
              await auditApi.flagRelated(clientId, { ledger_id: ledgerId, relationship: relationship.trim(), note: note.trim() || undefined })
              setLedgerId('')
              setRelationship('')
              setNote('')
            })
          }
        >
          Flag ledger
        </button>
      </div>
      <ErrorBox error={error ?? flags.error ?? ledgers.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Ledger</th>
            <th className={th}>Relationship</th>
            <th className={th}>Note</th>
            <th className={th}>Active</th>
            <th className={th}>Flagged by</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(flags.data ?? []).map((f) => (
            <FlagRow key={f.id + f.relationship + (f.note ?? '') + f.active} f={f} onSave={(b) => run(() => auditApi.updateRelated(clientId, f.id, b))} />
          ))}
        </tbody>
      </table>
      {flags.data?.length === 0 && <div className="text-sm text-slate-500">No ledger is flagged.</div>}
    </Page>
  )
}

function FlagRow({ f, onSave }: { f: RelatedFlag; onSave: (b: { relationship?: string; active?: boolean; note?: string }) => void }) {
  const [relationship, setRelationship] = useState(f.relationship)
  const [note, setNote] = useState(f.note ?? '')
  const changed = relationship.trim() !== f.relationship || note.trim() !== (f.note ?? '')
  return (
    <tr className={f.active ? '' : 'text-slate-400'}>
      <td className={td}>{f.ledger_name}</td>
      <td className={td}>
        <input className={input} value={relationship} onChange={(e) => setRelationship(e.target.value)} />
      </td>
      <td className={td}>
        <input className={input + ' w-64'} value={note} onChange={(e) => setNote(e.target.value)} />
      </td>
      <td className={td}>{f.active ? 'yes' : 'no'}</td>
      <td className={td + ' text-xs'}>
        {f.flagged_by}, {dt(f.flagged_at)}
      </td>
      <td className={td + ' whitespace-nowrap'}>
        <button className={btn} disabled={!changed || !relationship.trim()} onClick={() => onSave({ relationship: relationship.trim(), note: note.trim() })}>
          Save
        </button>{' '}
        <button className={btn} onClick={() => onSave({ active: !f.active })}>
          {f.active ? 'Set inactive' : 'Reactivate'}
        </button>
      </td>
    </tr>
  )
}
