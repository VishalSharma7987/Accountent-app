import { useState } from 'react'
import { aiApi, saveDocument, type TallyExportBody, type TallyExportResult } from '../api/ai'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'

export default function TallyExport() {
  const { clientId, latestYear } = useClient()
  const [kind, setKind] = useState<TallyExportBody['kind']>('both')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [postedOnly, setPostedOnly] = useState(false)
  const [result, setResult] = useState<TallyExportResult | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)
  const past = useLoad(clientId ? () => aiApi.listExports(clientId) : null, `ai-exports:${clientId}`)
  if (!clientId)
    return (
      <Page title="Tally export">
        <NoClient />
      </Page>
    )
  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const dateFrom = from || latestYear?.start_date || ''
  const dateTo = to || latestYear?.end_date || ''
  return (
    <Page title="Tally export">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="What to export">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value as TallyExportBody['kind'])}>
            <option value="both">Masters and vouchers</option>
            <option value="masters">Masters only</option>
            <option value="vouchers">Vouchers only</option>
          </select>
        </Field>
        <Field label="From">
          <input type="date" className={input} value={dateFrom} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To">
          <input type="date" className={input} value={dateTo} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={postedOnly} onChange={(e) => setPostedOnly(e.target.checked)} />
          Posted vouchers only (leave out drafts and approved ones)
        </label>
        <button
          className={btnPrimary}
          disabled={busy}
          onClick={() =>
            run(async () => {
              setResult(null)
              const r = await aiApi.exportTally(clientId, { kind, from_date: dateFrom || null, to_date: dateTo || null, posted_only: postedOnly })
              setResult(r)
              past.reload()
            })
          }
        >
          Create export
        </button>
      </div>
      <ErrorBox error={error} />
      {error?.code === 'unposted_vouchers' && !postedOnly && <div className="text-sm text-slate-600">The range holds vouchers that are not posted. Tick &quot;Posted vouchers only&quot; to export just the posted ones.</div>}
      {result && (
        <div className="space-y-1">
          <Notice>
            Export ready: {result.master_count} masters, {result.voucher_count} vouchers.
          </Notice>
          {result.warnings.length > 0 && (
            <ul className="list-disc rounded border border-amber-300 bg-amber-50 py-1 pl-6 pr-3 text-sm text-amber-900">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          <button className={btn} disabled={busy} onClick={() => run(() => saveDocument(clientId, result.document_id, `tally-export-${result.export_id.slice(0, 8)}.xml`))}>
            Download XML
          </button>
        </div>
      )}
      <ErrorBox error={past.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Earlier exports</th>
            <th className={th}>Created</th>
            <th className={th}>Masters</th>
            <th className={th}>Vouchers</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(past.data ?? []).map((x) => (
            <tr key={x.id}>
              <td className={td}>
                {x.kind}
                {x.from_date || x.to_date ? ` (${x.from_date ?? ''} to ${x.to_date ?? ''})` : ''}
              </td>
              <td className={td}>{x.created_at.slice(0, 19).replace('T', ' ')}</td>
              <td className={td}>{x.master_count}</td>
              <td className={td}>{x.voucher_count}</td>
              <td className={td}>
                <button className={btn} onClick={() => run(() => saveDocument(clientId, x.document_id, `tally-export-${x.document_id.slice(0, 8)}.xml`))}>
                  Download
                </button>
              </td>
            </tr>
          ))}
          {past.loading && !past.data && (
            <tr>
              <td className={td} colSpan={5}>
                Loading earlier exports...
              </td>
            </tr>
          )}
          {past.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={5}>
                No exports yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Page>
  )
}
