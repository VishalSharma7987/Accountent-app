import { useState } from 'react'
import { tdsApi, type AllocIn, type ChallanBody, type ChallanKind, type ChallanRow, type MatchRow } from '../api/tds'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { DataView, FySelect, NoClient, QuarterSelect, Row, RuleBadge, Tabs, useFy } from './common'
import { dueClass, mergeProposal, shortRows } from './lib'

type Tab = 'challans' | 'matching' | 'interest' | 'calendar'

/** Challan entry and allocation, matching with auto-proposal, interest working, due-date calendar. */
export default function Challans() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const [tab, setTab] = useState<Tab>('challans')
  const [quarter, setQuarter] = useState<number | ''>(1)
  const [kind, setKind] = useState<ChallanKind>('tds')
  if (!clientId) return <Page title="Challans"><NoClient /></Page>
  return (
    <Page title="TDS challans, interest and due dates">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        {tab !== 'calendar' && tab !== 'interest' && <QuarterSelect value={quarter} onChange={setQuarter} allowAll />}
        {tab !== 'calendar' && tab !== 'interest' && (
          <Field label="Kind">
            <select className={input} value={kind} onChange={(e) => setKind(e.target.value as ChallanKind)}>
              <option value="tds">TDS</option>
              <option value="tcs">TCS</option>
            </select>
          </Field>
        )}
      </Row>
      <Tabs
        tabs={[
          { key: 'challans', label: 'Challans' },
          { key: 'matching', label: 'Matching' },
          { key: 'interest', label: 'Interest' },
          { key: 'calendar', label: 'Due calendar' },
        ]}
        value={tab}
        onChange={setTab}
      />
      {!fyId ? (
        <div className="text-sm text-slate-600">This client has no financial year.</div>
      ) : (
        <>
          {tab === 'challans' && <ChallanTab clientId={clientId} fyId={fyId} quarter={quarter} kind={kind} />}
          {tab === 'matching' && <MatchingTab clientId={clientId} fyId={fyId} quarter={quarter} kind={kind} />}
          {tab === 'interest' && <InterestTab clientId={clientId} fyId={fyId} />}
          {tab === 'calendar' && <CalendarTab clientId={clientId} fyId={fyId} />}
        </>
      )}
    </Page>
  )
}

const blankChallan = (fy: string, quarter: number | '', kind: ChallanKind): ChallanBody => ({
  kind,
  financial_year_id: fy,
  quarter: quarter === '' ? 1 : quarter,
  bsr_code: '',
  deposit_date: today(),
  challan_serial_no: '',
  tax_amount: '',
  interest_amount: '',
  fee_amount: '',
  other_amount: '',
})

