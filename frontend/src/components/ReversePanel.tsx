import { useState } from 'react'
import { api } from '../api'
import type { ApiFailure } from '../lib/apiError'
import { today } from '../lib/dates'
import { asFailure } from '../lib/useLoad'
import { ErrorBox, Field, btnDanger, input } from './ui'

/** Reverse a POSTED voucher: a new mirror voucher is posted and linked both ways (V-12). */
export function ReversePanel({ voucherId, number, onDone }: { voucherId: string; number: string | null; onDone: (reversalId: string) => void }) {
  const [date, setDate] = useState(today())
  const [reason, setReason] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!window.confirm(`Reverse voucher ${number ?? ''}? A new voucher with every line swapped will be posted.`)) return
    setBusy(true)
    setError(null)
    try {
      const out = await api.reverseVoucher(voucherId, { reversal_date: date, reason })
      onDone(out.reversal_voucher_id)
    } catch (err) {
      setError(asFailure(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 rounded border border-red-200 bg-red-50 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Reversal date">
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Reason (required)">
          <input className={input + ' w-72'} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <button className={btnDanger} disabled={busy || !reason.trim()} onClick={submit}>
          Reverse voucher
        </button>
      </div>
      <ErrorBox error={error} />
    </div>
  )
}
