import { useState } from 'react'
import { inventoryApi, downloadFile } from '../api/inventory'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { today } from '../lib/dates'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, Issues, NoClient, Row, useFy } from './common'
import { cleanNumber, hasWriteDown, methodLabel, nrvRows } from './lib'

/** Closing stock at lower of cost and net realisable value (AS 2). Cost, NRV value and write-down are the server's figures. */
export default function ClosingStock() {
  const { clientId } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const [asOn, setAsOn] = useState('')
  const [drafts, setDrafts] = useState<Record<string, { nrv: string; note: string }>>({})
  const [error, setError] = useState<ApiFailure | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [notice, setNotice] = useState('')
  const key = `${clientId}:${fyId}:${asOn}`
  const rep = useLoad(clientId && fyId ? () => inventoryApi.closingStock(clientId, { financial_year_id: fyId, as_on: asOn || undefined }) : null, `inv-closing:${key}`)
  const saved = useLoad(clientId && fyId ? () => inventoryApi.getNrv(clientId, fyId, asOn || undefined) : null, `inv-nrv:${key}`)
  if (!clientId)
    return (
      <Page title="Closing stock valuation">
        <NoClient />
      </Page>
    )
  const data = rep.data
  const dateForNrv = asOn || data?.as_on || fy?.end_date || today()
  const savedFor = (id: string) => saved.data?.rows.find((r) => r.item_id === id)
  const value = (id: string) => drafts[id] ?? { nrv: savedFor(id)?.nrv_per_unit ?? '', note: savedFor(id)?.basis_note ?? '' }
  const setDraft = (id: string, patch: Partial<{ nrv: string; note: string }>) => setDrafts({ ...drafts, [id]: { ...value(id), ...patch } })
  const saveNrv = async () => {
    setError(null)
    setNotice('')
    const edited = Object.fromEntries(Object.keys(drafts).map((id) => [id, drafts[id]]))
    const { rows, problems: p } = nrvRows(edited)
    setProblems(p)
    if (p.length > 0 || rows.length === 0) return
    try {
      await inventoryApi.putNrv(clientId, fyId, { as_on_date: dateForNrv, rows })
      setNotice(`NRV saved as on ${dateForNrv}.`)
      setDrafts({})
      rep.reload()
      saved.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const download = async () => {
    setError(null)
    try {
      await downloadFile(inventoryApi.closingExportPath(clientId), 'closing-stock.xlsx', { financial_year_id: fyId, as_on: asOn || undefined })
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const missing = new Set(data?.items_without_nrv ?? [])
  return (
    <Page
      title="Closing stock valuation (lower of cost and NRV)"
      actions={
        <button className={btn} disabled={!fyId} onClick={download}>
          Export to Excel
        </button>
      }
    >
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <Field label="As on (blank = year end)">
          <input type="date" className={input} value={asOn} min={fy?.start_date} max={fy?.end_date} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
      </Row>
      <p className="text-xs text-slate-600">Enter the net realisable value per unit with a basis note (quote, price list, post-year sales). Items with no NRV are carried at cost and listed as a warning; the write-down below is calculated by the server (AS 2).</p>
      {data && (
        <div className="text-xs text-slate-600">
          Valuation: <b>{methodLabel(data.policy?.valuation_method)}</b>, as on {data.as_on}
        </div>
      )}
      <ErrorBox error={error ?? rep.error ?? saved.error} />
      {notice && <Notice>{notice}</Notice>}
      {problems.length > 0 && (
        <ul className="list-disc rounded border border-red-300 bg-red-50 py-1 pl-6 pr-3 text-sm text-red-800">
          {problems.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}
      <Issues errors={data?.errors} warnings={data?.warnings} />
      {data && missing.size > 0 && <div className="rounded border border-amber-400 bg-amber-50 px-3 py-1 text-sm text-amber-900">{missing.size} item(s) have no NRV entered (S-15); they are carried at cost.</div>}
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>SKU</th>
            <th className={th}>Item</th>
            <th className={thR}>Closing qty</th>
            <th className={thR}>Cost value</th>
            <th className={thR}>NRV per unit</th>
            <th className={th}>Basis of NRV</th>
            <th className={thR}>NRV value</th>
            <th className={thR}>Write-down (AS 2)</th>
            <th className={thR}>Carrying value</th>
          </tr>
        </thead>
        <tbody>
          {(data?.rows ?? []).map((r) => {
            const v = value(r.item_id)
            const down = Number(r.write_down) > 0
            return (
              <tr key={r.item_id} className={down ? 'bg-amber-50' : missing.has(r.item_id) ? 'bg-slate-50' : ''}>
                <td className={td}>{r.sku}</td>
                <td className={td}>{r.name}</td>
                <td className={tdR}>{r.closing_qty}</td>
                <td className={tdR}>
                  <Amount value={r.cost_value} />
                </td>
                <td className={td}>
                  <input className={`${input} w-24 text-right`} value={v.nrv} onChange={(e) => setDraft(r.item_id, { nrv: cleanNumber(e.target.value) })} />
                </td>
                <td className={td}>
                  <input className={`${input} w-48`} value={v.note} onChange={(e) => setDraft(r.item_id, { note: e.target.value })} />
                </td>
                <td className={tdR}>{r.nrv_value !== null && <Amount value={r.nrv_value} />}</td>
                <td className={`${tdR} ${down ? 'font-semibold text-red-700' : ''}`}>
                  <Amount value={r.write_down} />
                </td>
                <td className={tdR}>
                  <Amount value={r.carrying_value} />
                </td>
              </tr>
            )
          })}
          {data && data.rows.length === 0 && (
            <tr>
              <td colSpan={9} className={`${td} text-slate-500`}>
                No stock on hand.
              </td>
            </tr>
          )}
        </tbody>
        {data && (
          <tfoot>
            <tr className="bg-slate-100 font-semibold">
              <td className={td} colSpan={3}>
                Total
              </td>
              <td className={tdR}>
                <Amount value={data.totals.cost_value} />
              </td>
              <td className={td} colSpan={3} />
              <td className={tdR}>
                <Amount value={data.totals.write_down} />
              </td>
              <td className={tdR}>
                <Amount value={data.totals.carrying_value} />
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      <Row>
        <button className={btnPrimary} disabled={Object.keys(drafts).length === 0} onClick={saveNrv}>
          Save NRV (as on {dateForNrv})
        </button>
        {data && hasWriteDown(data.rows) && <span className="text-sm text-red-700">Stock is written down to NRV for the highlighted items.</span>}
      </Row>
    </Page>
  )
}
