import { useMemo, useRef, useState } from 'react'
import { gstApi, type ReconClass, type ReconRow } from '../api/gst'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { MonthInput, RegistrationSelect, Tabs, useRegistrations } from './common'
import { CLASS_LABEL, isMonth } from './lib'

type Tab = 'import' | ReconClass | 'all'
const CLASSES: ReconClass[] = ['matched', 'value_mismatch', 'gstin_mismatch', 'period_mismatch', 'only_in_books', 'only_in_2b', 'ambiguous']

export default function Recon2b() {
  const { clientId } = useClient()
  const { regs, active, regId, setRegId } = useRegistrations()
  const [period, setPeriod] = useState('')
  const [tab, setTab] = useState<Tab>('import')
  const [kind, setKind] = useState<'gstr2b' | 'ims'>('gstr2b')
  const file = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [linkRow, setLinkRow] = useState<ReconRow | null>(null)
  const [linkDoc, setLinkDoc] = useState('')
  const [linkVoucher, setLinkVoucher] = useState('')
  const [linkKind, setLinkKind] = useState<'manual' | 'accepted_difference'>('manual')
  const [linkNote, setLinkNote] = useState('')
  const [viewImport, setViewImport] = useState('')

  const imports = useLoad(clientId && regId ? () => gstApi.list2bImports(clientId, regId) : null, `2b-imports:${clientId}:${regId}`)
  const recon = useLoad(clientId && regId && isMonth(period) && tab !== 'import' ? () => gstApi.reconciliation(clientId, regId, period) : null, `2b-recon:${clientId}:${regId}:${period}:${tab === 'import'}`)
  const docs = useLoad(viewImport ? () => gstApi.list2bDocuments(viewImport) : null, `2b-docs:${viewImport}`)
  const d = recon.data
  const shown = useMemo(() => (d?.rows ?? []).filter((r) => tab === 'all' || r.class === tab), [d, tab])

  if (!clientId) return <Page title="GSTR-2B reconciliation">Select a client first.</Page>

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await work()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const upload = () =>
    act(async () => {
      const f = file.current?.files?.[0]
      if (!f) throw new Error('Choose the 2B / IMS file first.')
      if (!isMonth(period)) throw new Error('Enter the period as YYYY-MM.')
      const out = await gstApi.import2b(clientId, f, regId, kind, period)
      setNotice(`Imported ${out.documents} documents for ${out.period}.`)
      if (file.current) file.current.value = ''
      imports.reload()
    })
  const startLink = (r: ReconRow) => {
    setLinkRow(r)
    setLinkDoc(r.doc_2b?.document_id ?? '')
    setLinkVoucher(r.books?.voucher_id ?? '')
    setLinkKind(r.class === 'value_mismatch' ? 'accepted_difference' : 'manual')
    setLinkNote('')
  }
  const saveLink = () =>
    act(async () => {
      await gstApi.createLink(clientId, { document_id: linkDoc, voucher_id: linkVoucher, link_kind: linkKind, note: linkNote.trim() })
      setLinkRow(null)
      setNotice('Link saved.')
      recon.reload()
    })
  // for a manual link on an unmatched row the other half is chosen from the other unmatched rows
  const candidates = (want: 'books' | 'doc') =>
    (d?.rows ?? []).filter((r) => (want === 'books' ? r.class === 'only_in_books' && r.books : r.class === 'only_in_2b' && r.doc_2b))

  return (
    <Page title="GSTR-2B / IMS import and reconciliation">
      <div className="flex flex-wrap items-end gap-3">
        <RegistrationSelect regs={active.length ? active : regs} value={regId} onChange={setRegId} />
        <MonthInput value={period} onChange={setPeriod} label="Return period (YYYY-MM)" />
      </div>
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
      <Tabs
        tabs={[
          { key: 'import', label: 'Imports' },
          { key: 'all', label: 'All rows' },
          ...CLASSES.map((c) => ({ key: c as Tab, label: `${CLASS_LABEL[c]}${d ? ` (${d.summary[c] ?? 0})` : ''}` })),
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'import' && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="File type">
              <select className={input} value={kind} onChange={(e) => setKind(e.target.value as 'gstr2b' | 'ims')}>
                <option value="gstr2b">GSTR-2B</option>
                <option value="ims">IMS</option>
              </select>
            </Field>
            <Field label="File (portal JSON or Excel)">
              <input ref={file} type="file" accept=".json,.xlsx,.xls" className="text-sm" />
            </Field>
            <button className={btnPrimary} disabled={busy || !regId} onClick={upload}>
              Import
            </button>
          </div>
          <table className="min-w-full border-collapse bg-white">
            <thead>
              <tr>
                {['Kind', 'Period', 'File', 'Generated on', 'Documents', 'Imported at', ''].map((h) => (
                  <th key={h} className={th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(imports.data ?? []).map((i) => (
                <tr key={i.id}>
                  <td className={td}>{i.kind}</td>
                  <td className={td}>{i.period}</td>
                  <td className={td}>{i.file_name}</td>
                  <td className={td}>{i.generated_on ?? ''}</td>
                  <td className={td}>{i.document_count}</td>
                  <td className={td}>{i.created_at.slice(0, 16).replace('T', ' ')}</td>
                  <td className={td}>
                    <button className={btn} onClick={() => setViewImport(viewImport === i.id ? '' : i.id)}>
                      Documents
                    </button>
                  </td>
                </tr>
              ))}
              {imports.data?.length === 0 && (
                <tr>
                  <td className={td} colSpan={7}>
                    Nothing imported yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {viewImport && (
            <div className="overflow-x-auto">
              <ErrorBox error={docs.error} />
              <table className="min-w-full border-collapse bg-white">
                <thead>
                  <tr>
                    {['Section', 'Supplier GSTIN', 'Name', 'Type', 'Doc no', 'Date', 'ITC avail.', 'IMS'].map((h) => (
                      <th key={h} className={th}>
                        {h}
                      </th>
                    ))}
                    {['Taxable', 'IGST', 'CGST', 'SGST', 'Cess'].map((h) => (
                      <th key={h} className={thR}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(docs.data ?? []).map((x) => (
                    <tr key={x.id}>
                      <td className={td}>{x.section}</td>
                      <td className={`${td} font-mono text-xs`}>{x.supplier_gstin}</td>
                      <td className={td}>{x.supplier_name ?? ''}</td>
                      <td className={td}>{x.doc_type}</td>
                      <td className={td}>{x.doc_no}</td>
                      <td className={td}>{x.doc_date}</td>
                      <td className={td}>{String(x.itc_available ?? '')}</td>
                      <td className={td}>{x.ims_status ?? ''}</td>
                      {[x.taxable_value, x.igst, x.cgst, x.sgst, x.cess].map((v, i) => (
                        <td key={i} className={tdR}>
                          <Amount value={v} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab !== 'import' && (
        <div className="space-y-2">
          {!isMonth(period) && <div className="text-sm text-slate-600">Enter the return period above (YYYY-MM).</div>}
          <ErrorBox error={recon.error} />
          {d && (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span>Tolerance: {d.tolerance}</span>
              <button
                className={btn}
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    if (!window.confirm('Apply this reconciliation to the ITC register? Nothing becomes eligible without the evidence checks.')) return
                    const out = await gstApi.apply2b(clientId, regId, period)
                    setNotice(`${out.updated.length} ITC entr${out.updated.length === 1 ? 'y' : 'ies'} updated.`)
                    recon.reload()
                  })
                }
              >
                Apply to ITC register
              </button>
            </div>
          )}
          {d && (
            <table className="min-w-full border-collapse bg-white">
              <thead>
                <tr>
                  {['Class', 'Voucher', 'Supplier GSTIN', 'Bill / doc no', 'Date', 'ITC status / 2B'].map((h) => (
                    <th key={h} className={th}>
                      {h}
                    </th>
                  ))}
                  {['Taxable (books)', 'Taxable (2B)', 'Tax diff'].map((h) => (
                    <th key={h} className={thR}>
                      {h}
                    </th>
                  ))}
                  <th className={th}>Differences / note</th>
                  <th className={th} />
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => {
                  const tax = r.differences.filter((x) => x.field !== 'taxable_value')
                  return (
                    <tr key={i} className={r.class === 'matched' ? '' : r.class === 'ambiguous' ? 'bg-amber-50' : 'bg-red-50/40'}>
                      <td className={td}>{CLASS_LABEL[r.class] ?? r.class}</td>
                      <td className={td}>{r.books?.voucher_number ?? ''}</td>
                      <td className={`${td} font-mono text-xs`}>{r.books?.supplier_gstin ?? r.doc_2b?.supplier_gstin ?? ''}</td>
                      <td className={td}>{r.books?.supplier_invoice_no ?? r.doc_2b?.doc_no}</td>
                      <td className={td}>{r.books?.invoice_date ?? r.doc_2b?.doc_date}</td>
                      <td className={td}>{[r.books?.itc_status, r.doc_2b?.ims_status].filter(Boolean).join(' / ')}</td>
                      <td className={tdR}>{r.books ? <Amount value={r.books.taxable_value} /> : ''}</td>
                      <td className={tdR}>{r.doc_2b ? <Amount value={r.doc_2b.taxable_value} /> : ''}</td>
                      <td className={tdR}>{tax.length ? tax.map((x) => `${x.field} ${x.difference}`).join(', ') : ''}</td>
                      <td className={`${td} text-xs`}>{r.note}</td>
                      <td className={td}>
                        {r.link_id ? (
                          <button className={btnDanger} disabled={busy} onClick={() => act(async () => { await gstApi.deleteLink(clientId, r.link_id as string); recon.reload() })}>
                            Remove link
                          </button>
                        ) : r.class !== 'matched' ? (
                          <button className={btn} onClick={() => startLink(r)}>
                            Link / accept
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
                {shown.length === 0 && (
                  <tr>
                    <td className={td} colSpan={11}>
                      No rows in this class.
                    </td>
                  </tr>
                )}
              </tbody>
              <tfoot>
                {(['books', 'doc_2b', 'difference'] as const).map((k) => (
                  <tr key={k} className="bg-slate-50 font-medium">
                    <td className={td} colSpan={6}>
                      Total {k === 'doc_2b' ? 'GSTR-2B' : k}
                    </td>
                    <td className={tdR} colSpan={3}>
                      {Object.entries(d.totals[k]).map(([f, v]) => `${f} ${v}`).join('   ')}
                    </td>
                    <td className={td} colSpan={2} />
                  </tr>
                ))}
              </tfoot>
            </table>
          )}
          {linkRow && (
            <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
              <h2 className="text-sm font-semibold">Link a 2B document with a voucher</h2>
              <div className="flex flex-wrap items-end gap-3">
                <Field label="2B document">
                  <select className={input} value={linkDoc} onChange={(e) => setLinkDoc(e.target.value)}>
                    <option value="">(choose)</option>
                    {linkRow.doc_2b && <option value={linkRow.doc_2b.document_id}>{linkRow.doc_2b.supplier_gstin} {linkRow.doc_2b.doc_no}</option>}
                    {candidates('doc').filter((c) => c !== linkRow).map((c) => (
                      <option key={c.doc_2b?.document_id} value={c.doc_2b?.document_id}>
                        {c.doc_2b?.supplier_gstin} {c.doc_2b?.doc_no} {c.doc_2b?.doc_date}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Voucher">
                  <select className={input} value={linkVoucher} onChange={(e) => setLinkVoucher(e.target.value)}>
                    <option value="">(choose)</option>
                    {linkRow.books && <option value={linkRow.books.voucher_id}>{linkRow.books.voucher_number} {linkRow.books.supplier_invoice_no}</option>}
                    {candidates('books').filter((c) => c !== linkRow).map((c) => (
                      <option key={c.books?.voucher_id} value={c.books?.voucher_id}>
                        {c.books?.voucher_number} {c.books?.supplier_invoice_no} {c.books?.invoice_date}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Kind">
                  <select className={input} value={linkKind} onChange={(e) => setLinkKind(e.target.value as typeof linkKind)}>
                    <option value="manual">Manual match</option>
                    <option value="accepted_difference">Accept the difference</option>
                  </select>
                </Field>
                <Field label="Note (required)">
                  <input className={`${input} w-72`} value={linkNote} onChange={(e) => setLinkNote(e.target.value)} />
                </Field>
                <button className={btnPrimary} disabled={busy || !linkDoc || !linkVoucher || !linkNote.trim()} onClick={saveLink}>
                  Save link
                </button>
                <button className={btn} onClick={() => setLinkRow(null)}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Page>
  )
}
