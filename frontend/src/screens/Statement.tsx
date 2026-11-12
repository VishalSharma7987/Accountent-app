import { useState } from 'react'
import { api } from '../api'
import { Amount, BalanceText, ErrorBox, Field, LedgerPicker, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { exportXlsx } from '../lib/exportXlsx'
import { formatBalance, formatInr } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import type { ApiFailure } from '../lib/apiError'
import type { LedgerStatement } from '../types'

export default function Statement() {
  const { clientId, client, latestYear } = useClient()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [ledgerId, setLedgerId] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [result, setResult] = useState<LedgerStatement | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="Ledger statement">Select a client first.</Page>
  const fromDate = from || latestYear?.start_date || ''
  const toDate = to || latestYear?.end_date || ''

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.ledgerStatement(clientId, ledgerId, fromDate, toDate))
    } catch (e) {
      setResult(null)
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const exportIt = () => {
    if (!result) return
    exportXlsx(
      `ledger-${result.ledger_name}-${result.from_date}-${result.to_date}.xlsx`,
      `${client?.name ?? ''} — ${result.ledger_name} (${result.from_date} to ${result.to_date})`,
      ['Date', 'Voucher no', 'Type', 'Particulars', 'Narration', 'Debit', 'Credit', 'Balance'],
      result.rows.map((r) => [
        r.date,
        r.voucher_number ?? '',
        r.voucher_type ?? '',
        r.particulars,
        r.narration ?? '',
        r.debit === '0.00' ? '' : formatInr(r.debit),
        r.credit === '0.00' ? '' : formatInr(r.credit),
        formatBalance(r.balance),
      ]),
    )
  }

  return (
    <Page title="Ledger statement">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <div className="w-64">
          <Field label="Ledger">
            <LedgerPicker ledgers={ledgers.data ?? []} value={ledgerId} onChange={setLedgerId} />
          </Field>
        </div>
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
              <th className={th}>Voucher no</th>
              <th className={th}>Particulars</th>
              <th className={th}>Narration</th>
              <th className={thR}>Debit</th>
              <th className={thR}>Credit</th>
              <th className={thR}>Balance</th>
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r, i) => (
              <tr key={i} className={r.kind === 'entry' ? '' : 'bg-slate-50 font-semibold'}>
                <td className={td}>{r.date}</td>
                <td className={td}>{r.voucher_number}</td>
                <td className={td}>{r.particulars}</td>
                <td className={td}>{r.narration}</td>
                <td className={tdR}>{r.kind !== 'closing' && r.debit !== '0.00' ? <Amount value={r.debit} /> : ''}</td>
                <td className={tdR}>{r.kind !== 'closing' && r.credit !== '0.00' ? <Amount value={r.credit} /> : ''}</td>
                <td className={tdR}>
                  <BalanceText balance={r.balance} />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="font-semibold">
              <td className={td} colSpan={4}>
                Period totals
              </td>
              <td className={tdR}>
                <Amount value={result.total_debit} />
              </td>
              <td className={tdR}>
                <Amount value={result.total_credit} />
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
