import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AuditFinding } from '../api/audit'
import { td, tdR } from '../components/ui'
import { formatInr } from '../lib/money'
import { dmy, evidenceRows, findingLinks } from './lib'

export { NoClient, FySelect, useFy } from '../tds/common'
export { ErrorBox, Notice } from '../components/ui'

const SEV: Record<string, string> = {
  error: 'bg-red-200 text-red-900',
  review: 'bg-orange-200 text-orange-900',
  warning: 'bg-amber-200 text-amber-900',
  info: 'bg-slate-200 text-slate-800',
}
export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  const s = severity ?? 'info'
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${SEV[s] ?? SEV.info}`}>{s}</span>
}

const VERIF: Record<string, { label: string; cls: string }> = {
  pending: { label: 'pending: not verified', cls: 'bg-amber-100 text-amber-900 border-amber-400' },
  secondary_verified: { label: 'secondary verified', cls: 'bg-yellow-50 text-yellow-900 border-yellow-300' },
  verified: { label: 'verified', cls: 'bg-green-100 text-green-900 border-green-400' },
}
/** Verification status of a legal limit or form. An unknown or missing status is shown as pending, never as verified. */
export function VerifBadge({ status }: { status: string | null | undefined }) {
  const b = VERIF[status ?? ''] ?? VERIF.pending
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-xs font-medium ${b.cls}`}>{b.label}</span>
}

const STATUS: Record<string, string> = {
  open: 'bg-slate-200 text-slate-800',
  in_review: 'bg-amber-200 text-amber-900',
  signed_off: 'bg-green-200 text-green-900',
  cleared: 'bg-green-200 text-green-900',
  confirmed: 'bg-red-200 text-red-900',
}
export function StatusPill({ status }: { status: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS[status] ?? STATUS.open}`}>{status.replace('_', ' ')}</span>
}

/** Findings of the server as table rows with an expandable evidence block and links to the books. */
export function FindingRows({ findings, from, to, cols = 8 }: { findings: AuditFinding[]; from: string; to: string; cols?: number }) {
  const [open, setOpen] = useState<string>('')
  return (
    <>
      {findings.map((f) => {
        const links = findingLinks(f, from, to)
        return [
          <tr key={f.id}>
            <td className={td}>{f.check_id}</td>
            <td className={td}>
              <SeverityBadge severity={f.severity} />
            </td>
            <td className={td}>{dmy(f.finding_date)}</td>
            <td className={td}>{f.subject_ref}</td>
            <td className={td}>{f.message}</td>
            <td className={tdR}>{formatInr(f.amount)}</td>
            <td className={tdR}>{formatInr(f.disallowance_amount)}</td>
            <td className={td}>
              <button className="text-blue-700 underline" onClick={() => setOpen(open === f.id ? '' : f.id)}>
                {open === f.id ? 'Hide evidence' : 'Evidence'}
              </button>
              {links.map((l) => (
                <Link key={l.to} className="ml-2 text-blue-700 underline" to={l.to}>
                  {l.label}
                </Link>
              ))}
              {f.rule_status && (
                <span className="ml-2">
                  <VerifBadge status={f.rule_status} />
                </span>
              )}
            </td>
          </tr>,
          open === f.id && (
            <tr key={f.id + 'e'}>
              <td className={td + ' bg-slate-50'} colSpan={cols}>
                <table className="text-xs">
                  <tbody>
                    {evidenceRows(f.evidence).map(([k, v]) => (
                      <tr key={k}>
                        <td className="pr-3 align-top font-mono text-slate-600">{k}</td>
                        <td className="break-all">{v}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </td>
            </tr>
          ),
        ]
      })}
    </>
  )
}
