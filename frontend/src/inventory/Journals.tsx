import { useState } from 'react'
import { inventoryApi, type Journal, type JournalStatus, type JournalType, type ReasonCode } from '../api/inventory'
import { ErrorBox, Field, Notice, Page, StatusBadge, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { today } from '../lib/dates'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, GodownSelect, ItemSelect, NoClient, Row, useFy, useInventoryMasters } from './common'
import { blankJournalLine, cleanNumber, journalActions, journalBody, journalProblems, REASONS, type JournalDraft } from './lib'

const blankDraft = (type: JournalType): JournalDraft => ({
  journal_type: type,
  journal_date: today(),
  narration: '',
  reason_code: '',
  reason_note: '',
  lines: [blankJournalLine()],
})
const fromJournal = (j: Journal): JournalDraft => ({
  journal_type: j.journal_type,
  journal_date: j.journal_date,
  narration: j.narration,
  reason_code: j.reason_code ?? '',
  reason_note: j.reason_note ?? '',
  lines: j.lines.map((l) => ({ item_id: l.item_id, from_godown_id: l.from_godown_id, to_godown_id: l.to_godown_id ?? '', quantity: l.quantity })),
})

/** Stock journals: godown-to-godown transfer and write-off. Draft -> approved -> posted -> reversed. No money is typed. */
export default function Journals() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const [type, setType] = useState<JournalType | ''>('')
  const [status, setStatus] = useState<JournalStatus | ''>('')
  const [editing, setEditing] = useState<{ id: string | null; draft: JournalDraft } | null>(null)
  const masters = useInventoryMasters()
  const list = useLoad(clientId && fyId ? () => inventoryApi.listJournals(clientId, { financial_year_id: fyId, journal_type: type, status }) : null, `inv-journals:${clientId}:${fyId}:${type}:${status}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [reversing, setReversing] = useState<{ id: string; reason: string } | null>(null)
  if (!clientId)
    return (
      <Page title="Stock journals">
        <NoClient />
      </Page>
    )
  const act = async (fn: () => Promise<unknown>, done: string): Promise<boolean> => {
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
      setReversing(null)
      list.reload()
      return true
    } catch (e) {
      setError(asFailure(e))
      return false
    }
  }
  const itemName = (id: string) => masters.itemList.find((i) => i.item_id === id)?.name ?? id
  const godownName = (id: string | null) => (id ? (masters.godownList.find((g) => g.id === id)?.name ?? id) : '')
  return (
    <Page
      title="Stock journals (transfer and write-off)"
      actions={
        <>
          <button className={btn} onClick={() => setEditing({ id: null, draft: blankDraft('transfer') })}>
            New transfer
          </button>
          <button className={btn} onClick={() => setEditing({ id: null, draft: blankDraft('write_off') })}>
            New write-off
          </button>
        </>
      }
    >
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <Field label="Type">
          <select className={input} value={type} onChange={(e) => setType(e.target.value as JournalType | '')}>
            <option value="">All</option>
            <option value="transfer">Transfer</option>
            <option value="write_off">Write-off</option>
          </select>
        </Field>
        <Field label="Status">
          <select className={input} value={status} onChange={(e) => setStatus(e.target.value as JournalStatus | '')}>
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="posted">Posted</option>
            <option value="reversed">Reversed</option>
          </select>
        </Field>
      </Row>
      <ErrorBox error={error ?? list.error} />
      {notice && <Notice>{notice}</Notice>}
      {editing && (
        <JournalForm
          key={editing.id ?? 'new'}
          initial={editing.draft}
          masters={masters}
          onCancel={() => setEditing(null)}
          onSave={async (draft) => {
            const body = journalBody(draft)
            const ok = await act(() => (editing.id ? inventoryApi.updateJournal(clientId, editing.id, body) : inventoryApi.createJournal(clientId, body)), 'Draft saved. Approve it, then post it.')
            if (ok) setEditing(null)
          }}
        />
      )}
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Number</th>
            <th className={th}>Date</th>
            <th className={th}>Type</th>
            <th className={th}>Lines</th>
            <th className={th}>Narration / reason</th>
            <th className={th}>Status</th>
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((j) => (
            <tr key={j.id}>
              <td className={`${td} font-mono`}>{j.journal_number ?? '(draft)'}</td>
              <td className={td}>{j.journal_date}</td>
              <td className={td}>{j.journal_type === 'transfer' ? 'Transfer' : 'Write-off'}</td>
              <td className={`${td} text-xs`}>
                {j.lines.map((l, i) => (
                  <div key={i}>
                    {l.item_name ?? itemName(l.item_id)}: {l.quantity} from {godownName(l.from_godown_id)}
                    {l.to_godown_id ? ` to ${godownName(l.to_godown_id)}` : ''}
                  </div>
                ))}
              </td>
              <td className={`${td} text-xs`}>
                {j.narration}
                {j.reason_code && <div className="text-slate-600">Reason: {j.reason_code}{j.reason_note ? ` (${j.reason_note})` : ''}</div>}
                {j.reverse_reason && <div className="text-red-700">Reversed: {j.reverse_reason}</div>}
              </td>
              <td className={td}>
                <StatusBadge status={j.status} />
              </td>
              <td className={`${td} whitespace-nowrap`}>
                {journalActions(j.status).includes('edit') && (
                  <button className={btn} onClick={() => setEditing({ id: j.id, draft: fromJournal(j) })}>
                    Edit
                  </button>
                )}{' '}
                {journalActions(j.status).includes('delete') && (
                  <button className={btnDanger} onClick={() => window.confirm('Delete this draft journal?') && act(() => inventoryApi.deleteJournal(clientId, j.id), 'Draft deleted.')}>
                    Delete
                  </button>
                )}{' '}
                {journalActions(j.status).includes('approve') && (
                  <button className={btnPrimary} onClick={() => act(() => inventoryApi.approveJournal(clientId, j.id), 'Approved.')}>
                    Approve
                  </button>
                )}
                {journalActions(j.status).includes('post') && (
                  <button className={btnPrimary} onClick={() => act(() => inventoryApi.postJournal(clientId, j.id), 'Posted.')}>
                    Post
                  </button>
                )}
                {journalActions(j.status).includes('reverse') && (
                  <button className={btnDanger} onClick={() => setReversing({ id: j.id, reason: '' })}>
                    Reverse
                  </button>
                )}
                {reversing?.id === j.id && (
                  <div className="mt-1 flex items-end gap-1">
                    <input className={`${input} w-56`} placeholder="Reason (required)" value={reversing.reason} onChange={(e) => setReversing({ id: j.id, reason: e.target.value })} />
                    <button className={btnDanger} disabled={!reversing.reason.trim()} onClick={() => act(() => inventoryApi.reverseJournal(clientId, j.id, reversing.reason.trim()), 'Reversed.')}>
                      Confirm reverse
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {(list.data ?? []).length === 0 && !list.loading && (
            <tr>
              <td colSpan={7} className={`${td} text-slate-500`}>
                No stock journal for these filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Page>
  )
}

function JournalForm({ initial, masters, onSave, onCancel }: { initial: JournalDraft; masters: ReturnType<typeof useInventoryMasters>; onSave: (d: JournalDraft) => Promise<void>; onCancel: () => void }) {
  const [d, setD] = useState(initial)
  const [busy, setBusy] = useState(false)
  const transfer = d.journal_type === 'transfer'
  const problems = journalProblems(d)
  const setLine = (i: number, patch: Partial<JournalDraft['lines'][number]>) => setD({ ...d, lines: d.lines.map((l, k) => (k === i ? { ...l, ...patch } : l)) })
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <h2 className="text-sm font-semibold">{transfer ? 'Transfer between godowns' : 'Write-off (stock lost, damaged, expired...)'}</h2>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Date">
          <input type="date" className={input} value={d.journal_date} onChange={(e) => setD({ ...d, journal_date: e.target.value })} />
        </Field>
        <Field label="Narration">
          <input className={`${input} w-72`} value={d.narration} onChange={(e) => setD({ ...d, narration: e.target.value })} />
        </Field>
        {!transfer && (
          <>
            <Field label="Reason">
              <select className={input} value={d.reason_code} onChange={(e) => setD({ ...d, reason_code: e.target.value as ReasonCode | '' })}>
                <option value="">(choose)</option>
                {REASONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Note">
              <input className={`${input} w-56`} value={d.reason_note} onChange={(e) => setD({ ...d, reason_note: e.target.value })} />
            </Field>
          </>
        )}
      </div>
      <table className="border-collapse">
        <thead>
          <tr>
            <th className={th}>#</th>
            <th className={th}>Item</th>
            <th className={th}>{transfer ? 'From godown' : 'Godown'}</th>
            {transfer && <th className={th}>To godown</th>}
            <th className={thR}>Quantity</th>
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          {d.lines.map((l, i) => (
            <tr key={i}>
              <td className={tdR}>{i + 1}</td>
              <td className={td}>
                <ItemSelect items={masters.itemList} value={l.item_id} onChange={(v) => setLine(i, { item_id: v, from_godown_id: l.from_godown_id || (masters.itemList.find((x) => x.item_id === v)?.default_godown_id ?? '') })} />
              </td>
              <td className={td}>
                <GodownSelect godowns={masters.godownList} value={l.from_godown_id} onChange={(v) => setLine(i, { from_godown_id: v })} />
              </td>
              {transfer && (
                <td className={td}>
                  <GodownSelect godowns={masters.godownList} value={l.to_godown_id} onChange={(v) => setLine(i, { to_godown_id: v })} blank="(to godown)" />
                </td>
              )}
              <td className={td}>
                <input className={`${input} w-28 text-right`} value={l.quantity} onChange={(e) => setLine(i, { quantity: cleanNumber(e.target.value) })} />
              </td>
              <td className={td}>
                {d.lines.length > 1 && (
                  <button className={btn} onClick={() => setD({ ...d, lines: d.lines.filter((_, k) => k !== i) })}>
                    x
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {problems.length > 0 && <div className="text-xs text-amber-800">{problems[0]}{problems.length > 1 ? ` (+${problems.length - 1} more)` : ''}</div>}
      <Row>
        <button className={btn} onClick={() => setD({ ...d, lines: [...d.lines, blankJournalLine()] })}>
          Add line
        </button>
        <button
          className={btnPrimary}
          disabled={busy || problems.length > 0}
          onClick={async () => {
            setBusy(true)
            try {
              await onSave(d)
            } finally {
              setBusy(false)
            }
          }}
        >
          Save draft
        </button>
        <button className={btn} onClick={onCancel}>
          Cancel
        </button>
      </Row>
    </div>
  )
}
