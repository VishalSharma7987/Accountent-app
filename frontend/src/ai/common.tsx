import { useEffect, useState } from 'react'
import { aiApi, fetchDocumentBlob, type DocFinding, type DocumentRow } from '../api/ai'
import { Field, input } from '../components/ui'
import { asFailure, useLoad } from '../lib/useLoad'
import { groupByRule } from './lib'

export { NoClient } from '../tds/common'
export { ErrorBox, Notice } from '../components/ui'

const SEV: Record<string, string> = {
  error: 'bg-red-200 text-red-900',
  review: 'bg-orange-200 text-orange-900',
  warning: 'bg-amber-200 text-amber-900',
  info: 'bg-slate-200 text-slate-800',
}
export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${SEV[severity] ?? SEV.info}`}>{severity}</span>
}

/** Server findings grouped by rule id with their severity. Nothing is judged in the browser. */
export function DocFindings({ findings, empty = 'No findings.' }: { findings: DocFinding[] | undefined | null; empty?: string }) {
  const list = findings ?? []
  if (list.length === 0) return <div className="text-sm text-slate-500">{empty}</div>
  return (
    <div className="space-y-2">
      {groupByRule(list).map((g) => (
        <div key={g.rule_id} className="rounded border border-slate-200 bg-white">
          <div className="border-b border-slate-200 bg-slate-50 px-2 py-0.5 font-mono text-xs font-semibold">{g.rule_id}</div>
          <ul className="divide-y divide-slate-100">
            {g.items.map((f, i) => (
              <li key={i} className="flex items-start gap-2 px-2 py-1 text-sm">
                <SeverityBadge severity={f.severity} />
                <div>
                  <div>{f.message}</div>
                  {(f.field_path || f.printed || f.computed) && (
                    <div className="text-xs text-slate-500">
                      {f.field_path && <span className="font-mono">{f.field_path}</span>}
                      {f.printed && <span> printed {f.printed}</span>}
                      {f.computed && <span> computed {f.computed}</span>}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

/** Documents of a client, newest first as the server sends them. */
export function useDocuments(clientId: string, docType?: string) {
  const list = useLoad<DocumentRow[]>(clientId ? () => aiApi.listDocuments(clientId, { doc_type: docType }) : null, `ai-docs:${clientId}:${docType ?? ''}`)
  return { ...list, documents: list.data ?? [] }
}

export function DocSelect({ documents, value, onChange, label = 'Document' }: { documents: DocumentRow[]; value: string; onChange: (id: string) => void; label?: string }) {
  return (
    <Field label={label}>
      <select className={`${input} min-w-64`} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">(choose document)</option>
        {documents.map((d) => (
          <option key={d.id} value={d.id}>
            {d.original_filename} ({d.status})
          </option>
        ))}
      </select>
    </Field>
  )
}

/** The document through the authenticated download endpoint as a blob URL (released on change); never a public URL. */
export function useBlobUrl(clientId: string, documentId: string | null | undefined) {
  const [state, setState] = useState<{ key: string; url: string | null; error: string; type: string }>({ key: '', url: null, error: '', type: '' })
  const key = `${clientId}:${documentId ?? ''}`
  useEffect(() => {
    if (!clientId || !documentId) return
    let current = true
    let made: string | null = null
    fetchDocumentBlob(clientId, documentId)
      .then((blob) => {
        made = URL.createObjectURL(blob)
        if (current) setState({ key, url: made, error: '', type: blob.type })
        else URL.revokeObjectURL(made)
      })
      .catch((e: unknown) => {
        if (current) setState({ key, url: null, error: asFailure(e).message, type: '' })
      })
    return () => {
      current = false
      if (made) URL.revokeObjectURL(made)
    }
  }, [clientId, documentId, key])
  const ready = state.key === key
  return { url: ready ? state.url : null, error: ready ? state.error : '', type: ready ? state.type : '', loading: !!documentId && !ready }
}

/** The document image or PDF itself. */
export function DocumentViewer({ clientId, documentId, contentType }: { clientId: string; documentId: string | null | undefined; contentType?: string }) {
  const blob = useBlobUrl(clientId, documentId)
  if (!documentId) return <div className="text-sm text-slate-500">No document.</div>
  if (blob.loading) return <div className="text-sm text-slate-500">Loading document...</div>
  if (blob.error) return <div className="text-sm text-red-700">{blob.error}</div>
  if (!blob.url) return null
  const type = contentType ?? blob.type
  return type.startsWith('image/') ? (
    <img src={blob.url} alt="Source document" className="max-h-[75vh] w-full rounded border border-slate-300 object-contain" />
  ) : (
    <iframe src={blob.url} title="Source document" className="h-[75vh] w-full rounded border border-slate-300" />
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1 text-sm">
      {tabs.map(([k, label]) => (
        <button key={k} className={`rounded px-3 py-1 ${value === k ? 'bg-blue-700 text-white' : 'border border-slate-300 bg-white hover:bg-slate-100'}`} onClick={() => onChange(k)}>
          {label}
        </button>
      ))}
    </div>
  )
}
