import { useState } from 'react'
import { auditApi } from '../api/audit'
import { ErrorBox, Field, Page, btn, btnDanger, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'
import { dmy } from './lib'

const KINDS = ['national', 'state', 'local', 'client']

export default function Holidays() {
  const { clientId } = useClient()
  const [year, setYear] = useState('')
  const yearNum = /^\d{4}$/.test(year) ? Number(year) : undefined
  const list = useLoad(clientId ? () => auditApi.listHolidays(clientId, yearNum) : null, `audit-holidays:${clientId}:${yearNum ?? ''}`)
  const [date, setDate] = useState('')
  const [name, setName] = useState('')
  const [kind, setKind] = useState('national')
  const [note, setNote] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  if (!clientId)
    return (
      <Page title="Holidays">
        <NoClient />
      </Page>
    )
  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Holidays (check A-13)">
      <div className="text-sm text-slate-600">Dates entered here are treated as holidays when a voucher is checked. Sundays are never stored: the server always knows them.</div>
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
        <Field label="Date">
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Name">
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Kind">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </Field>
        <Field label="Note">
          <input className={input} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <button
          className={btnPrimary}
          disabled={!date || !name.trim()}
          onClick={() =>
            run(async () => {
              await auditApi.addHoliday(clientId, { holiday_date: date, name: name.trim(), kind, note: note.trim() || undefined })
              setDate('')
              setName('')
              setNote('')
            })
          }
        >
          Add holiday
        </button>
        <Field label="Show year">
          <input className={input + ' w-24'} placeholder="e.g. 2026" value={year} onChange={(e) => setYear(e.target.value)} />
        </Field>
        <button className={btn} onClick={() => list.reload()}>
          Refresh
        </button>
      </div>
      <ErrorBox error={error ?? list.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Date</th>
            <th className={th}>Name</th>
            <th className={th}>Kind</th>
            <th className={th}>Note</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((h) => (
            <tr key={h.id}>
              <td className={td}>{dmy(h.holiday_date)}</td>
              <td className={td}>{h.name}</td>
              <td className={td}>{h.kind}</td>
              <td className={td}>{h.note ?? ''}</td>
              <td className={td}>
                <button className={btnDanger} onClick={() => run(() => auditApi.deleteHoliday(clientId, h.id))}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.data?.length === 0 && <div className="text-sm text-slate-500">No holidays entered.</div>}
    </Page>
  )
}
