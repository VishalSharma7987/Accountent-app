import { useEffect, useState, type ReactNode } from 'react'
import { gstApi, type Registration, type RuleStatus } from '../api/gst'
import { Amount, Field, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { asFailure, useLoad } from '../lib/useLoad'
import { isAmountText, ruleBadge, shapeOf, titleCase } from './lib'

/** G-55: every working shows how far its rules are verified; amber while anything is pending. */
export function RuleBadge({ status, worst }: { status?: RuleStatus | null; worst?: string }) {
  const b = ruleBadge(status?.worst ?? worst)
  const pending = status?.pending_sources ?? []
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${b.cls}`} title={pending.join('\n')}>
      {b.label}
      {pending.length > 0 && ` (${pending.length} source${pending.length === 1 ? '' : 's'} pending)`}
    </span>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: string }[]; value: T; onChange: (k: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-slate-300">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={`-mb-px border px-3 py-1 text-sm ${value === t.key ? 'border-slate-300 border-b-white bg-white font-medium' : 'border-transparent text-slate-600 hover:bg-slate-100'}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function useRegistrations() {
  const { clientId } = useClient()
  const list = useLoad(clientId ? () => gstApi.listRegistrations(clientId) : null, `gst-regs:${clientId}`)
  const [chosen, setChosen] = useState('')
  const regs = list.data ?? []
  const active = regs.filter((r) => r.is_active)
  const regId = active.some((r) => r.id === chosen) ? chosen : (active[0]?.id ?? '')
  return { regs, active, regId, reg: regs.find((r) => r.id === regId), setRegId: setChosen, list }
}

export function RegistrationSelect({ regs, value, onChange }: { regs: Registration[]; value: string; onChange: (id: string) => void }) {
  return (
    <Field label="GST registration">
      <select className={input} value={value} onChange={(e) => onChange(e.target.value)}>
        {regs.length === 0 && <option value="">(none: add one under GST / Registrations)</option>}
        {regs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.gstin} {r.state_name} ({r.registration_type})
          </option>
        ))}
      </select>
    </Field>
  )
}

export function MonthInput({ value, onChange, label = 'Month (YYYY-MM)' }: { value: string; onChange: (v: string) => void; label?: string }) {
  return (
    <Field label={label}>
      <input className={`${input} w-28`} value={value} placeholder="2026-04" onChange={(e) => onChange(e.target.value.trim())} />
    </Field>
  )
}

/** Debounced live GSTIN check (POST /gst/validate-gstin); shows rule ids, no state is written. */
export function useGstinCheck(gstin: string, onDate?: string) {
  const [result, setResult] = useState<Awaited<ReturnType<typeof gstApi.validateGstin>> | null>(null)
  const [failure, setFailure] = useState('')
  useEffect(() => {
    const text = gstin.trim().toUpperCase()
    if (text.length < 2) {
      setResult(null)
      setFailure('')
      return
    }
    let current = true
    const t = setTimeout(() => {
      gstApi
        .validateGstin(text, onDate)
        .then((r) => {
          if (current) {
            setResult(r)
            setFailure('')
          }
        })
        .catch((e: unknown) => {
          if (current) setFailure(asFailure(e).message)
        })
    }, 300)
    return () => {
      current = false
      clearTimeout(t)
    }
  }, [gstin, onDate])
  return { result, failure }
}

function Cell({ v }: { v: unknown }) {
  if (v === null || v === undefined || v === '') return <span className="text-slate-400">-</span>
  if (isAmountText(v)) return <Amount value={v} />
  if (typeof v === 'boolean') return <>{v ? 'Yes' : 'No'}</>
  if (typeof v === 'object') return <span className="font-mono text-xs">{JSON.stringify(v)}</span>
  return <>{String(v)}</>
}

