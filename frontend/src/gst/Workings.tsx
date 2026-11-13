import { useState } from 'react'
import { gstApi } from '../api/gst'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { RegistrationSelect, useRegistrations } from './common'

export default function Workings() {
  const { clientId } = useClient()
  const { regs, active, regId, setRegId } = useRegistrations()
  const [type, setType] = useState('')
  const list = useLoad(clientId && regId ? () => gstApi.listWorkings(clientId, regId, type) : null, `gst-workings:${clientId}:${regId}:${type}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="GST workings">Select a client first.</Page>

  const finalise = async (id: string) => {
    if (!window.confirm('Finalise this working? It becomes read-only and cannot be changed.')) return
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await gstApi.finaliseWorking(id)
      setNotice('Working finalised.')
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page title="GST workings (saved versions)">
      <div className="flex items-end gap-3">
        <RegistrationSelect regs={active.length ? active : regs} value={regId} onChange={setRegId} />
        <Field label="Return">
          <select className={input} value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All</option>
            <option value="gstr1">GSTR-1</option>
            <option value="gstr3b">GSTR-3B</option>
            <option value="composition">Composition</option>
          </select>
        </Field>
      </div>
      <ErrorBox error={error ?? list.error} />
      {notice && <Notice>{notice}</Notice>}
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            {['Return', 'Period start', 'Version', 'Status', 'Hash', 'Saved by', 'Saved at', ''].map((h) => (
              <th key={h} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((w) => (
            <tr key={w.id}>
              <td className={td}>{w.return_type}</td>
              <td className={td}>{w.period_start}</td>
              <td className={td}>{w.version}</td>
              <td className={td}>{w.status}</td>
              <td className={`${td} font-mono text-xs`}>{w.data_hash.slice(0, 10)}</td>
              <td className={td}>{w.created_by}</td>
              <td className={td}>{w.created_at.slice(0, 16).replace('T', ' ')}</td>
              <td className={td}>
                <a className={btn} href={gstApi.workingExportUrl(w.id)}>
                  Excel
                </a>{' '}
                {w.status !== 'final' && (
                  <button className={btnPrimary} disabled={busy} onClick={() => finalise(w.id)}>
                    Finalise
                  </button>
                )}
              </td>
            </tr>
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={8}>
                No saved workings. Open GSTR-1 or GSTR-3B and use Save as working.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Page>
  )
}
