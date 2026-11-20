import { useState } from 'react'
import { auditApi } from '../api/audit'
import { ErrorBox, Page, td, th, thR, tdR } from '../components/ui'
import { formatInr } from '../lib/money'
import { useLoad } from '../lib/useLoad'
import { SeverityBadge, VerifBadge } from './common'
import { dmy } from './lib'

export default function Catalogue() {
  const checks = useLoad(() => auditApi.listChecks(), 'audit-checks')
  const rules = useLoad(() => auditApi.listRules(), 'audit-rules')
  const [open, setOpen] = useState('')
  return (
    <Page title="Audit checks and rule limits">
      <ErrorBox error={checks.error ?? rules.error} />
      <div className="text-sm text-slate-600">
        Every check is a fixed rule run by the server. Legal limits come from the rule table below; a limit that is not verified from an official source is shown as pending.
      </div>
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Check</th>
            <th className={th}>Title</th>
            <th className={th}>Category</th>
            <th className={th}>Severity</th>
            <th className={th}>Rule key</th>
            <th className={th}>Active</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(checks.data ?? []).map((c) => [
            <tr key={c.check_id}>
              <td className={td + ' font-mono'}>{c.check_id}</td>
              <td className={td}>{c.title}</td>
              <td className={td}>{c.category}</td>
              <td className={td}>
                <SeverityBadge severity={c.severity} />
              </td>
              <td className={td + ' font-mono text-xs'}>{c.rule_key ?? ''}</td>
              <td className={td}>{c.active ? 'yes' : 'no'}</td>
              <td className={td}>
                <button className="text-blue-700 underline" onClick={() => setOpen(open === c.check_id ? '' : c.check_id)}>
                  {open === c.check_id ? 'Hide' : 'Details'}
                </button>
              </td>
            </tr>,
            open === c.check_id && (
              <tr key={c.check_id + 'd'}>
                <td className={td + ' bg-slate-50 text-xs'} colSpan={7}>
                  <div>{c.description}</div>
                  <div className="mt-1">
                    <b>Rule:</b> {c.rule_text}
                  </div>
                  <div className="mt-1">
                    <b>Evidence kept:</b> {c.evidence_query}
                  </div>
                </td>
              </tr>
            ),
          ])}
        </tbody>
      </table>
      <h2 className="pt-2 font-semibold">Legal limits used by the checks</h2>
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Rule key</th>
            <th className={th}>Law</th>
            <th className={th}>Section</th>
            <th className={thR}>Limit</th>
            <th className={th}>Breach when</th>
            <th className={thR}>Disallow %</th>
            <th className={th}>From</th>
            <th className={th}>To</th>
            <th className={th}>Source</th>
            <th className={th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {(rules.data ?? []).map((r) => (
            <tr key={r.rule_key + r.effective_from}>
              <td className={td + ' font-mono text-xs'}>{r.rule_key}</td>
              <td className={td}>{r.law}</td>
              <td className={td}>{r.section_ref}</td>
              <td className={tdR}>{formatInr(r.amount)}</td>
              <td className={td}>{r.breach_when.replace(/_/g, ' ')}</td>
              <td className={tdR}>{r.disallow_percent ?? ''}</td>
              <td className={td}>{dmy(r.effective_from)}</td>
              <td className={td}>{dmy(r.effective_to)}</td>
              <td className={td + ' text-xs'}>
                {r.source_reference}
                {r.notes && <div className="text-slate-500">{r.notes}</div>}
              </td>
              <td className={td}>
                <VerifBadge status={r.verification_status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Page>
  )
}
