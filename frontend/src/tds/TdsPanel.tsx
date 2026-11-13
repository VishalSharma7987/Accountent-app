import { useEffect, useRef, useState } from 'react'
import { tdsApi, type Deductee, type TdsItemIn, type TdsPreview, type ThresholdPosition } from '../api/tds'
import { Amount, btn, input, td, tdR, th, thR } from '../components/ui'
import { asFailure, useLoad } from '../lib/useLoad'
import { RuleBadge, Warnings } from './common'
import { blankTdsItem, itemProblems, previewBody } from './lib'

export interface TdsPanelProps {
  clientId: string
  /** voucher header fields; the panel never edits them */
  base: { voucher_type: string; voucher_date: string; narration: string; reference_no: string | null; party_ledger_id: string | null }
  /** the bank (payment) or expense (purchase / journal) ledger on the other side of the gross amount */
  counterLedgerId: string
  natures: { key: string; label: string }[]
  items: TdsItemIn[]
  onChange: (items: TdsItemIn[]) => void
  /** called with every server preview (null while the entry is incomplete or the call failed) */
  onPreview?: (p: TdsPreview | null) => void
  readOnly?: boolean
}

/**
 * TDS block for Payment / Purchase / Journal entry. The accountant types deductee, nature, base amount and dates;
 * the tax, rate and the generated "TDS payable" line come from POST /vouchers/tds-preview and are READ-ONLY (T-05).
 * Nothing is calculated in the browser.
 */
