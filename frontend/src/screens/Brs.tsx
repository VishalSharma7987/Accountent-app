import { useState } from 'react'
import { api } from '../api'
import { BalanceText, ErrorBox, Field, Page, btn, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import { exportXlsx } from '../lib/exportXlsx'
import { formatBalance, formatInr } from '../lib/money'
import { cashBankLedgers } from '../lib/phase2'
import { useLoad } from '../lib/useLoad'
import type { Brs as BrsData, BrsItem } from '../types'

function Items({ title, items, hint }: { title: string; items: BrsItem[]; hint: string }) {
  return (
    <>
      <tr className="bg-slate-100">
        <td className={td + ' font-semibold'} colSpan={4}>
          {title} <span className="text-xs font-normal text-slate-500">{hint}</span>
        </td>
      </tr>
      {items.map((i, k) => (
        <tr key={k}>
          <td className={td + ' pl-6'}>{i.date}</td>
          <td className={td}>{i.reference}</td>
          <td className={td}>{i.description}</td>
          <td className={tdR}>{formatInr(i.amount)}</td>
        </tr>
      ))}
      {items.length === 0 && (
        <tr>
          <td className={td + ' pl-6 text-slate-500'} colSpan={4}>
            none
          </td>
        </tr>
      )}
    </>
  )
}

export default function Brs() {
  const { clientId, client } = useClient()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [bankId, setBankId] = useState('')
  const [asOn, setAsOn] = useState(today())
  const report = useLoad(clientId && bankId && asOn ? () => api.brs(clientId, bankId, asOn) : null, `brs:${clientId}:${bankId}:${asOn}`)
  if (!clientId) return <Page title="Bank reconciliation statement">Select a client first.</Page>
  const r = report.data
  const bankName = (ledgers.data ?? []).find((l) => l.id === bankId)?.name ?? ''

  const exportIt = (b: BrsData) => {
    const rows: string[][] = [['Balance as per books', '', '', formatBalance(b.balance_per_books)]]
    const add = (title: string, items: BrsItem[]) => {
      rows.push([title, '', '', ''])
      for (const i of items) rows.push([i.date, i.reference ?? '', i.description ?? '', formatInr(i.amount)])
    }
    add('Issued but not presented (cheques paid)', b.issued_not_presented)
    add('Deposited but not cleared', b.deposited_not_cleared)
    add('In the bank statement, not in books: credits', b.bank_only_credits)
    add('In the bank statement, not in books: debits', b.bank_only_debits)
    rows.push(['Balance as computed from the books', '', '', formatBalance(b.computed_bank_balance)])
    rows.push(['Balance as per bank statement', '', '', formatBalance(b.balance_per_bank)])
    rows.push([b.ties ? 'Difference (ties)' : 'DIFFERENCE: DOES NOT TIE', '', '', formatBalance(b.difference)])
    exportXlsx(`brs-${bankName}-${b.as_on}.xlsx`, `${client?.name ?? ''} — BRS ${bankName} as on ${b.as_on}`, ['Date / item', 'Reference', 'Description', 'Amount'], rows)
  }

  return (
    <Page title="Bank reconciliation statement (BRS)">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Bank ledger">
          <select className={input} value={bankId} onChange={(e) => setBankId(e.target.value)}>
            <option value="">(choose bank)</option>
            {cashBankLedgers(ledgers.data ?? [], true).map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="As on">
          <input type="date" className={input} value={asOn} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        <button className={btn} disabled={!r} onClick={() => r && exportIt(r)}>
          Export to Excel
        </button>
      </div>
      <ErrorBox error={report.error ?? ledgers.error} />
      {r && (
        <table className="w-full max-w-4xl border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Date</th>
              <th className={th}>Reference</th>
              <th className={th}>Description</th>
              <th className={thR}>Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr className="bg-slate-50 font-semibold">
              <td className={td} colSpan={3}>
                Balance as per books on {r.as_on}
              </td>
              <td className={tdR}>
                <BalanceText balance={r.balance_per_books} />
              </td>
            </tr>
            <Items title="Issued but not presented" hint="(cheques paid, not yet debited by the bank)" items={r.issued_not_presented} />
            <Items title="Deposited but not cleared" hint="(receipts banked, not yet credited by the bank)" items={r.deposited_not_cleared} />
            <Items title="In the bank statement, not in books: credits" hint="(bank-only items)" items={r.bank_only_credits} />
            <Items title="In the bank statement, not in books: debits" hint="(bank-only items)" items={r.bank_only_debits} />
            <tr className="bg-slate-50 font-semibold">
              <td className={td} colSpan={3}>
                Balance computed from the books and the items above
              </td>
              <td className={tdR}>
                <BalanceText balance={r.computed_bank_balance} />
              </td>
            </tr>
            <tr className="bg-slate-50 font-semibold">
              <td className={td} colSpan={3}>
                Balance as per bank statement
              </td>
              <td className={tdR}>
                <BalanceText balance={r.balance_per_bank} />
              </td>
            </tr>
            <tr className={r.ties ? 'font-semibold text-green-700' : 'bg-red-50 font-bold text-red-600'}>
              <td className={td} colSpan={3}>
                {r.ties ? 'Difference: the BRS ties' : 'Difference: the BRS DOES NOT TIE'}
              </td>
              <td className={tdR}>
                <BalanceText balance={r.difference} />
              </td>
            </tr>
          </tbody>
        </table>
      )}
    </Page>
  )
}
