import { useState } from 'react'
import { api } from '../api'
import { ErrorBox, Field, Notice, Page, btn, btnDanger, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import type { BlockingVoucher } from '../types'
import { Link } from 'react-router-dom'

export default function Periods() {
  const { clientId, client } = useClient()
  const [fyId, setFyId] = useState('')
  const years = client?.financial_years ?? []
  const chosen = fyId && years.some((y) => y.id === fyId) ? fyId : (years[years.length - 1]?.id ?? '')
  const periods = useLoad(clientId && chosen ? () => api.listPeriods(clientId, chosen) : null, `periods:${clientId}:${chosen}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [blocking, setBlocking] = useState<BlockingVoucher[]>([])
  const [notice, setNotice] = useState('')

  if (!clientId) return <Page title="Periods">Select a client first.</Page>

  const run = async (work: () => Promise<unknown>, done: string) => {
    setError(null)
    setBlocking([])
    setNotice('')
    try {
      await work()
      setNotice(done)
      periods.reload()
    } catch (e) {
      const f = asFailure(e)
      setError(f)
      if (f.code === 'period_has_open_vouchers' && Array.isArray(f.details)) setBlocking(f.details as BlockingVoucher[])
    }
  }

  const unlock = (id: string) => {
    const reason = window.prompt('Reason for unlocking this period (required):')
    if (reason === null) return
    void run(() => api.unlockPeriod(clientId, id, reason), 'Period unlocked.')
  }

  return (
    <Page title="Periods">
      <Field label="Financial year">
        <select className={input + ' w-64'} value={chosen} onChange={(e) => setFyId(e.target.value)}>
          {years.map((y) => (
            <option key={y.id} value={y.id}>
              {y.start_date} to {y.end_date}
            </option>
          ))}
        </select>
      </Field>
      <ErrorBox error={error ?? periods.error} />
      {blocking.length > 0 && (
        <table className="w-full border-collapse bg-white">
          <caption className="p-1 text-left text-sm font-semibold">Vouchers that block the lock</caption>
          <thead>
            <tr>
              <th className={th}>Date</th>
              <th className={th}>Type</th>
              <th className={th}>Status</th>
              <th className={th}>Narration</th>
            </tr>
          </thead>
          <tbody>
            {blocking.map((b) => (
              <tr key={b.voucher_id}>
                <td className={td}>
                  <Link className="text-blue-700 underline" to={`/vouchers/${b.voucher_id}`}>
                    {b.voucher_date}
                  </Link>
                </td>
                <td className={td}>{b.voucher_type}</td>
                <td className={td}>{b.status}</td>
                <td className={td}>{b.narration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {notice && <Notice>{notice}</Notice>}
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Period</th>
            <th className={th}>Status</th>
            <th className={th}>Locked by</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(periods.data ?? []).map((p) => (
            <tr key={p.id}>
              <td className={td}>
                {p.start} to {p.end}
              </td>
              <td className={td}>{p.status === 'locked' ? '🔒 locked' : 'open'}</td>
              <td className={td}>{p.locked_by ?? ''}</td>
              <td className={td}>
                {p.status === 'open' ? (
                  <button className={btn} onClick={() => run(() => api.lockPeriod(clientId, p.id), 'Period locked.')}>
                    Lock
                  </button>
                ) : (
                  <button className={btnDanger} onClick={() => unlock(p.id)}>
                    Unlock…
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Page>
  )
}
