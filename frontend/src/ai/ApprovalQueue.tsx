import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { aiApi, type DocFinding, type QueueDetail, type QueueRow } from '../api/ai'
import { ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, inputErr, td, th, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import { DocFindings, DocumentViewer, NoClient, SeverityBadge } from './common'
import { QUEUE_STATUSES, acknowledgements, canAccept, changedEdits, findingKey, findingsAt, flattenPayload, hasBlocking, splitDocFindings, statusLabel, voucherHref } from './lib'

/** The main Phase 7 screen: everything the system proposes waits here for a person. Accepting never approves or posts. */
export default function ApprovalQueue() {
  const { clientId } = useClient()
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
  const [blocking, setBlocking] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const list = useLoad(clientId ? () => aiApi.listQueue(clientId, { status, kind, has_blocking: blocking === '' ? undefined : blocking === 'yes' }) : null, `ai-queue:${clientId}:${status}:${kind}:${blocking}`)
  const itemId = params.get('item') ?? ''
  if (!clientId)
    return (
      <Page title="Approval queue">
        <NoClient />
      </Page>
    )
  const rows = list.data ?? []
  const clean = (r: QueueRow) => r.blocking_count === 0 && r.warning_count === 0 && (r.status === 'pending' || r.status === 'in_review')
  const openItem = (id: string) => setParams(id ? { item: id } : {})
  const bulk = async () => {
    setError(null)
    setNotice('')
    try {
      const r = await aiApi.acceptClean(clientId, picked)
      setNotice(`Accepted ${r.accepted.length}. ${r.refused.length ? `Refused ${r.refused.length}: ${r.refused.map((x) => x.reason).join('; ')}` : ''}`)
      setPicked([])
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Approval queue">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Status">
          <select className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {QUEUE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Kind">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option>
            <option value="invoice">Invoice</option>
            <option value="tally_voucher">Tally voucher</option>
          </select>
        </Field>
        <Field label="Blocking findings">
          <select className={input} value={blocking} onChange={(e) => setBlocking(e.target.value)}>
            <option value="">Any</option>
            <option value="yes">Has blocking</option>
            <option value="no">None</option>
          </select>
        </Field>
        <button className={btn} onClick={list.reload}>
          Refresh
        </button>
        <button className={btnPrimary} disabled={picked.length === 0} onClick={bulk}>
          Accept {picked.length} clean item(s)
        </button>
      </div>
      <ErrorBox error={error ?? list.error} />
      {notice && <Notice>{notice}</Notice>}
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}></th>
            <th className={th}>Kind</th>
            <th className={th}>Status</th>
            <th className={th}>Document</th>
            <th className={th}>Party</th>
            <th className={th}>Reference</th>
            <th className={th}>Date</th>
            <th className={th}>Total</th>
            <th className={th}>Blocking</th>
            <th className={th}>Warnings</th>
            <th className={th}>Reviewer</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={r.id === itemId ? 'bg-blue-50' : ''}>
              <td className={td}>
                {clean(r) && <input type="checkbox" aria-label="Select for bulk accept" checked={picked.includes(r.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, r.id] : picked.filter((x) => x !== r.id))} />}
              </td>
              <td className={td}>{r.kind === 'tally_voucher' ? 'Tally' : 'Invoice'}</td>
              <td className={td}>{statusLabel(r.status)}</td>
              <td className={td}>{r.document_name}</td>
              <td className={td}>{r.summary?.party}</td>
              <td className={td}>{r.summary?.reference_no}</td>
              <td className={td}>{r.summary?.date}</td>
              <td className={tdR}>{r.summary?.total ? formatInr(r.summary.total) : ''}</td>
              <td className={`${td} ${r.blocking_count ? 'font-semibold text-red-700' : ''}`}>{r.blocking_count}</td>
              <td className={td}>{r.warning_count}</td>
              <td className={td}>{r.reviewer}</td>
              <td className={td}>
                <button className={btn} onClick={() => openItem(r.id === itemId ? '' : r.id)}>
                  {r.id === itemId ? 'Close' : 'Review'}
                </button>
              </td>
            </tr>
          ))}
          {list.data && rows.length === 0 && (
            <tr>
              <td className={td} colSpan={12}>
                Nothing in the queue for this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {itemId && <Review key={itemId} clientId={clientId} id={itemId} onChanged={list.reload} onClose={() => openItem('')} />}
    </Page>
  )
}

