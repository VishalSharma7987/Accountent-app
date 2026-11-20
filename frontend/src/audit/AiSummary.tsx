import { useState } from 'react'
import { aiApi } from '../api/ai'
import { auditApi, type SummaryResult } from '../api/audit'
import { ErrorBox, Field, btn, input } from '../components/ui'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { dt } from './lib'

/** Plain-language AI summary of a run's exceptions. Suggestion only: the text is stored as a suggestion and never becomes a conclusion. */
export default function AiSummary({ clientId, runId, checkIds, paperId }: { clientId: string; runId: string; checkIds: string[]; paperId?: string }) {
  const settings = useLoad(() => aiApi.getSettings(clientId), `ai-settings:${clientId}`)
  const stored = useLoad(() => auditApi.listSummaries(clientId, runId), `audit-summaries:${clientId}:${runId}`)
  const [check, setCheck] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [last, setLast] = useState<SummaryResult | null>(null)
  const on = settings.data?.llm_enabled === true
  const ask = async () => {
    setBusy(true)
    setError(null)
    setLast(null)
    try {
      const res = await auditApi.summarise(clientId, runId, { check_id: check || undefined, paper_id: paperId })
      setLast(res)
      if (res.status === 'ok') stored.reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const list = (stored.data ?? []).filter((s) => !paperId || s.paper_id === paperId)
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="font-semibold">AI summary of the exceptions</div>
      <div className="flex flex-wrap items-end gap-3">
        {!paperId && (
          <Field label="Check (blank = whole run)">
            <select className={input} value={check} onChange={(e) => setCheck(e.target.value)}>
              <option value="">Whole run</option>
              {checkIds.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
        )}
        <button className={btn} disabled={!on || busy} onClick={ask} title={on ? '' : 'The AI switch of this client is off'}>
          {busy ? 'Asking...' : 'Write summary'}
        </button>
        {settings.data && !on && <span className="text-xs text-slate-600">The AI switch of this client is off (AI settings). Nothing is sent to the model.</span>}
      </div>
      <ErrorBox error={error ?? settings.error ?? stored.error} />
      {last && last.status !== 'ok' && (
        <div className={`rounded border px-3 py-2 text-sm ${last.status === 'rejected' ? 'border-red-300 bg-red-50 text-red-800' : 'border-amber-300 bg-amber-50 text-amber-900'}`}>
          <div>
            <b>Status: {last.status}</b>
            {last.reason ? `: ${last.reason}` : ''}
          </div>
          {last.message && <div>{last.message}</div>}
          {last.status === 'rejected' && <div>The text was not stored: it quoted something that is not in the findings or stated a conclusion.</div>}
          {(last.problems ?? []).length > 0 && (
            <ul className="list-disc pl-5">
              {(last.problems ?? []).map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {list.map((s) => (
        <div key={s.id} className="rounded border border-slate-200 bg-slate-50 p-2 text-sm">
          <div className="mb-1 flex items-center gap-2 text-xs text-slate-600">
            <span className="rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-900">Suggestion only, not a conclusion</span>
            <span>
              {s.created_by}, {dt(s.created_at)}
            </span>
          </div>
          <div className="whitespace-pre-wrap">{s.summary_text}</div>
        </div>
      ))}
      {stored.data && list.length === 0 && <div className="text-xs text-slate-500">No summary stored yet.</div>}
    </div>
  )
}
