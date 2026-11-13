import { useState } from 'react'
import { gstApi, type RuleTable } from '../api/gst'
import { ErrorBox, Field, Page, input } from '../components/ui'
import { today } from '../lib/dates'
import { useLoad } from '../lib/useLoad'
import { DataView, RuleBadge, Tabs } from './common'

const TABLES: { key: RuleTable; label: string }[] = [
  { key: 'rate-slabs', label: 'Rate slabs' },
  { key: 'rcm-categories', label: 'RCM categories' },
  { key: 'blocked-credit-categories', label: 'Blocked credit' },
  { key: 'itc-conditions', label: 'ITC conditions' },
  { key: 'composition-rules', label: 'Composition' },
  { key: 'thresholds', label: 'Thresholds' },
  { key: 'uqc', label: 'UQC' },
  { key: 'state-codes', label: 'State codes' },
]

/** Read-only viewer of the law tables; rows not verified from an official source are shown with an amber badge. */
export default function Rules() {
  const [tab, setTab] = useState<RuleTable>('rate-slabs')
  const [on, setOn] = useState(today())
  const data = useLoad(() => gstApi.ruleTable(tab, on), `gst-rules:${tab}:${on}`)
  const body = data.data as Record<string, unknown> | unknown[] | null
  // the contract says "the rows in force plus verification_status and source_reference": accept a bare array or an object
  const rows = Array.isArray(body) ? body : body && Array.isArray((body as Record<string, unknown>).rows) ? ((body as Record<string, unknown>).rows as unknown[]) : null
  const status = body && !Array.isArray(body) ? (body as { rule_status?: import('../api/gst').RuleStatus }).rule_status : undefined

  return (
    <Page title="GST rules (read-only)">
      <p className="text-xs text-slate-600">Law lives in rule tables with an effective date, a source and a verification status. Amber rows are not yet verified from an official source.</p>
      <div className="flex items-end gap-3">
        <Field label="In force on">
          <input type="date" className={input} value={on} onChange={(e) => setOn(e.target.value)} />
        </Field>
        {status && <RuleBadge status={status} />}
      </div>
      <Tabs tabs={TABLES} value={tab} onChange={setTab} />
      <ErrorBox error={data.error} />
      {data.loading && <div className="text-sm text-slate-500">Loading...</div>}
      {rows ? (
        <PendingRows rows={rows} />
      ) : body ? (
        <DataView value={body} />
      ) : null}
    </Page>
  )
}

function PendingRows({ rows }: { rows: unknown[] }) {
  const pending = rows.filter((r) => (r as { verification_status?: string })?.verification_status === 'pending')
  return (
    <div>
      {pending.length > 0 && (
        <div className="mb-2 rounded border border-amber-400 bg-amber-50 px-3 py-1 text-sm text-amber-900">
          {pending.length} of {rows.length} rows are pending verification. Do not rely on them for a filing until the CA has confirmed.
        </div>
      )}
      <DataView value={rows} />
    </div>
  )
}
