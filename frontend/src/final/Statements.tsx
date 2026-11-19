import { useState } from 'react'
import { Link } from 'react-router-dom'
import { finalApi, type Statement } from '../api/final'
import { Amount, ErrorBox, Field, Page, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { useLoad } from '../lib/useLoad'
import { ExportButtons } from './Export'
import { FySelect, NoClient, Row, StatementView, Tabs, useFy } from './common'
import { drillHref } from './lib'

type Which = 'trading' | 'profit_loss' | 'balance_sheet' | 'appropriation' | 'positions'

/** Trading account, Profit and Loss, Balance Sheet (non-company) and the appropriation account (firms). All figures are the server's; ledger names open the Ledger statement. */
export default function Statements() {
  const { clientId, client } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const [which, setWhich] = useState<Which>('trading')
  const [format, setFormat] = useState<'vertical' | 'horizontal'>('vertical')
  const [asOn, setAsOn] = useState('')
  const isCompany = client?.entity_type === 'company'
  const isFirm = client?.entity_type === 'partnership' || client?.entity_type === 'llp'
  const run = (): Promise<Statement | null> => {
    const q = { financial_year_id: fyId, as_on: asOn || undefined }
    if (which === 'trading') return finalApi.trading(clientId, q)
    if (which === 'profit_loss') return finalApi.profitLoss(clientId, { ...q, format })
    if (which === 'balance_sheet') return finalApi.balanceSheet(clientId, { ...q, format })
    if (which === 'appropriation') return finalApi.appropriation(clientId, fyId)
    return Promise.resolve(null)
  }
  const stmt = useLoad<Statement | null>(clientId && fyId && !isCompany && which !== 'positions' ? run : null, `final-stmt:${clientId}:${fyId}:${which}:${format}:${asOn}`)
  const pos = useLoad(clientId && fyId && !isCompany && which === 'positions' ? () => finalApi.ledgerPositions(clientId, { financial_year_id: fyId, as_on: asOn || undefined }) : null, `final-pos:${clientId}:${fyId}:${asOn}`)
  if (!clientId)
    return (
      <Page title="Trading, Profit and Loss, Balance Sheet">
        <NoClient />
      </Page>
    )
  if (isCompany)
    return (
      <Page title="Trading, Profit and Loss, Balance Sheet">
        <div className="rounded border border-slate-300 bg-white p-3 text-sm">
          This client is a company: its statements follow Schedule III. Open <Link className="text-blue-700 underline" to="/final/sch3">Schedule III statements</Link>.
        </div>
      </Page>
    )
  const tabs: { key: Which; label: string }[] = [
    { key: 'trading', label: 'Trading account' },
    { key: 'profit_loss', label: 'Profit and Loss' },
    { key: 'balance_sheet', label: 'Balance Sheet' },
    ...(isFirm ? [{ key: 'appropriation' as Which, label: 'Appropriation' }] : []),
    { key: 'positions', label: 'Ledger positions' },
  ]
  const formatted = which === 'profit_loss' || which === 'balance_sheet'
  const horizontal = format === 'horizontal'
  const titles: Record<string, [string, string]> = {
    trading: ['Debit', 'Credit'],
    profit_loss: ['Debit (expenses)', 'Credit (incomes)'],
    balance_sheet: ['Liabilities', 'Assets'],
  }
  return (
    <Page title="Trading, Profit and Loss, Balance Sheet">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <Field label="As on (blank = year end; earlier gives a provisional statement)">
          <input type="date" className={input} value={asOn} min={fy?.start_date} max={fy?.end_date} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        {formatted && (
          <Field label="Format">
            <select className={input} value={format} onChange={(e) => setFormat(e.target.value as 'vertical' | 'horizontal')}>
              <option value="vertical">Vertical</option>
              <option value="horizontal">Horizontal (T-form)</option>
            </select>
          </Field>
        )}
      </Row>
      {which !== 'positions' && <ExportButtons fyId={fyId} statements={[which]} layout={horizontal ? 'horizontal' : 'vertical'} />}
      <Tabs tabs={tabs} value={which} onChange={setWhich} />
      <ErrorBox error={stmt.error ?? pos.error} />
      {which !== 'positions' && stmt.data && <StatementView s={stmt.data} horizontal={formatted && horizontal} leftTitle={titles[which]?.[0]} rightTitle={titles[which]?.[1]} />}
      {which === 'positions' && (
        <table className="min-w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className={th}>Ledger</th>
              <th className={th}>Group</th>
              <th className={thR}>Opening</th>
              <th className={thR}>Debit</th>
              <th className={thR}>Credit</th>
              <th className={thR}>Closing</th>
            </tr>
          </thead>
          <tbody>
            {(pos.data ?? []).map((p) => (
              <tr key={p.ledger_id}>
                <td className={td}>
                  <Link className="text-blue-700 underline" to={drillHref(p.ledger_id, fy?.start_date ?? '', asOn || fy?.end_date || '')}>
                    {p.name}
                  </Link>
                </td>
                <td className={td}>{p.group_code}</td>
                <td className={tdR}>
                  <Amount value={p.opening} />
                </td>
                <td className={tdR}>
                  <Amount value={p.debit_total} />
                </td>
                <td className={tdR}>
                  <Amount value={p.credit_total} />
                </td>
                <td className={tdR}>
                  <Amount value={p.closing} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {stockNote(stmt.error?.code)}
    </Page>
  )
}

function stockNote(code: string | undefined) {
  if (code === 'closing_stock_missing') return <div className="text-sm">Approve the closing stock under Final accounts / Closing stock approval first.</div>
  return null
}