function ChallanTab({ clientId, fyId, quarter, kind }: { clientId: string; fyId: string; quarter: number | ''; kind: ChallanKind }) {
  const list = useLoad(() => tdsApi.listChallans(clientId, { financial_year_id: fyId, quarter, kind }), `tds-ch:${clientId}:${fyId}:${quarter}:${kind}`)
  const [form, setForm] = useState<ChallanBody>(blankChallan(fyId, quarter, kind))
  const [error, setError] = useState<ApiFailure | null>(null)
  const [open, setOpen] = useState('')
  const f: ChallanBody = { ...form, kind, financial_year_id: fyId, quarter: quarter === '' ? form.quarter : quarter }
  const text = (k: 'bsr_code' | 'challan_serial_no' | 'tax_amount' | 'interest_amount' | 'fee_amount' | 'other_amount', label: string, w: string) => (
    <Field label={label}>
      <input className={`${input} ${w} ${k.endsWith('amount') ? 'text-right' : ''}`} value={f[k] ?? ''} onChange={(e) => setForm({ ...f, [k]: e.target.value.replace(/[,\s]/g, '') })} />
    </Field>
  )
  const save = async () => {
    setError(null)
    try {
      const clean = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== '')) as unknown as ChallanBody
      await tdsApi.createChallan(clientId, clean)
      setForm(blankChallan(fyId, quarter, kind))
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
        <div className="text-sm font-semibold">New challan</div>
        <Row>
          {text('bsr_code', 'BSR code (7 digits)', 'w-24')}
          <Field label="Deposit date">
            <input type="date" className={input} value={f.deposit_date} onChange={(e) => setForm({ ...f, deposit_date: e.target.value })} />
          </Field>
          {text('challan_serial_no', 'Serial no', 'w-24')}
          {quarter === '' && <QuarterSelect value={f.quarter} onChange={(q) => setForm({ ...f, quarter: q === '' ? 1 : q })} />}
          {text('tax_amount', 'Tax', 'w-28')}
          {text('interest_amount', 'Interest', 'w-24')}
          {text('fee_amount', 'Fee', 'w-24')}
          {text('other_amount', 'Other', 'w-24')}
          <button className={btnPrimary} onClick={save}>
            Save challan
          </button>
        </Row>
        <ErrorBox error={error} />
      </div>
      <ErrorBox error={list.error} />
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Deposit date</th>
            <th className={th}>BSR</th>
            <th className={th}>Serial</th>
            <th className={thR}>Tax</th>
            <th className={thR}>Interest</th>
            <th className={thR}>Fee</th>
            <th className={thR}>Total</th>
            <th className={thR}>Allocated</th>
            <th className={thR}>Unallocated</th>
            <th className={th}>Status</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((c) => (
            <ChallanLine key={c.id} c={c} open={open === c.id} toggle={() => setOpen(open === c.id ? '' : c.id)} clientId={clientId} fyId={fyId} quarter={quarter} kind={kind} onChanged={list.reload} />
          ))}
          {list.data?.length === 0 && (
            <tr>
              <td colSpan={11} className={`${td} text-slate-500`}>
                No challans for this selection.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function ChallanLine({ c, open, toggle, clientId, fyId, quarter, kind, onChanged }: { c: ChallanRow; open: boolean; toggle: () => void; clientId: string; fyId: string; quarter: number | ''; kind: ChallanKind; onChanged: () => void }) {
  return (
    <>
      <tr className={c.status === 'locked' ? 'bg-slate-100' : ''}>
        <td className={td}>{c.deposit_date}</td>
        <td className={`${td} font-mono`}>{c.bsr_code}</td>
        <td className={td}>{c.challan_serial_no}</td>
        <td className={tdR}><Amount value={c.tax_amount} /></td>
        <td className={tdR}><Amount value={c.interest_amount} /></td>
        <td className={tdR}><Amount value={c.fee_amount} /></td>
        <td className={tdR}><Amount value={c.total_amount} /></td>
        <td className={tdR}><Amount value={c.allocated} /></td>
        <td className={tdR}><Amount value={c.unallocated} /></td>
        <td className={td}>{c.status}</td>
        <td className={td}>
          <button className={btn} onClick={toggle}>
            Allocate
          </button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={11} className="bg-slate-50 p-2">
            <Allocator clientId={clientId} challanId={c.id} locked={c.status === 'locked'} fyId={fyId} quarter={quarter} kind={kind} onChanged={onChanged} />
          </td>
        </tr>
      )}
    </>
  )
}

