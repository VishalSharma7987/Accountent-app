import { useState } from 'react'
import { api } from '../api'
import { Amount, ErrorBox, Field, Page, btn, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import { exportXlsx } from '../lib/exportXlsx'
import { formatInr } from '../lib/money'
import { useLoad } from '../lib/useLoad'

export default function MsmeDue() {
  const { clientId, client } = useClient()
  const [asOn, setAsOn] = useState(today())
  const report = useLoad(clientId && asOn ? () => api.msmeDue(clientId, asOn) : null, `msme:${clientId}:${asOn}`)
  if (!clientId) return <Page title="MSME dues">Select a client first.</Page>
  const r = report.data

  const exportIt = () => {
    if (!r) return
    exportXlsx(
      `msme-due-${asOn}.xlsx`,
      `${client?.name ?? ''} — MSME dues as on ${asOn}${r.rule_status === 'pending' ? ' (legal rule not yet verified)' : r.rule_status === 'secondary_verified' ? ' (verified from secondary sources; awaiting CA confirmation)' : ''}`,
      ['Party', 'Bill ref', 'Bill date', 'Acceptance date', 'Acceptance basis', 'Legal days', 'Legal due date', 'Days overdue', 'Outstanding'],
      [
        ...r.items.map((i) => [i.party_name, i.bill_ref ?? '', i.bill_date, i.acceptance_date, i.acceptance_basis, String(i.legal_days), i.legal_due_date, String(i.days_overdue), formatInr(i.outstanding)]),
        ['Total', '', '', '', '', '', '', '', formatInr(r.total_outstanding)],
      ],
    )
  }

  return (
    <Page title="MSME dues (payments past the legal limit)">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="As on">
          <input type="date" className={input} value={asOn} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        <button className={btn} disabled={!r} onClick={exportIt}>
          Export to Excel
        </button>
      </div>
      <ErrorBox error={report.error} />
      {r && r.rule_status === 'pending' && (
        <div role="alert" className="rounded border border-amber-400 bg-amber-100 px-3 py-2 text-sm text-amber-900">
          <strong>Legal rule not yet verified.</strong> The payment time limits behind this report have not been confirmed from the official
          text. Treat the dates below as a flag for review, not as a legal conclusion.
          {r.rule_source && <div className="text-xs">Source noted: {r.rule_source}</div>}
        </div>
      )}
      {r && r.rule_status === 'secondary_verified' && (
        <div role="note" className="rounded border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900">
          Verified from secondary sources; awaiting CA confirmation.
          {r.rule_source && <div className="text-xs">Source noted: {r.rule_source}</div>}
        </div>
      )}
      {r && (
        <>
          <div className="text-xs text-slate-600">
            Rule status: <span className="font-mono">{r.rule_status}</span>
          </div>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Party</th>
                <th className={th}>Bill ref</th>
                <th className={th}>Bill date</th>
                <th className={th}>Counted from</th>
                <th className={thR}>Legal days</th>
                <th className={th}>Legal due date</th>
                <th className={thR}>Days overdue</th>
                <th className={thR}>Outstanding</th>
              </tr>
            </thead>
            <tbody>
              {r.items.map((i, k) => (
                <tr key={k}>
                  <td className={td}>{i.party_name}</td>
                  <td className={td}>{i.bill_ref}</td>
                  <td className={td}>{i.bill_date}</td>
                  <td className={td}>
                    {i.acceptance_date} <span className="text-xs text-slate-500">({i.acceptance_basis})</span>
                  </td>
                  <td className={tdR}>{i.legal_days}</td>
                  <td className={td}>{i.legal_due_date}</td>
                  <td className={tdR + ' font-semibold text-red-700'}>{i.days_overdue}</td>
                  <td className={tdR}>
                    <Amount value={i.outstanding} />
                  </td>
                </tr>
              ))}
              {r.items.length === 0 && (
                <tr>
                  <td className={td} colSpan={8}>
                    No bills past the legal limit as on {asOn}.
                  </td>
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr className="font-semibold">
                <td className={td} colSpan={7}>
                  Total outstanding past the limit
                </td>
                <td className={tdR}>
                  <Amount value={r.total_outstanding} />
                </td>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </Page>
  )
}
