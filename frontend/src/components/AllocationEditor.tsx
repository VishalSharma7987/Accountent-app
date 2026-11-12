import { useEffect, useRef } from 'react'
import { api } from '../api'
import { useLoad } from '../lib/useLoad'
import { formatBalance, formatInr } from '../lib/money'
import { ALLOC_KINDS, allocationProgress, blankAllocRow, followPrefill, prefillRows, type AllocRow } from '../lib/phase2'
import type { AllocationKind, VoucherType } from '../types'
import { btn, input, inputErr } from './ui'

/** Bill-wise allocation of ONE voucher line of a bill-wise party ledger. Shows what the server will check (B-01..B-05)
 *  but decides nothing: totals here are display only. */
export function AllocationEditor({
  clientId,
  partyLedgerId,
  partyName,
  voucherType,
  side,
  lineAmount,
  reference,
  voucherDate,
  rows,
  onChange,
  readOnly,
  hasError,
}: {
  clientId: string
  partyLedgerId: string
  partyName: string
  voucherType: VoucherType
  side: 'Dr' | 'Cr' | null
  lineAmount: string
  reference: string
  voucherDate: string
  rows: AllocRow[]
  onChange: (rows: AllocRow[]) => void
  readOnly: boolean
  hasError: boolean
}) {
  const needsBills = !readOnly && rows.some((r) => r.kind === 'against_ref')
  const bills = useLoad(needsBills ? () => api.openBills(clientId, partyLedgerId, voucherDate) : null, `open-bills:${clientId}:${partyLedgerId}:${voucherDate}:${needsBills}`)
  const choices = (bills.data ?? []).filter((b) => b.kind === 'bill' && b.bill_ref)

  // the visible default for Sales / Purchase (one New Ref = whole line, named from the Reference No); the user can edit it
  const prev = useRef<{ amount: string; reference: string } | null>(null)
  useEffect(() => {
    if (readOnly) return
    const now = { amount: lineAmount, reference }
    const before = prev.current
    prev.current = now
    if (rows.length === 0) {
      const fill = prefillRows(voucherType, side, reference, lineAmount)
      if (fill.length) onChange(fill)
    } else if (before) {
      const next = followPrefill(rows, before, now)
      if (next !== rows) onChange(next)
    }
    // only the line amount, the reference and the side drive this; rows are read as they are at that moment
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineAmount, reference, side])

  const progress = allocationProgress(lineAmount, rows)
  const bad = progress.state !== 'full'
  const setRow = (i: number, patch: Partial<AllocRow>) => onChange(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)))

  return (
    <div className={`rounded border px-2 py-1 ${bad || hasError ? 'border-amber-400 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-slate-700">Bill-wise allocation: {partyName}</span>
        <span className={bad ? 'font-semibold text-amber-800' : 'text-green-700'} data-testid="alloc-progress">
          allocated {formatInr(progress.allocated)} of {formatInr(progress.total)}
          {progress.state === 'partial' && ` (${formatInr(progress.remaining)} left)`}
          {progress.state === 'over' && ` (over by ${formatInr(progress.remaining.replace('-', ''))})`}
          {progress.state === 'unreadable' && ' (an amount is not readable)'}
        </span>
      </div>
      <table className="mt-1 w-full">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="w-32 pr-1">
                <select
                  className={input + ' w-full'}
                  value={r.kind}
                  disabled={readOnly}
                  aria-label={`allocation ${i + 1} kind`}
                  onChange={(e) => setRow(i, { kind: e.target.value as AllocationKind, bill_ref: '' })}
                >
                  {ALLOC_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </td>
              <td className="pr-1">
                {r.kind === 'on_account' ? (
                  <span className="text-xs text-slate-500">no bill reference</span>
                ) : r.kind === 'against_ref' && !readOnly ? (
                  <select
                    className={(r.bill_ref ? input : inputErr) + ' w-full'}
                    value={r.bill_ref}
                    aria-label={`allocation ${i + 1} bill`}
                    onChange={(e) => setRow(i, { bill_ref: e.target.value })}
                  >
                    <option value="">(choose open bill)</option>
                    {r.bill_ref && !choices.some((c) => c.bill_ref === r.bill_ref) && <option value={r.bill_ref}>{r.bill_ref}</option>}
                    {choices.map((c) => (
                      <option key={c.bill_ref} value={c.bill_ref ?? ''}>
                        {c.bill_ref} — {formatBalance(c.outstanding)} due {c.due_date}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={input + ' w-full'}
                    value={r.bill_ref}
                    disabled={readOnly}
                    placeholder="Bill / reference no"
                    aria-label={`allocation ${i + 1} reference`}
                    onChange={(e) => setRow(i, { bill_ref: e.target.value })}
                  />
                )}
              </td>
              <td className="w-36 pr-1">
                <input
                  className={input + ' w-full text-right'}
                  value={r.amount}
                  disabled={readOnly}
                  inputMode="decimal"
                  placeholder="Amount"
                  aria-label={`allocation ${i + 1} amount`}
                  onChange={(e) => setRow(i, { amount: e.target.value })}
                />
              </td>
              <td className="w-36 pr-1">
                {(r.kind === 'new_ref' || r.kind === 'advance') && (
                  <input
                    type="date"
                    className={input + ' w-full'}
                    value={r.due_date}
                    disabled={readOnly}
                    title="Due date (blank = bill date + the party's credit days)"
                    aria-label={`allocation ${i + 1} due date`}
                    onChange={(e) => setRow(i, { due_date: e.target.value })}
                  />
                )}
              </td>
              <td className="w-6">
                {!readOnly && (
                  <button type="button" className="text-slate-400 hover:text-red-600" aria-label={`remove allocation ${i + 1}`} onClick={() => onChange(rows.filter((_, k) => k !== i))}>
                    ×
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!readOnly && (
        <div className="mt-1 flex gap-2">
          <button type="button" className={btn + ' !px-2 !py-0 text-xs'} onClick={() => onChange([...rows, { ...blankAllocRow(), amount: progress.state === 'partial' ? progress.remaining : '' }])}>
            + Allocation
          </button>
        </div>
      )}
    </div>
  )
}
