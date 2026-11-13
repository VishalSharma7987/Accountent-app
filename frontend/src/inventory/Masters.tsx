import { useState } from 'react'
import { gstApi } from '../api/gst'
import { inventoryApi, type OpeningRow, type StockItem } from '../api/inventory'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, GodownSelect, ItemSelect, NoClient, Row, Tabs, useFy, useInventoryMasters } from './common'
import { cleanNumber, isMoney, isQuantity } from './lib'

type Tab = 'godowns' | 'items' | 'opening'

/** Godowns, stock items (HSN / unit come from the GST item master) and opening stock per financial year. */
export default function Masters() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const [tab, setTab] = useState<Tab>('godowns')
  const masters = useInventoryMasters()
  if (!clientId)
    return (
      <Page title="Godowns, stock items and opening stock">
        <NoClient />
      </Page>
    )
  return (
    <Page title="Godowns, stock items and opening stock">
      <Tabs
        tabs={[
          { key: 'godowns', label: 'Godowns' },
          { key: 'items', label: 'Stock items' },
          { key: 'opening', label: 'Opening stock' },
        ]}
        value={tab}
        onChange={setTab}
      />
      <ErrorBox error={masters.godowns.error ?? masters.items.error} />
      {tab === 'godowns' && <GodownTab clientId={clientId} masters={masters} />}
      {tab === 'items' && <ItemTab clientId={clientId} fyId={fyId} masters={masters} />}
      {tab === 'opening' && (
        <>
          <Row>
            <FySelect years={years} value={fyId} onChange={setFyId} />
          </Row>
          {fyId ? <OpeningTab key={fyId} clientId={clientId} fyId={fyId} masters={masters} /> : <div className="text-sm text-slate-600">This client has no financial year.</div>}
        </>
      )}
    </Page>
  )
}

type Masters = ReturnType<typeof useInventoryMasters>

