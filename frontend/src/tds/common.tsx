import { useState } from 'react'
import { Field, input } from '../components/ui'
import { useClient } from '../context'
import type { FinancialYear } from '../types'
import { QUARTERS, fyLabel, newestFirst } from './lib'

export { DataView, RuleBadge, Row, Tabs, Warnings } from '../gst/common'

/** Financial year choice for a screen; defaults to the client's latest year. */
export function useFy() {
  const { client, latestYear } = useClient()
  const years: FinancialYear[] = newestFirst(client?.financial_years ?? [])
  const [chosen, setChosen] = useState('')
  const fyId = years.some((y) => y.id === chosen) ? chosen : (latestYear?.id ?? '')
  return { years, fyId, fy: years.find((y) => y.id === fyId) ?? null, setFyId: setChosen }
}

export function FySelect({ years, value, onChange }: { years: FinancialYear[]; value: string; onChange: (id: string) => void }) {
  return (
    <Field label="Financial year">
      <select className={input} value={value} onChange={(e) => onChange(e.target.value)}>
        {years.length === 0 && <option value="">(none)</option>}
        {years.map((y) => (
          <option key={y.id} value={y.id}>
            {fyLabel(y)}
          </option>
        ))}
      </select>
    </Field>
  )
}

export function QuarterSelect({ value, onChange, allowAll }: { value: number | ''; onChange: (q: number | '') => void; allowAll?: boolean }) {
  return (
    <Field label="Quarter">
      <select className={input} value={value} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}>
        {allowAll && <option value="">All quarters</option>}
        {QUARTERS.map((q) => (
          <option key={q.value} value={q.value}>
            {q.label}
          </option>
        ))}
      </select>
    </Field>
  )
}

export const NoClient = () => <div className="text-sm text-slate-600">Select a client first.</div>
