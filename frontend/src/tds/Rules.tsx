import { useState } from 'react'
import { tdsApi, type RuleTableName, type SectionMapRow } from '../api/tds'
import { Field, ErrorBox, Page, input, td, th } from '../components/ui'
import { today } from '../lib/dates'
import { useLoad } from '../lib/useLoad'
import { DataView, RuleBadge, Tabs } from './common'
import { countPending } from './lib'

const TABLES: { key: RuleTableName; label: string }[] = [
  { key: 'section-map', label: '1961 <-> 2025 sections' },
  { key: 'natures', label: 'Natures' },
  { key: 'rates', label: 'Rates and thresholds' },
  { key: 'provisions', label: 'Other provisions' },
  { key: 'due-dates', label: 'Due dates' },
  { key: 'interest-rules', label: 'Interest' },
  { key: 'forms', label: 'Forms' },
]

/** Read-only viewer of the TDS law tables; pending rows are amber, nothing is edited here. */
export default function Rules() {
  const [tab, setTab] = useState<RuleTableName>('section-map')
  const [on, setOn] = useState(today())
  const [nature, setNature] = useState('')
  const data = useLoad(() => tdsApi.ruleTable(tab, { on, nature_key: tab === 'rates' ? nature : undefined }), `tds-rules:${tab}:${on}:${nature}`)
  const rows = data.data?.rows ?? []
  const pending = countPending(rows)
  return (
    <Page title="TDS / TCS rules (read-only)">
      <p className="text-xs text-slate-600">Law lives in rule tables with an effective date, a source and a verification status. Amber means not yet verified from an official source: do not rely on it for a filing until the CA confirms.</p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="In force on">
          <input type="date" className={input} value={on} onChange={(e) => setOn(e.target.value)} />
        </Field>
        {tab === 'rates' && (
          <Field label="Nature key (optional)">
            <input className={`${input} w-40`} value={nature} onChange={(e) => setNature(e.target.value.trim())} />
          </Field>
        )}
        {data.data && <RuleBadge worst={data.data.status.overall} />}
      </div>
      <Tabs tabs={TABLES} value={tab} onChange={setTab} />
      <ErrorBox error={data.error} />
      {data.loading && <div className="text-sm text-slate-500">Loading...</div>}
      {pending > 0 && (
        <div className="rounded border border-amber-400 bg-amber-50 px-3 py-1 text-sm text-amber-900">
          {pending} of {rows.length} rows are pending verification.
        </div>
      )}
      {tab === 'section-map' ? <SectionMap rows={rows as unknown as SectionMapRow[]} /> : rows.length > 0 ? <DataView value={rows} /> : !data.loading && <div className="text-sm text-slate-500">Nothing in force on this date.</div>}
    </Page>
  )
}

function SectionMap({ rows }: { rows: SectionMapRow[] }) {
  return (
    <table className="min-w-full border-collapse bg-white">
      <thead>
        <tr>
          <th className={th}>Nature</th>
          <th className={th}>Income-tax Act 1961 (to 31-03-2026)</th>
          <th className={th}>Income-tax Act 2025 (from 01-04-2026)</th>
          <th className={th}>Table</th>
          <th className={th}>Payment code</th>
          <th className={th}>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.nature_key} className={r.status === 'pending' ? 'bg-amber-50' : ''}>
            <td className={td}>{r.description || r.nature_key}</td>
            <td className={td}>{r.sec_1961 ?? '-'}</td>
            <td className={td}>{r.sec_2025 ?? '-'}</td>
            <td className={td}>{r.table_ref_2025 ?? '-'}</td>
            <td className={td}>{r.payment_code_2025 ?? '-'}</td>
            <td className={td}>{r.status}</td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={6} className={`${td} text-slate-500`}>
              Nothing in force on this date.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}
