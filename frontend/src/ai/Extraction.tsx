import { useState } from 'react'
import { Link } from 'react-router-dom'
import { aiApi, type CheckResult, type DocFinding, type ExtractResult } from '../api/ai'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { DocFindings, DocSelect, NoClient, Tabs, useDocuments } from './common'
import { HEADER_FIELDS, LINE_FIELDS, TOTAL_FIELDS, buildInvoicePayload, statusLabel } from './lib'

type Mode = 'llm' | 'manual'

/** Run an extraction (language model or typed by hand), see the rule findings, then send it to the approval queue. */
export default function Extraction() {
  const { clientId } = useClient()
  const docs = useDocuments(clientId)
  const [docId, setDocId] = useState('')
  const [mode, setMode] = useState<Mode>('llm')
  const [result, setResult] = useState<ExtractResult | null>(null)
  const [check, setCheck] = useState<CheckResult | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const doc = useLoad(clientId && docId ? () => aiApi.getDocument(clientId, docId) : null, `ai-extdoc:${clientId}:${docId}`)
  if (!clientId)
    return (
      <Page title="Extraction">
        <NoClient />
      </Page>
    )
  const candidates = docs.documents.filter((d) => d.doc_type !== 'tally_xml' && d.doc_type !== 'tally_export')
  const isBank = candidates.find((d) => d.id === docId)?.doc_type === 'bank_statement'
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
  const submit = (payload?: Record<string, unknown>) =>
    run(async () => {
      setCheck(null)
      const r = await aiApi.extract(clientId, docId, mode === 'llm' ? { mode: 'llm' } : { mode: 'manual', payload })
      setResult(r)
      doc.reload()
    })
  const showCheck = (id: string) => run(async () => setCheck(await aiApi.checkExtraction(clientId, id)))
  const buildDraft = () =>
    run(async () => {
      const r = await aiApi.buildDraft(clientId, docId, result?.extraction_id ?? undefined)
      setResult((x) => (x ? { ...x, findings: r.findings } : x))
      setNotice(`Sent to the approval queue (${statusLabel(r.status)}). ${r.draft_voucher_id ? 'A draft voucher was built.' : 'No draft yet: fix the findings in the queue.'}`)
    })
  return (
    <Page title="Extraction">
      <div className="flex flex-wrap items-end gap-3">
        <DocSelect documents={candidates} value={docId} onChange={(id) => { setDocId(id); setResult(null); setCheck(null) }} />
        <Tabs<Mode> tabs={[['llm', 'Language model'], ['manual', 'Type it in']]} value={mode} onChange={setMode} />
      </div>
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
      {docId && doc.data && (
        <div className="text-sm text-slate-600">
          Text read: {doc.data.texts.length ? `${doc.data.texts.length} page(s)` : 'not yet (Documents screen, Read text)'}. Earlier versions: {doc.data.extractions.length}.{' '}
          {doc.data.queue_item_id && (
            <Link className="text-blue-700 underline" to={`/ai/queue?item=${doc.data.queue_item_id}`}>
              Open its queue item
            </Link>
          )}
        </div>
      )}
      {docId && mode === 'llm' && (
        <div className="space-y-1 text-sm">
          <div className="text-slate-600">The model only reads the document and drafts the fields. Rules check them; a person approves. It needs the AI switch on for this client and a text read.</div>
          <button className={btnPrimary} disabled={busy} onClick={() => submit()}>
            Run extraction
          </button>
        </div>
      )}
      {docId && mode === 'manual' && (isBank ? <BankForm busy={busy} onSubmit={submit} onError={setError} /> : <InvoiceForm busy={busy} onSubmit={submit} />)}
      {result && (
        <div className="space-y-2">
          <div className={`rounded border px-3 py-2 text-sm ${result.status === 'ok' ? 'border-green-300 bg-green-50' : 'border-amber-300 bg-amber-50'}`}>
            <b>{statusLabel(result.status)}.</b> {result.message}
          </div>
          <DocFindings findings={result.findings as DocFinding[]} />
          {result.extraction_id && (
            <div className="flex gap-2">
              <button className={btn} disabled={busy} onClick={() => showCheck(result.extraction_id!)}>
                Show recomputed values
              </button>
              <button className={btnPrimary} disabled={busy || result.status !== 'ok'} onClick={buildDraft}>
                Send to approval queue
              </button>
            </div>
          )}
          {check && <Recomputed check={check} />}
        </div>
      )}
    </Page>
  )
}

