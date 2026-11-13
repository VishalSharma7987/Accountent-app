import { inventoryApi, type Godown, type StockIssue, type StockItem } from '../api/inventory'
import { useClient } from '../context'
import { useLoad } from '../lib/useLoad'

export { FySelect, NoClient, Row, Tabs, useFy } from '../tds/common'

/** Active-and-inactive godowns and stock items of the selected client, with reload. */
export function useInventoryMasters() {
  const { clientId } = useClient()
  const godowns = useLoad<Godown[]>(clientId ? () => inventoryApi.listGodowns(clientId) : null, `inv-godowns:${clientId}`)
  const items = useLoad<StockItem[]>(clientId ? () => inventoryApi.listStockItems(clientId) : null, `inv-items:${clientId}`)
  return { godowns, items, godownList: godowns.data ?? [], itemList: items.data ?? [] }
}

export function Issues({ errors = [], warnings = [] }: { errors?: StockIssue[]; warnings?: StockIssue[] }) {
  return (
    <>
      {errors.length > 0 && (
        <ul className="list-disc rounded border border-red-300 bg-red-50 py-1 pl-6 pr-3 text-sm text-red-800">
          {errors.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="list-disc rounded border border-amber-300 bg-amber-50 py-1 pl-6 pr-3 text-sm text-amber-900">
          {warnings.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

export function ItemSelect({ items, value, onChange, blank = '(choose item)', className }: { items: StockItem[]; value: string; onChange: (id: string) => void; blank?: string; className?: string }) {
  return (
    <select className={`rounded border border-slate-300 px-2 py-1 text-sm ${className ?? ''}`} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{blank}</option>
      {items
        .filter((i) => i.is_active || i.item_id === value)
        .map((i) => (
          <option key={i.item_id} value={i.item_id}>
            {i.sku} {i.name} ({i.uqc})
          </option>
        ))}
    </select>
  )
}

export function GodownSelect({ godowns, value, onChange, blank = '(godown)', className }: { godowns: Godown[]; value: string; onChange: (id: string) => void; blank?: string; className?: string }) {
  return (
    <select className={`rounded border border-slate-300 px-2 py-1 text-sm ${className ?? ''}`} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{blank}</option>
      {godowns
        .filter((g) => g.is_active || g.id === value)
        .map((g) => (
          <option key={g.id} value={g.id}>
            {g.name}
          </option>
        ))}
    </select>
  )
}
