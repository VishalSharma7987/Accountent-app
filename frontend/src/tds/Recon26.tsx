import { useRef, useState } from 'react'
import { tdsApi, type ReconRow, type Source26 } from '../api/tds'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { DataView, FySelect, NoClient, Row, useFy } from './common'

const CLASS_CLS: Record<string, string> = {
  matched: 'bg-green-50',
  amount_mismatch: 'bg-amber-50',
  date_mismatch: 'bg-amber-50',
  only_in_books: 'bg-red-50',
  only_in_26as: 'bg-red-50',
}
const CLASS_LABEL: Record<string, string> = {
  matched: 'Matched',
  amount_mismatch: 'Amount differs',
  date_mismatch: 'Month differs',
  only_in_books: 'Only in books',
  only_in_26as: 'Only in 26AS / AIS',
}

/** Import Form 26AS / AIS / TIS and reconcile with the TDS register; manual links need a note (T-43). */
export default function Recon26() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const file = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<Source26>('form_26as')
  const [side, setSide] = useState<'deductee' | 'deductor'>('deductor')
  const [importId, setImportId] = useState('')
  const imports = useLoad(clientId && fyId ? () => tdsApi.list26Imports(clientId, fyId) : null, `tds-26i:${clientId}:${fyId}`)
  const recon = useLoad(clientId && fyId ? () => tdsApi.reconciliation(clientId, { financial_year_id: fyId, import_id: importId }) : null, `tds-26r:${clientId}:${fyId}:${importId}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  if (!clientId) return <Page title="26AS reconciliation"><NoClient /></Page>

  const upload = async () => {
    const f = file.current?.files?.[0]
    if (!f) return
    setError(null)
    setNotice('')
    const form = new FormData()
    form.append('file', f)
    form.append('financial_year_id', fyId)
    form.append('source', source)
    form.append('side', side)
    try {
      const out = await tdsApi.import26(clientId, form)
      setNotice(`Imported ${out.rows} rows: paid ${out.totals.amount_paid}, deducted ${out.totals.tax_deducted}, deposited ${out.totals.tax_deposited}.`)
      setImportId(out.import_id)
      if (file.current) file.current.value = ''
      imports.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }

  const summary = recon.data?.summary ?? {}
  return (
    <Page title="26AS / AIS reconciliation">
      <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
        <Row>
          <FySelect years={years} value={fyId} onChange={setFyId} />
          <Field label="Statement">
            <select className={input} value={source} onChange={(e) => setSource(e.target.value as Source26)}>
              <option value="form_26as">Form 26AS</option>
              <option value="ais">AIS</option>
              <option value="tis">TIS</option>
            </select>
          </Field>
          <Field label="Side">
            <select className={input} value={side} onChange={(e) => setSide(e.target.value as typeof side)}>
              <option value="deductor">Deductor (our deductions)</option>
              <option value="deductee">Deductee (our TDS receivable)</option>
            </select>
          </Field>
          <Field label="Excel / CSV file">
            <input ref={file} type="file" accept=".xlsx,.xls,.csv" className="text-sm" />
          </Field>
          <button className={btnPrimary} disabled={!fyId} onClick={upload}>
            Import
          </button>
        </Row>
        <ErrorBox error={error} />
        {notice && <Notice>{notice}</Notice>}
      </div>
      <Row>
        <Field label="Imported statement">
          <select className={`${input} w-80`} value={importId} onChange={(e) => setImportId(e.target.value)}>
            <option value="">(latest)</option>
            {(imports.data ?? []).map((i) => (
              <option key={i.id} value={i.id}>
                {String(i.source ?? '')} {String(i.side ?? '')} {String(i.file_name ?? i.id)} {String(i.imported_at ?? '')}
              </option>
            ))}
          </select>
        </Field>
      </Row>
      <ErrorBox error={recon.error ?? imports.error} />
      {recon.data && (
        <>
          <div className="flex flex-wrap gap-2 text-sm">
            {Object.entries(CLASS_LABEL).map(([k, label]) => (
              <span key={k} className={`rounded border border-slate-300 px-2 py-0.5 ${CLASS_CLS[k]}`}>
                {label}: <b>{summary[k] ?? 0}</b>
              </span>
            ))}
            <span className="text-xs text-slate-600">Amount tolerance <Amount value={recon.data.tolerance} />. Key: PAN / TAN + section (old or new code) + amount + month.</span>
          </div>
          <table className="min-w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Result</th>
                <th className={th}>Statement row</th>
                <th className={th}>Books</th>
                <th className={thR}>Books TDS</th>
                <th className={thR}>Difference</th>
                <th className={th}>Section mapping</th>
                <th className={th}></th>
              </tr>
            </thead>
            <tbody>
              {recon.data.rows.map((r, i) => (
                <ReconLine key={i} r={r} clientId={clientId} onChanged={recon.reload} />
              ))}
              {recon.data.rows.length === 0 && (
                <tr>
                  <td colSpan={7} className={`${td} text-slate-500`}>
                    Nothing to reconcile. Import a statement first.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </Page>
  )
}

function rowText(row: Record<string, unknown> | null): string {
  if (!row) return '-'
  const pick = ['deductor_name', 'name', 'pan', 'tan', 'section', 'transaction_date', 'amount_paid', 'tax_deducted']
  return pick.filter((k) => row[k] !== undefined && row[k] !== null).map((k) => String(row[k])).join(' | ') || JSON.stringify(row)
}

function ReconLine({ r, clientId, onChanged }: { r: ReconRow; clientId: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<'manual' | 'accepted_difference'>('manual')
  const [note, setNote] = useState('')
  const [target, setTarget] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const rowId = r.row ? String(r.row.id ?? r.row.row_id ?? '') : ''
  const link = async () => {
    setError(null)
    try {
      await tdsApi.link(clientId, { row_id: rowId, item_id: r.books?.item_id ?? (target || undefined), link_kind: kind, note })
      setOpen(false)
      onChanged()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <>
      <tr className={CLASS_CLS[r.class] ?? ''}>
        <td className={td}>{CLASS_LABEL[r.class] ?? r.class}</td>
        <td className={td}>{rowText(r.row)}</td>
        <td className={td}>{r.books ? `${r.books.deductee_name} ${r.books.section_ref} ${r.books.event_date}` : '-'}</td>
        <td className={tdR}>{r.books ? <Amount value={r.books.tds_amount} /> : ''}</td>
        <td className={tdR}>{r.difference ? <Amount value={r.difference} /> : ''}</td>
        <td className={td}>{r.section_mapping_status}</td>
        <td className={td}>
          {rowId && r.class !== 'matched' && (
            <button className={btn} onClick={() => setOpen(!open)}>
              Link / accept
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="bg-slate-50 p-2">
            <Row>
              <Field label="Link kind">
                <select className={input} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                  <option value="manual">Manual link</option>
                  <option value="accepted_difference">Accept the difference</option>
                </select>
              </Field>
              {!r.books?.item_id && (
                <Field label="Books deduction id">
                  <input className={`${input} w-72`} value={target} onChange={(e) => setTarget(e.target.value.trim())} />
                </Field>
              )}
              <Field label="Note (required)">
                <input className={`${input} w-80`} value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <button className={btnPrimary} disabled={!note.trim()} onClick={link}>
                Save link
              </button>
            </Row>
            <ErrorBox error={error} />
            {r.row && <DataView value={r.row} />}
          </td>
        </tr>
      )}
    </>
  )
}
