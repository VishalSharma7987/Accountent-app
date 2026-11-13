import { useState } from 'react'
import { gstApi, type ExposureItem, type Heads, type ItcEntry, type ItcStatus, type SupplierTaxPaid } from '../api/gst'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { DataView, RegistrationSelect, RuleBadge, Tabs, useRegistrations } from './common'

type Tab = 'register' | 'exposure' | 'reversals' | 'tie'
const STATUSES: ItcStatus[] = ['eligible', 'pending', 'blocked', 'reversed']
const STATUS_CLS: Record<ItcStatus, string> = {
  eligible: 'bg-green-100 text-green-900',
  pending: 'bg-amber-100 text-amber-900',
  blocked: 'bg-red-100 text-red-900',
  reversed: 'bg-slate-200 text-slate-800',
}
const HEADS: (keyof Heads)[] = ['igst', 'cgst', 'sgst', 'cess']

function HeadCells({ h }: { h: Heads }) {
  return (
    <>
      {HEADS.map((k) => (
        <td key={k} className={tdR}>
          <Amount value={h[k]} />
        </td>
      ))}
    </>
  )
}
const headCols = ['IGST', 'CGST', 'SGST', 'Cess']

export default function ItcRegister() {
  const { clientId } = useClient()
  const { regs, active, regId, setRegId } = useRegistrations()
  const [tab, setTab] = useState<Tab>('register')
  const [status, setStatus] = useState('')
  const [period, setPeriod] = useState('')
  const [asOn, setAsOn] = useState(today())
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="ITC register">Select a client first.</Page>

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

  return (
    <Page title="Input tax credit (ITC)">
      <div className="flex flex-wrap items-end gap-3">
        <RegistrationSelect regs={active.length ? active : regs} value={regId} onChange={setRegId} />
        <Field label="As on">
          <input type="date" className={input} value={asOn} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
      </div>
      <Tabs
        tabs={[
          { key: 'register', label: 'Register' },
          { key: 'exposure', label: '180-day exposure' },
          { key: 'reversals', label: 'Reversals' },
          { key: 'tie', label: 'Ledger tie' },
        ]}
        value={tab}
        onChange={setTab}
      />
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
      {tab === 'register' && <Register clientId={clientId} regId={regId} status={status} setStatus={setStatus} period={period} setPeriod={setPeriod} act={act} busy={busy} setNotice={setNotice} />}
      {tab === 'exposure' && <Exposure clientId={clientId} regId={regId} asOn={asOn} act={act} busy={busy} setNotice={setNotice} />}
      {tab === 'reversals' && <Reversals clientId={clientId} asOn={asOn} act={act} busy={busy} setNotice={setNotice} />}
      {tab === 'tie' && <Tie clientId={clientId} regId={regId} asOn={asOn} />}
    </Page>
  )
}

interface Common {
  clientId: string
  act: (w: () => Promise<void>) => Promise<void>
  busy: boolean
  setNotice: (s: string) => void
}