/** Generic read-only table view of a server working: arrays of records become tables, records become key/value rows. */
export function DataView({ name, value, depth = 0 }: { name?: string; value: unknown; depth?: number }) {
  const shape = shapeOf(value)
  const heading = name ? (
    <h3 className={`${depth === 0 ? 'text-sm' : 'text-xs'} mt-3 font-semibold text-slate-700`}>{titleCase(name)}</h3>
  ) : null
  if (shape.kind === 'empty') {
    return (
      <div>
        {heading}
        <div className="text-xs text-slate-500">Nothing in this table.</div>
      </div>
    )
  }
  if (shape.kind === 'scalar') {
    return (
      <div className="text-sm">
        {name && <span className="text-slate-600">{titleCase(name)}: </span>}
        <Cell v={value} />
      </div>
    )
  }
  if (shape.kind === 'rows') {
    const rows = value as Record<string, unknown>[]
    const nested = shape.columns.filter((c) => rows.some((r) => shapeOf(r[c]).kind === 'rows'))
    const flat = shape.columns.filter((c) => !nested.includes(c))
    return (
      <div>
        {heading}
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse">
            <thead>
              <tr>
                {flat.map((c) => (
                  <th key={c} className={rows.some((r) => isAmountText(r[c])) ? thR : th}>
                    {titleCase(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {flat.map((c) => (
                    <td key={c} className={isAmountText(r[c]) ? tdR : td}>
                      <Cell v={r[c]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {nested.map((c) =>
          rows.map((r, i) =>
            shapeOf(r[c]).kind === 'rows' ? (
              <div key={`${c}-${i}`} className="ml-4 border-l-2 border-slate-200 pl-2">
                <DataView name={`${c} of row ${i + 1}`} value={r[c]} depth={depth + 1} />
              </div>
            ) : null,
          ),
        )}
      </div>
    )
  }
  const rec = value as Record<string, unknown>
  const scalars = Object.entries(rec).filter(([, v]) => shapeOf(v).kind === 'scalar' || shapeOf(v).kind === 'empty')
  const complex = Object.entries(rec).filter(([, v]) => !(shapeOf(v).kind === 'scalar' || shapeOf(v).kind === 'empty'))
  // a record whose values are all flat records of amounts (e.g. t3_1) reads best as one grid
  const grid = complex.length > 0 && complex.every(([, v]) => shapeOf(v).kind === 'record' && Object.values(v as object).every((x) => shapeOf(x).kind === 'scalar'))
  return (
    <div>
      {heading}
      {scalars.length > 0 && (
        <table className="border-collapse">
          <tbody>
            {scalars.map(([k, v]) => (
              <tr key={k}>
                <td className={`${td} text-slate-600`}>{titleCase(k)}</td>
                <td className={isAmountText(v) ? tdR : td}>{shapeOf(v).kind === 'empty' ? <span className="text-slate-400">-</span> : <Cell v={v} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {grid ? (
        <GridTable rec={Object.fromEntries(complex) as Record<string, Record<string, unknown>>} />
      ) : (
        complex.map(([k, v]) => <DataView key={k} name={k} value={v} depth={depth + 1} />)
      )}
    </div>
  )
}

function GridTable({ rec }: { rec: Record<string, Record<string, unknown>> }) {
  const cols: string[] = []
  for (const r of Object.values(rec)) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k)
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse">
        <thead>
          <tr>
            <th className={th}>Row</th>
            {cols.map((c) => (
              <th key={c} className={thR}>
                {titleCase(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(rec).map(([k, r]) => (
            <tr key={k}>
              <td className={td}>{titleCase(k)}</td>
              {cols.map((c) => (
                <td key={c} className={tdR}>
                  <Cell v={r[c]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Warnings({ items }: { items: (string | { rule_id?: string; message: string })[] }) {
  if (items.length === 0) return null
  return (
    <ul className="list-disc rounded border border-amber-300 bg-amber-50 py-2 pl-7 pr-3 text-sm text-amber-900">
      {items.map((w, i) => (
        <li key={i}>
          {typeof w === 'string' ? (
            w
          ) : (
            <>
              {w.rule_id && <span className="font-mono text-xs">{w.rule_id} </span>}
              {w.message}
            </>
          )}
        </li>
      ))}
    </ul>
  )
}

export function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-end gap-3">{children}</div>
}
