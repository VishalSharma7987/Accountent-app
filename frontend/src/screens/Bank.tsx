import { useState } from 'react'
import { api } from '../api'
import { ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { DATE_FORMATS, blankMapping, cashBankLedgers, cleanMapping, mappingProblems } from '../lib/phase2'
import { asFailure, useLoad } from '../lib/useLoad'
import type { BankMapping, StatementPreview } from '../types'

type Tab = 'import' | 'formats' | 'statements'

export default function Bank() {
  const { clientId } = useClient()
  const [tab, setTab] = useState<Tab>('import')
  const formats = useLoad(clientId ? () => api.listBankFormats(clientId) : null, `bank-formats:${clientId}`)
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  if (!clientId) return <Page title="Bank statements">Select a client first.</Page>
  const banks = cashBankLedgers(ledgers.data ?? [], true)

  return (
    <Page title="Bank statements">
      <div className="flex gap-1 text-sm">
        {(
          [
            ['import', 'Import a statement'],
            ['formats', 'Statement formats'],
            ['statements', 'Imported statements'],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button key={k} className={`rounded px-3 py-1 ${tab === k ? 'bg-blue-700 text-white' : 'border border-slate-300 bg-white hover:bg-slate-100'}`} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>
      <ErrorBox error={formats.error ?? ledgers.error} />
      {tab === 'formats' && <Formats clientId={clientId} formats={formats.data ?? []} reload={formats.reload} />}
      {tab === 'import' && <Import clientId={clientId} formats={formats.data ?? []} banks={banks} />}
      {tab === 'statements' && <Statements clientId={clientId} banks={banks} />}
    </Page>
  )
}

function Formats({ clientId, formats, reload }: { clientId: string; formats: { id: string; name: string; mapping: BankMapping }[]; reload: () => void }) {
  const [name, setName] = useState('')
  const [m, setM] = useState<BankMapping>(blankMapping())
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (patch: Partial<BankMapping>) => setM((x) => ({ ...x, ...patch }))
  const problems = [...(name.trim() ? [] : ['Give the format a name.']), ...mappingProblems(m)]
  const text = (key: keyof BankMapping, label: string, hint?: string) => (
    <Field label={label}>
      <input className={input} value={(m[key] as string | null | undefined) ?? ''} placeholder={hint} onChange={(e) => set({ [key]: e.target.value } as Partial<BankMapping>)} />
    </Field>
  )

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await api.createBankFormat(clientId, name.trim(), cleanMapping(m))
      setNotice(`Format "${name.trim()}" saved.`)
      setName('')
      setM(blankMapping())
      reload()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Format</th>
            <th className={th}>Header row</th>
            <th className={th}>Date</th>
            <th className={th}>Description</th>
            <th className={th}>Debit / Credit or Amount / Dr-Cr</th>
            <th className={th}>Balance</th>
          </tr>
        </thead>
        <tbody>
          {formats.map((f) => (
            <tr key={f.id}>
              <td className={td}>{f.name}</td>
              <td className={td}>{f.mapping.header_row}</td>
              <td className={td}>
                {f.mapping.date_col} ({f.mapping.date_format})
              </td>
              <td className={td}>{f.mapping.description_col}</td>
              <td className={td}>{f.mapping.debit_col ? `${f.mapping.debit_col} / ${f.mapping.credit_col}` : `${f.mapping.amount_col} / ${f.mapping.drcr_col}`}</td>
              <td className={td}>{f.mapping.balance_col}</td>
            </tr>
          ))}
          {formats.length === 0 && (
            <tr>
              <td className={td} colSpan={6}>
                No formats yet. Describe your bank's file below once, then reuse it for every statement.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
        <div className="font-semibold">New format (column names exactly as in the file's header row)</div>
        <ErrorBox error={error} />
        {notice && <Notice>{notice}</Notice>}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Field label="Format name">
            <input className={input} value={name} placeholder="e.g. HDFC current account" onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Header row (1 = first row)">
            <input className={input} inputMode="numeric" value={String(m.header_row)} onChange={(e) => set({ header_row: Number(e.target.value) || 0 })} />
          </Field>
          {text('date_col', 'Date column')}
          <Field label="Date format">
            <input className={input} list="date-formats" value={m.date_format} onChange={(e) => set({ date_format: e.target.value })} />
            <datalist id="date-formats">
              {DATE_FORMATS.map((f) => (
                <option key={f} value={f} />
              ))}
            </datalist>
          </Field>
          {text('description_col', 'Description column')}
          {text('reference_col', 'Reference / cheque no column (optional)')}
          {text('debit_col', 'Debit (withdrawal) column')}
          {text('credit_col', 'Credit (deposit) column')}
          {text('amount_col', 'or: Amount column')}
          {text('drcr_col', 'or: Dr/Cr column')}
          {text('balance_col', 'Balance column (optional)')}
          {text('opening_balance', 'Opening balance (if not in the file)')}
        </div>
        {problems.length > 0 && (
          <ul className="list-disc pl-5 text-xs text-amber-800">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <button className={btnPrimary} disabled={busy || problems.length > 0} onClick={save}>
          Save format
        </button>
      </div>
    </>
  )
}

function Import({ clientId, formats, banks }: { clientId: string; formats: { id: string; name: string }[]; banks: { id: string; name: string }[] }) {
  const [bankId, setBankId] = useState('')
  const [formatId, setFormatId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<StatementPreview | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const reset = () => {
    setPreview(null)
    setNotice('')
    setError(null)
  }
  const runPreview = async () => {
    if (!file) return
    setBusy(true)
    reset()
    try {
      setPreview(await api.previewStatement(clientId, file, formatId))
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const confirm = async () => {
    if (!file || !window.confirm('Import this statement? Lines already imported are never duplicated, but an import cannot be edited.')) return
    setBusy(true)
    setError(null)
    try {
      const out = await api.importStatement(clientId, file, bankId, formatId)
      setNotice(`Imported ${out.lines} lines. Opening ${formatInr(out.opening_balance)}, closing ${formatInr(out.closing_balance)}.${(out.notes ?? []).map((n) => ` Note: ${n}.`).join('')}`)
      setPreview(null)
      setFile(null)
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  const columns = preview && preview.rows.length ? Object.keys(preview.rows[0]) : []
  const details = Array.isArray(error?.details) ? (error?.details as { row?: number | null; message?: string }[]) : []

  return (
    <>
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Bank ledger">
          <select className={input} value={bankId} onChange={(e) => setBankId(e.target.value)}>
            <option value="">(choose bank)</option>
            {banks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Statement format">
          <select className={input} value={formatId} onChange={(e) => { setFormatId(e.target.value); reset() }}>
            <option value="">(choose format)</option>
            {formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Statement file (.xlsx / .csv)">
          <input type="file" accept=".xlsx,.xls,.csv" className="text-sm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); reset() }} />
        </Field>
        <button className={btnPrimary} disabled={!file || !formatId || busy} onClick={runPreview}>
          Preview
        </button>
      </div>
      <ErrorBox error={error} />
      {details.length > 0 && (
        <ul className="list-disc rounded border border-red-300 bg-red-50 py-2 pl-7 pr-3 text-sm text-red-800">
          {details.map((d, i) => (
            <li key={i}>
              {d.row ? `Row ${d.row}: ` : ''}
              {d.message}
            </li>
          ))}
        </ul>
      )}
      {notice && <Notice>{notice}</Notice>}
      {preview && (
        <>
          <div className="text-sm">
            {preview.count} lines. Opening {preview.opening_balance === null ? '(not found)' : formatInr(preview.opening_balance)}, closing{' '}
            {preview.closing_balance === null ? '(not found)' : formatInr(preview.closing_balance)}. First {preview.rows.length} lines shown.
          </div>
          {(preview.notes ?? []).map((n, i) => (
            <Notice key={i}>{n}</Notice>
          ))}
          {preview.problems.length > 0 ? (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
              <div className="font-semibold">Problems found: fix the file or the format, then preview again.</div>
              <ul className="list-disc pl-5">
                {preview.problems.map((p, i) => (
                  <li key={i}>
                    {p.row ? `Row ${p.row}: ` : ''}
                    {p.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <Notice>No problems found.</Notice>
          )}
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c} className={th}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c} className={td}>
                      {String(r[c] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <button className={btnPrimary} disabled={busy || !bankId || preview.problems.length > 0} onClick={confirm} title={!bankId ? 'Choose the bank ledger first' : ''}>
            Confirm import
          </button>
        </>
      )}
    </>
  )
}

function Statements({ clientId, banks }: { clientId: string; banks: { id: string; name: string }[] }) {
  const [bankId, setBankId] = useState('')
  const list = useLoad(() => api.listStatements(clientId, bankId || undefined), `statements:${clientId}:${bankId}`)
  const [open, setOpen] = useState('')
  const lines = useLoad(open ? () => api.statementLines(open) : null, `statement-lines:${open}`)
  const [error, setError] = useState<ApiFailure | null>(null)

  const remove = async (id: string) => {
    if (!window.confirm('Delete this imported statement? This is refused while any line is matched.')) return
    setError(null)
    try {
      await api.deleteStatement(id)
      if (open === id) setOpen('')
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }

  return (
    <>
      <div className="flex items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Bank ledger">
          <select className={input} value={bankId} onChange={(e) => setBankId(e.target.value)}>
            <option value="">All banks</option>
            {banks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ErrorBox error={error ?? list.error ?? lines.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>File</th>
            <th className={th}>From</th>
            <th className={th}>To</th>
            <th className={thR}>Opening</th>
            <th className={thR}>Closing</th>
            <th className={thR}>Lines</th>
            <th className={thR}>Matched</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((s) => (
            <tr key={s.id} className={open === s.id ? 'bg-blue-50' : ''}>
              <td className={td}>{s.file_name}</td>
              <td className={td}>{s.period_from}</td>
              <td className={td}>{s.period_to}</td>
              <td className={tdR}>{formatInr(s.opening_balance)}</td>
              <td className={tdR}>{formatInr(s.closing_balance)}</td>
              <td className={tdR}>{s.line_count}</td>
              <td className={tdR}>{s.matched_count}</td>
              <td className={td + ' space-x-1'}>
                <button className={btn} onClick={() => setOpen(open === s.id ? '' : s.id)}>
                  {open === s.id ? 'Hide lines' : 'Lines'}
                </button>
                <button className={btnDanger} disabled={s.matched_count > 0} title={s.matched_count > 0 ? 'Unmatch its lines first' : ''} onClick={() => remove(s.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={8}>
                No statements imported yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {lines.data && (
        <table className="w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>#</th>
              <th className={th}>Date</th>
              <th className={th}>Description</th>
              <th className={th}>Reference</th>
              <th className={thR}>Debit</th>
              <th className={thR}>Credit</th>
              <th className={thR}>Balance</th>
              <th className={th}>Matched</th>
            </tr>
          </thead>
          <tbody>
            {lines.data.map((l) => (
              <tr key={l.id}>
                <td className={td}>{l.line_no}</td>
                <td className={td}>{l.txn_date}</td>
                <td className={td}>{l.description}</td>
                <td className={td}>{l.reference}</td>
                <td className={tdR}>{l.debit === '0.00' ? '' : formatInr(l.debit)}</td>
                <td className={tdR}>{l.credit === '0.00' ? '' : formatInr(l.credit)}</td>
                <td className={tdR}>{l.balance ? formatInr(l.balance) : ''}</td>
                <td className={td}>{l.match_id ? 'Yes' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
