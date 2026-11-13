import { useState } from 'react'
import { inventoryApi, type NegativeMode, type ValuationMethod } from '../api/inventory'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, NoClient, Row, useFy } from './common'
import { METHODS, NEGATIVE_MODES } from './lib'

/** Valuation policy per financial year. The method cannot change once the year has movements (policy_locked). */
export default function Policy() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  if (!clientId)
    return (
      <Page title="Inventory valuation policy">
        <NoClient />
      </Page>
    )
  return (
    <Page title="Inventory valuation policy">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
      </Row>
      {fyId ? <PolicyForm key={`${clientId}:${fyId}`} clientId={clientId} fyId={fyId} years={years} /> : <div className="text-sm text-slate-600">This client has no financial year.</div>}
    </Page>
  )
}

function PolicyForm({ clientId, fyId, years }: { clientId: string; fyId: string; years: { id: string; start_date: string; end_date: string }[] }) {
  const current = useLoad(() => inventoryApi.getPolicy(clientId, fyId), `inv-policy:${clientId}:${fyId}`)
  const [method, setMethod] = useState<ValuationMethod | ''>('')
  const [mode, setMode] = useState<NegativeMode | ''>('')
  const [from, setFrom] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const notSet = current.error?.code === 'no_policy' || (current.error?.ruleErrors ?? []).some((e) => e.rule_id === 'S-04')
  const m: ValuationMethod | '' = method || current.data?.valuation_method || ''
  const n: NegativeMode | '' = mode || current.data?.negative_stock_mode || ''
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
      setMethod('')
      setMode('')
      current.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const label = (y: { start_date: string; end_date: string }) => `FY ${y.start_date.slice(0, 4)}-${y.end_date.slice(2, 4)}`
  return (
    <div className="space-y-3">
      {!notSet && <ErrorBox error={current.error} />}
      {notSet && <div className="rounded border border-amber-400 bg-amber-50 px-3 py-1 text-sm text-amber-900">No valuation policy is set for this year (S-04). Stock cannot be valued or posted until you save one.</div>}
      {current.data && (
        <div className="text-xs text-slate-600">
          Set by {current.data.set_by ?? '-'} on {current.data.set_at?.slice(0, 10) ?? '-'}.
        </div>
      )}
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
        <Field label="Valuation method">
          <select className={input} value={m} onChange={(e) => setMethod(e.target.value as ValuationMethod)}>
            <option value="">(choose)</option>
            {METHODS.map((x) => (
              <option key={x.value} value={x.value}>
                {x.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="If stock would go negative">
          <select className={input} value={n} onChange={(e) => setMode(e.target.value as NegativeMode)}>
            <option value="">(choose)</option>
            {NEGATIVE_MODES.map((x) => (
              <option key={x.value} value={x.value}>
                {x.label}
              </option>
            ))}
          </select>
        </Field>
        <button className={btnPrimary} disabled={!m || !n} onClick={() => run(() => inventoryApi.putPolicy(clientId, fyId, { valuation_method: m as ValuationMethod, negative_stock_mode: n as NegativeMode }), 'Policy saved.')}>
          Save policy
        </button>
      </div>
      <p className="text-xs text-slate-600">The valuation method is locked once the year has stock movements; the negative-stock choice can still be changed. All costs are worked out by the server from the posted movements.</p>
      <Row>
        <Field label="Copy the policy from">
          <select className={input} value={from} onChange={(e) => setFrom(e.target.value)}>
            <option value="">(choose year)</option>
            {years
              .filter((y) => y.id !== fyId)
              .map((y) => (
                <option key={y.id} value={y.id}>
                  {label(y)}
                </option>
              ))}
          </select>
        </Field>
        <button className={btn} disabled={!from || !notSet} title={notSet ? '' : 'This year already has a policy'} onClick={() => run(() => inventoryApi.copyPolicy(clientId, { from_financial_year_id: from, to_financial_year_id: fyId }), 'Policy copied.')}>
          Copy to this year
        </button>
      </Row>
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
    </div>
  )
}
