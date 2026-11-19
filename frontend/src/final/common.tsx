import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Finding, Line, RuleStatusRow, Statement } from '../api/final'
import { Amount, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { titleCase } from '../gst/lib'
import { useLoad } from '../lib/useLoad'
import type { LedgerRow } from '../types'
import { drillHref, ruleRowLabel, ruleStatusBadge, splitFindings, statusBadge, worstRuleStatus } from './lib'

export { ErrorBox, Notice } from '../components/ui'
export { FySelect, NoClient, Row, Tabs, useFy } from '../tds/common'

/** Active ledgers of the client for the pickers. */
export function useLedgers() {
  const { clientId } = useClient()
  const list = useLoad<LedgerRow[]>(clientId ? () => api.listLedgers(clientId) : null, `final-ledgers:${clientId}`)
  return { ...list, ledgers: list.data ?? [] }
}

export function LedgerSelect({ ledgers, value, onChange, groups, blank = '(choose ledger)', className }: { ledgers: LedgerRow[]; value: string; onChange: (id: string) => void; groups?: string[]; blank?: string; className?: string }) {
  const shown = ledgers.filter((l) => (l.is_active || l.id === value) && (!groups || groups.includes(l.group_code) || l.id === value))
  return (
    <select className={`rounded border border-slate-300 px-2 py-1 text-sm ${className ?? ''}`} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{blank}</option>
      {shown.map((l) => (
        <option key={l.id} value={l.id}>
          {l.name} ({l.group_name})
        </option>
      ))}
    </select>
  )
}

/** Server findings: errors block, warnings inform. Nothing is judged in the browser. */
export function Findings({ findings }: { findings: Finding[] | undefined }) {
  const { errors, warnings } = splitFindings(findings)
  return (
    <>
      {errors.length > 0 && (
        <ul role="alert" className="list-disc rounded border border-red-300 bg-red-50 py-1 pl-6 pr-3 text-sm text-red-800">
          {errors.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="list-disc rounded border border-amber-300 bg-amber-50 py-1 pl-6 pr-3 text-sm text-amber-900">
          {warnings.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

export function Problems({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <ul className="list-disc rounded border border-red-300 bg-red-50 py-1 pl-6 pr-3 text-sm text-red-800">
      {items.map((p, i) => (
        <li key={i}>{p}</li>
      ))}
    </ul>
  )
}

/** The law rows a working used and how far each is verified; pending is shown in amber (and printed on exports). */
export function RuleStatusPanel({ rows, engineVersion }: { rows: RuleStatusRow[] | undefined; engineVersion?: string }) {
  const [open, setOpen] = useState(false)
  const worst = worstRuleStatus(rows)
  const badge = ruleStatusBadge(worst)
  const list = rows ?? []
  return (
    <div className="text-xs">
      <span className={`inline-block rounded border px-2 py-0.5 font-medium ${badge.cls}`}>{badge.label}</span>
      {engineVersion && <span className="ml-2 text-slate-500">engine {engineVersion}</span>}
      {list.length > 0 && (
        <button type="button" className="ml-2 text-blue-700 underline" onClick={() => setOpen(!open)}>
          {open ? 'hide' : 'show'} rules used ({list.length})
        </button>
      )}
      {open && (
        <ul className="mt-1 space-y-0.5">
          {list.map((r, i) => {
            const b = statusBadge(String(r.verification_status ?? ''))
            return (
              <li key={i}>
                {ruleRowLabel(r)} <span className={`rounded border px-1 ${b.cls}`}>{b.label}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export function PendingBadge({ status }: { status: string | null | undefined }) {
  const b = statusBadge(status)
  return <span className={`inline-block rounded border px-1.5 text-xs ${b.cls}`}>{b.label}</span>
}

function LineRows({ lines, showPrev, from, to }: { lines: Line[]; showPrev: boolean; from: string; to: string }) {
  return (
    <>
      {lines.map((l, i) => (
        <tr key={`${l.code}-${i}`} className={l.is_total ? 'bg-slate-50 font-semibold' : ''}>
          <td className={td} style={{ paddingLeft: `${0.5 + l.level * 1}rem` }}>
            {l.label}
            {l.note_no !== null && l.note_no !== undefined && <span className="ml-1 text-xs text-slate-500">(Note {l.note_no})</span>}
            {l.drill.length > 0 && (
              <div className="text-xs font-normal text-slate-500">
                {l.drill.map((d, j) => (
                  <span key={d.ledger_id} className="mr-2">
                    {j === 0 ? '' : ''}
                    <Link className="text-blue-700 underline" to={drillHref(d.ledger_id, from, to)} title="Open the ledger statement">
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
          {showPrev && (
            <td className={tdR}>{l.previous_amount === null || l.previous_amount === undefined ? <span className="text-slate-400">-</span> : <Amount value={l.previous_amount} />}</td>
          )}
        </tr>
      ))}
    </>
  )
}

function SideTable({ title, lines, showPrev, from, to }: { title?: string; lines: Line[]; showPrev: boolean; from: string; to: string }) {
  return (
    <table className="min-w-full border-collapse bg-white">
      <thead>
        <tr>
          <th className={th}>{title ?? 'Particulars'}</th>
          <th className={thR}>Amount</th>
          {showPrev && <th className={thR}>Previous year</th>}
        </tr>
      </thead>
      <tbody>
        <LineRows lines={lines} showPrev={showPrev} from={from} to={to} />
      </tbody>
    </table>
  )
}

/** A server Statement as a table: vertical / Schedule III use `left`; horizontal puts `left` and `right` side by side. Ledger names link to the ledger statement. */
export function StatementView({ s, horizontal, leftTitle, rightTitle }: { s: Statement; horizontal?: boolean; leftTitle?: string; rightTitle?: string }) {
  const showPrev = [...s.left, ...s.right].some((l) => l.previous_amount !== null && l.previous_amount !== undefined)
  const side = horizontal && s.right.length > 0
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-semibold">{s.title}</h2>
        <span className="text-xs text-slate-500">
          {s.from_date} to {s.to_date}
        </span>
        {s.previous_source && s.previous_source !== 'none' && <span className="text-xs text-slate-500">previous year: {s.previous_source}</span>}
      </div>
      <RuleStatusPanel rows={s.rule_status} engineVersion={s.engine_version} />
      <BasisLine basis={s.basis} />
      <Findings findings={s.findings} />
      {side ? (
        <div className="grid gap-3 lg:grid-cols-2">
          <SideTable title={leftTitle} lines={s.left} showPrev={showPrev} from={s.from_date} to={s.to_date} />
          <SideTable title={rightTitle} lines={s.right} showPrev={showPrev} from={s.from_date} to={s.to_date} />
        </div>
      ) : (
        <SideTable lines={s.left} showPrev={showPrev} from={s.from_date} to={s.to_date} />
      )}
      <Totals totals={s.totals} />
    </div>
  )
}

export function Totals({ totals }: { totals: Record<string, string | null> }) {
  const entries = Object.entries(totals ?? {}).filter(([, v]) => v !== null && v !== undefined)
  if (entries.length === 0) return null
  return (
    <table className="border-collapse text-sm">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td className={`${td} text-slate-600`}>{titleCase(k)}</td>
            <td className={tdR}>
              <Amount value={v} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function BasisLine({ basis }: { basis: Record<string, string | null> | undefined }) {
  const entries = Object.entries(basis ?? {}).filter(([, v]) => v)
  if (entries.length === 0) return null
  return (
    <div className="text-xs text-slate-600">
      Basis: {entries.map(([k, v], i) => (
        <span key={k}>
          {i > 0 && '; '}
          {titleCase(k)} <b>{String(v).replace(/_/g, ' ')}</b>
        </span>
      ))}
    </div>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
      {children}
    </div>
  )
}

export function VoucherLink({ id, label }: { id: string; label?: string }) {
  return (
    <Link className="text-blue-700 underline" to={`/vouchers/${id}`}>
      {label ?? 'open voucher'}
    </Link>
  )
}
