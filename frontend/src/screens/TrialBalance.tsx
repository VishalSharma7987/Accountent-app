import { useState } from 'react'
import { api } from '../api'
import { today } from '../lib/dates'
import { Amount, BalanceText, ErrorBox, Field, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { exportXlsx } from '../lib/exportXlsx'
import { formatBalance, formatInr } from '../lib/money'
import { asFailure } from '../lib/useLoad'
import type { ApiFailure } from '../lib/apiError'
import type { TrialBalance as Tb } from '../types'


export default function TrialBalance() {
  const { clientId, client, latestYear } = useClient()
  const [asOn, setAsOn] = useState('')
  const [view, setView] = useState<'group' | 'ledger'>('group')
  const [hideZero, setHideZero] = useState(false)
  const [result, setResult] = useState<Tb | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="Trial Balance">Select a client first.</Page>
  const date = asOn || clampToYear(today(), latestYear)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.trialBalance(clientId, date, hideZero))
    } catch (e) {
      setResult(null)
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const exportIt = () => {
    if (!result) return
    const rows: string[][] = []
    for (const s of result.sections) {
      rows.push([s.group_name, '', formatInr(s.debit), formatInr(s.credit)])
      for (const r of s.rows) rows.push(['', `${r.group_path.slice(1).join(' > ')}${r.group_path.length > 1 ? ' / ' : ''}${r.ledger_name}`, r.debit === '0.00' ? '' : formatInr(r.debit), r.credit === '0.00' ? '' : formatInr(r.credit)])
    }
    rows.push(['TOTAL', '', formatInr(result.total_debit), formatInr(result.total_credit)])
    if (!result.is_balanced) rows.push(['DIFFERENCE', '', formatBalance(result.difference), ''])
    exportXlsx(`trial-balance-${result.as_on}.xlsx`, `${client?.name ?? ''} — Trial Balance as on ${result.as_on}`, ['Group', 'Ledger', 'Debit', 'Credit'], rows)
  }

  return (
    <Page title="Trial Balance">
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
        <Field label="As on">
          <input type="date" className={input} value={date} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        <Field label="View">
          <select className={input} value={view} onChange={(e) => setView(e.target.value as 'group' | 'ledger')}>
            <option value="group">Group-wise (with ledgers)</option>
            <option value="ledger">Ledger-wise</option>
          </select>
        </Field>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={hideZero} onChange={(e) => setHideZero(e.target.checked)} /> hide nil ledgers
        </label>
        <button className={btnPrimary} disabled={busy} onClick={run}>
          Show
        </button>
        <button className={btn} disabled={!result} onClick={exportIt}>
          Export to Excel
        </button>
      </div>
      <ErrorBox error={error} />
      {result && (
        <>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>{view === 'group' ? 'Group / Ledger' : 'Ledger'}</th>
                {view === 'ledger' && <th className={th}>Group</th>}
                <th className={thR + ' w-44'}>Debit</th>
                <th className={thR + ' w-44'}>Credit</th>
              </tr>
            </thead>
            <tbody>
              {view === 'group'
                ? result.sections.map((s) => (
                    <GroupSection key={s.group_code} s={s} />
                  ))
                : result.sections
                    .flatMap((s) => s.rows)
                    .sort((a, b) => a.ledger_name.localeCompare(b.ledger_name))
                    .map((r) => (
                      <tr key={r.ledger_id}>
                        <td className={td}>{r.ledger_name}</td>
                        <td className={td + ' text-slate-500'}>{r.group_path.join(' > ')}</td>
                        <td className={tdR}>{r.debit !== '0.00' && <Amount value={r.debit} />}</td>
                        <td className={tdR}>{r.credit !== '0.00' && <Amount value={r.credit} />}</td>
                      </tr>
                    ))}
            </tbody>
            <tfoot>
              <tr className="bg-slate-100 font-semibold">
                <td className={td} colSpan={view === 'ledger' ? 2 : 1}>
                  Total
                </td>
                <td className={tdR}>
                  <Amount value={result.total_debit} />
                </td>
                <td className={tdR}>
                  <Amount value={result.total_credit} />
                </td>
              </tr>
            </tfoot>
          </table>
          {result.is_balanced ? (
            <div className="text-sm text-green-700">Debit and Credit totals are equal.</div>
          ) : (
            <div role="alert" className="rounded border border-red-400 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
              The Trial Balance does not balance. Difference: <BalanceText balance={result.difference} danger />
            </div>
          )}
        </>
      )}
    </Page>
  )
}

function GroupSection({ s }: { s: Tb['sections'][number] }) {
  return (
    <>
      <tr className="bg-slate-50 font-semibold">
        <td className={td}>{s.group_name}</td>
        <td className={tdR}>
          <Amount value={s.debit} />
        </td>
        <td className={tdR}>
          <Amount value={s.credit} />
        </td>
      </tr>
      {s.rows.map((r) => (
        <tr key={r.ledger_id}>
          <td className={td + ' pl-6'}>
            {r.group_path.length > 1 && <span className="text-xs text-slate-500">{r.group_path.slice(1).join(' > ')} / </span>}
            {r.ledger_name}
          </td>
          <td className={tdR}>{r.debit !== '0.00' && <Amount value={r.debit} />}</td>
          <td className={tdR}>{r.credit !== '0.00' && <Amount value={r.credit} />}</td>
        </tr>
      ))}
    </>
  )
}

/** Default as-on date: today when it lies inside the latest year, else the year's end (a display default only). */
function clampToYear(now: string, year: { start_date: string; end_date: string } | null): string {
  if (!year) return now
  if (now < year.start_date) return year.start_date
  if (now > year.end_date) return year.end_date
  return now
}