function GodownTab({ clientId, masters }: { clientId: string; masters: Masters }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      masters.godowns.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-2">
      <Row>
        <Field label="New godown">
          <input className={`${input} w-56`} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <button
          className={btnPrimary}
          disabled={!name.trim()}
          onClick={() =>
            run(async () => {
              await inventoryApi.addGodown(clientId, name.trim())
              setName('')
            })
          }
        >
          Add godown
        </button>
      </Row>
      <ErrorBox error={error} />
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Godown</th>
            <th className={th}>Status</th>
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          {masters.godownList.map((g) => (
            <tr key={g.id} className={g.is_active ? '' : 'text-slate-500'}>
              <td className={td}>{g.name}</td>
              <td className={td}>{g.is_active ? 'Active' : 'Inactive'}</td>
              <td className={td}>
                <button className={btn} onClick={() => run(() => inventoryApi.updateGodown(clientId, g.id, { is_active: !g.is_active }))}>
                  {g.is_active ? 'Deactivate' : 'Activate'}
                </button>
              </td>
            </tr>
          ))}
          {masters.godownList.length === 0 && (
            <tr>
              <td colSpan={3} className={`${td} text-slate-500`}>
                No godown yet. Add the first one (e.g. Main godown).
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function ItemTab({ clientId, fyId, masters }: { clientId: string; fyId: string; masters: Masters }) {
  const withOpening = useLoad(() => inventoryApi.listStockItems(clientId, { financial_year_id: fyId || undefined }), `inv-items-fy:${clientId}:${fyId}`)
  const gstItems = useLoad(() => gstApi.listItems(clientId, undefined, 'goods'), `inv-gst-goods:${clientId}`)
  const [gstItemId, setGstItemId] = useState('')
  const [sku, setSku] = useState('')
  const [godown, setGodown] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const stocked = new Set((masters.items.data ?? []).map((i) => i.item_id))
  const candidates = (gstItems.data ?? []).filter((g) => g.is_active && !stocked.has(g.id))
  const save = async (itemId: string, body: { sku: string; default_godown_id: string; is_active?: boolean }) => {
    setError(null)
    setNotice('')
    try {
      await inventoryApi.putStockItem(clientId, itemId, body)
      setNotice('Saved.')
      masters.items.reload()
      withOpening.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const rows: StockItem[] = withOpening.data ?? masters.itemList
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-600">Name, HSN and unit come from the GST item master (GST / Item master); create the goods item there first, then make it a stock item here.</p>
      <Row>
        <Field label="Goods item (GST master)">
          <select
            className={`${input} w-64`}
            value={gstItemId}
            onChange={(e) => {
              setGstItemId(e.target.value)
              setError(null)
            }}
          >
            <option value="">(choose)</option>
            {candidates.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} ({g.hsn_sac}, {g.uqc})
              </option>
            ))}
          </select>
        </Field>
        <Field label="SKU">
          <input className={`${input} w-32`} value={sku} onChange={(e) => setSku(e.target.value.trim())} />
        </Field>
        <Field label="Default godown">
          <GodownSelect godowns={masters.godownList} value={godown} onChange={setGodown} />
        </Field>
        <button
          className={btnPrimary}
          disabled={!gstItemId || !sku || !godown}
          onClick={async () => {
            await save(gstItemId, { sku, default_godown_id: godown })
            setGstItemId('')
            setSku('')
          }}
        >
          Make stock item
        </button>
      </Row>
      <ErrorBox error={error ?? withOpening.error} />
      {notice && <Notice>{notice}</Notice>}
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>SKU</th>
            <th className={th}>Item</th>
            <th className={th}>HSN</th>
            <th className={th}>Unit</th>
            <th className={th}>Default godown</th>
            <th className={thR}>Opening qty</th>
            <th className={thR}>Opening value</th>
            <th className={th}>Status</th>
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => (
            <ItemRow key={i.item_id} item={i} godowns={masters.godownList} onSave={(b) => save(i.item_id, b)} />
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={9} className={`${td} text-slate-500`}>
                No stock item yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function ItemRow({ item, godowns, onSave }: { item: StockItem; godowns: Masters['godownList']; onSave: (b: { sku: string; default_godown_id: string; is_active?: boolean }) => void }) {
  const [sku, setSku] = useState(item.sku)
  const [godown, setGodown] = useState(item.default_godown_id ?? '')
  const dirty = sku !== item.sku || godown !== (item.default_godown_id ?? '')
  return (
    <tr className={item.is_active ? '' : 'text-slate-500'}>
      <td className={td}>
        <input className={`${input} w-28`} value={sku} onChange={(e) => setSku(e.target.value.trim())} />
      </td>
      <td className={td}>{item.name}</td>
      <td className={`${td} font-mono`}>{item.hsn_sac}</td>
      <td className={td}>{item.uqc}</td>
      <td className={td}>
        <GodownSelect godowns={godowns} value={godown} onChange={setGodown} />
      </td>
      <td className={tdR}>{item.opening_qty ?? ''}</td>
      <td className={tdR}>{item.opening_value !== undefined && <Amount value={item.opening_value} />}</td>
      <td className={td}>{item.is_active ? 'Active' : 'Inactive'}</td>
      <td className={`${td} whitespace-nowrap`}>
        <button className={btn} disabled={!dirty || !sku || !godown} onClick={() => onSave({ sku, default_godown_id: godown })}>
          Save
        </button>{' '}
        <button className={btn} disabled={!godown} onClick={() => onSave({ sku, default_godown_id: godown, is_active: !item.is_active })}>
          {item.is_active ? 'Deactivate' : 'Activate'}
        </button>
      </td>
    </tr>
  )
}

interface OpenDraft {
  item_id: string
  godown_id: string
  quantity: string
  value: string
}

function OpeningTab({ clientId, fyId, masters }: { clientId: string; fyId: string; masters: Masters }) {
  const data = useLoad(() => inventoryApi.getOpening(clientId, fyId), `inv-open:${clientId}:${fyId}`)
  const [draft, setDraft] = useState<OpenDraft[] | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const rows: OpenDraft[] = draft ?? (data.data?.rows ?? []).map((r: OpeningRow) => ({ item_id: r.item_id, godown_id: r.godown_id, quantity: r.quantity, value: r.value }))
  const setRow = (i: number, patch: Partial<OpenDraft>) => setDraft(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  const bad = (r: OpenDraft) => !r.item_id || !r.godown_id || !isQuantity(r.quantity, true) || !isMoney(r.value)
  const save = async () => {
    setError(null)
    setNotice('')
    try {
      const out = await inventoryApi.putOpening(
        clientId,
        fyId,
        rows.map((r) => ({ ...r })),
      )
      setNotice(`Opening stock saved, total value ${out.total_value}.`)
      setDraft(null)
      data.reload()
      masters.items.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const ledgerDiff = data.data?.difference
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-600">Quantity up to 3 decimals; value is the amount in rupees (the unit cost is worked out by the server). Saving replaces the whole opening stock of this year.</p>
      <ErrorBox error={error ?? data.error} />
      {notice && <Notice>{notice}</Notice>}
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Item</th>
            <th className={th}>Godown</th>
            <th className={thR}>Quantity</th>
            <th className={thR}>Value</th>
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={bad(r) && (r.quantity || r.value) ? 'bg-red-50' : ''}>
              <td className={td}>
                <ItemSelect items={masters.itemList} value={r.item_id} onChange={(v) => setRow(i, { item_id: v })} />
              </td>
              <td className={td}>
                <GodownSelect godowns={masters.godownList} value={r.godown_id} onChange={(v) => setRow(i, { godown_id: v })} />
              </td>
              <td className={td}>
                <input className={`${input} w-28 text-right`} value={r.quantity} onChange={(e) => setRow(i, { quantity: cleanNumber(e.target.value) })} />
              </td>
              <td className={td}>
                <input className={`${input} w-32 text-right`} value={r.value} onChange={(e) => setRow(i, { value: cleanNumber(e.target.value) })} />
              </td>
              <td className={td}>
                <button className={btn} onClick={() => setDraft(rows.filter((_, k) => k !== i))}>
                  x
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Row>
        <button className={btn} onClick={() => setDraft([...rows, { item_id: '', godown_id: '', quantity: '', value: '' }])}>
          Add row
        </button>
        <button className={btnPrimary} disabled={rows.some(bad)} onClick={save}>
          Save opening stock
        </button>
        {draft && (
          <button className={btn} onClick={() => setDraft(null)}>
            Discard changes
          </button>
        )}
      </Row>
      {data.data && (
        <div className="text-sm">
          Saved total <b>{<Amount value={data.data.total_value} />}</b>
          {data.data.ledger_opening_value !== null && (
            <>
              {' '}
              | Stock-in-hand ledger opening <Amount value={data.data.ledger_opening_value} />
              {ledgerDiff && ledgerDiff !== '0.00' ? <span className="ml-2 rounded border border-amber-400 bg-amber-50 px-2 py-0.5 text-amber-900">Difference <Amount value={ledgerDiff} /> (information only)</span> : <span className="ml-2 text-green-700">agrees</span>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