export function TdsPanel({ clientId, base, counterLedgerId, natures, items, onChange, onPreview, readOnly }: TdsPanelProps) {
  const deductees = useLoad(() => tdsApi.listDeductees(clientId), `tds-ded:${clientId}:`)
  const [preview, setPreview] = useState<TdsPreview | null>(null)
  const [failure, setFailure] = useState('')
  const [loading, setLoading] = useState(false)
  const onPreviewRef = useRef(onPreview)
  onPreviewRef.current = onPreview

  const body = previewBody(base, items, counterLedgerId)
  const sig = body ? JSON.stringify(body) : ''
  useEffect(() => {
    if (!sig) {
      setPreview(null)
      setFailure('')
      onPreviewRef.current?.(null)
      return
    }
    let current = true
    setLoading(true)
    const t = setTimeout(() => {
      tdsApi
        .tdsPreview(clientId, JSON.parse(sig))
        .then((p) => {
          if (!current) return
          setPreview(p)
          setFailure('')
          onPreviewRef.current?.(p)
        })
        .catch((e: unknown) => {
          if (!current) return
          setPreview(null)
          setFailure(asFailure(e).message)
          onPreviewRef.current?.(null)
        })
        .finally(() => {
          if (current) setLoading(false)
        })
    }, 400)
    return () => {
      current = false
      clearTimeout(t)
    }
  }, [sig, clientId])

  const set = (i: number, patch: Partial<TdsItemIn>) => onChange(items.map((it, k) => (k === i ? { ...it, ...patch } : it)))
  const dedOf = (id: string): Deductee | undefined => deductees.data?.find((d) => d.ledger_id === id)
  const activeDeductees = (deductees.data ?? []).filter((d) => d.is_active)
  const outOf = (i: number) => preview?.tds.items.find((o) => o.item_no === i + 1)
  const itemErrors = (i: number) => (preview?.errors ?? []).filter((e) => e.line_no === i + 1)
  const headerErrors = (preview?.errors ?? []).filter((e) => e.line_no === null)

  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="flex items-center gap-2">
        <div className="text-sm font-semibold">TDS deduction</div>
        {preview?.rule_status && <RuleBadge status={preview.rule_status} />}
        {loading && <span className="text-xs text-slate-500">Calculating on the server...</span>}
      </div>
      <p className="text-xs text-slate-600">Enter the amount to which the nature applies (leave out GST shown separately). The tax is worked out by the server from the rule in force on the earlier of the credit and payment dates.</p>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr>
              <th className={th}>#</th>
              <th className={th}>Deductee</th>
              <th className={th}>Nature</th>
              <th className={thR}>Amount</th>
              <th className={th}>Credit date</th>
              <th className={th}>Payment date</th>
              <th className={th}>Lower certificate</th>
              <th className={thR}>Manual tax (salary only)</th>
              <th className={th}></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => {
              const ded = dedOf(it.deductee_ledger_id)
              return (
                <tr key={i} className="align-top">
                  <td className={td}>{i + 1}</td>
                  <td className={td}>
                    <select className={`${input} w-44`} disabled={readOnly} value={it.deductee_ledger_id} onChange={(e) => set(i, { deductee_ledger_id: e.target.value, lower_cert_id: null, nature_key: it.nature_key || dedOf(e.target.value)?.default_nature_key || '' })}>
                      <option value="">(choose)</option>
                      {activeDeductees.map((d) => (
                        <option key={d.ledger_id} value={d.ledger_id}>
                          {d.ledger_name}
                        </option>
                      ))}
                    </select>
                    {ded && ded.pan_status !== 'valid' && <div className="text-xs text-red-700">PAN {ded.pan_status.replace('_', ' ')}: higher rate applies</div>}
                  </td>
                  <td className={td}>
                    <select className={`${input} w-48`} disabled={readOnly} value={it.nature_key} onChange={(e) => set(i, { nature_key: e.target.value })}>
                      <option value="">(choose)</option>
                      {natures.map((n) => (
                        <option key={n.key} value={n.key}>
                          {n.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className={td}>
                    <input className={`${input} w-28 text-right`} disabled={readOnly} value={it.amount} onChange={(e) => set(i, { amount: e.target.value.replace(/[,\s]/g, '') })} />
                  </td>
                  <td className={td}>
                    <input type="date" className={input} disabled={readOnly} value={it.credit_date ?? ''} onChange={(e) => set(i, { credit_date: e.target.value || null })} />
                  </td>
                  <td className={td}>
                    <input type="date" className={input} disabled={readOnly} value={it.payment_date ?? ''} onChange={(e) => set(i, { payment_date: e.target.value || null })} />
                  </td>
                  <td className={td}>
                    <select className={`${input} w-40`} disabled={readOnly || !ded} value={it.lower_cert_id ?? ''} onChange={(e) => set(i, { lower_cert_id: e.target.value || null })}>
                      <option value="">(none)</option>
                      {(ded?.lower_certs ?? [])
                        .filter((c) => c.is_active && (!c.nature_key || c.nature_key === it.nature_key))
                        .map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.certificate_no} ({c.rate}%)
                          </option>
                        ))}
                    </select>
                  </td>
                  <td className={td}>
                    <input className={`${input} w-24 text-right`} disabled={readOnly} value={it.manual_tax ?? ''} onChange={(e) => set(i, { manual_tax: e.target.value.replace(/[,\s]/g, '') || null })} />
                  </td>
                  <td className={td}>
                    {!readOnly && items.length > 1 && (
                      <button className={btn} onClick={() => onChange(items.filter((_, k) => k !== i))}>
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!readOnly && (
        <button className={btn} onClick={() => onChange([...items, blankTdsItem()])}>
          Add deduction
        </button>
      )}
      {items.map((it, i) => {
        const problems = itemProblems(it)
        const typed = it.deductee_ledger_id || it.nature_key || it.amount
        return typed && problems.length > 0 ? (
          <div key={i} className="text-xs text-slate-500">
            Item {i + 1}: {problems.join('; ')}.
          </div>
        ) : null
      })}
      {failure && <div className="rounded border border-red-300 bg-red-50 px-3 py-1 text-sm text-red-800">{failure}</div>}
      {headerErrors.length > 0 && (
        <ul className="list-disc rounded border border-red-300 bg-red-50 py-2 pl-7 pr-3 text-sm text-red-800">
          {headerErrors.map((e, k) => (
            <li key={k}>
              <span className="font-mono text-xs">{e.rule_id} </span>
              {e.message}
            </li>
          ))}
        </ul>
      )}
      {preview && (
        <div className="space-y-2">
          <table className="min-w-full border-collapse">
            <thead>
              <tr>
                <th className={th}>#</th>
                <th className={th}>Act and section</th>
                <th className={th}>Event date</th>
                <th className={thR}>Paid this year before</th>
                <th className={thR}>After this payment</th>
                <th className={thR}>Taxable base</th>
                <th className={thR}>Rate %</th>
                <th className={th}>Reason</th>
                <th className={thR}>Tax already on base</th>
                <th className={thR}>TDS</th>
              </tr>
            </thead>
            <tbody>
              {preview.tds.items.map((o) => (
                <tr key={o.item_no} className={o.verification_status === 'pending' ? 'bg-amber-50' : ''}>
                  <td className={td}>{o.item_no}</td>
                  <td className={td}>
                    {o.act} {o.section_ref}
                    {o.table_ref ? ` (${o.table_ref})` : ''}
                  </td>
                  <td className={td}>{o.event_date}</td>
                  <td className={tdR}><Amount value={o.cumulative_before} /></td>
                  <td className={tdR}>
                    <Amount value={o.cumulative_after} />
                    {o.threshold_crossed && <div className="text-xs text-amber-800">threshold crossed</div>}
                  </td>
                  <td className={tdR}><Amount value={o.taxable_base} /></td>
                  <td className={tdR}>{o.rate_applied}</td>
                  <td className={td}>{o.rate_reason.replace(/_/g, ' ')}</td>
                  <td className={tdR}><Amount value={o.tax_already_on_base} /></td>
                  <td className={`${tdR} font-semibold`}><Amount value={o.tds_amount} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.map((_, i) => {
            const errs = itemErrors(i)
            const warns = outOf(i)?.warnings ?? []
            return errs.length + warns.length > 0 ? (
              <div key={i} className="space-y-1">
                <div className="text-xs font-semibold">Item {i + 1}</div>
                {errs.length > 0 && (
                  <ul className="list-disc rounded border border-red-300 bg-red-50 py-2 pl-7 pr-3 text-sm text-red-800">
                    {errs.map((e, k) => (
                      <li key={k}>
                        <span className="font-mono text-xs">{e.rule_id} </span>
                        {e.message}
                      </li>
                    ))}
                  </ul>
                )}
                <Warnings items={warns} />
              </div>
            ) : null
          })}
          <div className="text-xs font-semibold">Voucher lines (generated, read-only)</div>
          <table className="border-collapse">
            <thead>
              <tr>
                <th className={th}>Ledger</th>
                <th className={thR}>Debit</th>
                <th className={thR}>Credit</th>
              </tr>
            </thead>
            <tbody>
              {preview.lines.map((l, k) => (
                <tr key={k} className={l.tds_role ? 'bg-slate-50 italic' : ''}>
                  <td className={td}>
                    {l.ledger_name}
                    {l.tds_role && <span className="ml-1 text-xs text-slate-500">(generated)</span>}
                  </td>
                  <td className={tdR}>{Number(l.debit) ? <Amount value={l.debit} /> : ''}</td>
                  <td className={tdR}>{Number(l.credit) ? <Amount value={l.credit} /> : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Headroom clientId={clientId} items={items} on={base.voucher_date} />
    </div>
  )
}

/** Threshold headroom of each chosen deductee + nature (server figures, shown only). */
function Headroom({ clientId, items, on }: { clientId: string; items: TdsItemIn[]; on: string }) {
  const keys = [...new Set(items.filter((i) => i.deductee_ledger_id && i.nature_key).map((i) => `${i.deductee_ledger_id}|${i.nature_key}`))]
  const [rows, setRows] = useState<Record<string, ThresholdPosition | string>>({})
  const sig = keys.join(',') + on
  useEffect(() => {
    let current = true
    for (const k of keys) {
      const [deductee_ledger_id, nature_key] = k.split('|')
      tdsApi
        .thresholdPosition(clientId, { deductee_ledger_id, nature_key, on })
        .then((p) => current && setRows((r) => ({ ...r, [k]: p })))
        .catch((e: unknown) => current && setRows((r) => ({ ...r, [k]: asFailure(e).message })))
    }
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, clientId])
  if (keys.length === 0) return null
  return (
    <div className="space-y-0.5 text-xs text-slate-700">
      {keys.map((k) => {
        const r = rows[k]
        const name = k.split('|')
        if (!r) return null
        if (typeof r === 'string') return <div key={k}>Threshold position ({name[1]}): {r}</div>
        return (
          <div key={k}>
            Paid so far this year ({name[1]}): <Amount value={r.cumulative_amount} />, tax deducted <Amount value={r.tax_deducted} />
            {r.annual_threshold && <>, annual threshold <Amount value={r.annual_threshold} /></>}
            {r.single_threshold && <>, single-payment threshold <Amount value={r.single_threshold} /></>}
            {r.headroom !== null && <>, headroom <Amount value={r.headroom} /></>}
          </div>
        )
      })}
    </div>
  )
}

