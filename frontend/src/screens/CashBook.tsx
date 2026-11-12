import { Fragment, useState } from 'react'
import { api } from '../api'
import { Amount, BalanceText, ErrorBox, Field, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { exportXlsx } from '../lib/exportXlsx'
import { formatBalance, formatInr } from '../lib/money'
import { cashBankLedgers } from '../lib/phase2'
import { asFailure, useLoad } from '../lib/useLoad'
import type { CashBook as CashBookData } from '../types'

const nz = (v: string) => (v === '0.00' ? '' : formatInr(v))

export default function CashBook() {
  const { clientId, client, latestYear } = useClient()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [ledgerId, setLedgerId] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [result, setResult] = useState<CashBookData | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="Cash / Bank book">Select a client first.</Page>
  const fromDate = from || latestYear?.start_date || ''
  const toDate = to || latestYear?.end_date || ''

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.cashBook(clientId, ledgerId, fromDate, toDate))
    } catch (e) {
      setResult(null)
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const exportIt = () => {
    if (!result) return
    const rows: string[][] = [['', 'Opening balance', '', '', formatBalance(result.opening)]]
    for (const d of result.days) {
      for (const e of d.entries) rows.push([d.date, `${e.voucher_number ?? ''} ${e.counter_ledgers.join(', ')} ${e.narration}`.trim(), nz(e.receipt), nz(e.payment), ''])
      rows.push([d.date, 'Day total', nz(d.receipts), nz(d.payments), formatBalance(d.closing)])
    }
    rows.push(['', 'Total', formatInr(result.total_receipts), formatInr(result.total_payments), formatBalance(result.closing)])
    exportXlsx(`book-${result.ledger_name}-${fromDate}-${toDate}.xlsx`, `${client?.name ?? ''} — ${result.ledger_name} (${fromDate} to ${toDate})`, ['Date', 'Particulars', 'Receipts', 'Payments', 'Closing'], rows)
  }

  const choices = cashBankLedgers(ledgers.data ?? [])

  return (
    <Page title="Cash / Bank book">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Cash or bank ledger">
          <select className={input} value={ledgerId} onChange={(e) => setLedgerId(e.target.value)}>
            <option value="">(choose ledger)</option>
            {choices.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} ({l.group_name})
              </option>
            ))}
          </select>
        </Field>
        <Field label="From">
          <input type="date" className={input} value={fromDate} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To">
          <input type="date" className={input} value={toDate} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <button className={btnPrimary} disabled={!ledgerId || busy} onClick={run}>
          Show
        </button>
        <button className={btn} disabled={!result} onClick={exportIt}>
          Export to Excel
        </button>
      </div>
      <ErrorBox error={error ?? ledgers.error} />
      {result && (
        <table className="w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Date</th>
              <th className={th}>Voucher</th>
              <th className={th}>Particulars</th>
              <th className={thR}>Receipts</th>
              <th className={thR}>Payments</th>
              <th className={thR}>Closing</th>
            </tr>
          </thead>
          <tbody>
            <tr className="bg-slate-50 font-semibold">
              <td className={td} colSpan={5}>
                Opening balance
              </td>
              <td className={tdR}>
                <BalanceText balance={result.opening} />
              </td>
            </tr>
            {result.days.map((d) => (
              <Fragment key={d.date}>
                {d.entries.map((e, i) => (
                  <tr key={i}>
                    <td className={td}>{i === 0 ? d.date : ''}</td>
                    <td className={td}>{e.voucher_number ?? '(draft)'}</td>
                    <td className={td}>
                      {e.counter_ledgers.join(', ')} <span className="text-xs text-slate-500">{e.narration}</span>
                    </td>
                    <td className={tdR}>{nz(e.receipt)}</td>
                    <td className={tdR}>{nz(e.payment)}</td>
                    <td className={td}></td>
                  </tr>
                ))}
                <tr className="bg-slate-50 font-semibold">
                  <td className={td}>{d.date}</td>
                  <td className={td} colSpan={2}>
                    Day total
                  </td>
                  <td className={tdR}>
                    <Amount value={d.receipts} />
                  </td>
                  <td className={tdR}>
                    <Amount value={d.payments} />
                  </td>
                  <td className={tdR}>
                    <BalanceText balance={d.closing} />
                  </td>
                </tr>
              </Fragment>
            ))}
          </tbody>
          <tfoot>
            <tr className="font-semibold">
              <td className={td} colSpan={3}>
                Total for the period
              </td>
              <td className={tdR}>
                <Amount value={result.total_receipts} />
              </td>
              <td className={tdR}>
                <Amount value={result.total_payments} />
              </td>
              <td className={tdR}>
                <BalanceText balance={result.closing} />
              </td>
            </tr>
          </tfoot>
        </table>
      )}
    </Page>
  )
}
