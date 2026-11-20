import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { auditApi, type PaperDetail as Paper, type PaperItem } from '../api/audit'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th, thR, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import AiSummary from './AiSummary'
import { NoClient, StatusPill } from './common'
import { dmy, dt, evidenceRows, findingLinks, isSignedOff, itemOpen, sampleLine } from './lib'

export default function PaperDetail() {
  const { id = '' } = useParams()
  const { clientId } = useClient()
  const paper = useLoad(clientId && id ? () => auditApi.getPaper(clientId, id) : null, `audit-paper:${clientId}:${id}`)
  if (!clientId)
    return (
      <Page title="Working paper">
        <NoClient />
      </Page>
    )
  return (
    <Page
      title="Working paper"
      actions={
        <Link className={btn} to="/audit/papers">
          All working papers
        </Link>
      }
    >
      <ErrorBox error={paper.error} />
      {paper.loading && !paper.data && <div className="text-sm text-slate-500">Loading the working paper...</div>}
      {paper.data && <Body key={paper.data.id} clientId={clientId} p={paper.data} reload={paper.reload} />}
    </Page>
  )
}

function Body({ clientId, p, reload }: { clientId: string; p: Paper; reload: () => void }) {
  const [error, setError] = useState<ApiFailure | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const locked = isSignedOff(p.status)
  const openCount = p.items.filter((i) => itemOpen(i.status)).length
  const act = async (fn: () => Promise<unknown>, done = '') => {
    setBusy(true)
    setError(null)
    setMsg('')
    try {
      await fn()
      setMsg(done)
      reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div className="rounded border border-slate-300 bg-white p-3 text-sm">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
          <span>
            Check <b className="font-mono">{p.check_id}</b>
          </span>
          <span>
            Run{' '}
            <Link className="text-blue-700 underline" to={`/audit/runs/${p.run_id}`}>
              {p.run_id.slice(0, 8)}
            </Link>
          </span>
          <span>
            Status <StatusPill status={p.status} />
          </span>
          <span>Population {p.population_count}</span>
          <span>Amount {formatInr(p.population_amount)}</span>
          <span className="font-mono text-xs">Digest {p.population_digest ?? 'none'}</span>
          <span>Created by {p.created_by}, {dt(p.created_at)}</span>
        </div>
        {locked && (
          <div className="mt-2 rounded border border-green-300 bg-green-50 px-3 py-2 text-green-900">
            Signed off by {p.signed_off_by} on {dt(p.signed_off_at)}. This paper is read-only.
            {p.conclusion && <div className="mt-1 whitespace-pre-wrap">Conclusion: {p.conclusion}</div>}
          </div>
        )}
      </div>
      <ErrorBox error={error} />
      {msg && <Notice>{msg}</Notice>}
      <Sampling clientId={clientId} p={p} locked={locked} busy={busy} act={act} />
      <Items clientId={clientId} p={p} locked={locked} busy={busy} act={act} />
      <Notes clientId={clientId} p={p} locked={locked} busy={busy} act={act} />
      <Workflow clientId={clientId} p={p} locked={locked} busy={busy} act={act} openCount={openCount} />
      <AiSummary clientId={clientId} runId={p.run_id} checkIds={[p.check_id]} paperId={p.id} />
    </>
  )
}

type Act = (fn: () => Promise<unknown>, done?: string) => Promise<void>
interface Common {
  clientId: string
  p: Paper
  locked: boolean
  busy: boolean
  act: Act
}

function Sampling({ clientId, p, locked, busy, act }: Common) {
  const [method, setMethod] = useState<'random' | 'systematic' | 'value'>('random')
  const [seed, setSeed] = useState('')
  const [size, setSize] = useState('')
  const [threshold, setThreshold] = useState('')
  const [rest, setRest] = useState('')
  const [showIds, setShowIds] = useState(false)
  const draw = () =>
    act(
      () =>
        auditApi.sample(clientId, p.id, {
          method,
          seed: Number(seed),
          size: size ? Number(size) : undefined,
          threshold: method === 'value' && threshold ? threshold.replace(/,/g, '') : undefined,
          rest_size: method === 'value' && rest ? Number(rest) : undefined,
        }),
      'Sample drawn and stored.',
    )
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="font-semibold">Sample</div>
      <div className="text-sm">{sampleLine(p.sample)}</div>
      <div className="text-xs text-slate-500">
        The method, seed and population digest are stored; the same seed on the same population always gives the same items.
      </div>
      {p.sample.ids.length > 0 && (
        <div className="text-xs">
          <button className="text-blue-700 underline" onClick={() => setShowIds(!showIds)}>
            {showIds ? 'Hide' : 'Show'} the {p.sample.ids.length} sampled id(s)
          </button>
          {showIds && <div className="mt-1 break-all font-mono">{p.sample.ids.join(', ')}</div>}
        </div>
      )}
      {!locked && (
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Method">
            <select className={input} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
              <option value="random">random</option>
              <option value="systematic">systematic</option>
              <option value="value">value (largest first)</option>
            </select>
          </Field>
          <Field label="Seed (whole number)">
            <input className={input + ' w-28'} value={seed} onChange={(e) => setSeed(e.target.value)} />
          </Field>
          <Field label="Size">
            <input className={input + ' w-24'} value={size} onChange={(e) => setSize(e.target.value)} />
          </Field>
          {method === 'value' && (
            <>
              <Field label="Threshold amount">
                <input className={input + ' w-32'} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
              </Field>
              <Field label="Extra items below threshold">
                <input className={input + ' w-24'} value={rest} onChange={(e) => setRest(e.target.value)} />
              </Field>
            </>
          )}
          <button className={btn} disabled={busy || !/^-?\d+$/.test(seed)} onClick={draw}>
            Draw sample
          </button>
        </div>
      )}
    </div>
  )
}

