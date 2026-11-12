import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ReversePanel } from '../components/ReversePanel'
import { Amount, ErrorBox, Field, LedgerPicker, Page, StatusBadge, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { useLoad } from '../lib/useLoad'
import { VOUCHER_TYPES, type VoucherFilters } from '../types'

const PAGE = 50
const STATUSES = ['draft', 'approved', 'posted', 'reversed']

export default function VoucherList() {
  const { clientId, client } = useClient()
  const navigate = useNavigate()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [draft, setDraft] = useState<VoucherFilters>({})
  const [applied, setApplied] = useState<VoucherFilters>({})
  const [offset, setOffset] = useState(0)
  const [reversing, setReversing] = useState<string | null>(null)
  const list = useLoad(clientId ? () => api.listVouchers(clientId, { ...applied, limit: PAGE, offset }) : null, `vouchers:${clientId}:${JSON.stringify(applied)}:${offset}`)

  if (!clientId) return <Page title="Vouchers">Select a client first.</Page>
  const total = list.data?.total_count ?? 0

  return (
    <Page
      title={`Vouchers — ${client?.name ?? ''}`}
      actions={
        <Link to="/vouchers/new" className={btnPrimary}>
          + New voucher
        </Link>
      }
    >
      <form
        className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault()
          setOffset(0)
          setApplied({ ...draft })
        }}
      >
        <Field label="From">
          <input type="date" className={input} value={draft.from ?? ''} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
        </Field>
        <Field label="To">
          <input type="date" className={input} value={draft.to ?? ''} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
        </Field>
        <Field label="Type">
          <select className={input} value={draft.type ?? ''} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
            <option value="">All</option>
            {VOUCHER_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select className={input} value={draft.status ?? ''} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <div className="w-56">
          <Field label="Ledger">
            <LedgerPicker ledgers={ledgers.data ?? []} value={draft.ledger_id ?? ''} onChange={(v) => setDraft({ ...draft, ledger_id: v })} placeholder="Any ledger" />
          </Field>
        </div>
        <button className={btnPrimary}>Apply</button>
        <button
          type="button"
          className={btn}
          onClick={() => {
            setDraft({})
            setApplied({})
            setOffset(0)
          }}
        >
          Clear
        </button>
      </form>
      <ErrorBox error={list.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Date</th>
            <th className={th}>Number</th>
            <th className={th}>Type</th>
            <th className={th}>Narration</th>
            <th className={th}>Ref no</th>
            <th className={thR}>Amount</th>
            <th className={th}>Status</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data?.items ?? []).map((v) => (
            <VoucherRow
              key={v.id}
              v={v}
              open={() => navigate(`/vouchers/${v.id}`)}
              reversing={reversing === v.id}
              toggleReverse={() => setReversing(reversing === v.id ? null : v.id)}
              onReversed={(rid) => navigate(`/vouchers/${rid}`)}
            />
          ))}
          {list.data && list.data.items.length === 0 && (
            <tr>
              <td className={td} colSpan={8}>
                No vouchers match.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="flex items-center gap-2 text-sm">
        <button className={btn} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          Previous
        </button>
        <span>
          {total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}
        </span>
        <button className={btn} disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
          Next
        </button>
      </div>
    </Page>
  )
}

function VoucherRow({
  v,
  open,
  reversing,
  toggleReverse,
  onReversed,
}: {
  v: import('../types').VoucherListItem
  open: () => void
  reversing: boolean
  toggleReverse: () => void
  onReversed: (id: string) => void
}) {
  return (
    <>
      <tr className="cursor-pointer hover:bg-slate-50" onDoubleClick={open}>
        <td className={td}>{v.voucher_date}</td>
        <td className={td}>
          <Link className="text-blue-700 underline" to={`/vouchers/${v.id}`}>
            {v.voucher_number ?? '(draft)'}
          </Link>
        </td>
        <td className={td}>{v.voucher_type}</td>
        <td className={td}>{v.narration}</td>
        <td className={td}>{v.reference_no}</td>
        <td className={tdR}>
          <Amount value={v.total} />
        </td>
        <td className={td}>
          <StatusBadge status={v.status} />
        </td>
        <td className={td}>
          {v.status === 'posted' && (
            <button className={btn} onClick={toggleReverse}>
              Reverse…
            </button>
          )}
        </td>
      </tr>
      {reversing && (
        <tr>
          <td colSpan={8} className="p-2">
            <ReversePanel voucherId={v.id} number={v.voucher_number} onDone={onReversed} />
          </td>
        </tr>
      )}
    </>
  )
}