function Register({ clientId, regId, status, setStatus, period, setPeriod, act, busy, setNotice }: Common & { regId: string; status: string; setStatus: (s: string) => void; period: string; setPeriod: (s: string) => void }) {
  const list = useLoad(regId ? () => gstApi.listItc(clientId, { registration_id: regId, status, period }) : null, `itc:${clientId}:${regId}:${status}:${period}`)
  const [open, setOpen] = useState<ItcEntry | null>(null)
  const d = list.data
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Status">
          <select className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field label="Period (YYYY-MM)">
          <input className={`${input} w-28`} value={period} placeholder="2026-04" onChange={(e) => setPeriod(e.target.value.trim())} />
        </Field>
        {d?.rule_status && <RuleBadge status={d.rule_status} />}
      </div>
      <ErrorBox error={list.error} />
      {d && (
        <table className="border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Totals</th>
              {headCols.map((h) => (
                <th key={h} className={thR}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {STATUSES.map((s) => (
              <tr key={s}>
                <td className={td}>
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_CLS[s]}`}>{s}</span>
                </td>
                {d.totals[s] ? <HeadCells h={d.totals[s]} /> : <td colSpan={4} className={td} />}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse bg-white">
          <thead>
            <tr>
              {['Voucher', 'Supplier', 'GSTIN', 'Bill no', 'Bill date', 'Src', 'Status', 'Reason', '2B', 'Deadline', ...headCols].map((h, i) => (
                <th key={h} className={i >= 10 ? thR : th}>
                  {h}
                </th>
              ))}
              <th className={th} />
            </tr>
          </thead>
          <tbody>
            {(d?.entries ?? []).map((e) => (
              <tr key={e.id} className={open?.id === e.id ? 'bg-blue-50' : ''}>
                <td className={td}>
                  {e.voucher_number ?? '(draft)'}
                  {e.item_line_no ? `/${e.item_line_no}` : ''}
                </td>
                <td className={td}>{e.supplier_name}</td>
                <td className={`${td} font-mono text-xs`}>{e.supplier_gstin ?? ''}</td>
                <td className={td}>{e.supplier_invoice_no}</td>
                <td className={td}>{e.supplier_invoice_date}</td>
                <td className={td}>{e.source}</td>
                <td className={td}>
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_CLS[e.status]}`}>{e.status}</span>
                </td>
                <td className={td}>{e.pending_reason ?? e.blocked_category_key ?? ''}</td>
                <td className={td}>{e.supplier_tax_paid}</td>
                <td className={td}>{e.claim_deadline ?? ''}</td>
                <HeadCells h={e} />
                <td className={td}>
                  <button className={btn} onClick={() => setOpen(open?.id === e.id ? null : e)}>
                    Details
                  </button>
                </td>
              </tr>
            ))}
            {d?.entries.length === 0 && (
              <tr>
                <td className={td} colSpan={15}>
                  No ITC entries for these filters. Entries appear when a purchase invoice is posted.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {open && (
        <EntryPanel
          key={open.id}
          clientId={clientId}
          entry={open}
          act={act}
          busy={busy}
          setNotice={setNotice}
          onChanged={(e) => {
            setOpen(e)
            list.reload()
          }}
        />
      )}
    </div>
  )
}

function EntryPanel({ clientId, entry, act, busy, setNotice, onChanged }: Common & { entry: ItcEntry; onChanged: (e: ItcEntry) => void }) {
  const [held, setHeld] = useState(entry.tax_document_held)
  const [recv, setRecv] = useState(entry.goods_services_received)
  const [recvDate, setRecvDate] = useState(entry.received_date ?? '')
  const [paid, setPaid] = useState<SupplierTaxPaid>(entry.supplier_tax_paid)
  const [note, setNote] = useState(entry.evidence_note ?? '')
  const [reason, setReason] = useState('')
  const [cat, setCat] = useState('')
  const [blockNote, setBlockNote] = useState('')
  const events = useLoad(() => gstApi.itcEvents(clientId, entry.id), `itc-events:${entry.id}:${entry.status}:${entry.supplier_tax_paid}`)
  return (
    <div className="grid gap-3 rounded border border-slate-300 bg-white p-3 lg:grid-cols-3">
      <div className="space-y-2">
        <h2 className="text-sm font-semibold">Evidence (Section 16(2))</h2>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={held} onChange={(e) => setHeld(e.target.checked)} /> Tax invoice / debit note held
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={recv} onChange={(e) => setRecv(e.target.checked)} /> Goods / services received
        </label>
        <Field label="Received on">
          <input type="date" className={input} value={recvDate} onChange={(e) => setRecvDate(e.target.value)} />
        </Field>
        <Field label="Supplier has paid the tax">
          <select className={input} value={paid} onChange={(e) => setPaid(e.target.value as SupplierTaxPaid)}>
            <option value="unknown">Unknown</option>
            <option value="in_2b">In GSTR-2B</option>
            <option value="not_in_2b">Not in GSTR-2B</option>
            <option value="manual_confirmed">Manually confirmed</option>
          </select>
        </Field>
        <Field label="Evidence note">
          <input className={input} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <button
          className={btnPrimary}
          disabled={busy}
          onClick={() =>
            act(async () => {
              const e = await gstApi.itcEvidence(clientId, entry.id, { tax_document_held: held, goods_services_received: recv, received_date: recvDate || null, supplier_tax_paid: paid, evidence_note: note })
              setNotice('Evidence saved; the entry was re-classified by the server.')
              onChanged(e)
            })
          }
        >
          Save evidence
        </button>
      </div>
      <div className="space-y-2">
        <h2 className="text-sm font-semibold">Manual confirmation (supplier not in 2B)</h2>
        <Field label="Reason (required, recorded)">
          <input className={input} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <button
          className={btn}
          disabled={busy || !reason.trim() || entry.status === 'eligible'}
          onClick={() =>
            act(async () => {
              onChanged(await gstApi.itcConfirm(clientId, entry.id, reason.trim()))
              setNotice('Confirmed manually.')
            })
          }
        >
          Confirm
        </button>
        <h2 className="pt-2 text-sm font-semibold">Tag as blocked credit (identified late)</h2>
        <Field label="Category key (see Rules / Blocked credit)">
          <input className={input} value={cat} onChange={(e) => setCat(e.target.value)} />
        </Field>
        <Field label="Note">
          <input className={input} value={blockNote} onChange={(e) => setBlockNote(e.target.value)} />
        </Field>
        <button
          className={btn}
          disabled={busy || !cat.trim() || !blockNote.trim()}
          onClick={() =>
            act(async () => {
              if (!window.confirm('Tag this credit as blocked? A reversal proposal is created.')) return
              onChanged(await gstApi.itcTagBlocked(clientId, entry.id, cat.trim(), blockNote.trim()))
              setNotice('Tagged as blocked.')
            })
          }
        >
          Tag blocked
        </button>
      </div>
      <div>
        <h2 className="text-sm font-semibold">History</h2>
        <ErrorBox error={events.error} />
        <ul className="space-y-1 text-xs">
          {(events.data ?? []).map((e, i) => (
            <li key={i} className="border-b border-slate-200 pb-1">
              {e.created_at.slice(0, 16).replace('T', ' ')} {e.actor}: {e.from_status ?? 'new'} to <b>{e.to_status}</b>
              <div className="text-slate-600">{e.reason}</div>
            </li>
          ))}
          {events.data?.length === 0 && <li className="text-slate-500">No events.</li>}
        </ul>
      </div>
    </div>
  )
}

function ExposureTable({ rows, selected, toggle }: { rows: ExposureItem[]; selected?: string[]; toggle?: (id: string) => void }) {
  return (
    <table className="min-w-full border-collapse bg-white">
      <thead>
        <tr>
          {toggle && <th className={th} />}
          {['Voucher', 'Supplier', 'Bill no', 'Bill date', 'Days', 'Due on day'].map((h) => (
            <th key={h} className={th}>
              {h}
            </th>
          ))}
          <th className={thR}>Outstanding</th>
          {headCols.map((h) => (
            <th key={h} className={thR}>
              {h}
            </th>
          ))}
          <th className={th}>Reversed</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.itc_entry_id}>
            {toggle && (
              <td className={td}>
                <input type="checkbox" disabled={r.already_reversed} checked={selected?.includes(r.itc_entry_id) ?? false} onChange={() => toggle(r.itc_entry_id)} />
              </td>
            )}
            <td className={td}>{r.voucher_number ?? ''}</td>
            <td className={td}>{r.supplier_name}</td>
            <td className={td}>{r.supplier_invoice_no}</td>
            <td className={td}>{r.invoice_date}</td>
            <td className={td}>{r.days}</td>
            <td className={td}>{r.due_on_day}</td>
            <td className={tdR}>
              <Amount value={r.outstanding} />
            </td>
            <HeadCells h={r} />
            <td className={td}>{r.already_reversed ? 'Yes' : ''}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td className={td} colSpan={13}>
              None.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}

function Exposure({ clientId, regId, asOn, act, busy, setNotice }: Common & { regId: string; asOn: string }) {
  const data = useLoad(regId ? () => gstApi.exposure180(clientId, regId, asOn) : null, `exposure:${clientId}:${regId}:${asOn}`)
  const [sel, setSel] = useState<string[]>([])
  const d = data.data
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-600">Credit on bills not paid within the legal period must be reversed (and may be reclaimed when paid). The server counts the days; nothing is posted until you approve the drafts.</p>
      <ErrorBox error={data.error} />
      {d?.rule_status && <RuleBadge status={d.rule_status} />}
      <h2 className="text-sm font-semibold">Due now</h2>
      <ExposureTable rows={d?.items ?? []} selected={sel} toggle={(id) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))} />
      {d && (
        <div className="text-sm">
          Total due: {headCols.map((h, i) => `${h} ${d.total[HEADS[i]]}`).join(', ')}
        </div>
      )}
      <div className="flex gap-2">
        <button
          className={btnPrimary}
          disabled={busy || !d || d.items.length === 0}
          onClick={() =>
            act(async () => {
              const out = await gstApi.createReversals(clientId, regId, asOn, sel.length ? sel : undefined)
              setNotice(`${out.created.length} draft reversal journal(s) created. Review and approve them under Vouchers.`)
              setSel([])
              data.reload()
            })
          }
        >
          Create reversal drafts {sel.length ? `(${sel.length} selected)` : '(all due)'}
        </button>
      </div>
      <h2 className="text-sm font-semibold">Approaching (within 30 days)</h2>
      <ExposureTable rows={d?.approaching ?? []} />
    </div>
  )
}

function Reversals({ clientId, asOn, act, busy, setNotice }: Common & { asOn: string }) {
  const list = useLoad(() => gstApi.listReversals(clientId), `itc-reversals:${clientId}`)
  return (
    <div className="space-y-2">
      <ErrorBox error={list.error} />
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            {['As on', 'Reason', 'Status', 'Reversal voucher', 'Reclaim voucher', ...headCols].map((h, i) => (
              <th key={h} className={i >= 5 ? thR : th}>
                {h}
              </th>
            ))}
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((r) => (
            <tr key={r.id}>
              <td className={td}>{r.as_on_date}</td>
              <td className={td}>{r.reason}</td>
              <td className={td}>{r.status}</td>
              <td className={`${td} font-mono text-xs`}>{r.reversal_voucher_id?.slice(0, 8) ?? ''}</td>
              <td className={`${td} font-mono text-xs`}>{r.reclaim_voucher_id?.slice(0, 8) ?? ''}</td>
              {r.amounts ? <HeadCells h={r.amounts} /> : <td colSpan={4} className={td} />}
              <td className={td}>
                <button
                  className={btn}
                  disabled={busy || !!r.reclaim_voucher_id}
                  onClick={() =>
                    act(async () => {
                      await gstApi.reclaim(clientId, r.id, asOn)
                      setNotice('Reclaim draft journal created for the share paid since.')
                      list.reload()
                    })
                  }
                >
                  Reclaim (as on date)
                </button>
              </td>
            </tr>
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={10}>
                No reversals yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function Tie({ clientId, regId, asOn }: { clientId: string; regId: string; asOn: string }) {
  const data = useLoad(regId ? () => gstApi.registerTie(clientId, regId, asOn) : null, `itc-tie:${clientId}:${regId}:${asOn}`)
  const d = data.data
  return (
    <div className="space-y-2">
      <ErrorBox error={data.error} />
      {d && (
        <>
          <div className={`rounded border px-3 py-1 text-sm ${d.ties ? 'border-green-400 bg-green-50 text-green-900' : 'border-red-400 bg-red-50 text-red-900'}`}>
            {d.ties ? 'Input tax ledgers agree with the ITC register.' : 'Input tax ledgers and the ITC register differ. The difference is shown, not adjusted.'}
          </div>
          <DataView name="input_ledgers" value={Object.fromEntries(Object.entries(d.input_ledgers).map(([k, b]) => [k, b.side ? `${b.amount} ${b.side}` : b.amount]))} />
          <DataView name="itc_register" value={d.itc_register} />
          <DataView name="difference" value={d.difference} />
          {d.notes.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-slate-700">
              {d.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
