import { Fragment, useState } from 'react'
import { api } from '../api'
import { Amount, BalanceText, ErrorBox, Field, Page, btn, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import { exportXlsx } from '../lib/exportXlsx'
import { formatBalance, formatInr } from '../lib/money'
import { BUCKETS } from '../lib/phase2'
import { useLoad } from '../lib/useLoad'
import type { BucketKey } from '../types'

const bucketCell = (v: string | undefined) => (v === undefined || v === '0.00' ? '' : formatInr(v))

export default function Outstanding() {
  const { clientId, client } = useClient()
  const [kind, setKind] = useState<'receivable' | 'payable'>('receivable')
  const [asOn, setAsOn] = useState(today())
  const report = useLoad(clientId && asOn ? () => api.outstanding(clientId, kind, asOn) : null, `outstanding:${clientId}:${kind}:${asOn}`)
  const ageing = useLoad(clientId && asOn ? () => api.ageing(clientId, kind, asOn) : null, `ageing:${clientId}:${kind}:${asOn}`)

  if (!clientId) return <Page title="Outstanding">Select a client first.</Page>
  const r = report.data
  const a = ageing.data
  const heading = kind === 'receivable' ? 'Receivable (debtors)' : 'Payable (creditors)'

  const exportOutstanding = () => {
    if (!r) return
    const rows: string[][] = []
    for (const p of r.parties) {
      for (const b of p.bills) {
        rows.push([p.party_name, b.bill_ref ?? (b.kind === 'advance' ? '(advance)' : '(on account)'), b.bill_date, b.due_date, formatBalance(b.original), formatBalance(b.outstanding), String(b.days_past_due), b.bucket])
      }
      rows.push([`${p.party_name} total`, '', '', '', '', formatBalance(p.total), '', p.ties ? '' : `DOES NOT TIE to ledger ${formatBalance(p.ledger_balance)}`])
    }
    rows.push(['Total', '', '', '', '', formatBalance(r.total), '', r.ties ? '' : 'DOES NOT TIE to ledger balances'])
    exportXlsx(`outstanding-${kind}-${asOn}.xlsx`, `${client?.name ?? ''} — Outstanding ${heading} as on ${asOn}`, ['Party', 'Bill ref', 'Bill date', 'Due date', 'Original', 'Outstanding', 'Days past due', 'Bucket'], rows)
  }
  const exportAgeing = () => {
    if (!a) return
    const keys = BUCKETS.map((b) => b.key)
    exportXlsx(
      `ageing-${kind}-${asOn}.xlsx`,
      `${client?.name ?? ''} — Ageing ${heading} as on ${asOn}`,
      ['Party', ...BUCKETS.map((b) => b.label), 'Total'],
      [
        ...a.rows.map((x) => [x.party_name, ...keys.map((k) => bucketCell(x[k])), formatInr(x.total)]),
        ['Total', ...keys.map((k) => bucketCell(a.totals[k])), a.totals.total ? formatInr(a.totals.total) : ''],
      ],
    )
  }

  return (
    <Page title="Outstanding and ageing">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Show">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value as 'receivable' | 'payable')}>
            <option value="receivable">Receivable (debtors)</option>
            <option value="payable">Payable (creditors)</option>
          </select>
        </Field>
        <Field label="As on">
          <input type="date" className={input} value={asOn} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        <button className={btn} disabled={!r} onClick={exportOutstanding}>
          Export outstanding
        </button>
        <button className={btn} disabled={!a} onClick={exportAgeing}>
          Export ageing
        </button>
      </div>
      <ErrorBox error={report.error ?? ageing.error} />

      {r && !r.ties && (
        <div role="alert" className="rounded border border-red-400 bg-red-50 px-3 py-2 text-sm font-semibold text-red-800">
          Does not tie: the open items do not add up to the ledger balances. Parties that differ are marked below.
        </div>
      )}

      {r && (
        <table className="w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Party / bill</th>
              <th className={th}>Bill date</th>
              <th className={th}>Due date</th>
              <th className={thR}>Original</th>
              <th className={thR}>Outstanding</th>
              <th className={thR}>Days past due</th>
              {BUCKETS.map((b) => (
                <th key={b.key} className={thR}>
                  {b.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {r.parties.map((p) => (
              <Fragment key={p.party_ledger_id}>
                <tr className="bg-slate-100 font-semibold">
                  <td className={td} colSpan={4}>
                    {p.party_name}
                    {!p.ties && (
                      <span className="ml-2 rounded bg-red-200 px-2 py-0.5 text-xs font-medium text-red-900">
                        does not tie: ledger balance {formatBalance(p.ledger_balance)}
                      </span>
                    )}
                  </td>
                  <td className={tdR}>
                    <BalanceText balance={p.total} />
                  </td>
                  <td className={td} colSpan={6}></td>
                </tr>
                {p.bills.map((b, i) => (
                  <tr key={i}>
                    <td className={td + ' pl-6'}>{b.bill_ref ?? (b.kind === 'advance' ? '(advance)' : '(on account)')}</td>
                    <td className={td}>{b.bill_date}</td>
                    <td className={td}>{b.due_date}</td>
                    <td className={tdR}>
                      <BalanceText balance={b.original} />
                    </td>
                    <td className={tdR}>
                      <BalanceText balance={b.outstanding} />
                    </td>
                    <td className={tdR}>{b.days_past_due}</td>
                    {BUCKETS.map((k) => (
                      <td key={k.key} className={tdR}>
                        {b.bucket === k.key ? <Amount value={b.outstanding.amount} /> : ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))}
            {r.parties.length === 0 && (
              <tr>
                <td className={td} colSpan={11}>
                  Nothing outstanding as on {asOn}.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="bg-slate-50 font-semibold">
              <td className={td} colSpan={4}>
                Total {heading}
              </td>
              <td className={tdR}>
                <BalanceText balance={r.total} danger={!r.ties} />
              </td>
              <td className={td}></td>
              {BUCKETS.map((k: { key: BucketKey }) => (
                <td key={k.key} className={tdR}>
                  {bucketCell(r.buckets[k.key])}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      )}

      {a && (
        <>
          <h2 className="pt-2 text-base font-semibold">Ageing summary: {heading} as on {asOn}</h2>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Party</th>
                {BUCKETS.map((b) => (
                  <th key={b.key} className={thR}>
                    {b.label}
                  </th>
                ))}
                <th className={thR}>Total</th>
              </tr>
            </thead>
            <tbody>
              {a.rows.map((x) => (
                <tr key={x.party_ledger_id}>
                  <td className={td}>{x.party_name}</td>
                  {BUCKETS.map((b) => (
                    <td key={b.key} className={tdR}>
                      {bucketCell(x[b.key])}
                    </td>
                  ))}
                  <td className={tdR}>
                    <Amount value={x.total} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-slate-50 font-semibold">
                <td className={td}>Total</td>
                {BUCKETS.map((b) => (
                  <td key={b.key} className={tdR}>
                    {bucketCell(a.totals[b.key])}
                  </td>
                ))}
                <td className={tdR}>{a.totals.total ? <Amount value={a.totals.total} /> : ''}</td>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </Page>
  )
}
