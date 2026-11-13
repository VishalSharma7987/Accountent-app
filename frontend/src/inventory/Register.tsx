import { useState } from 'react'
import { inventoryApi, downloadFile, type RegisterRow } from '../api/inventory'
import { Amount, ErrorBox, Field, Page, btn, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, GodownSelect, Issues, ItemSelect, NoClient, Row, useFy, useInventoryMasters } from './common'
import { methodLabel } from './lib'

/** Stock register: opening, inward, outward, closing quantity and value per item. Everything is computed by the server from posted movements. */
export default function Register() {
  const { clientId } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const masters = useInventoryMasters()
  const [itemId, setItemId] = useState('')
  const [godownId, setGodownId] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [drill, setDrill] = useState<RegisterRow | null>(null)
  const [exportError, setExportError] = useState<ApiFailure | null>(null)
  const query = { financial_year_id: fyId, from: from || undefined, to: to || undefined, item_id: itemId || undefined, godown_id: godownId || undefined }
  const reg = useLoad(clientId && fyId ? () => inventoryApi.stockRegister(clientId, query) : null, `inv-reg:${clientId}:${fyId}:${from}:${to}:${itemId}:${godownId}`)
  if (!clientId)
    return (
      <Page title="Stock register">
        <NoClient />
      </Page>
    )
  const data = reg.data
  const godownMode = !!godownId
  const download = async () => {
    setExportError(null)
    try {
      await downloadFile(inventoryApi.registerExportPath(clientId), 'stock-register.xlsx', query)
    } catch (e) {
      setExportError(asFailure(e))
    }
  }
  return (
    <Page
      title="Stock register"
      actions={
        <button className={btn} disabled={!fyId} onClick={download}>
          Export to Excel
        </button>
      }
    >
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <Field label="From (blank = year start)">
          <input type="date" className={input} value={from} min={fy?.start_date} max={fy?.end_date} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To (blank = year end)">
          <input type="date" className={input} value={to} min={fy?.start_date} max={fy?.end_date} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <Field label="Item">
          <ItemSelect items={masters.itemList} value={itemId} onChange={setItemId} blank="All items" />
        </Field>
        <Field label="Godown">
          <GodownSelect godowns={masters.godownList} value={godownId} onChange={setGodownId} blank="All godowns" />
        </Field>
      </Row>
      <ErrorBox error={reg.error ?? exportError} />
      {data && (
        <div className="text-xs text-slate-600">
          Valuation: <b>{methodLabel(data.policy?.valuation_method)}</b>, {data.from} to {data.to}
          {godownMode && ' | Godown view: quantities only (valuation is per item, not per godown).'}
        </div>
      )}
      <Issues errors={data?.errors} warnings={data?.warnings} />
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>SKU</th>
            <th className={th}>Item</th>
            <th className={th}>Unit</th>
            <th className={thR}>Opening qty</th>
            <th className={thR}>Opening value</th>
            <th className={thR}>Inward qty</th>
            <th className={thR}>Inward value</th>
            <th className={thR}>Outward qty</th>
            <th className={thR}>Outward value</th>
            <th className={thR}>Closing qty</th>
            <th className={thR}>Closing value</th>
          </tr>
        </thead>
        <tbody>
          {(data?.rows ?? []).map((r) => (
            <tr key={r.item_id}>
              <td className={td}>{r.sku}</td>
              <td className={td}>
                <button className="text-blue-700 underline" onClick={() => setDrill(r)}>
                  {r.name}
                </button>
              </td>
              <td className={td}>{r.uqc}</td>
              <td className={tdR}>{r.opening_qty}</td>
              <td className={tdR}>{r.opening_value !== null && <Amount value={r.opening_value} />}</td>
              <td className={tdR}>{r.inward_qty}</td>
              <td className={tdR}>{r.inward_value !== null && <Amount value={r.inward_value} />}</td>
              <td className={tdR}>{r.outward_qty}</td>
              <td className={tdR}>{r.outward_value !== null && <Amount value={r.outward_value} />}</td>
              <td className={tdR}>{r.closing_qty}</td>
              <td className={tdR}>{r.closing_value !== null && <Amount value={r.closing_value} />}</td>
            </tr>
          ))}
          {data && data.rows.length === 0 && (
            <tr>
              <td colSpan={11} className={`${td} text-slate-500`}>
                No stock item or movement for these filters.
              </td>
            </tr>
          )}
        </tbody>
        {data && !godownMode && (
          <tfoot>
            <tr className="bg-slate-100 font-semibold">
              <td className={td} colSpan={4}>
                Total value
              </td>
              <td className={tdR}>
                <Amount value={data.totals.opening_value} />
              </td>
              <td className={td} />
              <td className={tdR}>
                <Amount value={data.totals.inward_value} />
              </td>
              <td className={td} />
              <td className={tdR}>
                <Amount value={data.totals.outward_value} />
              </td>
              <td className={td} />
              <td className={tdR}>
                <Amount value={data.totals.closing_value} />
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      {drill && <ItemLedger clientId={clientId} fyId={fyId} row={drill} from={from} to={to} godowns={masters.godownList} onClose={() => setDrill(null)} />}
    </Page>
  )
}

function ItemLedger({ clientId, fyId, row, from, to, godowns, onClose }: { clientId: string; fyId: string; row: RegisterRow; from: string; to: string; godowns: { id: string; name: string }[]; onClose: () => void }) {
  const led = useLoad(() => inventoryApi.itemLedger(clientId, row.item_id, { financial_year_id: fyId, from: from || undefined, to: to || undefined }), `inv-led:${clientId}:${row.item_id}:${fyId}:${from}:${to}`)
  const gname = (id: string) => godowns.find((g) => g.id === id)?.name ?? ''
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          Movements of {row.sku} {row.name}
        </h2>
        <button className={btn} onClick={onClose}>
          Close
        </button>
      </div>
      <ErrorBox error={led.error} />
      <table className="min-w-full border-collapse">
        <thead>
          <tr>
            <th className={th}>Date</th>
            <th className={th}>Kind</th>
            <th className={th}>Document</th>
            <th className={th}>Godown</th>
            <th className={thR}>In qty</th>
            <th className={thR}>In value</th>
            <th className={thR}>Out qty</th>
            <th className={thR}>Out value</th>
            <th className={thR}>Balance qty</th>
            <th className={thR}>Balance value</th>
          </tr>
        </thead>
        <tbody>
          {(led.data?.rows ?? []).map((m, i) => (
            <tr key={i}>
              <td className={td}>{m.date}</td>
              <td className={td}>{m.kind}</td>
              <td className={`${td} font-mono`}>{m.voucher_number ?? m.journal_number ?? ''}</td>
              <td className={td}>{gname(m.godown_id)}</td>
              <td className={tdR}>{m.in_qty}</td>
              <td className={tdR}>{m.in_value !== null && <Amount value={m.in_value} />}</td>
              <td className={tdR}>{m.out_qty}</td>
              <td className={tdR}>{m.out_value !== null && <Amount value={m.out_value} />}</td>
              <td className={tdR}>{m.balance_qty}</td>
              <td className={tdR}>{m.balance_value !== null && <Amount value={m.balance_value} />}</td>
            </tr>
          ))}
          {led.data && led.data.rows.length === 0 && (
            <tr>
              <td colSpan={10} className={`${td} text-slate-500`}>
                No movement in this period.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
