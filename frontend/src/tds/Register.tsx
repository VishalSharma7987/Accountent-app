import { useState } from 'react'
import { tdsApi, type RegisterFilter } from '../api/tds'
import { Amount, ErrorBox, Field, Page, btn, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { exportXlsx } from '../lib/exportXlsx'
import { formatInr } from '../lib/money'
import { useLoad } from '../lib/useLoad'
import { DataView, FySelect, NoClient, QuarterSelect, Row, RuleBadge, Tabs, useFy } from './common'
import { useNatures } from './hooks'
import { fyLabel } from './lib'

/** TDS register: items of POSTED vouchers with deposit status, plus the per-deductee threshold view. */
export default function Register() {
  const { clientId } = useClient()
  const { years, fyId, fy, setFyId } = useFy()
  const [tab, setTab] = useState<'register' | 'by-deductee'>('register')
  const [quarter, setQuarter] = useState<number | ''>('')
  const [nature, setNature] = useState('')
  const [status, setStatus] = useState<NonNullable<RegisterFilter['deposit_status']>>('all')
  const natures = useNatures()
  const filter: RegisterFilter = { financial_year_id: fyId, quarter, nature_key: nature, deposit_status: status }
  const reg = useLoad(clientId && fyId && tab === 'register' ? () => tdsApi.register(clientId, filter) : null, `tds-reg:${clientId}:${JSON.stringify(filter)}`)
  const by = useLoad(clientId && fyId && tab === 'by-deductee' ? () => tdsApi.registerByDeductee(clientId, fyId) : null, `tds-by:${clientId}:${fyId}`)
  if (!clientId) return <Page title="TDS register"><NoClient /></Page>
  const rows = reg.data?.rows ?? []
  const byRows = Array.isArray(by.data) ? by.data : (by.data?.rows ?? [])

  const exportRows = () =>
    exportXlsx(
      `tds-register-${fy ? fyLabel(fy) : ''}.xlsx`,
      'TDS register',
      ['Voucher', 'Date', 'Deductee', 'PAN', 'Section', 'Event date', 'Paid', 'Base', 'Rate %', 'Reason', 'TDS', 'Deposited', 'Balance', 'Due date', 'Deposited on', 'Days late'],
      rows.map((r) => [r.voucher_number ?? '', r.voucher_date, r.deductee_name, r.pan ?? '', r.section_ref, r.event_date, formatInr(r.payment_amount), formatInr(r.taxable_base), r.rate_applied, r.rate_reason, formatInr(r.tds_amount), formatInr(r.deposited), formatInr(r.balance), r.due_date, r.deposited_on ?? '', r.days_late === null ? '' : String(r.days_late)]),
    )

  return (
    <Page title="TDS register" actions={tab === 'register' ? <button className={btn} disabled={rows.length === 0} onClick={exportRows}>Export to Excel</button> : undefined}>
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        {tab === 'register' && (
          <>
            <QuarterSelect allowAll value={quarter} onChange={setQuarter} />
            <Field label="Nature">
              <select className={input} value={nature} onChange={(e) => setNature(e.target.value)}>
                <option value="">All</option>
                {natures.options.map((n) => (
                  <option key={n.key} value={n.key}>
                    {n.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Deposit status">
              <select className={input} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
                <option value="all">All</option>
                <option value="deposited">Deposited</option>
                <option value="short">Short deposited</option>
                <option value="undeposited">Not deposited</option>
              </select>
            </Field>
          </>
        )}
        {reg.data?.rule_status && <RuleBadge status={reg.data.rule_status} />}
      </Row>
      <Tabs
        tabs={[
          { key: 'register', label: 'Register' },
          { key: 'by-deductee', label: 'By deductee (thresholds)' },
        ]}
        value={tab}
        onChange={setTab}
      />
      <ErrorBox error={reg.error ?? by.error} />
      {tab === 'register' && (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse bg-white">
              <thead>
                <tr>
                  <th className={th}>Voucher</th>
                  <th className={th}>Deductee</th>
                  <th className={th}>PAN</th>
                  <th className={th}>Section</th>
                  <th className={th}>Event date</th>
                  <th className={thR}>Paid</th>
                  <th className={thR}>Base</th>
                  <th className={thR}>Rate %</th>
                  <th className={th}>Reason</th>
                  <th className={thR}>TDS</th>
                  <th className={thR}>Deposited</th>
                  <th className={thR}>Balance</th>
                  <th className={th}>Due</th>
                  <th className={th}>Deposited on</th>
                  <th className={thR}>Days late</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.item_id} className={r.days_late && r.days_late > 0 ? 'bg-red-50' : ''}>
                    <td className={td}>{r.voucher_number ?? r.voucher_date}</td>
                    <td className={td}>{r.deductee_name}</td>
                    <td className={`${td} font-mono`}>{r.pan ?? <span className="text-red-700">missing</span>}</td>
                    <td className={td}>{r.section_ref}</td>
                    <td className={td}>{r.event_date}</td>
                    <td className={tdR}><Amount value={r.payment_amount} /></td>
                    <td className={tdR}><Amount value={r.taxable_base} /></td>
                    <td className={tdR}>{r.rate_applied}</td>
                    <td className={td}>{r.rate_reason.replace(/_/g, ' ')}</td>
                    <td className={tdR}><Amount value={r.tds_amount} /></td>
                    <td className={tdR}><Amount value={r.deposited} /></td>
                    <td className={tdR}><Amount value={r.balance} /></td>
                    <td className={td}>{r.due_date}</td>
                    <td className={td}>{r.deposited_on ?? '-'}</td>
                    <td className={tdR}>{r.days_late ?? ''}</td>
                  </tr>
                ))}
                {rows.length === 0 && !reg.loading && (
                  <tr>
                    <td colSpan={15} className={`${td} text-slate-500`}>
                      No deductions in posted vouchers for this selection.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {reg.data && <DataView name="Totals" value={reg.data.totals} />}
        </>
      )}
      {tab === 'by-deductee' && (
        <table className="min-w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Deductee</th>
              <th className={th}>Nature</th>
              <th className={thR}>Paid / credited</th>
              <th className={thR}>Tax deducted</th>
              <th className={thR}>Threshold</th>
              <th className={th}>Crossed on</th>
            </tr>
          </thead>
          <tbody>
            {byRows.map((r, i) => (
              <tr key={i}>
                <td className={td}>{r.deductee_name}</td>
                <td className={td}>{r.nature_key}</td>
                <td className={tdR}><Amount value={r.cumulative_amount} /></td>
                <td className={tdR}><Amount value={r.tax_deducted} /></td>
                <td className={tdR}>{r.threshold ? <Amount value={r.threshold} /> : '-'}</td>
                <td className={td}>{r.threshold_crossed_on ?? 'not crossed'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Page>
  )
}