function Items({ clientId, p, locked, busy, act }: Common) {
  const sampled = new Set(p.sample.ids)
  const inSample = (i: PaperItem) => {
    const v = i.finding.evidence?.voucher_ids
    return Array.isArray(v) && v.some((x) => typeof x === 'string' && sampled.has(x))
  }
  return (
    <div>
      <h2 className="mb-1 font-semibold">Exceptions ({p.items.length})</h2>
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Date</th>
            <th className={th}>Subject</th>
            <th className={th}>Exception</th>
            <th className={thR}>Amount</th>
            <th className={th}>Sample</th>
            <th className={th}>Decision</th>
          </tr>
        </thead>
        <tbody>
          {p.items.map((i) => (
            <ItemRow key={i.id + i.status + (i.decided_at ?? '')} clientId={clientId} p={p} item={i} locked={locked} busy={busy} act={act} sampled={inSample(i)} />
          ))}
        </tbody>
      </table>
      {p.items.length === 0 && <div className="text-sm text-slate-500">This check had no exceptions in the run.</div>}
    </div>
  )
}

function ItemRow({ clientId, p, item, locked, busy, act, sampled }: Common & { item: PaperItem; sampled: boolean }) {
  const [status, setStatus] = useState<'cleared' | 'confirmed'>(item.status === 'confirmed' ? 'confirmed' : 'cleared')
  const [reason, setReason] = useState(item.reviewer_note ?? '')
  const [open, setOpen] = useState(false)
  const f = item.finding
  return (
    <>
      <tr>
        <td className={td}>{dmy(f.finding_date)}</td>
        <td className={td}>{f.subject_ref}</td>
        <td className={td}>
          {f.message}
          <div>
            <button className="text-xs text-blue-700 underline" onClick={() => setOpen(!open)}>
              {open ? 'Hide evidence' : 'Evidence'}
            </button>
            {findingLinks({ subject_kind: f.subject_kind, subject_id: null, evidence: f.evidence }, '', '')
              .filter((l) => l.to.startsWith('/vouchers/'))
              .map((l) => (
                <Link key={l.to} className="ml-2 text-xs text-blue-700 underline" to={l.to}>
                  {l.label}
                </Link>
              ))}
          </div>
        </td>
        <td className={tdR}>{formatInr(f.amount)}</td>
        <td className={td}>{sampled ? 'in sample' : ''}</td>
        <td className={td}>
          <StatusPill status={item.status} />
          {item.decided_by && (
            <div className="text-xs text-slate-600">
              {item.decided_by}, {dt(item.decided_at)}
              {item.reviewer_note && <div className="whitespace-pre-wrap">Why: {item.reviewer_note}</div>}
            </div>
          )}
          {!locked && (
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <select className={input} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
                <option value="cleared">cleared (not an issue)</option>
                <option value="confirmed">confirmed (issue)</option>
              </select>
              <input className={input + ' w-56'} placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button
                className={btn}
                disabled={busy || !reason.trim()}
                onClick={() => act(() => auditApi.decideItem(clientId, p.id, item.id, { status, reviewer_note: reason.trim() }), 'Decision saved.')}
              >
                Save
              </button>
            </div>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td className={td + ' bg-slate-50'} colSpan={6}>
            <table className="text-xs">
              <tbody>
                {evidenceRows(f.evidence).map(([k, v]) => (
                  <tr key={k}>
                    <td className="pr-3 align-top font-mono text-slate-600">{k}</td>
                    <td className="break-all">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  )
}

function Notes({ clientId, p, locked, busy, act }: Common) {
  const [note, setNote] = useState('')
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-3">
      <div className="font-semibold">Notes</div>
      {p.notes.map((n) => (
        <div key={n.id} className="text-sm">
          <span className="text-xs text-slate-500">
            {n.created_by}, {dt(n.created_at)}:{' '}
          </span>
          <span className="whitespace-pre-wrap">{n.note}</span>
        </div>
      ))}
      {p.notes.length === 0 && <div className="text-sm text-slate-500">No notes.</div>}
      {!locked && (
        <div className="flex gap-2 pt-1">
          <input className={input + ' flex-1'} placeholder="Add a note" value={note} onChange={(e) => setNote(e.target.value)} />
          <button
            className={btn}
            disabled={busy || !note.trim()}
            onClick={async () => {
              await act(() => auditApi.addNote(clientId, p.id, note.trim()), 'Note added.')
              setNote('')
            }}
          >
            Add note
          </button>
        </div>
      )}
    </div>
  )
}

function Workflow({ clientId, p, locked, busy, act, openCount }: Common & { openCount: number }) {
  const [conclusion, setConclusion] = useState('')
  if (locked) return null
  const canSign = p.status === 'in_review' && openCount === 0 && conclusion.trim() !== ''
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="font-semibold">Review and sign-off</div>
      <div className="flex flex-wrap items-center gap-2">
        {p.status === 'open' && (
          <button className={btn} disabled={busy} onClick={() => act(() => auditApi.sendToReview(clientId, p.id), 'Sent to review.')}>
            Send to review
          </button>
        )}
        {p.status === 'in_review' && (
          <button className={btn} disabled={busy} onClick={() => act(() => auditApi.reopenPaper(clientId, p.id), 'Reopened.')}>
            Reopen
          </button>
        )}
      </div>
      {openCount > 0 && <div className="text-sm text-amber-800">{openCount} exception(s) are still open. Sign-off is blocked until each is cleared or confirmed with a reason.</div>}
      {p.status === 'open' && <div className="text-sm text-slate-600">Send the paper to review before signing off.</div>}
      <Field label="Your conclusion (required)">
        <textarea className={input + ' h-20 w-full'} value={conclusion} onChange={(e) => setConclusion(e.target.value)} />
      </Field>
      <button
        className={btnPrimary}
        disabled={busy || !canSign}
        onClick={() => act(() => auditApi.signOff(clientId, p.id, conclusion.trim()), 'Signed off.')}
      >
        Sign off
      </button>
    </div>
  )
}
