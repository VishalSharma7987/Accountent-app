import { useState } from 'react'
import { Link } from 'react-router-dom'
import { finalApi, type Finding, type Note, type Sch3Classification, type Statement } from '../api/final'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th } from '../components/ui'
import { useClient } from '../context'
import { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { ExportButtons } from './Export'
import { BasisLine, Findings, FySelect, NoClient, Row, RuleStatusPanel, Section, StatementView, Tabs, useFy } from './common'
import { CF_CLASSES, classificationRows, drillHref, sourceLabel } from './lib'

type Tab = 'bs' | 'pl' | 'notes' | 'class'

interface Loaded {
  statement: Statement | null
  blocked: Finding[] | null
}

/** F-44: the server answers 422 `unclassified` with the statement it could build and the findings; show both. */
async function tolerant(fn: () => Promise<Statement>): Promise<Loaded> {
  try {
    return { statement: await fn(), blocked: null }
  } catch (e) {
    if (e instanceof ApiFailure && e.code === 'unclassified') {
      const d = (e.details ?? {}) as { statement?: Statement; findings?: Finding[] }
      return { statement: d.statement ?? null, blocked: d.findings ?? [] }
    }
    throw e
  }
}

/** Schedule III Balance Sheet, Statement of Profit and Loss, notes and the ledger classification editor (company clients). */
export default function Schedule3() {
  const { clientId, client } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const [tab, setTab] = useState<Tab>('bs')
  const [asOn, setAsOn] = useState('')
  const isCompany = client?.entity_type === 'company'
  const ok = !!clientId && !!fyId && isCompany
  const bs = useLoad<Loaded>(ok && tab === 'bs' ? () => tolerant(() => finalApi.sch3BalanceSheet(clientId, { financial_year_id: fyId, as_on: asOn || undefined })) : null, `final-s3bs:${clientId}:${fyId}:${asOn}`)
  const pl = useLoad<Loaded>(ok && tab === 'pl' ? () => tolerant(() => finalApi.sch3ProfitLoss(clientId, fyId)) : null, `final-s3pl:${clientId}:${fyId}`)
  const notes = useLoad(
    ok && tab === 'notes'
      ? async () => {
          try {
            return { data: await finalApi.sch3Notes(clientId, fyId), blocked: null as Finding[] | null }
          } catch (e) {
            if (e instanceof ApiFailure && e.code === 'unclassified') return { data: null, blocked: ((e.details ?? {}) as { findings?: Finding[] }).findings ?? [] }
            throw e
          }
        }
      : null,
    `final-s3n:${clientId}:${fyId}`,
  )
  if (!clientId)
    return (
      <Page title="Schedule III statements">
        <NoClient />
      </Page>
    )
  if (!isCompany)
    return (
      <Page title="Schedule III statements">
        <div className="rounded border border-slate-300 bg-white p-3 text-sm">
          Schedule III applies to company clients. This client is a {client?.entity_type}: use <Link className="text-blue-700 underline" to="/final/statements">Trading, Profit and Loss, Balance Sheet</Link>.
        </div>
      </Page>
    )
  const cur = tab === 'bs' ? bs : pl
  return (
    <Page title="Schedule III statements">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        {tab === 'bs' && (
          <Field label="As on (blank = year end)">
            <input type="date" className={input} value={asOn} min={fy?.start_date} max={fy?.end_date} onChange={(e) => setAsOn(e.target.value)} />
          </Field>
        )}
        <ExportButtons fyId={fyId} statements={['balance_sheet', 'profit_loss', 'cash_flow']} />
      </Row>
      <Tabs
        tabs={[
          { key: 'bs', label: 'Balance Sheet' },
          { key: 'pl', label: 'Statement of Profit and Loss' },
          { key: 'notes', label: 'Notes' },
          { key: 'class', label: 'Classification' },
        ]}
        value={tab}
        onChange={setTab}
      />
      {(tab === 'bs' || tab === 'pl') && (
        <>
          <ErrorBox error={cur.error} />
          {cur.data?.blocked && (
            <div className="space-y-1">
              <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">Some ledgers are not classified to a Schedule III line (F-44). Fix them under Classification; the statement below is what the server could build.</div>
              <Findings findings={cur.data.blocked} />
            </div>
          )}
          {cur.data?.statement && <StatementView s={cur.data.statement} />}
          {cur.data?.statement && cur.data.statement.notes.length > 0 && <NotesView notes={cur.data.statement.notes} from={cur.data.statement.from_date} to={cur.data.statement.to_date} />}
        </>
      )}
      {tab === 'notes' && (
        <>
          <ErrorBox error={notes.error} />
          {notes.data?.blocked && <Findings findings={notes.data.blocked} />}
          {notes.data?.data && (
            <div className="space-y-2">
              <RuleStatusPanel rows={notes.data.data.rule_status} engineVersion={notes.data.data.engine_version} />
              <BasisLine basis={notes.data.data.basis} />
              <Findings findings={notes.data.data.findings} />
              <NotesView notes={notes.data.data.notes} from={fy?.start_date ?? ''} to={asOn || fy?.end_date || ''} />
            </div>
          )}
        </>
      )}
      {tab === 'class' && <Classification clientId={clientId} fyId={fyId} from={fy?.start_date ?? ''} to={fy?.end_date ?? ''} />}
    </Page>
  )
}

function NotesView({ notes, from, to }: { notes: Note[]; from: string; to: string }) {
  return (
    <div className="space-y-3">
      {notes.map((n) => (
        <Section key={String(n.note_no)} title={`Note ${n.note_no}: ${n.title}`}>
          <table className="min-w-full border-collapse bg-white">
            <tbody>
              {n.lines.map((l, i) => (
                <tr key={i} className={l.is_total ? 'bg-slate-50 font-semibold' : ''}>
                  <td className={td} style={{ paddingLeft: `${0.5 + l.level}rem` }}>
                    {l.label}
                    {l.drill.length > 0 && (
                      <div className="text-xs font-normal text-slate-500">
                        {l.drill.map((d) => (
                          <span key={d.ledger_id} className="mr-2">
                            <Link className="text-blue-700 underline" to={drillHref(d.ledger_id, from, to)}>
                              {d.ledger_name}
                            </Link>{' '}
                            <Amount value={d.amount} />
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className={tdR}>
                    <Amount value={l.amount} />
                  </td>
                  <td className={tdR}>{l.previous_amount ? <Amount value={l.previous_amount} /> : <span className="text-slate-400">-</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      ))}
    </div>
  )
}

type Edits = Record<string, { line_code: string; cf_class: string }>

function Classification({ clientId, fyId, from, to }: { clientId: string; fyId: string; from: string; to: string }) {
  const [edits, setEdits] = useState<Edits>({})
  const [onlyOpen, setOnlyOpen] = useState(true)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const data = useLoad<Sch3Classification>(fyId ? () => finalApi.sch3Classification(clientId, fyId) : null, `final-s3class:${clientId}:${fyId}`)
  const c = data.data
  const open = new Set([...(c?.unclassified ?? []), ...(c?.defaults ?? [])])
  const rows = (c?.ledgers ?? []).filter((l) => !onlyOpen || open.has(l.ledger_id) || edits[l.ledger_id])
  const edit = (id: string, base: { line_code: string | null; cf_class: string | null }, patch: Partial<{ line_code: string; cf_class: string }>) =>
    setEdits({ ...edits, [id]: { line_code: edits[id]?.line_code ?? base.line_code ?? '', cf_class: edits[id]?.cf_class ?? base.cf_class ?? '', ...patch } })
  const save = async () => {
    setError(null)
    setNotice('')
    try {
      await finalApi.putSch3Classification(clientId, classificationRows(edits))
      setNotice('Classification saved.')
      setEdits({})
      data.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const sections = [...new Set((c?.lines ?? []).map((l) => l.section))]
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-600">Every ledger must map to a Schedule III line (F-44). A group default is only a suggestion: confirm it by saving the line for the ledger. Clearing both fields removes the ledger override.</p>
      <ErrorBox error={error ?? data.error} />
      {notice && <Notice>{notice}</Notice>}
      <div className="flex items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Only unclassified and group-default ledgers ({open.size})
        </label>
        <button className={btnPrimary} disabled={Object.keys(edits).length === 0} onClick={save}>
          Save {Object.keys(edits).length} change(s)
        </button>
        <button className={btn} disabled={Object.keys(edits).length === 0} onClick={() => setEdits({})}>
          Discard
        </button>
      </div>
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Ledger</th>
            <th className={th}>Group</th>
            <th className={th}>Schedule III line</th>
            <th className={th}>Source</th>
            <th className={th}>Cash-flow class</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => {
            const e = edits[l.ledger_id]
            const line = e?.line_code ?? l.line_code ?? ''
            return (
              <tr key={l.ledger_id} className={l.source === 'none' ? 'bg-red-50' : l.source === 'group_default' ? 'bg-amber-50' : ''}>
                <td className={td}>
                  <Link className="text-blue-700 underline" to={drillHref(l.ledger_id, from, to)}>
                    {l.name}
                  </Link>
                </td>
                <td className={td}>{l.group_code}</td>
                <td className={td}>
                  <select className={`${input} w-72`} value={line} onChange={(ev) => edit(l.ledger_id, l, { line_code: ev.target.value })}>
                    <option value="">(none)</option>
                    {sections.map((s) => (
                      <optgroup key={s} label={s}>
                        {(c?.lines ?? [])
                          .filter((x) => x.section === s)
                          .map((x) => (
                            <option key={x.line_code} value={x.line_code}>
                              {x.label}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                </td>
                <td className={td}>{e ? 'changed (not saved)' : sourceLabel(l.source)}</td>
                <td className={td}>
                  <select className={input} value={e?.cf_class ?? l.cf_class ?? ''} onChange={(ev) => edit(l.ledger_id, l, { cf_class: ev.target.value })}>
                    <option value="">(default)</option>
                    {CF_CLASSES.map((k) => (
                      <option key={k.value} value={k.value}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td className={td} colSpan={5}>
                {onlyOpen ? 'Every ledger is classified.' : 'No ledgers.'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
