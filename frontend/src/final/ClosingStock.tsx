import { useState } from 'react'
import { finalApi, type StockSource } from '../api/final'
import { Amount, ErrorBox, Field, Notice, Page, btnPrimary, input, td, tdR } from '../components/ui'
import { useClient } from '../context'
import { DataView } from '../gst/common'
import type { ApiFailure } from '../lib/apiError'
import { cleanTyped, toPaise } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, NoClient, Problems, Row, Section, useFy } from './common'
import { CLOSING_STOCK_SOURCES } from './lib'

/** Approve the closing stock figure the Trading account uses (F-41). Values from the stock report are read by the server, never typed. */
export default function ClosingStock() {
  const { clientId } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const [source, setSource] = useState<StockSource>('inventory_report')
  const [asOn, setAsOn] = useState('')
  const [cost, setCost] = useState('')
  const [down, setDown] = useState('')
  const [note, setNote] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const stock = useLoad(clientId && fyId ? () => finalApi.getClosingStock(clientId, fyId) : null, `final-cstock:${clientId}:${fyId}`)
  if (!clientId)
    return (
      <Page title="Closing stock approval">
        <NoClient />
      </Page>
    )
  const date = asOn || fy?.end_date || ''
  const approved = stock.data?.approved
  const save = async () => {
    setError(null)
    setNotice('')
    const p: string[] = []
    if (!date) p.push('Enter the stock date.')
    if (note.trim() === '') p.push('Enter the basis note.')
    const c = cleanTyped(cost)
    const d = cleanTyped(down)
    if (source === 'manual') {
      if (c === '' || toPaise(c) === null) p.push('Enter the cost value with at most 2 decimals.')
      if (d !== '' && toPaise(d) === null) p.push('Write-down must have at most 2 decimals.')
    }
    setProblems(p)
    if (p.length > 0) return
    try {
      const r = await finalApi.putClosingStock(clientId, fyId, {
        source,
        as_on_date: date,
        cost_value: source === 'manual' ? c : null,
        write_down: source === 'manual' ? d || '0.00' : null,
        basis_note: note.trim(),
      })
      setNotice(`Closing stock approved at carrying value ${r.carrying_value}.`)
      stock.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Closing stock approval">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
      </Row>
      <ErrorBox error={error ?? stock.error} />
      {notice && <Notice>{notice}</Notice>}
      <Section title="Approved closing stock">
        {!approved && <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">Not approved yet (F-41). The Trading account and the year-end close are blocked until it is.</div>}
        {approved && (
          <table className="border-collapse">
            <tbody>
              <tr>
                <td className={td}>As on</td>
                <td className={td}>{approved.as_on_date}</td>
              </tr>
              <tr>
                <td className={td}>Source / method</td>
                <td className={td}>
                  {approved.source.replace(/_/g, ' ')} {approved.inventory_method ? `(${approved.inventory_method})` : ''}
                </td>
              </tr>
              <tr>
                <td className={td}>Cost value</td>
                <td className={tdR}>
                  <Amount value={approved.cost_value} />
                </td>
              </tr>
              <tr>
                <td className={td}>Write-down (AS 2)</td>
                <td className={tdR}>
                  <Amount value={approved.write_down} />
                </td>
              </tr>
              <tr className="font-semibold">
                <td className={td}>Carrying value used in the accounts</td>
                <td className={tdR}>
                  <Amount value={approved.carrying_value} />
                </td>
              </tr>
              <tr>
                <td className={td}>Basis</td>
                <td className={td}>{approved.basis_note}</td>
              </tr>
              <tr>
                <td className={td}>Approved by</td>
                <td className={td}>
                  {approved.approved_by} {approved.approved_at?.slice(0, 10)}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </Section>
      {stock.data?.proposal && (
        <Section title="Closing stock report (Phase 5) proposal">
          <DataView value={stock.data.proposal} />
        </Section>
      )}
      <Section title={approved ? 'Approve again (replaces the figure, audit-logged)' : 'Approve closing stock'}>
        <Row>
          <Field label="Source">
            <select className={input} value={source} onChange={(e) => setSource(e.target.value as StockSource)}>
              {CLOSING_STOCK_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Stock as on">
            <input type="date" className={input} value={date} onChange={(e) => setAsOn(e.target.value)} />
          </Field>
          {source === 'manual' && (
            <>
              <Field label="Cost value">
                <input className={`${input} w-32 text-right`} value={cost} onChange={(e) => setCost(e.target.value)} />
              </Field>
              <Field label="Write-down">
                <input className={`${input} w-32 text-right`} value={down} onChange={(e) => setDown(e.target.value)} />
              </Field>
            </>
          )}
          <Field label="Basis note (required)">
            <input className={`${input} w-80`} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <button className={btnPrimary} disabled={!fyId} onClick={save}>
            Approve closing stock
          </button>
        </Row>
        {source === 'inventory_report' && <p className="text-xs text-slate-600">The cost and the AS 2 write-down are read from the closing stock report by the server.</p>}
        {source === 'none' && <p className="text-xs text-slate-600">Only for a client that holds no stock. The server refuses it for a trading or manufacturing client.</p>}
        <Problems items={problems} />
      </Section>
    </Page>
  )
}
