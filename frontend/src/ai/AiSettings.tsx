import { useState } from 'react'
import { aiApi, type AiSettings as Settings } from '../api/ai'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th, thR, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'
import { DATA_CLASSES, maskingSummary, usageFromCalls } from './lib'

export default function AiSettings() {
  const { clientId } = useClient()
  const settings = useLoad(clientId ? () => aiApi.getSettings(clientId) : null, `ai-settings:${clientId}`)
  const calls = useLoad(clientId ? () => aiApi.listCalls(clientId, { limit: 200 }) : null, `ai-calls:${clientId}`)
  const [openCall, setOpenCall] = useState('')
  if (!clientId)
    return (
      <Page title="AI settings">
        <NoClient />
      </Page>
    )
  const usage = usageFromCalls(calls.data ?? [])
  return (
    <Page title="AI settings">
      <ErrorBox error={settings.error} />
      {settings.data && <Switch key={settings.data.enabled_at ?? 'off'} clientId={clientId} s={settings.data} onSaved={() => { settings.reload(); calls.reload() }} />}
      <div className="rounded border border-slate-300 bg-white p-3 text-sm">
        <div className="mb-1 font-semibold">Usage (counted from the last 200 calls in the log)</div>
        <div className="flex flex-wrap gap-6">
          <span>Calls: {usage.calls}</span>
          <span>Succeeded: {usage.ok}</span>
          <span>Failed or blocked: {usage.failed}</span>
          <span>Tokens in: {usage.tokens_in}</span>
          <span>Tokens out: {usage.tokens_out}</span>
        </div>
        <div className="mt-1 text-xs text-slate-500">The server does not publish a usage limit for this client, so none is shown. Limits, if any, are set at the provider.</div>
      </div>
      <ErrorBox error={calls.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>When</th>
            <th className={th}>Purpose</th>
            <th className={th}>Model</th>
            <th className={th}>Status</th>
            <th className={th}>Masked</th>
            <th className={thR}>Tokens in / out</th>
            <th className={thR}>ms</th>
            <th className={th}>By</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(calls.data ?? []).map((c) => (
            <tr key={c.id}>
              <td className={td}>{c.created_at.slice(0, 19).replace('T', ' ')}</td>
              <td className={td}>{c.purpose}</td>
              <td className={td}>{c.model ?? ''}</td>
              <td className={td}>{c.status}</td>
              <td className={td}>{c.masking_applied ? maskingSummary(c.masking_report) : 'no'}</td>
              <td className={tdR}>
                {c.tokens_in ?? '-'} / {c.tokens_out ?? '-'}
              </td>
              <td className={tdR}>{c.latency_ms ?? ''}</td>
              <td className={td}>{c.created_by}</td>
              <td className={td}>
                <button className={btn} onClick={() => setOpenCall(openCall === c.id ? '' : c.id)}>
                  {openCall === c.id ? 'Hide' : 'Prompt'}
                </button>
              </td>
            </tr>
          ))}
          {calls.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={9}>
                No model calls yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {openCall && <CallDetail clientId={clientId} id={openCall} />}
    </Page>
  )
}

function Switch({ clientId, s, onSaved }: { clientId: string; s: Settings; onSaved: () => void }) {
  const [enabled, setEnabled] = useState(s.llm_enabled)
  const [dataClass, setDataClass] = useState(s.data_class)
  const [note, setNote] = useState(s.note ?? '')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const needNote = enabled && note.trim() === ''
  const save = async () => {
    setError(null)
    setNotice('')
    try {
      await aiApi.putSettings(clientId, { llm_enabled: enabled, data_class: dataClass, note: note.trim() || null })
      setNotice(enabled ? 'AI extraction switched on for this client.' : 'AI extraction switched off for this client.')
      onSaved()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3 text-sm">
      <div className="text-slate-600">
        Model: {s.model ?? 'not set'}. Model configured: {s.model_configured ? 'yes' : 'no'}. Key configured: {s.key_configured ? 'yes' : 'no'}. The key is never shown.
        {s.enabled_by && ` Last enabled by ${s.enabled_by}${s.enabled_at ? ` on ${s.enabled_at.slice(0, 10)}` : ''}.`}
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span className="font-semibold">Allow the language model to read this client&apos;s documents</span>
      </label>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Kind of data">
          <select className={input} value={dataClass} onChange={(e) => setDataClass(e.target.value)}>
            {DATA_CLASSES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={enabled ? 'Note (required to enable)' : 'Note'}>
          <input className={`${input} w-96 ${needNote ? 'border-red-500' : ''}`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why is this allowed for this client?" />
        </Field>
        <button className={btnPrimary} disabled={needNote} onClick={save}>
          Save
        </button>
      </div>
      <div className="text-xs text-slate-500">PAN, Aadhaar, bank account numbers and GSTIN are masked before anything is sent. The model only drafts; every field is checked by rules and approved by a person.</div>
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
    </div>
  )
}

function CallDetail({ clientId, id }: { clientId: string; id: string }) {
  const call = useLoad(() => aiApi.getCall(clientId, id), `ai-call:${clientId}:${id}`)
  const c = call.data
  if (!c) return <ErrorBox error={call.error} />
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3 text-sm">
      <div>
        <b>Masked prompt</b> (what was sent; original text is never stored)
      </div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{c.prompt_masked ?? '(not stored)'}</pre>
      {c.error_message && <div className="text-red-700">Error: {c.error_message}</div>}
      <div>
        <b>Response</b>
      </div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{c.response_raw ?? '(none)'}</pre>
    </div>
  )
}
