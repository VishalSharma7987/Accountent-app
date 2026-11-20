import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { auditApi } from '../api/audit'
import { ErrorBox, Field, Page, btnPrimary, input, td, th, thR, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient, StatusPill } from './common'
import { dt } from './lib'

export default function Papers() {
  const { clientId } = useClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [runId, setRunId] = useState(params.get('run') ?? '')
  const [checkId, setCheckId] = useState(params.get('check') ?? '')
  const [status, setStatus] = useState('')
  const runs = useLoad(clientId ? () => auditApi.listRuns(clientId) : null, `audit-runs:${clientId}`)
  const papers = useLoad(
    clientId ? () => auditApi.listPapers(clientId, { status: status || undefined }) : null,
    `audit-papers:${clientId}:${status}`,
  )
  const [error, setError] = useState<ApiFailure | null>(null)
  if (!clientId)
    return (
      <Page title="Working papers">
        <NoClient />
      </Page>
    )
  const run = (runs.data ?? []).find((r) => r.id === runId)
  const create = async () => {
    setError(null)
    try {
      const p = await auditApi.createPaper(clientId, { run_id: runId, check_id: checkId })
      navigate(`/audit/papers/${p.id}`)
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Working papers">
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
        <Field label="Audit run">
          <select
            className={input}
            value={runId}
            onChange={(e) => {
              setRunId(e.target.value)
              setCheckId('')
            }}
          >
            <option value="">(choose run)</option>
            {(runs.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.id.slice(0, 8)} - {dt(r.created_at)} - {r.finding_count} finding(s)
              </option>
            ))}
          </select>
        </Field>
        <Field label="Check">
          <select className={input} value={checkId} onChange={(e) => setCheckId(e.target.value)}>
            <option value="">(choose check)</option>
            {(run?.check_ids ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <button className={btnPrimary} disabled={!runId || !checkId} onClick={create}>
          Create working paper
        </button>
        <Field label="Show status">
          <select className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option value="open">open</option>
            <option value="in_review">in review</option>
            <option value="signed_off">signed off</option>
          </select>
        </Field>
      </div>
      <ErrorBox error={error ?? papers.error ?? runs.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Paper</th>
            <th className={th}>Run</th>
            <th className={th}>Check</th>
            <th className={th}>Status</th>
            <th className={thR}>Population</th>
            <th className={thR}>Amount</th>
            <th className={thR}>Exceptions</th>
            <th className={thR}>Open</th>
            <th className={th}>Sample</th>
            <th className={th}>By</th>
          </tr>
        </thead>
        <tbody>
          {(papers.data ?? [])
            .filter((p) => (!runId || p.run_id === runId) && (!checkId || p.check_id === checkId))
            .map((p) => (
              <tr key={p.id}>
                <td className={td}>
                  <Link className="text-blue-700 underline" to={`/audit/papers/${p.id}`}>
                    {p.id.slice(0, 8)}
                  </Link>
                </td>
                <td className={td}>
                  <Link className="text-blue-700 underline" to={`/audit/runs/${p.run_id}`}>
                    {p.run_id.slice(0, 8)}
                  </Link>
                </td>
                <td className={td + ' font-mono'}>{p.check_id}</td>
                <td className={td}>
                  <StatusPill status={p.status} />
                </td>
                <td className={tdR}>{p.population_count}</td>
                <td className={tdR}>{formatInr(p.population_amount)}</td>
                <td className={tdR}>{p.item_count}</td>
                <td className={tdR}>{p.open_count}</td>
                <td className={td}>{p.sample_method}</td>
                <td className={td}>{p.created_by}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </Page>
  )
}
