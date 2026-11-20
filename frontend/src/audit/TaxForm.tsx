import { useState } from 'react'
import { auditApi, downloadFile, formXlsxPath, type DeriveResult, type FormSet } from '../api/audit'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, NoClient, VerifBadge, useFy } from './common'
import { dt, entryFindingIds, entryValueText } from './lib'

export default function TaxForm() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const form = useLoad(clientId && fyId ? () => auditApi.getForm(clientId, fyId) : null, `audit-form:${clientId}:${fyId}`)
  const [setId, setSetId] = useState<{ fy: string; id: string }>({ fy: '', id: '' })
  const [error, setError] = useState<ApiFailure | null>(null)
  if (!clientId)
    return (
      <Page title="Tax audit form">
        <NoClient />
      </Page>
    )
  const currentSet = setId.fy === fyId ? setId.id : ''
  const open = async () => {
    setError(null)
    try {
      const s = await auditApi.createFormSet(clientId, fyId)
      setSetId({ fy: fyId, id: s.id })
    } catch (e) {
      const f = asFailure(e)
      // the server refuses a second set for the same year and names the existing one
      const existing = f.code === 'duplicate_form_set' && f.details && typeof f.details === 'object' ? (f.details as { id?: unknown }).id : null
      if (typeof existing === 'string') setSetId({ fy: fyId, id: existing })
      else setError(f)
    }
  }
  const f = form.data
  return (
    <Page title="Tax audit form (Form 3CD / Form 26)">
      <div className="flex items-end gap-3">
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <button className={btnPrimary} disabled={!f || !!currentSet} onClick={open}>
          Open working set for this year
        </button>
      </div>
      <ErrorBox error={error ?? form.error} />
      {f && (
        <div className="rounded border border-slate-300 bg-white p-3 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <b>{f.title}</b>
            <span>
              {f.law}, {f.section_ref}
            </span>
            <VerifBadge status={f.verification_status} />
          </div>
          {f.verification_status !== 'verified' && (
            <div className="mt-1 text-amber-800">This form is not verified against the official form. Every clause below is shown with its own status.</div>
          )}
          {f.note && <div className="mt-1 text-slate-700">{f.note}</div>}
        </div>
      )}
      {currentSet ? (
        <SetView key={currentSet} clientId={clientId} setId={currentSet} fyId={fyId} />
      ) : (
        f && (
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Clause</th>
                <th className={th}>Title</th>
                <th className={th}>How it is filled</th>
                <th className={th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {f.clauses.map((c) => (
                <tr key={c.clause_no}>
                  <td className={td + ' font-mono'}>{c.clause_no}</td>
                  <td className={td}>{c.title}</td>
                  <td className={td + ' text-xs'}>
                    {c.derivability.replace(/_/g, ' ')}
                    {c.derivable_here ? ' (derived from audit findings)' : ' (manual entry)'}
                  </td>
                  <td className={td}>
                    <VerifBadge status={c.verification_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </Page>
  )
}

function SetView({ clientId, setId, fyId }: { clientId: string; setId: string; fyId: string }) {
  const set = useLoad(() => auditApi.getFormSet(clientId, setId), `audit-formset:${setId}`)
  const runs = useLoad(() => auditApi.listRuns(clientId), `audit-runs:${clientId}`)
  const [runId, setRunId] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [result, setResult] = useState<DeriveResult | null>(null)
  const [clause, setClause] = useState('')
  const [field, setField] = useState('')
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const s: FormSet | null = set.data
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      set.reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const finalised = s?.status === 'finalised'
  const yearRuns = (runs.data ?? []).filter((r) => r.financial_year_id === fyId)
  const [showIds, setShowIds] = useState('')
  return (
    <div className="space-y-3">
      <ErrorBox error={error ?? set.error ?? runs.error} />
      {s && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span>
              Status <b>{s.status}</b>
            </span>
            {finalised && (
              <span>
                Finalised by {s.finalised_by}, {dt(s.finalised_at)}. Read-only.
              </span>
            )}
            <button className={btn} onClick={() => run(() => downloadFile(formXlsxPath(clientId, setId), `tax-audit-form-${setId}.xlsx`, { format: 'xlsx' }))}>
              Excel export
            </button>
          </div>
          {!finalised && (
            <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
              <Field label="Derive from audit run">
                <select className={input} value={runId} onChange={(e) => setRunId(e.target.value)}>
                  <option value="">(choose run)</option>
                  {yearRuns.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id.slice(0, 8)} - {dt(r.created_at)}
                    </option>
                  ))}
                </select>
              </Field>
              <button
                className={btn}
                disabled={!runId || busy}
                onClick={() =>
                  run(async () => {
                    setResult(await auditApi.deriveForm(clientId, setId, { run_id: runId }))
                  })
                }
              >
                Derive clauses
              </button>
              <div className="text-xs text-slate-500">Only clauses that the books can fill are derived. Manual entries are never overwritten.</div>
            </div>
          )}
          {result && (
            <Notice>
              {result.entries.length} entr{result.entries.length === 1 ? 'y' : 'ies'} derived.
              {result.skipped.map((x) => (
                <div key={x.clause_no}>
                  Clause {x.clause_no} skipped: {x.reason}
                </div>
              ))}
              {result.kept_manual.length > 0 && <div>Kept your manual entries: {result.kept_manual.map((k) => `${k.clause_no}/${k.field_key}`).join(', ')}</div>}
            </Notice>
          )}
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Clause</th>
                <th className={th}>Title</th>
                <th className={th}>Status</th>
                <th className={th}>Field</th>
                <th className={th}>Value</th>
                <th className={th}>Origin</th>
              </tr>
            </thead>
            <tbody>
              {s.clauses.map((c) => {
                const rows = s.entries.filter((e) => e.clause_no === c.clause_no)
                return (rows.length ? rows : [null]).map((e, i) => (
                  <tr key={c.clause_no + i + (e?.field_key ?? '')}>
                    <td className={td + ' font-mono'}>{i === 0 ? c.clause_no : ''}</td>
                    <td className={td}>{i === 0 ? c.title : ''}</td>
                    <td className={td}>{i === 0 && <VerifBadge status={c.verification_status} />}</td>
                    <td className={td + ' text-xs'}>{e?.field_key ?? ''}</td>
                    <td className={td}>
                      {e ? entryValueText(e.value) : <span className="text-slate-400">no entry</span>}
                      {e && entryFindingIds(e.value).length > 0 && (
                        <>
                          {' '}
                          <button className="text-xs text-blue-700 underline" onClick={() => setShowIds(showIds === c.clause_no + e.field_key ? '' : c.clause_no + e.field_key)}>
                            finding ids
                          </button>
                          {showIds === c.clause_no + e.field_key && <div className="break-all font-mono text-xs">{entryFindingIds(e.value).join(', ')}</div>}
                        </>
                      )}
                    </td>
                    <td className={td + ' text-xs'}>{e ? `${e.origin} by ${e.entered_by}, ${dt(e.entered_at)}` : ''}</td>
                  </tr>
                ))
              })}
              {s.entries
                .filter((e) => !s.clauses.some((c) => c.clause_no === e.clause_no))
                .map((e) => (
                  <tr key={e.clause_no + e.field_key}>
                    <td className={td + ' font-mono'}>{e.clause_no}</td>
                    <td className={td}></td>
                    <td className={td}></td>
                    <td className={td + ' text-xs'}>{e.field_key}</td>
                    <td className={td}>{entryValueText(e.value)}</td>
                    <td className={td + ' text-xs'}>{`${e.origin} by ${e.entered_by}, ${dt(e.entered_at)}`}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          {!finalised && (
            <>
              <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
                <Field label="Clause no (manual entry)">
                  <input className={input + ' w-32'} list="clause-list" value={clause} onChange={(e) => setClause(e.target.value)} />
                </Field>
                <datalist id="clause-list">
                  {s.clauses.map((c) => (
                    <option key={c.clause_no} value={c.clause_no}>
                      {c.title}
                    </option>
                  ))}
                </datalist>
                <Field label="Field">
                  <input className={input} value={field} onChange={(e) => setField(e.target.value)} />
                </Field>
                <Field label="Value (amounts as text, e.g. 1250.00)">
                  <input className={input + ' w-64'} value={value} onChange={(e) => setValue(e.target.value)} />
                </Field>
                <button
                  className={btn}
                  disabled={busy || !clause.trim() || !field.trim() || !value.trim()}
                  onClick={() =>
                    run(async () => {
                      await auditApi.enterForm(clientId, setId, { clause_no: clause.trim(), field_key: field.trim(), value: value.trim() })
                      setValue('')
                    })
                  }
                >
                  Save entry
                </button>
              </div>
              <button className={btnPrimary} disabled={busy} onClick={() => run(() => auditApi.finaliseForm(clientId, setId))}>
                Finalise this form set
              </button>
              <span className="ml-2 text-xs text-slate-500">After finalising nothing can be changed.</span>
            </>
          )}
        </>
      )}
    </div>
  )
}
