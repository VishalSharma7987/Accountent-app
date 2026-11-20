import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { auditApi, downloadFile, reportXlsxPath } from '../api/audit'
import { ErrorBox, Page, btn, td, th, thR, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import AiSummary from './AiSummary'
import { FindingRows, NoClient, SeverityBadge, VerifBadge } from './common'
import { dmy } from './lib'

export default function RunReport() {
  const { id = '' } = useParams()
  const { clientId } = useClient()
  const navigate = useNavigate()
  const report = useLoad(clientId && id ? () => auditApi.getReport(clientId, id) : null, `audit-report:${clientId}:${id}`)
  const [only, setOnly] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  if (!clientId)
    return (
      <Page title="Audit report">
        <NoClient />
      </Page>
    )
  const r = report.data
  const makePaper = async (checkId: string) => {
    setError(null)
    try {
      const p = await auditApi.createPaper(clientId, { run_id: id, check_id: checkId })
      navigate(`/audit/papers/${p.id}`)
    } catch (e) {
      const f = asFailure(e)
      if (f.code === 'paper_exists') navigate(`/audit/papers?run=${id}&check=${checkId}`)
      else setError(f)
    }
  }
  const save = async () => {
    setError(null)
    try {
      await downloadFile(reportXlsxPath(clientId, id), `audit-run-${id}.xlsx`, { format: 'xlsx' })
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const from = r?.run.from_date ?? ''
  const to = r?.run.to_date ?? ''
  const shown = (r?.checks ?? []).filter((c) => !only || c.check_id === only)
  return (
    <Page
      title="Audit report"
      actions={
        <>
          <Link className={btn} to="/audit/runs">
            All runs
          </Link>
          <button className={btn} disabled={!r} onClick={save}>
            Excel export
          </button>
        </>
      }
    >
      <ErrorBox error={report.error ?? error} />
      {report.loading && !r && <div className="text-sm text-slate-500">Loading the report...</div>}
      {r && (
        <>
          <div className="text-sm text-slate-700">
            Period {dmy(from)} to {dmy(to)}. Status {String(r.run.status)}. Run by {String(r.run.created_by)}. Engine {String(r.run.engine_version ?? '')}.
          </div>
          {r.rules_pending.length > 0 && (
            <div className="rounded border border-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <div className="font-semibold">
                <VerifBadge status="pending" /> Limits used here are not verified from an official source
              </div>
              <ul className="list-disc pl-5">
                {r.rules_pending.map((p) => (
                  <li key={p.rule_key}>{p.line}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap gap-6 rounded border border-slate-300 bg-white p-3 text-sm">
            <span>Findings: {r.totals.findings}</span>
            {Object.entries(r.totals.by_severity).map(([k, v]) => (
              <span key={k}>
                <SeverityBadge severity={k} /> {v}
              </span>
            ))}
            <span>Possible disallowance: {formatInr(r.totals.disallowance_amount)}</span>
          </div>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Check</th>
                <th className={th}>Title</th>
                <th className={th}>Severity</th>
                <th className={thR}>Population</th>
                <th className={thR}>Findings</th>
                <th className={th}>Notes / errors</th>
                <th className={th}></th>
              </tr>
            </thead>
            <tbody>
              {r.checks.map((c) => (
                <tr key={c.check_id} className={only === c.check_id ? 'bg-blue-50' : ''}>
                  <td className={td + ' font-mono'}>{c.check_id}</td>
                  <td className={td}>{c.title}</td>
                  <td className={td}>
                    <SeverityBadge severity={c.severity} />
                  </td>
                  <td className={tdR}>{c.population}</td>
                  <td className={tdR}>{c.findings.length}</td>
                  <td className={td + ' text-xs'}>
                    {c.error && <div className="text-red-700">Could not run: {c.error}</div>}
                    {c.notes.map((n, i) => (
                      <div key={i}>{n}</div>
                    ))}
                  </td>
                  <td className={td + ' whitespace-nowrap'}>
                    <button className="text-blue-700 underline" onClick={() => setOnly(only === c.check_id ? '' : c.check_id)}>
                      {only === c.check_id ? 'Show all' : 'Show findings'}
                    </button>
                    {c.findings.length > 0 && (
                      <button className="ml-2 text-blue-700 underline" onClick={() => makePaper(c.check_id)}>
                        Working paper
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2 className="font-semibold">Findings{only ? ` of ${only}` : ''}</h2>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Check</th>
                <th className={th}>Severity</th>
                <th className={th}>Date</th>
                <th className={th}>Subject</th>
                <th className={th}>Finding</th>
                <th className={thR}>Amount</th>
                <th className={thR}>Disallowance</th>
                <th className={th}></th>
              </tr>
            </thead>
            <tbody>
              <FindingRows key={only} findings={shown.flatMap((c) => c.findings)} from={from} to={to} />
            </tbody>
          </table>
          {r.totals.findings === 0 && <div className="text-sm text-slate-500">No findings in this run.</div>}
          <AiSummary clientId={clientId} runId={id} checkIds={r.checks.filter((c) => c.findings.length > 0).map((c) => c.check_id)} />
        </>
      )}
    </Page>
  )
}
