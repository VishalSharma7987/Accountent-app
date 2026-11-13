import { useState } from 'react'
import { gstApi, type AnyTables, type ReturnQuery, type Working } from '../api/gst'
import { ErrorBox, Notice, Page, btn, btnPrimary, td, tdR, th, thR, Amount } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { DataView, MonthInput, RegistrationSelect, RuleBadge, Warnings, useRegistrations } from './common'
import { isQuarterly, returnQuery } from './lib'

type Kind = 'gstr1' | 'gstr3b' | 'tie-out' | 'composition'
const TITLE: Record<Kind, string> = {
  gstr1: 'GSTR-1 working',
  gstr3b: 'GSTR-3B working',
  'tie-out': 'Tie-out: books, GSTR-1, GSTR-3B',
  composition: 'Composition (CMP-08) working',
}

function GstR1Tables({ tables }: { tables: AnyTables }) {
  // every table is drawn as the server sent it; entries carry portal_table where the server knows the portal number
  return (
    <div className="space-y-1">
      {Object.entries(tables).map(([k, v]) => (
        <DataView key={k} name={k} value={v} />
      ))}
    </div>
  )
}

export default function Returns({ kind }: { kind: Kind }) {
  const { clientId } = useClient()
  const { regs, active, regId, reg, setRegId } = useRegistrations()
  const [month, setMonth] = useState('')
  const q: ReturnQuery | null = returnQuery(reg, month)
  const key = q ? `${q.registration_id}:${q.period_start}:${q.period_kind}` : ''
  const load = useLoad<unknown>(
    clientId && q
      ? () =>
          kind === 'gstr1' ? gstApi.gstr1(clientId, q) : kind === 'gstr3b' ? gstApi.gstr3b(clientId, q) : kind === 'tie-out' ? gstApi.tieOut(clientId, q) : gstApi.composition(clientId, q.registration_id, q.period_start)
      : null,
    `gst-${kind}:${clientId}:${key}`,
  )
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title={TITLE[kind]}>Select a client first.</Page>

  const data = load.data as unknown
  const working = kind === 'gstr1' || kind === 'gstr3b' ? (data as Working<AnyTables> | null) : null
  const ruleStatus = (data as { rule_status?: Working<AnyTables>['rule_status'] } | null)?.rule_status

  const saveWorking = async () => {
    if (!q) return
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      const out = await gstApi.saveWorking(clientId, { registration_id: q.registration_id, return_type: kind, period_start: q.period_start, period_kind: q.period_kind })
      setNotice(`Saved as draft version ${out.version}. Finalise it under GST / Workings.`)
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page title={TITLE[kind]}>
      <div className="flex flex-wrap items-end gap-3">
        <RegistrationSelect regs={active.length ? active : regs} value={regId} onChange={setRegId} />
        <MonthInput value={month} onChange={setMonth} label={isQuarterly(reg) ? 'Any month of the quarter (YYYY-MM)' : 'Month (YYYY-MM)'} />
        {q && <span className="pb-1 text-xs text-slate-600">Period: {q.period_kind} starting {q.period_start}</span>}
        {q && kind !== 'composition' && (
          <>
            {(kind === 'gstr1' || kind === 'gstr3b' || kind === 'tie-out') && (
              <>
                <a className={btn} href={gstApi.returnExportUrl(clientId, kind, 'xlsx', q)}>
                  Excel
                </a>
                {kind !== 'tie-out' && (
                  <a className={btn} href={gstApi.returnExportUrl(clientId, kind, 'json', q)} title="Offline-tool JSON as understood; not yet checked against a portal sample">
                    JSON (unverified format)
                  </a>
                )}
              </>
            )}
            {kind !== 'tie-out' && (
              <button className={btnPrimary} disabled={busy} onClick={saveWorking}>
                Save as working
              </button>
            )}
          </>
        )}
      </div>
      {ruleStatus && <RuleBadge status={ruleStatus} />}
      <ErrorBox error={error ?? load.error} />
      {notice && <Notice>{notice}</Notice>}
      {!q && <div className="text-sm text-slate-600">Choose a registration and a month. Figures come from posted vouchers only.</div>}
      {load.loading && <div className="text-sm text-slate-500">Loading...</div>}

      {working && (
        <>
          <div className="text-xs text-slate-600">
            {working.gstin} / {working.period_start} to {working.period_end} / {working.source_voucher_count} posted vouchers / generated {working.generated_at.slice(0, 16).replace('T', ' ')}
          </div>
          <Warnings items={working.warnings} />
          {working.unposted_drafts_in_period.length > 0 && (
            <div className="rounded border border-amber-400 bg-amber-50 px-3 py-1 text-sm text-amber-900">
              {working.unposted_drafts_in_period.length} unposted draft voucher(s) in this period are NOT included. Post or discard them first.
            </div>
          )}
          <GstR1Tables tables={working.tables} />
        </>
      )}

      {kind === 'tie-out' && load.data ? <TieOutView data={load.data as unknown as import('../api/gst').TieOut} /> : null}
      {kind === 'composition' && load.data ? <DataView value={load.data} /> : null}
    </Page>
  )
}

function TieOutView({ data }: { data: import('../api/gst').TieOut }) {
  const heads = ['Books output', 'GSTR-1 working', 'GSTR-3B working', 'Filed GSTR-1', 'Filed GSTR-3B', 'Books - GSTR-1', 'GSTR-1 - 3B', 'Books - filed']
  return (
    <div className="space-y-2">
      <div className={`rounded border px-3 py-1 text-sm ${data.ties ? 'border-green-400 bg-green-50 text-green-900' : 'border-red-400 bg-red-50 text-red-900'}`}>
        {data.ties ? 'Books, GSTR-1 and GSTR-3B tie.' : 'They do not tie. Differences are shown below and are never forced.'}
      </div>
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Head</th>
            {heads.map((h) => (
              <th key={h} className={thR}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.head}>
              <td className={td}>{r.head}</td>
              {[r.books_output, r.gstr1_working, r.gstr3b_working, r.filed_gstr1, r.filed_gstr3b, r.d_books_gstr1, r.d_gstr1_gstr3b, r.d_books_filed].map((v, i) => (
                <td key={i} className={tdR}>
                  {v === null ? <span className="text-slate-400">-</span> : <Amount value={v} />}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <DataView name="itc" value={data.itc} />
      <h3 className="text-sm font-semibold text-slate-700">Likely causes of a difference</h3>
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Cause</th>
            <th className={th}>Reference</th>
            <th className={thR}>Amount</th>
          </tr>
        </thead>
        <tbody>
          {data.causes.map((c, i) => (
            <tr key={i}>
              <td className={td}>{c.kind}</td>
              <td className={td}>{c.reference}</td>
              <td className={tdR}>
                <Amount value={c.amount} />
              </td>
            </tr>
          ))}
          {data.causes.length === 0 && (
            <tr>
              <td className={td} colSpan={3}>
                None found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
