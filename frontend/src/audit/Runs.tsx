import { useState } from 'react'
import { Link } from 'react-router-dom'
import { auditApi, type RunCreated } from '../api/audit'
import { ErrorBox, Field, Notice, Page, btnPrimary, input, td, th, thR, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { fyLabel } from '../tds/lib'
import { FySelect, NoClient, useFy } from './common'
import { PARAM_FIELDS, buildRunParams, dmy, dt } from './lib'

export default function Runs() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const checks = useLoad(() => auditApi.listChecks(), 'audit-checks')
  const runs = useLoad(clientId ? () => auditApi.listRuns(clientId) : null, `audit-runs:${clientId}`)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [params, setParams] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [done, setDone] = useState<RunCreated | null>(null)
  if (!clientId)
    return (
      <Page title="Run audit">
        <NoClient />
      </Page>
    )
  const active = (checks.data ?? []).filter((c) => c.active)
  const shownParams = PARAM_FIELDS.filter((p) => picked.length === 0 || picked.includes(p.check))
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const run = async () => {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      const res = await auditApi.createRun(clientId, {
        financial_year_id: fyId,
        from_date: from || undefined,
        to_date: to || undefined,
        check_ids: picked.length ? picked : undefined,
        params: buildRunParams(params),
      })
      setDone(res)
      runs.reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const fyName = (id: string) => {
    const y = years.find((x) => x.id === id)
    return y ? fyLabel(y) : ''
  }
  return (
    <Page title="Run audit">
      <div className="rounded border border-slate-300 bg-white p-3">
        <div className="flex flex-wrap items-end gap-3">
          <FySelect years={years} value={fyId} onChange={setFyId} />
          <Field label="From (blank = whole year)">
            <input type="date" className={input} value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="To">
            <input type="date" className={input} value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          <button className={btnPrimary} disabled={!fyId || busy} onClick={run}>
            {busy ? 'Running...' : 'Run audit'}
          </button>
        </div>
        <div className="mt-3 text-xs font-semibold text-slate-600">Checks (none ticked = every active check)</div>
        <div className="mt-1 grid gap-x-4 gap-y-0.5 text-sm md:grid-cols-2 lg:grid-cols-3">
          {active.map((c) => (
            <label key={c.check_id} className="flex items-center gap-1">
              <input type="checkbox" checked={picked.includes(c.check_id)} onChange={() => toggle(c.check_id)} />
              <span className="font-mono text-xs">{c.check_id}</span> {c.title}
            </label>
          ))}
        </div>
        <div className="mt-3 text-xs font-semibold text-slate-600">Parameters (blank = server default)</div>
        <div className="mt-1 flex flex-wrap gap-3">
          {shownParams.map((p) => (
            <Field key={p.key} label={`${p.label} (${p.check})`}>
              <input
                className={input + ' w-52'}
                placeholder={p.hint}
                value={params[p.key] ?? ''}
                onChange={(e) => setParams({ ...params, [p.key]: e.target.value })}
              />
            </Field>
          ))}
        </div>
      </div>
      <ErrorBox error={error} />
      {done && (
        <Notice>
          Run stored with {done.finding_count} finding(s).{' '}
          <Link className="underline" to={`/audit/runs/${done.id}`}>
            Open the report
          </Link>
          {Object.entries(done.summary.by_check ?? {})
            .filter(([, v]) => v.error)
            .map(([k, v]) => (
              <div key={k} className="text-red-800">
                {k} could not run: {v.error}
              </div>
            ))}
        </Notice>
      )}
      <h2 className="font-semibold">Earlier runs</h2>
      <ErrorBox error={runs.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Run</th>
            <th className={th}>Year</th>
            <th className={th}>Period</th>
            <th className={th}>Checks</th>
            <th className={thR}>Findings</th>
            <th className={th}>Status</th>
            <th className={th}>By</th>
            <th className={th}>When</th>
          </tr>
        </thead>
        <tbody>
          {(runs.data ?? []).map((r) => (
            <tr key={r.id}>
              <td className={td}>
                <Link className="text-blue-700 underline" to={`/audit/runs/${r.id}`}>
                  {r.id.slice(0, 8)}
                </Link>
              </td>
              <td className={td}>{fyName(r.financial_year_id)}</td>
              <td className={td}>
                {dmy(r.from_date)} to {dmy(r.to_date)}
              </td>
              <td className={td + ' text-xs'}>{r.check_ids.join(', ')}</td>
              <td className={tdR}>{r.finding_count}</td>
              <td className={td}>{r.status}</td>
              <td className={td}>{r.created_by}</td>
              <td className={td}>{dt(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.data?.length === 0 && <div className="text-sm text-slate-500">No audit run yet.</div>}
    </Page>
  )
}
