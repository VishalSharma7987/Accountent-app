import { useState } from 'react'
import { api } from '../api'
import { ErrorBox, Notice, Page, btn, btnPrimary, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure } from '../lib/useLoad'
import type { DryRun, ImportCommit } from '../types'

export default function ImportScreen() {
  const { clientId } = useClient()
  const [file, setFile] = useState<File | null>(null)
  const [dry, setDry] = useState<DryRun | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<ImportCommit | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="Excel import">Select a client first.</Page>

  const runDry = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const out = await api.importDryRun(clientId, file)
      setDry(out)
      setSelected(new Set(out.vouchers.filter((v) => v.status === 'ok').map((v) => v.ref_id)))
    } catch (e) {
      setDry(null)
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    if (!file || selected.size === 0) return
    if (!window.confirm(`Create ${selected.size} draft voucher(s)? Nothing is approved or posted.`)) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.importCommit(clientId, file, [...selected]))
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const toggle = (ref: string) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })

  return (
    <Page title="Excel import">
      <div className="flex flex-wrap items-center gap-3 rounded border border-slate-300 bg-white p-3 text-sm">
        <a className="text-blue-700 underline" href={api.importTemplateUrl(clientId)}>
          Download the .xlsx template
        </a>
        <input
          type="file"
          accept=".xlsx"
          aria-label="Excel file"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setDry(null)
            setResult(null)
          }}
        />
        <button className={btnPrimary} disabled={!file || busy} onClick={runDry}>
          Check file (dry run)
        </button>
      </div>
      <ErrorBox error={error} />
      {dry && (
        <>
          <div className="text-sm">
            {dry.ok_count} voucher(s) OK, {dry.error_count} with errors. Only OK vouchers can be imported; imported vouchers become
            <b> drafts</b> for you to review.
          </div>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th + ' w-10'}></th>
                <th className={th}>Ref</th>
                <th className={th}>First row</th>
                <th className={th}>Result</th>
              </tr>
            </thead>
            <tbody>
              {dry.vouchers.map((v) => (
                <tr key={v.ref_id} className={v.status === 'error' ? 'bg-red-50' : ''}>
                  <td className={td}>
                    <input
                      type="checkbox"
                      disabled={v.status !== 'ok'}
                      checked={selected.has(v.ref_id)}
                      onChange={() => toggle(v.ref_id)}
                      aria-label={`import ${v.ref_id}`}
                    />
                  </td>
                  <td className={td}>{v.ref_id}</td>
                  <td className={td}>{v.first_row}</td>
                  <td className={td}>
                    {v.status === 'ok' ? (
                      <span className="text-green-700">OK</span>
                    ) : (
                      <ul className="list-disc pl-4 text-red-800">
                        {v.errors.map((e, i) => (
                          <li key={i}>
                            {e.row !== null && <b>Row {e.row}: </b>}
                            <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className={btn + ' ' + btnPrimary} disabled={busy || selected.size === 0} onClick={commit}>
            Import {selected.size} selected as drafts
          </button>
        </>
      )}
      {result && (
        <Notice>
          Created {result.created.length} draft(s)
          {result.skipped.length > 0 && `; skipped ${result.skipped.length}: ${result.skipped.map((s) => `${s.ref_id} (${s.reason})`).join(', ')}`}.
        </Notice>
      )}
    </Page>
  )
}
