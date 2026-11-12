import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { BalanceText, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatBalance } from '../lib/money'
import { openingBillsTotal } from '../lib/phase2'
import { asFailure, useLoad } from '../lib/useLoad'

interface Row {
  bill_ref: string
  bill_date: string
  due_date: string
  amount: string
  side: 'Dr' | 'Cr'
}

export default function OpeningBills() {
  const { clientId, client, latestYear } = useClient()
  const parties = useLoad(clientId ? () => api.listParties(clientId) : null, `parties:${clientId}:all`)
  const [partyId, setPartyId] = useState('')
  const [fyChoice, setFyChoice] = useState('')
  const fyId = fyChoice || latestYear?.id || ''
  const party = (parties.data ?? []).find((p) => p.ledger_id === partyId)
  const loaded = useLoad(clientId && fyId && partyId ? () => api.getOpeningBills(clientId, fyId, partyId) : null, `opening-bills:${clientId}:${fyId}:${partyId}`)
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!loaded.data) return
    setRows(
      loaded.data.bills.map((b) => ({ bill_ref: b.bill_ref, bill_date: b.bill_date, due_date: b.due_date ?? '', amount: b.amount, side: b.side })),
    )
  }, [loaded.data])

  const typedTotal = useMemo(() => openingBillsTotal(rows), [rows])

  if (!clientId) return <Page title="Opening bills">Select a client first.</Page>

  const setRow = (i: number, patch: Partial<Row>) => {
    setRows((r) => r.map((x, k) => (k === i ? { ...x, ...patch } : x)))
    setNotice('')
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await api.saveOpeningBills(
        clientId,
        fyId,
        partyId,
        rows.map((r) => ({
          bill_ref: r.bill_ref.trim(),
          bill_date: r.bill_date,
          amount: r.amount.trim(),
          side: r.side,
          ...(r.due_date ? { due_date: r.due_date } : {}),
        })),
      )
      setNotice('Opening bills saved.')
      loaded.reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const d = loaded.data
  return (
    <Page title="Opening bills (per party)">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Party">
          <select className={input} value={partyId} onChange={(e) => setPartyId(e.target.value)}>
            <option value="">(choose party)</option>
            {(parties.data ?? []).map((p) => (
              <option key={p.ledger_id} value={p.ledger_id}>
                {p.ledger_name}
                {p.bill_wise ? '' : ' (not bill-wise)'}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Financial year">
          <select className={input} value={fyId} onChange={(e) => setFyChoice(e.target.value)}>
            {(client?.financial_years ?? []).map((y) => (
              <option key={y.id} value={y.id}>
                {y.start_date} to {y.end_date}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ErrorBox error={error ?? parties.error ?? loaded.error} />
      {notice && <Notice>{notice}</Notice>}

      {party && (
        <>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Bill ref</th>
                <th className={th}>Bill date</th>
                <th className={th}>Due date (blank = bill date + credit days)</th>
                <th className={thR}>Amount</th>
                <th className={th}>Side</th>
                <th className={th}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className={td}>
                    <input className={input + ' w-full'} value={r.bill_ref} aria-label={`bill ${i + 1} ref`} onChange={(e) => setRow(i, { bill_ref: e.target.value })} />
                  </td>
                  <td className={td}>
                    <input type="date" className={input} value={r.bill_date} aria-label={`bill ${i + 1} date`} onChange={(e) => setRow(i, { bill_date: e.target.value })} />
                  </td>
                  <td className={td}>
                    <input type="date" className={input} value={r.due_date} aria-label={`bill ${i + 1} due date`} onChange={(e) => setRow(i, { due_date: e.target.value })} />
                  </td>
                  <td className={tdR}>
                    <input className={input + ' w-36 text-right'} inputMode="decimal" value={r.amount} aria-label={`bill ${i + 1} amount`} onChange={(e) => setRow(i, { amount: e.target.value })} />
                  </td>
                  <td className={td}>
                    <select className={input} value={r.side} aria-label={`bill ${i + 1} side`} onChange={(e) => setRow(i, { side: e.target.value as 'Dr' | 'Cr' })}>
                      <option value="Dr">Dr</option>
                      <option value="Cr">Cr</option>
                    </select>
                  </td>
                  <td className={td}>
                    <button className="text-slate-400 hover:text-red-600" aria-label={`remove bill ${i + 1}`} onClick={() => setRows((x) => x.filter((_, k) => k !== i))}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-slate-50 font-semibold">
                <td className={td} colSpan={3}>
                  Total of rows as typed (display only)
                </td>
                <td className={tdR}>{formatBalance(typedTotal)}</td>
                <td className={td} colSpan={2}></td>
              </tr>
            </tfoot>
          </table>
          <div className="flex gap-2">
            <button className={btn} onClick={() => setRows((r) => [...r, { bill_ref: '', bill_date: '', due_date: '', amount: '', side: party.nature === 'debtor' ? 'Dr' : 'Cr' }])}>
              + Add bill
            </button>
            <button className={btnPrimary} disabled={busy} onClick={save}>
              Save opening bills
            </button>
          </div>
          {d && (
            <table className="w-auto border-collapse bg-white text-sm">
              <tbody>
                <tr>
                  <td className={td}>Total of saved opening bills</td>
                  <td className={tdR}>
                    <BalanceText balance={d.total} />
                  </td>
                </tr>
                <tr>
                  <td className={td}>Opening balance of the ledger</td>
                  <td className={tdR}>
                    <BalanceText balance={d.ledger_opening} />
                  </td>
                </tr>
                <tr>
                  <td className={td + ' font-semibold'}>Difference</td>
                  <td className={tdR + (d.is_balanced ? ' text-green-700' : ' font-semibold text-red-600')}>
                    <BalanceText balance={d.difference} />
                    {d.is_balanced ? ' (agrees)' : ' (bills do not add up to the opening balance)'}
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </>
      )}
    </Page>
  )
}
