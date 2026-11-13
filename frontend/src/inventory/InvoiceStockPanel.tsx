import { inventoryApi, type ItemStockIn } from '../api/inventory'
import type { GstIn, GstItemIn } from '../api/gst'
import { Field, input, td, th } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { GodownSelect, ItemSelect, useInventoryMasters } from './common'

/** The GST item line plus the optional `stock` object of the Phase 5 contract (voucher integration). */
export type StockLine = GstItemIn & { stock?: ItemStockIn | null }

interface Props {
  clientId: string
  voucherType: string
  voucherDate: string
  value: GstIn
  onChange: (v: GstIn) => void
}

/**
 * Stock side of an invoice: per item line pick the stock item and godown (blank = the item's default godown).
 * Credit / Debit Note lines move stock only when "goods came back" is ticked, and then name the original movement (S-12).
 * No quantity or cost is decided here: the quantity is the invoice line's, the cost is the server's.
 */
export function InvoiceStockPanel({ clientId, voucherType, voucherDate, value, onChange }: Props) {
  const masters = useInventoryMasters()
  const note = voucherType === 'credit_note' || voucherType === 'debit_note'
  const items = value.items as StockLine[]
  if (masters.itemList.length === 0) return null
  const setItem = (i: number, patch: Partial<StockLine>) => onChange({ ...value, items: items.map((it, k) => (k === i ? { ...it, ...patch } : it)) })
  const pick = (i: number, id: string) => {
    const s = masters.itemList.find((x) => x.item_id === id)
    const it = items[i]
    setItem(i, id && s ? { item_id: id, description: it.description || s.name, hsn_sac: it.hsn_sac || s.hsn_sac, uqc: it.uqc ?? s.uqc } : { item_id: null, stock: null })
  }
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-3">
      <h3 className="text-xs font-semibold text-slate-700">Stock (inventory items only)</h3>
      <table className="border-collapse">
        <thead>
          <tr>
            <th className={th}>#</th>
            <th className={th}>Stock item</th>
            <th className={th}>Godown</th>
            {note && <th className={th}>Goods {voucherType === 'credit_note' ? 'returned by customer' : 'returned to supplier'}</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i}>
              <td className={td}>{i + 1}</td>
              <td className={td}>
                <ItemSelect items={masters.itemList} value={it.item_id ?? ''} onChange={(id) => pick(i, id)} blank="(not a stock item)" />
              </td>
              <td className={td}>
                {it.item_id && (!note || it.stock) && (
                  <GodownSelect
                    godowns={masters.godownList}
                    blank="(item's default godown)"
                    value={it.stock?.godown_id ?? ''}
                    onChange={(g) => setItem(i, { stock: { godown_id: g || null, original_movement_id: it.stock?.original_movement_id ?? null } })}
                  />
                )}
              </td>
              {note && (
                <td className={td}>
                  {it.item_id && (
                    <ReturnPick
                      clientId={clientId}
                      itemId={it.item_id}
                      on={voucherDate}
                      stock={it.stock ?? null}
                      onChange={(s) => setItem(i, { stock: s })}
                    />
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-500">A sale or purchase of a stock item always moves stock. {note ? 'A note moves stock only when you tick the box and choose the original sale / purchase.' : ''}</p>
    </div>
  )
}

function ReturnPick({ clientId, itemId, on, stock, onChange }: { clientId: string; itemId: string; on: string; stock: ItemStockIn | null; onChange: (s: ItemStockIn | null) => void }) {
  const moves = !!stock
  const list = useLoad(moves ? () => inventoryApi.returnable(clientId, itemId, on) : null, `inv-returnable:${clientId}:${itemId}:${on}:${moves}`)
  return (
    <div className="flex items-center gap-2">
      <Field label="">
        <input type="checkbox" checked={moves} onChange={(e) => onChange(e.target.checked ? { godown_id: null, original_movement_id: null } : null)} />
      </Field>
      {moves && (
        <select className={input} value={stock?.original_movement_id ?? ''} onChange={(e) => onChange({ godown_id: stock?.godown_id ?? null, original_movement_id: e.target.value || null })}>
          <option value="">(choose original movement)</option>
          {(list.data ?? []).map((r) => (
            <option key={r.movement_id} value={r.movement_id} disabled={Number(r.returnable) <= 0}>
              {r.voucher_number ?? r.kind} {r.date}: qty {r.quantity}, returnable {r.returnable}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