function Recomputed({ check }: { check: CheckResult }) {
  const lines = (check.recomputed.lines as Record<string, string>[] | undefined) ?? []
  const totals = (check.recomputed.totals as Record<string, string> | undefined) ?? {}
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-2 text-sm">
      <div className="font-semibold">Recomputed by the server (direction {check.direction ?? 'unknown'}, place of supply {check.place_of_supply ?? 'unknown'})</div>
      {lines.length > 0 && (
        <table className="border-collapse">
          <thead>
            <tr>
              <th className={th}>Line</th>
              {Object.keys(lines[0]).map((k) => (
                <th key={k} className={th}>
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td className={td}>{i + 1}</td>
                {Object.values(l).map((v, j) => (
                  <td key={j} className={td}>
                    {String(v ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="text-xs text-slate-600">{Object.entries(totals).map(([k, v]) => `${k}: ${String(v)}`).join('; ')}</div>
    </div>
  )
}

function InvoiceForm({ busy, onSubmit }: { busy: boolean; onSubmit: (p: Record<string, unknown>) => void }) {
  const [header, setHeader] = useState<Record<string, string>>({})
  const [lines, setLines] = useState<Record<string, string>[]>([{}])
  const [totals, setTotals] = useState<Record<string, string>>({})
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="text-xs text-slate-600">Type each value exactly as the document prints it. Nothing is calculated here; the server recomputes and compares.</div>
      <div className="grid grid-cols-3 gap-2">
        {HEADER_FIELDS.map(([k, label]) => (
          <Field key={k} label={label}>
            <input className={input} value={header[k] ?? ''} onChange={(e) => setHeader({ ...header, [k]: e.target.value })} />
          </Field>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="border-collapse">
          <thead>
            <tr>
              <th className={th}>#</th>
              {LINE_FIELDS.map(([k, label]) => (
                <th key={k} className={th}>
                  {label}
                </th>
              ))}
              <th className={th}></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td className={td}>{i + 1}</td>
                {LINE_FIELDS.map(([k, label]) => (
                  <td key={k} className={td}>
                    <input aria-label={`Line ${i + 1} ${label}`} className={`${input} w-24`} value={l[k] ?? ''} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />
                  </td>
                ))}
                <td className={td}>
                  <button className={btn} disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className={`${btn} mt-1`} onClick={() => setLines([...lines, {}])}>
          Add line
        </button>
      </div>
      <div className="grid grid-cols-4 gap-2">
        {TOTAL_FIELDS.map(([k, label]) => (
          <Field key={k} label={label}>
            <input className={input} value={totals[k] ?? ''} onChange={(e) => setTotals({ ...totals, [k]: e.target.value })} />
          </Field>
        ))}
      </div>
      <button className={btnPrimary} disabled={busy} onClick={() => onSubmit(buildInvoicePayload(header, lines, totals))}>
        Check and save extraction
      </button>
    </div>
  )
}

function BankForm({ busy, onSubmit, onError }: { busy: boolean; onSubmit: (p: Record<string, unknown>) => void; onError: (e: ApiFailure | null) => void }) {
  const [text, setText] = useState('')
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-3 text-sm">
      <div className="text-xs text-slate-600">
        Paste the bank statement as JSON (schema bank-extract-1: bank_name, account_ref, period_from, period_to, opening_balance, closing_balance, lines [date, narration, reference, debit, credit, balance], currency, notes).
      </div>
      <textarea className={`${input} h-48 w-full font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} />
      <button
        className={btnPrimary}
        disabled={busy || text.trim() === ''}
        onClick={() => {
          try {
            onError(null)
            onSubmit(JSON.parse(text) as Record<string, unknown>)
          } catch {
            onError(asFailure(new Error('The text is not valid JSON.')))
          }
        }}
      >
        Check and save extraction
      </button>
    </div>
  )
}
