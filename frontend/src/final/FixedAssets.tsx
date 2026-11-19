import { useState } from 'react'
import { downloadFile, finalApi, type Asset, type AssetBody, type DepPreview, type EventKind, type ItWorking } from '../api/final'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { cleanTyped, toPaise } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, Findings, LedgerSelect, NoClient, PendingBadge, Problems, Row, RuleStatusPanel, Section, Tabs, VoucherLink, useFy, useLedgers } from './common'
import { EVENT_KINDS } from './lib'

type Tab = 'assets' | 'register' | 'book' | 'it'

/** Fixed asset register, events, the Companies Act book depreciation run and the income-tax block working (a working only). */
export default function FixedAssets() {
  const { clientId } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const [tab, setTab] = useState<Tab>('assets')
  if (!clientId)
    return (
      <Page title="Fixed assets and depreciation">
        <NoClient />
      </Page>
    )
  return (
    <Page title="Fixed assets and depreciation">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
      </Row>
      <Tabs
        tabs={[
          { key: 'assets', label: 'Assets and events' },
          { key: 'register', label: 'Register' },
          { key: 'book', label: 'Book depreciation (Companies Act)' },
          { key: 'it', label: 'Income-tax block working' },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'assets' && <AssetsTab clientId={clientId} asOn={fy?.end_date} />}
      {tab === 'register' && <RegisterTab clientId={clientId} fyId={fyId} />}
      {tab === 'book' && <BookTab clientId={clientId} fyId={fyId} />}
      {tab === 'it' && <ItTab clientId={clientId} fyId={fyId} />}
    </Page>
  )
}

const EMPTY_ASSET = { asset_no: '', name: '', asset_ledger_id: '', accumulated_dep_ledger_id: '', is_depreciable: true, it_block_key: '', sched2_class_key: '', useful_life_years: '', life_override_reason: '', residual_value: '', book_method: 'wdv' }

function AssetsTab({ clientId, asOn }: { clientId: string; asOn?: string }) {
  const { ledgers } = useLedgers()
  const [f, setF] = useState(EMPTY_ASSET)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [notice, setNotice] = useState('')
  const assets = useLoad(() => finalApi.listAssets(clientId), `final-assets:${clientId}`)
  const rules = useLoad(() => finalApi.assetRules(clientId, asOn), `final-asset-rules:${clientId}:${asOn ?? ''}`)
  const set = (patch: Partial<typeof EMPTY_ASSET>) => setF({ ...f, ...patch })
  const save = async () => {
    setError(null)
    setNotice('')
    const p: string[] = []
    if (!f.asset_no.trim() || !f.name.trim()) p.push('Enter the asset number and name.')
    if (!f.asset_ledger_id) p.push('Choose the asset ledger (Fixed Assets group).')
    const residual = cleanTyped(f.residual_value)
    if (residual !== '' && toPaise(residual) === null) p.push('Residual value must have at most 2 decimals.')
    setProblems(p)
    if (p.length > 0) return
    const body: AssetBody = {
      asset_no: f.asset_no.trim(),
      name: f.name.trim(),
      asset_ledger_id: f.asset_ledger_id,
      accumulated_dep_ledger_id: f.accumulated_dep_ledger_id || null,
      is_depreciable: f.is_depreciable,
      it_block_key: f.it_block_key || null,
      sched2_class_key: f.sched2_class_key || null,
      useful_life_years: f.useful_life_years.trim() || null,
      life_override_reason: f.life_override_reason.trim() || null,
      residual_value: residual || null,
      book_method: f.book_method || null,
    }
    try {
      await finalApi.addAsset(clientId, body)
      setNotice('Asset added. Now add its opening / purchase events.')
      setF(EMPTY_ASSET)
      assets.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-3">
      <ErrorBox error={error ?? assets.error ?? rules.error} />
      {notice && <Notice>{notice}</Notice>}
      <Section title="Add an asset">
        <Row>
          <Field label="Asset no">
            <input className={`${input} w-28`} value={f.asset_no} onChange={(e) => set({ asset_no: e.target.value })} />
          </Field>
          <Field label="Name">
            <input className={`${input} w-56`} value={f.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="Asset ledger">
            <LedgerSelect ledgers={ledgers} value={f.asset_ledger_id} onChange={(id) => set({ asset_ledger_id: id })} groups={['fixed_assets']} className="w-60" />
          </Field>
          <Field label="Accumulated depreciation ledger">
            <LedgerSelect ledgers={ledgers} value={f.accumulated_dep_ledger_id} onChange={(id) => set({ accumulated_dep_ledger_id: id })} className="w-60" blank="(role ledger)" />
          </Field>
          <label className="flex items-center gap-1 pb-1 text-sm">
            <input type="checkbox" checked={f.is_depreciable} onChange={(e) => set({ is_depreciable: e.target.checked })} /> Depreciable
          </label>
        </Row>
        {f.is_depreciable && (
          <Row>
            <Field label="Income-tax block">
              <select className={input} value={f.it_block_key} onChange={(e) => set({ it_block_key: e.target.value })}>
                <option value="">(choose)</option>
                {(rules.data?.it_blocks ?? []).map((b) => (
                  <option key={b.block_key} value={b.block_key}>
                    {b.description} {b.rate}% [{b.verification_status}]
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Schedule II class">
              <select className={input} value={f.sched2_class_key} onChange={(e) => set({ sched2_class_key: e.target.value })}>
                <option value="">(choose)</option>
                {(rules.data?.sched2_classes ?? []).map((c) => (
                  <option key={c.class_key} value={c.class_key}>
                    {c.description} {c.useful_life_years} yrs [{c.verification_status}]
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Useful life years (blank = class life)">
              <input className={`${input} w-24 text-right`} value={f.useful_life_years} onChange={(e) => set({ useful_life_years: e.target.value })} />
            </Field>
            <Field label="Reason if life differs from the class">
              <input className={`${input} w-56`} value={f.life_override_reason} onChange={(e) => set({ life_override_reason: e.target.value })} />
            </Field>
            <Field label="Residual value">
              <input className={`${input} w-28 text-right`} value={f.residual_value} onChange={(e) => set({ residual_value: e.target.value })} />
            </Field>
            <Field label="Book method">
              <select className={input} value={f.book_method} onChange={(e) => set({ book_method: e.target.value })}>
                <option value="wdv">Written down value</option>
                <option value="slm">Straight line</option>
              </select>
            </Field>
          </Row>
        )}
        <Problems items={problems} />
        <button className={btnPrimary} onClick={save}>
          Add asset
        </button>
        {rules.data && (
          <div className="text-xs text-slate-600">
            Half-rate rule: assets put to use for fewer than {rules.data.half_rate_days} days get {rules.data.half_rate_percent}% of the rate (law rows in force, status shown against each choice above).
          </div>
        )}
      </Section>
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>No</th>
            <th className={th}>Asset</th>
            <th className={th}>IT block</th>
            <th className={th}>Sch II class</th>
            <th className={thR}>Life (yrs)</th>
            <th className={thR}>Cost</th>
            <th className={thR}>Additions</th>
            <th className={th}>Status</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(assets.data ?? []).map((a) => (
            <tr key={a.id} className={a.is_active ? '' : 'text-slate-400'}>
              <td className={td}>{a.asset_no}</td>
              <td className={td}>{a.name}</td>
              <td className={td}>{a.it_block_key}</td>
              <td className={td}>{a.sched2_class_key}</td>
              <td className={tdR}>{a.useful_life_years}</td>
              <td className={tdR}>
                <Amount value={a.cost} />
              </td>
              <td className={tdR}>
                <Amount value={a.additions} />
              </td>
              <td className={td}>{a.disposed ? 'Disposed' : a.is_active ? 'In use' : 'Inactive'}</td>
              <td className={td}>
                <button className={btn} onClick={() => setSelected(selected === a.id ? '' : a.id)}>
                  {selected === a.id ? 'Hide events' : 'Events'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <Events clientId={clientId} asset={(assets.data ?? []).find((a) => a.id === selected)} onChange={assets.reload} />}
    </div>
  )
}

function Events({ clientId, asset, onChange }: { clientId: string; asset?: Asset; onChange: () => void }) {
  const [kind, setKind] = useState<EventKind>('opening')
  const [date, setDate] = useState('')
  const [use, setUse] = useState('')
  const [amount, setAmount] = useState('')
  const [accBf, setAccBf] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const events = useLoad(asset ? () => finalApi.listEvents(clientId, asset.id) : null, `final-events:${asset?.id}`)
  if (!asset) return null
  const add = async () => {
    setError(null)
    const p: string[] = []
    if (!date) p.push('Enter the event date.')
    const a = cleanTyped(amount)
    if (toPaise(a) === null || a === '') p.push('Enter the amount with at most 2 decimals.')
    const b = cleanTyped(accBf)
    if (b !== '' && toPaise(b) === null) p.push('Accumulated depreciation b/f must have at most 2 decimals.')
    setProblems(p)
    if (p.length > 0) return
    try {
      await finalApi.addEvent(clientId, asset.id, { kind, event_date: date, put_to_use_date: use || null, amount: a, accumulated_dep_bf: kind === 'opening' && b ? b : null, note: note.trim() || null })
      setAmount('')
      setAccBf('')
      events.reload()
      onChange()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const remove = async (id: string) => {
    setError(null)
    try {
      await finalApi.deleteEvent(clientId, asset.id, id)
      events.reload()
      onChange()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Section title={`Events of ${asset.asset_no} ${asset.name}`}>
      <ErrorBox error={error ?? events.error} />
      <Problems items={problems} />
      <Row>
        <Field label="Kind">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value as EventKind)}>
            {EVENT_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Date">
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        {kind !== 'disposal' && (
          <Field label="Put to use date">
            <input type="date" className={input} value={use} onChange={(e) => setUse(e.target.value)} />
          </Field>
        )}
        <Field label={kind === 'disposal' ? 'Sale proceeds' : 'Cost'}>
          <input className={`${input} w-28 text-right`} value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        {kind === 'opening' && (
          <Field label="Accumulated depreciation b/f">
            <input className={`${input} w-28 text-right`} value={accBf} onChange={(e) => setAccBf(e.target.value)} />
          </Field>
        )}
        <Field label="Note">
          <input className={`${input} w-48`} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <button className={btnPrimary} onClick={add}>
          Add event
        </button>
      </Row>
      <table className="border-collapse">
        <thead>
          <tr>
            <th className={th}>Kind</th>
            <th className={th}>Date</th>
            <th className={th}>Put to use</th>
            <th className={thR}>Amount</th>
            <th className={thR}>Acc. dep. b/f</th>
            <th className={th}>Note</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(events.data ?? []).map((e) => (
            <tr key={e.id}>
              <td className={td}>{e.kind}</td>
              <td className={td}>{e.event_date}</td>
              <td className={td}>{e.put_to_use_date}</td>
              <td className={tdR}>
                <Amount value={String(e.amount)} />
              </td>
              <td className={tdR}>{e.accumulated_dep_bf != null && <Amount value={String(e.accumulated_dep_bf)} />}</td>
              <td className={td}>{e.note}</td>
              <td className={td}>
                <button className={btnDanger} onClick={() => remove(e.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  )
}

function RegisterTab({ clientId, fyId }: { clientId: string; fyId: string }) {
  const [error, setError] = useState<ApiFailure | null>(null)
  const reg = useLoad(fyId ? () => finalApi.register(clientId, fyId) : null, `final-register:${clientId}:${fyId}`)
  const download = async () => {
    setError(null)
    try {
      await downloadFile(finalApi.registerExportPath(clientId), 'fixed-asset-register.xlsx', { financial_year_id: fyId })
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const cols: [string, (r: NonNullable<typeof reg.data>['rows'][number]) => string, string][] = [
    ['Opening cost', (r) => r.opening_cost, 'opening_cost'],
    ['Additions', (r) => r.additions, 'additions'],
    ['Disposals', (r) => r.disposals, 'disposals'],
    ['Closing cost', (r) => r.closing_cost, 'closing_cost'],
    ['Opening acc. dep.', (r) => r.opening_accumulated, 'opening_accumulated'],
    ['Depreciation for year', (r) => r.depreciation_for_year, 'depreciation_for_year'],
    ['Disposal acc. dep.', (r) => r.disposal_accumulated, 'disposal_accumulated'],
    ['Closing acc. dep.', (r) => r.closing_accumulated, 'closing_accumulated'],
    ['Net block', (r) => r.net_block, 'net_block'],
  ]
  return (
    <div className="space-y-3">
      <ErrorBox error={error ?? reg.error} />
      <button className={btn} disabled={!fyId} onClick={download}>
        Export to Excel
      </button>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>No</th>
              <th className={th}>Asset</th>
              {cols.map(([h]) => (
                <th key={h} className={thR}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(reg.data?.rows ?? []).map((r) => (
              <tr key={r.asset_id}>
                <td className={td}>{r.asset_no}</td>
                <td className={td}>{r.name}</td>
                {cols.map(([h, fn]) => (
                  <td key={h} className={tdR}>
                    <Amount value={fn(r)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {reg.data && (
            <tfoot>
              <tr className="bg-slate-50 font-semibold">
                <td className={td} colSpan={2}>
                  Total
                </td>
                {cols.map(([h, , key]) => (
                  <td key={h} className={tdR}>
                    <Amount value={reg.data?.totals?.[key]} />
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  )
}

function BookTab({ clientId, fyId }: { clientId: string; fyId: string }) {
  const [preview, setPreview] = useState<DepPreview | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState<{ voucherId: string; total: string } | null>(null)
  const runs = useLoad(fyId ? () => finalApi.bookRuns(clientId, fyId) : null, `final-runs:${clientId}:${fyId}`)
  const act = async (fn: () => Promise<void>) => {
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-600">
        Depreciation as per Schedule II of the Companies Act, used for the books. The run creates a draft Journal; approve and post it as a voucher. Rows marked pending use a useful-life or rate row that is not yet verified from an official source.
      </p>
      <ErrorBox error={error ?? runs.error} />
      <div className="flex gap-2">
        <button
          className={btn}
          disabled={!fyId}
          onClick={() =>
            act(async () => {
              setNotice(null)
              setPreview(await finalApi.bookPreview(clientId, fyId))
            })
          }
        >
          Preview depreciation
        </button>
        <button
          className={btnPrimary}
          disabled={!fyId}
          onClick={() =>
            act(async () => {
              const r = await finalApi.bookRun(clientId, fyId)
              setNotice({ voucherId: r.voucher_id, total: r.total })
              runs.reload()
            })
          }
        >
          Create draft journal
        </button>
      </div>
      {notice && (
        <Notice>
          Draft depreciation journal of <Amount value={notice.total} /> created. <VoucherLink id={notice.voucherId} label="Open the draft voucher" />
        </Notice>
      )}
      {preview && (
        <div className="space-y-2">
          <RuleStatusPanel rows={preview.rule_status} engineVersion={preview.engine_version} />
          <Findings findings={preview.findings} />
          <table className="min-w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Asset</th>
                <th className={th}>Method</th>
                <th className={thR}>Cost</th>
                <th className={thR}>Opening acc. dep.</th>
                <th className={thR}>Rate %</th>
                <th className={thR}>Days</th>
                <th className={thR}>Depreciation</th>
                <th className={thR}>Closing acc. dep.</th>
                <th className={th}>Rule status</th>
              </tr>
            </thead>
            <tbody>
              {preview.lines.map((l) => (
                <tr key={l.asset_id}>
                  <td className={td}>{l.asset_no}</td>
                  <td className={td}>{l.method}</td>
                  <td className={tdR}>
                    <Amount value={l.cost} />
                  </td>
                  <td className={tdR}>
                    <Amount value={l.opening_accumulated} />
                  </td>
                  <td className={tdR}>{l.wdv_rate_percent}</td>
                  <td className={tdR}>
                    {l.days_used}/{l.days_in_year}
                  </td>
                  <td className={tdR}>
                    <Amount value={l.depreciation} />
                  </td>
                  <td className={tdR}>
                    <Amount value={l.closing_accumulated} />
                  </td>
                  <td className={td}>
                    <PendingBadge status={statusOf(l.rule_status)} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-slate-50 font-semibold">
                <td className={td} colSpan={6}>
                  Total depreciation
                </td>
                <td className={tdR}>
                  <Amount value={preview.total} />
                </td>
                <td className={td} colSpan={2}></td>
              </tr>
            </tfoot>
          </table>
          {preview.disposal_workings.length > 0 && (
            <table className="border-collapse">
              <thead>
                <tr>
                  <th className={th}>Disposal of asset</th>
                  <th className={thR}>Proceeds</th>
                  <th className={thR}>Book value</th>
                  <th className={thR}>Profit / (loss)</th>
                </tr>
              </thead>
              <tbody>
                {preview.disposal_workings.map((d) => (
                  <tr key={d.asset_id}>
                    <td className={td}>{preview.lines.find((l) => l.asset_id === d.asset_id)?.asset_no ?? d.asset_id}</td>
                    <td className={tdR}>
                      <Amount value={d.proceeds} />
                    </td>
                    <td className={tdR}>
                      <Amount value={d.book_value} />
                    </td>
                    <td className={tdR}>
                      <Amount value={d.profit_or_loss} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <h3 className="text-sm font-semibold">Runs of this year</h3>
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Created</th>
            <th className={thR}>Total</th>
            <th className={th}>Voucher</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(runs.data ?? []).map((r) => (
            <tr key={r.run_id}>
              <td className={td}>{r.created_at?.slice(0, 10)}</td>
              <td className={tdR}>
                <Amount value={r.total} />
              </td>
              <td className={td}>
                {r.voucher_status} <VoucherLink id={r.voucher_id} />
              </td>
              <td className={td}>
                {r.voucher_status === 'draft' && (
                  <button
                    className={btnDanger}
                    onClick={() =>
                      act(async () => {
                        await finalApi.deleteBookRun(clientId, r.run_id)
                        runs.reload()
                      })
                    }
                  >
                    Delete draft run
                  </button>
                )}
              </td>
            </tr>
          ))}
          {(runs.data ?? []).length === 0 && (
            <tr>
              <td className={td} colSpan={4}>
                No run yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function statusOf(rs: DepPreview['lines'][number]['rule_status']): string {
  if (rs === null || rs === undefined) return ''
  if (typeof rs === 'string') return rs
  const v = (rs as Record<string, unknown>).verification_status ?? (rs as Record<string, unknown>).worst ?? (rs as Record<string, unknown>).status
  return typeof v === 'string' ? v : JSON.stringify(rs)
}

function ItTab({ clientId, fyId }: { clientId: string; fyId: string }) {
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [openings, setOpenings] = useState<Record<string, string>>({})
  const [ack, setAck] = useState<string[]>([])
  const w = useLoad<ItWorking>(fyId ? () => finalApi.itWorking(clientId, fyId) : null, `final-it:${clientId}:${fyId}`)
  const act = async (fn: () => Promise<void>, done: string) => {
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
      w.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const data = w.data
  const final = data?.status === 'final'
  const flagged = (data?.blocks ?? []).filter((b) => b.flags.length > 0).map((b) => b.block_key)
  const saveOpenings = () => {
    const rows = Object.entries(openings).map(([block_key, v]) => ({ block_key, opening_wdv: cleanTyped(v) }))
    if (rows.some((r) => toPaise(r.opening_wdv) === null)) {
      setError(asFailure(new Error('Opening WDV must be an amount with at most 2 decimals.')))
      return
    }
    void act(async () => {
      await finalApi.putItOpenings(clientId, fyId, rows)
      setOpenings({})
    }, 'Opening WDV saved.')
  }
  const download = async () => {
    setError(null)
    try {
      await downloadFile(finalApi.itExportPath(clientId), 'it-depreciation-working.xlsx', { financial_year_id: fyId })
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-600">Income-tax depreciation by block is a WORKING for the tax computation. It posts no voucher. The rates and the half-rate rule come from law rows whose status is shown below.</p>
      <ErrorBox error={error ?? w.error} />
      {notice && <Notice>{notice}</Notice>}
      {data && (
        <div className="space-y-1">
          <div className="text-sm">
            Status: <b>{data.status}</b>
          </div>
          <RuleStatusPanel rows={data.rule_status} engineVersion={data.engine_version} />
          <Findings findings={data.findings} />
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Block</th>
              <th className={thR}>Rate %</th>
              <th className={th}>Rate status</th>
              <th className={thR}>Opening WDV</th>
              <th className={thR}>Additions (full)</th>
              <th className={thR}>Additions (half rate)</th>
              <th className={thR}>Disposals</th>
              <th className={thR}>Depreciation</th>
              <th className={thR}>Closing WDV</th>
              <th className={th}>Flags</th>
            </tr>
          </thead>
          <tbody>
            {(data?.blocks ?? []).map((b) => (
              <tr key={b.block_key} className={b.flags.length > 0 ? 'bg-amber-50' : ''}>
                <td className={td}>
                  {b.description}
                  <div className="text-xs text-slate-500">{b.block_key}</div>
                </td>
                <td className={tdR}>{b.rate}</td>
                <td className={td}>
                  <PendingBadge status={b.rate_verification} /> <span className="text-xs text-slate-500">{b.rate_act}</span>
                </td>
                <td className={tdR}>
                  {final ? (
                    <Amount value={b.opening_wdv} />
                  ) : (
                    <input className={`${input} w-28 text-right`} value={openings[b.block_key] ?? b.opening_wdv} onChange={(e) => setOpenings({ ...openings, [b.block_key]: e.target.value })} />
                  )}
                </td>
                <td className={tdR}>
                  <Amount value={b.additions_full} />
                </td>
                <td className={tdR}>
                  <Amount value={b.additions_half} />
                </td>
                <td className={tdR}>
                  <Amount value={b.disposals} />
                </td>
                <td className={tdR}>
                  <Amount value={b.depreciation} />
                </td>
                <td className={tdR}>
                  <Amount value={b.closing_wdv} />
                </td>
                <td className={td}>
                  {b.flags.map((f) => (
                    <div key={f} className="text-xs text-amber-900">
                      {f}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
          {data && (
            <tfoot>
              <tr className="bg-slate-50 font-semibold">
                <td className={td} colSpan={7}>
                  Total depreciation
                </td>
                <td className={tdR}>
                  <Amount value={data.total_depreciation} />
                </td>
                <td className={td} colSpan={2}></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {flagged.length > 0 && !final && (
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Acknowledge the flagged blocks before finalising:
          {flagged.map((k) => (
            <label key={k} className="ml-3 inline-flex items-center gap-1">
              <input type="checkbox" checked={ack.includes(k)} onChange={(e) => setAck(e.target.checked ? [...ack, k] : ack.filter((x) => x !== k))} /> {k}
            </label>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        {!final && (
          <button className={btn} disabled={Object.keys(openings).length === 0} onClick={saveOpenings}>
            Save opening WDV (first year)
          </button>
        )}
        {!final && (
          <button className={btnPrimary} disabled={!data} onClick={() => act(async () => void (await finalApi.finalizeIt(clientId, fyId, ack)), 'Income-tax working finalised.')}>
            Finalise working
          </button>
        )}
        <button className={btn} disabled={!fyId} onClick={download}>
          Export to Excel
        </button>
      </div>
    </div>
  )
}
