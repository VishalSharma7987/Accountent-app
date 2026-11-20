import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { aiApi, saveDocument, type PageText, type ReadMethod } from '../api/ai'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'
import { DOC_TYPES, docTypeLabel, fileSize, statusLabel, voucherHref } from './lib'

export default function Documents() {
  const { clientId, client } = useClient()
  const [typeFilter, setTypeFilter] = useState('')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState('')
  const list = useLoad(clientId ? () => aiApi.listDocuments(clientId, { doc_type: typeFilter, q }) : null, `ai-doclist:${clientId}:${typeFilter}:${q}`)
  if (!clientId)
    return (
      <Page title="Documents">
        <NoClient />
      </Page>
    )
  return (
    <Page title="Documents">
      <Upload clientId={clientId} years={client?.financial_years ?? []} onDone={(id) => { list.reload(); setOpenId(id) }} onOpen={setOpenId} />
      <div className="flex items-end gap-2">
        <Field label="Type">
          <select className={input} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">All types</option>
            {DOC_TYPES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Search file name">
          <input className={input} value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
      </div>
      <ErrorBox error={list.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>File</th>
            <th className={th}>Type</th>
            <th className={th}>Size</th>
            <th className={th}>Status</th>
            <th className={th}>Uploaded</th>
            <th className={th}>Vouchers</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((d) => (
            <tr key={d.id} className={d.id === openId ? 'bg-blue-50' : ''}>
              <td className={td}>{d.original_filename}</td>
              <td className={td}>{docTypeLabel(d.doc_type)}</td>
              <td className={td}>{fileSize(d.size_bytes)}</td>
              <td className={td}>{statusLabel(d.status)}</td>
              <td className={td}>
                {d.uploaded_at.slice(0, 10)} by {d.uploaded_by}
              </td>
              <td className={td}>
                {d.linked_voucher_ids.map((v) => (
                  <Link key={v} className="mr-1 text-blue-700 underline" to={voucherHref(v)}>
                    voucher
                  </Link>
                ))}
              </td>
              <td className={td}>
                <button className={btn} onClick={() => setOpenId(d.id === openId ? '' : d.id)}>
                  {d.id === openId ? 'Close' : 'Open'}
                </button>
              </td>
            </tr>
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={7}>
                No documents yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {openId && <Detail key={openId} clientId={clientId} id={openId} onChange={list.reload} />}
    </Page>
  )
}

function Upload({ clientId, years, onDone, onOpen }: { clientId: string; years: { id: string; start_date: string }[]; onDone: (id: string) => void; onOpen: (id: string) => void }) {
  const [docType, setDocType] = useState('purchase_invoice')
  const [fy, setFy] = useState('')
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const send = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      const r = await aiApi.uploadDocument(clientId, file, docType, fy || undefined)
      setNotice(`Uploaded ${file.name} (${fileSize(r.size_bytes)}).`)
      onDone(r.id)
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const existing = error?.code === 'duplicate_document' && error.details && typeof error.details === 'object' ? String((error.details as { document_id?: string }).document_id ?? '') : ''
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Document type">
          <select className={input} value={docType} onChange={(e) => setDocType(e.target.value)}>
            {DOC_TYPES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Financial year (optional)">
          <select className={input} value={fy} onChange={(e) => setFy(e.target.value)}>
            <option value="">(none)</option>
            {years.map((y) => (
              <option key={y.id} value={y.id}>
                {y.start_date.slice(0, 4)}-{String(Number(y.start_date.slice(0, 4)) + 1).slice(2)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Drop a file here or press Enter to choose one"
        className={`flex h-20 cursor-pointer items-center justify-center rounded border-2 border-dashed text-sm ${over ? 'border-blue-600 bg-blue-50' : 'border-slate-300 text-slate-600'}`}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          void send(e.dataTransfer.files[0])
        }}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      >
        {busy ? 'Uploading...' : 'Drop a PDF, PNG, JPEG, TIFF or Tally XML here, or click to choose'}
        <input ref={inputRef} type="file" className="hidden" onChange={(e) => { void send(e.target.files?.[0]); e.target.value = '' }} />
      </div>
      <ErrorBox error={error} />
      {existing && (
        <div className="text-sm">
          This file is already stored.{' '}
          <button className="text-blue-700 underline" onClick={() => onOpen(existing)}>
            Open the existing document
          </button>
        </div>
      )}
      {notice && <Notice>{notice}</Notice>}
    </div>
  )
}

function Detail({ clientId, id, onChange }: { clientId: string; id: string; onChange: () => void }) {
  const doc = useLoad(() => aiApi.getDocument(clientId, id), `ai-doc:${clientId}:${id}`)
  const [method, setMethod] = useState<ReadMethod>('auto')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [text, setText] = useState<PageText | null>(null)
  const [voucherId, setVoucherId] = useState('')
  const d = doc.data
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
  if (!d) return <ErrorBox error={doc.error} />
  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <b>{d.original_filename}</b>
        <span className="text-slate-500">
          {d.content_type}, {fileSize(d.size_bytes)}
          {d.page_count ? `, ${d.page_count} page(s)` : ''}, status {statusLabel(d.status)}
        </span>
        <button className={btn} disabled={busy} onClick={() => run(() => saveDocument(clientId, d.id, d.original_filename))}>
          Download
        </button>
      </div>
      {d.status_note && <div className="text-slate-600">{d.status_note}</div>}
      {d.doc_type !== 'tally_xml' && d.doc_type !== 'tally_export' && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Read text with">
            <select className={input} value={method} onChange={(e) => setMethod(e.target.value as ReadMethod)}>
              <option value="auto">Automatic (text layer, else OCR)</option>
              <option value="pdf_text">PDF text layer only</option>
              <option value="tesseract">OCR: Tesseract</option>
              <option value="paddleocr">OCR: PaddleOCR</option>
            </select>
          </Field>
          <button
            className={btnPrimary}
            disabled={busy}
            onClick={() =>
              run(async () => {
                const r = await aiApi.readText(clientId, d.id, method)
                setNotice(`Text read: ${r.pages.map((p) => `page ${p.page_no} by ${p.method} (${p.char_count} characters)`).join('; ')}`)
                doc.reload()
                onChange()
              })
            }
          >
            Read text / OCR
          </button>
        </div>
      )}
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
      {d.texts.length > 0 && (
        <div>
          <div className="font-semibold">Text read</div>
          <ul className="list-disc pl-5">
            {d.texts.map((t) => (
              <li key={t.page_no}>
                Page {t.page_no}: {t.method} {t.engine_version}, {t.char_count} characters{t.mean_confidence ? `, confidence ${t.mean_confidence}` : ''}{' '}
                <button className="text-blue-700 underline" onClick={() => run(async () => setText(await aiApi.pageText(clientId, d.id, t.page_no)))}>
                  show text
                </button>
              </li>
            ))}
          </ul>
          {text && <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{text.text}</pre>}
        </div>
      )}
      <div>
        <div className="font-semibold">Extractions</div>
        {d.extractions.length === 0 ? (
          <div className="text-slate-500">None yet. Use the Extraction screen.</div>
        ) : (
          <ul className="list-disc pl-5">
            {d.extractions.map((x) => (
              <li key={x.id}>
                Version {x.version}, {x.source}, {x.status}
                {x.superseded ? ' (superseded)' : ''}
              </li>
            ))}
          </ul>
        )}
        {d.queue_item_id && (
          <Link className="text-blue-700 underline" to={`/ai/queue?item=${d.queue_item_id}`}>
            Open in the approval queue
          </Link>
        )}
      </div>
      <div>
        <div className="font-semibold">Linked vouchers</div>
        <ul className="list-disc pl-5">
          {d.linked_voucher_ids.map((v) => (
            <li key={v}>
              <Link className="text-blue-700 underline" to={voucherHref(v)}>
                {v}
              </Link>{' '}
              <button className="text-red-700 underline" onClick={() => run(async () => { await aiApi.unlinkVoucher(clientId, d.id, v); doc.reload(); onChange() })}>
                unlink (draft vouchers only)
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-1 flex items-end gap-2">
          <Field label="Voucher id to link as support">
            <input className={`${input} w-80`} value={voucherId} onChange={(e) => setVoucherId(e.target.value.trim())} />
          </Field>
          <button className={btn} disabled={busy || !voucherId} onClick={() => run(async () => { await aiApi.linkVoucher(clientId, d.id, voucherId); setVoucherId(''); doc.reload(); onChange() })}>
            Link
          </button>
        </div>
      </div>
    </div>
  )
}