function Allocator({ clientId, challanId, locked, fyId, quarter, kind, onChanged }: { clientId: string; challanId: string; locked: boolean; fyId: string; quarter: number | ''; kind: ChallanKind; onChanged: () => void }) {
  const one = useLoad(() => tdsApi.getChallan(clientId, challanId), `tds-ch1:${challanId}`)
  const matching = useLoad(() => tdsApi.matching(clientId, { financial_year_id: fyId, quarter, kind }), `tds-match:${clientId}:${fyId}:${quarter}:${kind}`)
  const [edit, setEdit] = useState<AllocIn[] | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const current: AllocIn[] = edit ?? (one.data?.allocations ?? []).map((a) => ({ item_id: a.item_id, amount: a.amount }))
  const items = matching.data?.rows ?? []
  const label = (id: string) => {
    const r = items.find((m) => m.item_id === id)
    return r ? `${r.deductee_name} ${r.section_ref} (balance ${r.balance})` : id
  }
  const save = async () => {
    setError(null)
    try {
      await tdsApi.putAllocations(clientId, challanId, current)
      setEdit(null)
      one.reload()
      matching.reload()
      onChanged()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold">Tax of this challan applied to deductions (replaces the list on save){locked ? ' - locked by a final return working' : ''}</div>
      {current.map((a, i) => (
        <Row key={i}>
          <select className={`${input} w-96`} disabled={locked} value={a.item_id} onChange={(e) => setEdit(current.map((x, k) => (k === i ? { ...x, item_id: e.target.value } : x)))}>
            <option value="">(choose deduction)</option>
            {items.map((m) => (
              <option key={m.item_id} value={m.item_id}>
                {label(m.item_id)}
              </option>
            ))}
            {!items.some((m) => m.item_id === a.item_id) && a.item_id && <option value={a.item_id}>{a.item_id}</option>}
          </select>
          <input className={`${input} w-28 text-right`} disabled={locked} value={a.amount} onChange={(e) => setEdit(current.map((x, k) => (k === i ? { ...x, amount: e.target.value.replace(/[,\s]/g, '') } : x)))} />
          {!locked && (
            <button className={btn} onClick={() => setEdit(current.filter((_, k) => k !== i))}>
              Remove
            </button>
          )}
        </Row>
      ))}
      {!locked && (
        <Row>
          <button className={btn} onClick={() => setEdit([...current, { item_id: '', amount: '' }])}>
            Add line
          </button>
          <button className={btnPrimary} disabled={edit === null} onClick={save}>
            Save allocations
          </button>
        </Row>
      )}
      <ErrorBox error={error ?? one.error} />
    </div>
  )
}

function MatchingTab({ clientId, fyId, quarter, kind }: { clientId: string; fyId: string; quarter: number | ''; kind: ChallanKind }) {
  const m = useLoad(() => tdsApi.matching(clientId, { financial_year_id: fyId, quarter, kind }), `tds-match:${clientId}:${fyId}:${quarter}:${kind}`)
  const [proposal, setProposal] = useState<{ item_id: string; challan_id: string; amount: string }[] | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const rows = m.data?.rows ?? []
  const name = (id: string) => rows.find((r) => r.item_id === id)?.deductee_name ?? id

  const propose = async () => {
    setError(null)
    setNotice('')
    if (quarter === '') {
      setError(asFailure(new Error('Choose one quarter to propose an allocation.')))
      return
    }
    try {
      setProposal((await tdsApi.autoMatch(clientId, { financial_year_id: fyId, quarter, kind })).proposed)
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const apply = async () => {
    if (!proposal) return
    setError(null)
    try {
      for (const id of [...new Set(proposal.map((p) => p.challan_id))]) {
        const existing = (await tdsApi.getChallan(clientId, id)).allocations ?? []
        await tdsApi.putAllocations(clientId, id, mergeProposal(proposal, id, existing))
      }
      setProposal(null)
      setNotice('Allocations saved.')
      m.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const mRow = (r: MatchRow) => (
    <tr key={r.item_id} className={r.days_late && r.days_late > 0 ? 'bg-red-50' : ''}>
      <td className={td}>{r.deductee_name}</td>
      <td className={td}>{r.section_ref}</td>
      <td className={tdR}><Amount value={r.tds_amount} /></td>
      <td className={tdR}><Amount value={r.allocated} /></td>
      <td className={tdR}><Amount value={r.balance} /></td>
      <td className={td}>{r.due_date}</td>
      <td className={td}>{r.deposited_on ?? '-'}</td>
      <td className={tdR}>{r.days_late ?? ''}</td>
      <td className={tdR}><Amount value={r.interest_late_deposit} /></td>
    </tr>
  )
  return (
    <div className="space-y-3">
      <Row>
        <button className={btn} onClick={propose}>
          Propose allocation
        </button>
        {proposal && (
          <button className={btnPrimary} disabled={proposal.length === 0} onClick={apply}>
            Accept proposal ({proposal.length})
          </button>
        )}
        <span className="text-xs text-slate-600">Rule: same quarter, oldest deduction first, never more than the tax. Nothing is saved until you accept.</span>
      </Row>
      <ErrorBox error={error ?? m.error} />
      {notice && <Notice>{notice}</Notice>}
      {proposal && (
        <table className="border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Deduction</th>
              <th className={th}>Challan</th>
              <th className={thR}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {proposal.map((p, i) => (
              <tr key={i}>
                <td className={td}>{name(p.item_id)}</td>
                <td className={td}>{(m.data?.unallocated_challans ?? []).find((c) => c.id === p.challan_id)?.challan_serial_no ?? p.challan_id}</td>
                <td className={tdR}><Amount value={p.amount} /></td>
              </tr>
            ))}
            {proposal.length === 0 && (
              <tr>
                <td colSpan={3} className={`${td} text-slate-500`}>
                  Nothing to propose.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Deductee</th>
            <th className={th}>Section</th>
            <th className={thR}>TDS</th>
            <th className={thR}>Allocated</th>
            <th className={thR}>Balance</th>
            <th className={th}>Due</th>
            <th className={th}>Deposited on</th>
            <th className={thR}>Days late</th>
            <th className={thR}>Interest (late deposit)</th>
          </tr>
        </thead>
        <tbody>{rows.map(mRow)}</tbody>
      </table>
      <div className="text-xs text-slate-600">{shortRows(rows).length} deduction(s) not fully deposited.</div>
      {(m.data?.unallocated_challans ?? []).length > 0 && <DataView name="Challans with unallocated tax" value={m.data?.unallocated_challans} />}
      {m.data && <DataView name="Totals" value={m.data.totals} />}
    </div>
  )
}

function InterestTab({ clientId, fyId }: { clientId: string; fyId: string }) {
  const [asOn, setAsOn] = useState(today())
  const data = useLoad(() => tdsApi.interest(clientId, { financial_year_id: fyId, as_on: asOn }), `tds-int:${clientId}:${fyId}:${asOn}`)
  return (
    <div className="space-y-2">
      <Row>
        <Field label="Undeposited tax counted up to">
          <input type="date" className={input} value={asOn} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        {data.data?.rows[0]?.rule_status && <RuleBadge status={data.data.rows[0].rule_status} />}
      </Row>
      <p className="text-xs text-slate-600">Interest is a working shown for the accountant; it is not posted to the books. Part of a month counts as a full month.</p>
      <ErrorBox error={data.error} />
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Deductee</th>
            <th className={thR}>TDS</th>
            <th className={th}>Deductible on</th>
            <th className={th}>Deducted on</th>
            <th className={thR}>Months late</th>
            <th className={thR}>Interest (late deduction)</th>
            <th className={th}>Due</th>
            <th className={th}>Deposited on</th>
            <th className={thR}>Months late</th>
            <th className={thR}>Interest (late deposit)</th>
          </tr>
        </thead>
        <tbody>
          {(data.data?.rows ?? []).map((r) => (
            <tr key={r.item_id}>
              <td className={td}>{r.deductee_name}</td>
              <td className={tdR}><Amount value={r.tds_amount} /></td>
              <td className={td}>{r.deductible_on}</td>
              <td className={td}>{r.deducted_on}</td>
              <td className={tdR}>{r.months_late_deduction}</td>
              <td className={tdR}><Amount value={r.interest_late_deduction} /></td>
              <td className={td}>{r.due_date}</td>
              <td className={td}>{r.deposited_on ?? 'not deposited'}</td>
              <td className={tdR}>{r.months_late_deposit}</td>
              <td className={tdR}><Amount value={r.interest_late_deposit} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.data && <DataView name="Totals" value={data.data.totals} />}
    </div>
  )
}

function CalendarTab({ clientId, fyId }: { clientId: string; fyId: string }) {
  const data = useLoad(() => tdsApi.dueCalendar(clientId, fyId), `tds-cal:${clientId}:${fyId}`)
  return (
    <div className="space-y-2">
      <ErrorBox error={data.error} />
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Due date</th>
            <th className={th}>Event</th>
            <th className={th}>Kind</th>
            <th className={th}>Quarter</th>
            <th className={th}>Period</th>
            <th className={th}>Status</th>
            <th className={thR}>Amount due</th>
          </tr>
        </thead>
        <tbody>
          {(data.data ?? []).map((e, i) => (
            <tr key={i}>
              <td className={td}>{e.due_date}</td>
              <td className={td}>{e.event}</td>
              <td className={td}>{e.kind}</td>
              <td className={td}>{e.quarter ? `Q${e.quarter}` : ''}</td>
              <td className={td}>{e.period}</td>
              <td className={td}>
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${dueClass(e.status)}`}>{e.status}</span>
              </td>
              <td className={tdR}>{e.amount_due ? <Amount value={e.amount_due} /> : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
