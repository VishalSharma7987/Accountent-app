import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { aiApi, type QueueVouchersResult, type TallyMaster, type TallyReport } from '../api/ai'
import { LedgerSelect } from '../final/common'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import type { LedgerRow } from '../types'
import { DocSelect, NoClient, useDocuments } from './common'
import { statusLabel } from './lib'

export default function TallyImport() {
  const { clientId, client, latestYear } = useClient()
  const docs = useDocuments(clientId, 'tally_xml')
  const imports = useLoad(clientId ? () => aiApi.listImports(clientId) : null, `ai-imports:${clientId}`)
  const [docId, setDocId] = useState('')
  const [importId, setImportId] = useState('')
  const [report, setReport] = useState<TallyReport | null>(null)
  const [fy, setFy] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [queued, setQueued] = useState<QueueVouchersResult | null>(null)
  const [busy, setBusy] = useState(false)
  const masters = useLoad(clientId && importId ? () => aiApi.listMasters(clientId) : null, `ai-masters:${clientId}:${importId}`)
  const ledgers = useLoad<LedgerRow[]>(clientId ? () => api.listLedgers(clientId) : null, `ai-tally-ledgers:${clientId}`)
  if (!clientId)
    return (
      <Page title="Tally import">
        <NoClient />
      </Page>
    )
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
  const open = (id: string) =>
    run(async () => {
      const row = await aiApi.getImport(clientId, id)
      setImportId(id)
      setReport(row.report)
      setQueued(null)
    })
  const existingImport = error?.code === 'import_exists' ? imports.data?.find((i) => i.document_id === docId) : undefined
  return (
    <Page title="Tally import">
      <div className="flex flex-wrap items-end gap-2">
        <DocSelect label="Tally XML (upload it on the Documents screen first)" documents={docs.documents} value={docId} onChange={setDocId} />
        <button
          className={btnPrimary}
          disabled={busy || !docId}
          onClick={() =>
            run(async () => {
              const r = await aiApi.createImport(clientId, docId)
              setImportId(r.import_id)
              setReport(r.report)
              setQueued(null)
              imports.reload()
              setNotice(`Read ${r.company_name ?? 'the file'}. Nothing was created yet: decide the masters below.`)
            })
          }
        >
          Read file and make mapping report
        </button>
        <Field label="Or open an earlier import">
          <select className={input} value={importId} onChange={(e) => e.target.value && open(e.target.value)}>
            <option value="">(choose)</option>
            {(imports.data ?? []).map((i) => (
              <option key={i.import_id} value={i.import_id}>
                {i.company_name ?? 'Tally file'} {i.created_at.slice(0, 10)} ({statusLabel(i.status)})
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ErrorBox error={error} />
      {existingImport && (
        <div className="text-sm">
          This file was imported before.{' '}
          <button className="text-blue-700 underline" onClick={() => open(existingImport.import_id)}>
            Open that import
          </button>
        </div>
      )}
      {notice && <Notice>{notice}</Notice>}
      {report && (
        <>
          <div className="rounded border border-slate-300 bg-white p-3 text-sm">
            <div className="font-semibold">Mapping report</div>
            <div>{Object.entries(report.counts).map(([k, v]) => `${k.replace('_', ' ')}: ${v}`).join(', ')}</div>
            <div>Vouchers by type: {Object.entries(report.vouchers.by_type).map(([k, v]) => `${k} ${v}`).join(', ') || 'none'}</div>
            {report.opening_balances_not_applied !== false && <div className="text-amber-800">D-33: opening balances in the Tally file are reported below and never applied. Enter them in Opening Balances.</div>}
            <table className="mt-2 w-full border-collapse">
              <thead>
                <tr>
                  <th className={th}>Tally ledger</th>
                  <th className={th}>Tally group</th>
                  <th className={th}>Suggested group</th>
                  <th className={th}>Suggestion</th>
                  <th className={th}>Opening balance reported</th>
                </tr>
              </thead>
              <tbody>
                {report.ledgers.map((l, i) => (
                  <tr key={i}>
                    <td className={td}>{l.name}</td>
                    <td className={td}>{l.parent_group}</td>
                    <td className={td}>{l.suggested_group_code}</td>
                    <td className={td}>
                      {statusLabel(l.decision)}
                      {l.reason ? `: ${l.reason}` : ''}
                    </td>
                    <td className={td}>{l.opening_balance_reported ? formatInr(l.opening_balance_reported) : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Masters
            clientId={clientId}
            masters={masters.data ?? []}
            ledgers={ledgers.data ?? []}
            run={run}
            reload={masters.reload}
          />
          <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3 text-sm">
            <button className={btn} disabled={busy} onClick={() => run(async () => { const r = await aiApi.confirmExact(clientId, importId); setNotice(`${r.confirmed} exact matches confirmed.`); masters.reload() })}>
              Confirm exact matches
            </button>
            <button className={btn} disabled={busy} onClick={() => run(async () => { const r = await aiApi.applyMasters(clientId, importId); setNotice(`Masters created: ${Object.entries(r.created).map(([k, v]) => `${v} ${k}`).join(', ') || 'none'}.`); masters.reload(); ledgers.reload() })}>
              Apply masters (create the ones marked create)
            </button>
            <Field label="Financial year for the drafts">
              <select className={input} value={fy || latestYear?.id || ''} onChange={(e) => setFy(e.target.value)}>
                {(client?.financial_years ?? []).map((y) => (
                  <option key={y.id} value={y.id}>
                    {y.start_date.slice(0, 4)}-{String(Number(y.start_date.slice(0, 4)) + 1).slice(2)}
                  </option>
                ))}
              </select>
            </Field>
            <button className={btnPrimary} disabled={busy} onClick={() => run(async () => setQueued(await aiApi.queueVouchers(clientId, importId, fy || latestYear?.id)))}>
              Create drafts and queue them
            </button>
          </div>
          {queued && (
            <div className="space-y-2 rounded border border-slate-300 bg-white p-3 text-sm">
              <div>
                Queued {queued.queued}: {queued.drafted} drafted, {queued.needs_review} need review. Nothing is approved or posted.{' '}
                <Link className="text-blue-700 underline" to="/ai/queue">
                  Open the approval queue
                </Link>
              </div>
              <div className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-amber-900">
                D-35: a Tally voucher is drafted as plain ledger lines. Where it uses a tax ledger it is not a GST invoice and will not reach GSTR-1 or GSTR-3B, the ITC register or GST reconciliation; the queue shows a D-35 warning on it.
              </div>
              <Skipped rows={queued.skipped} title="Skipped while queuing" />
            </div>
          )}
          <Skipped rows={report.vouchers.skipped} title="Vouchers skipped by the file report" />
        </>
      )}
    </Page>
  )
}

function Skipped({ rows, title }: { rows: { type: string; date: string; number: string | null; reason_rule: string; reason: string }[]; title: string }) {
  if (rows.length === 0) return null
  return (
    <div className="rounded border border-slate-300 bg-white p-3 text-sm">
      <div className="font-semibold">
        {title} ({rows.length})
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className={th}>Type</th>
            <th className={th}>Date</th>
            <th className={th}>Number</th>
            <th className={th}>Rule</th>
            <th className={th}>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className={td}>{r.type}</td>
              <td className={td}>{r.date}</td>
              <td className={td}>{r.number}</td>
              <td className={`${td} font-mono text-xs`}>{r.reason_rule}</td>
              <td className={td}>{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Masters({ clientId, masters, ledgers, run, reload }: { clientId: string; masters: TallyMaster[]; ledgers: LedgerRow[]; run: (fn: () => Promise<void>) => Promise<void>; reload: () => void }) {
  const [filter, setFilter] = useState('')
  const [acceptNature, setAcceptNature] = useState(false)
  const shown = masters.filter((m) => (filter ? m.decision === filter : true))
  const decide = (m: TallyMaster, decision: 'confirmed' | 'create' | 'skip', extra: { target_group_id?: string | null; target_ledger_id?: string | null } = {}) =>
    run(async () => {
      await aiApi.decideMaster(clientId, m.id, {
        decision,
        target_group_id: extra.target_group_id ?? m.target_group_id,
        target_ledger_id: extra.target_ledger_id ?? m.target_ledger_id,
        target_item_id: m.target_item_id,
        accept_nature_change: acceptNature,
      })
      reload()
    })
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-3 text-sm">
      <div className="flex items-end gap-3">
        <b>Master decisions</b>
        <Field label="Show">
          <select className={input} value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All</option>
            {['suggested', 'confirmed', 'create', 'skip'].map((d) => (
              <option key={d} value={d}>
                {statusLabel(d)}
              </option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={acceptNature} onChange={(e) => setAcceptNature(e.target.checked)} />
          accept a change of nature when a ledger goes into a group of another nature
        </label>
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className={th}>Kind</th>
            <th className={th}>Tally name</th>
            <th className={th}>Parent</th>
            <th className={th}>Decision</th>
            <th className={th}>Target ledger</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {shown.map((m) => (
            <tr key={m.id}>
              <td className={td}>{m.kind}</td>
              <td className={td}>{m.source_name}</td>
              <td className={td}>{m.source_parent}</td>
              <td className={td}>
                {statusLabel(m.decision)}
                {m.reason ? ` (${m.reason})` : ''}
              </td>
              <td className={td}>
                {m.kind === 'ledger' && <LedgerSelect ledgers={ledgers} value={m.target_ledger_id ?? ''} blank="(existing ledger)" onChange={(id) => decide(m, 'confirmed', { target_ledger_id: id })} />}
                {m.kind !== 'ledger' && (m.target_group_id ? 'suggested group kept' : '')}
              </td>
              <td className={td}>
                <button className={btn} onClick={() => decide(m, 'confirmed')}>
                  Confirm
                </button>{' '}
                {m.kind !== 'group' && (
                  <button className={btn} onClick={() => decide(m, 'create')}>
                    Create
                  </button>
                )}{' '}
                <button className={btn} onClick={() => decide(m, 'skip')}>
                  Skip
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