function Review({ clientId, id, onChanged, onClose }: { clientId: string; id: string; onChanged: () => void; onClose: () => void }) {
  const detail = useLoad(() => aiApi.getQueueItem(clientId, id), `ai-qitem:${clientId}:${id}`)
  const d = detail.data
  if (!d) return <ErrorBox error={detail.error} />
  return <ReviewBody clientId={clientId} d={d} reload={() => { detail.reload(); onChanged() }} onClose={onClose} />
}

function ReviewBody({ clientId, d, reload, onClose }: { clientId: string; d: QueueDetail; reload: () => void; onClose: () => void }) {
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [live, setLive] = useState<DocFinding[] | null>(null)
  const [draftId, setDraftId] = useState<string | null | undefined>(undefined)
  const [acked, setAcked] = useState<Set<string>>(() => new Set(d.acknowledged.map(findingKey)))
  const [learn, setLearn] = useState(true)
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const rows = flattenPayload(d.current)
  const findings = live ?? d.findings
  const finished = d.status === 'accepted' || d.status === 'rejected'
  const draft = d.draft_voucher
  const split = splitDocFindings(findings)
  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await fn()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  // re-check on the server whenever a field loses focus with a changed value; the browser decides nothing
  const recheck = () => {
    const changes = changedEdits(rows, edits)
    if (changes.length === 0) return Promise.resolve()
    return run(async () => {
      const r = await aiApi.editFields(clientId, d.id, changes)
      setLive(r.findings)
      setDraftId(r.draft_voucher_id)
      reload()
    })
  }
  const toggleAck = (f: DocFinding) => {
    const k = findingKey(f)
    const n = new Set(acked)
    if (n.has(k)) n.delete(k)
    else n.add(k)
    setAcked(n)
  }
  const okToAccept = canAccept(findings, acked, d.status) && Object.keys(changedEdits(rows, edits)).length === 0
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-1">
        <div className="text-sm font-semibold">Source document</div>
        <DocumentViewer clientId={clientId} documentId={d.document?.id ?? d.document_id} contentType={d.document?.content_type} />
      </div>
      <div className="space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <b>{d.document_name ?? 'Queue item'}</b>
          <span className="rounded bg-slate-200 px-2 py-0.5 text-xs">{statusLabel(d.status)}</span>
          {d.reviewer && <span className="text-slate-500">reviewer {d.reviewer}</span>}
          {d.status === 'pending' && (
            <button className={btn} disabled={busy} onClick={() => run(async () => { await aiApi.claim(clientId, d.id); reload() })}>
              Start review
            </button>
          )}
          {d.status === 'in_review' && (
            <button className={btn} disabled={busy} onClick={() => run(async () => { await aiApi.release(clientId, d.id); reload() })}>
              Release
            </button>
          )}
          <button className={btn} onClick={onClose}>
            Close
          </button>
        </div>
        <ErrorBox error={error} />
        {error?.code === 'queue_blocked' && <DocFindings findings={((error.details as { findings?: DocFinding[] } | null)?.findings) ?? []} />}
        {notice && <Notice>{notice}</Notice>}
        <div className="rounded border border-slate-300 bg-white">
          <div className="border-b border-slate-200 bg-slate-50 px-2 py-1 font-semibold">Fields (every field can be edited; the server re-checks on leaving a field)</div>
          <table className="w-full border-collapse">
            <tbody>
              {rows.map((r) => {
                const here = findingsAt(findings, r.path)
                const original = flattenPayload(d.original).find((o) => o.path === r.path)?.value
                const value = edits[r.path] ?? r.value
                return (
                  <tr key={r.path}>
                    <td className={`${td} w-48 text-xs text-slate-600`}>{r.label}</td>
                    <td className={td}>
                      <input
                        aria-label={r.label}
                        className={`${here.some((f) => hasBlocking([f])) ? inputErr : input} w-full`}
                        disabled={finished || busy}
                        value={value}
                        onChange={(e) => setEdits({ ...edits, [r.path]: e.target.value })}
                        onBlur={() => void recheck()}
                      />
                      {original !== undefined && original !== r.value && <div className="text-xs text-slate-500">extracted: {original || '(blank)'}</div>}
                      {here.map((f, i) => (
                        <div key={i} className="mt-0.5 flex items-start gap-1 text-xs">
                          <SeverityBadge severity={f.severity} /> <span className="font-mono">{f.rule_id}</span> {f.message}
                        </div>
                      ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div>
          <div className="mb-1 font-semibold">
            Findings from the server ({split.blocking.length} blocking, {split.warnings.length} warnings)
          </div>
          <DocFindings findings={findings} empty="No findings. The checks passed." />
          {split.warnings.length > 0 && (
            <div className="mt-1 rounded border border-amber-300 bg-amber-50 p-2">
              <div className="font-semibold text-amber-900">Warnings need your acknowledgement before accepting</div>
              {split.warnings.map((f, i) => (
                <label key={i} className="flex items-center gap-1">
                  <input type="checkbox" disabled={finished} checked={acked.has(findingKey(f))} onChange={() => toggleAck(f)} />
                  <span className="font-mono text-xs">{f.rule_id}</span> {f.message}
                </label>
              ))}
            </div>
          )}
        </div>
        <div className="rounded border border-slate-300 bg-white p-2">
          <div className="font-semibold">Draft voucher</div>
          {draft && draftId !== null ? (
            <div>
              <div>
                {draft.voucher_type} {draft.voucher_date} ref {draft.reference_no ?? '-'} ({draft.status}){' '}
                <Link className="text-blue-700 underline" to={voucherHref(draft.id)}>
                  open
                </Link>
              </div>
              <div className="text-xs text-slate-600">{draft.narration}</div>
              <table className="mt-1 w-full border-collapse">
                <tbody>
                  {draft.lines.map((l, i) => (
                    <tr key={i}>
                      <td className={td}>{l.ledger_name ?? l.ledger_id}</td>
                      <td className={tdR}>{l.debit && l.debit !== '0.00' ? formatInr(l.debit) : ''}</td>
                      <td className={tdR}>{l.credit && l.credit !== '0.00' ? formatInr(l.credit) : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-slate-500">No draft yet{draftId === null ? ' (the edit removed it: fix the findings)' : ''}.</div>
          )}
        </div>
        {!finished && (
          <div className="space-y-2 rounded border border-slate-300 bg-white p-2">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />
              Remember the party and ledger choices for next time (saved mappings)
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <button
                className={btnPrimary}
                disabled={busy || !okToAccept}
                title={hasBlocking(findings) ? 'Blocking findings must be fixed first' : ''}
                onClick={() =>
                  run(async () => {
                    await aiApi.accept(clientId, d.id, acknowledgements(findings, acked), learn)
                    setNotice(`Accepted. The draft voucher still has to be approved and posted in the usual way.`)
                    reload()
                  })
                }
              >
                Accept
              </button>
              {hasBlocking(findings) && <span className="text-red-700">Blocking findings: Accept is disabled.</span>}
              {!rejecting && (
                <button className={btnDanger} onClick={() => setRejecting(true)}>
                  Reject
                </button>
              )}
            </div>
            {rejecting && (
              <div className="flex items-end gap-2">
                <Field label="Reason for rejecting (required)">
                  <input className={`${input} w-96`} value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
                <button className={btnDanger} disabled={busy || reason.trim() === ''} onClick={() => run(async () => { await aiApi.reject(clientId, d.id, reason.trim()); setNotice('Rejected. The draft was removed; the extraction is kept.'); setRejecting(false); reload() })}>
                  Confirm reject
                </button>
                <button className={btn} onClick={() => setRejecting(false)}>
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}
        {d.history.length > 0 && (
          <details>
            <summary className="cursor-pointer">History ({d.history.length})</summary>
            <ul className="list-disc pl-5 text-xs">
              {d.history.map((h, i) => (
                <li key={i}>{[h.created_at, h.actor, h.action].filter(Boolean).map(String).join(' ')}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  )
}
