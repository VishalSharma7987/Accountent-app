import { useState } from 'react'
import { api } from '../api'
import { gstApi, type GstItem, type GstItemBody, type RateLookup } from '../api/gst'
import { ErrorBox, Field, LedgerPicker, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { RuleBadge } from './common'

const blank = (): GstItemBody => ({
  name: '',
  item_kind: 'goods',
  hsn_sac: '',
  uqc: '',
  sales_ledger_id: null,
  purchase_ledger_id: null,
  default_itc_category_key: null,
  default_rcm_category_key: null,
  is_active: true,
})

export default function Items() {
  const { clientId } = useClient()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const items = useLoad(clientId ? () => gstApi.listItems(clientId, q, kind) : null, `gst-items:${clientId}:${q}:${kind}`)
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [form, setForm] = useState<GstItemBody | null>(null)
  const [editId, setEditId] = useState('')
  const [rate, setRate] = useState<RateLookup | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  if (!clientId) return <Page title="Item master">Select a client first.</Page>

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      await work()
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  const lookup = (hsn: string, itemKind: GstItemBody['item_kind']) =>
    act(async () => setRate(await gstApi.rateLookup(hsn.trim(), itemKind === 'goods' ? 'goods' : 'services')))
  const save = () =>
    act(async () => {
      if (!form) return
      if (editId) await gstApi.updateItem(clientId, editId, form)
      else await gstApi.createItem(clientId, form)
      setForm(null)
      setEditId('')
      setRate(null)
      setNotice('Item saved.')
      items.reload()
    })
  const edit = (i: GstItem) => {
    setEditId(i.id)
    const { id: _id, ...rest } = i
    void _id
    setForm(rest)
    setRate(null)
  }
  const set = (patch: Partial<GstItemBody>) => setForm((f) => (f ? { ...f, ...patch } : f))

  return (
    <Page
      title="Item master (HSN / SAC)"
      actions={
        <button
          className={btnPrimary}
          onClick={() => {
            setEditId('')
            setForm(blank())
            setRate(null)
          }}
        >
          Add item
        </button>
      }
    >
      <ErrorBox error={error ?? items.error} />
      {notice && <Notice>{notice}</Notice>}
      <div className="flex gap-3">
        <Field label="Search name / HSN">
          <input className={input} value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
        <Field label="Kind">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option>
            <option value="goods">Goods</option>
            <option value="service">Service</option>
          </select>
        </Field>
      </div>

      {form && (
        <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Name">
              <input className={`${input} w-56`} value={form.name} onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field label="Kind">
              <select className={input} value={form.item_kind} onChange={(e) => set({ item_kind: e.target.value as GstItemBody['item_kind'] })}>
                <option value="goods">Goods (HSN)</option>
                <option value="service">Service (SAC)</option>
              </select>
            </Field>
            <Field label="HSN / SAC">
              <input className={`${input} w-28 font-mono`} value={form.hsn_sac} onChange={(e) => set({ hsn_sac: e.target.value })} />
            </Field>
            <Field label="UQC">
              <input className={`${input} w-20 uppercase`} value={form.uqc} onChange={(e) => set({ uqc: e.target.value.toUpperCase() })} />
            </Field>
            <button className={btn} disabled={busy || !form.hsn_sac.trim()} onClick={() => lookup(form.hsn_sac, form.item_kind)}>
              Look up rate
            </button>
            <label className="flex items-center gap-1 text-xs text-slate-600">
              <input type="checkbox" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} /> Active
            </label>
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
            <Field label="Sales ledger">
              <LedgerPicker ledgers={ledgers.data ?? []} value={form.sales_ledger_id ?? ''} onChange={(id) => set({ sales_ledger_id: id || null })} />
            </Field>
            <Field label="Purchase ledger">
              <LedgerPicker ledgers={ledgers.data ?? []} value={form.purchase_ledger_id ?? ''} onChange={(id) => set({ purchase_ledger_id: id || null })} />
            </Field>
            <Field label="Default ITC category key">
              <input className={input} value={form.default_itc_category_key ?? ''} onChange={(e) => set({ default_itc_category_key: e.target.value || null })} />
            </Field>
            <Field label="Default RCM category key">
              <input className={input} value={form.default_rcm_category_key ?? ''} onChange={(e) => set({ default_rcm_category_key: e.target.value || null })} />
            </Field>
          </div>
          {rate && (
            <div className="rounded border border-slate-200 bg-slate-50 p-2 text-sm">
              Rate in force: <b>{rate.treatment}</b>, GST {rate.rate}%, cess {rate.cess_rate}%{' '}
              {rate.is_default && <span className="text-amber-800">(default rate: no rule for this HSN, confirm it)</span>}{' '}
              {rate.is_example && <span className="text-amber-800">(example data)</span>}
              <div className="text-xs text-slate-600">
                Rule {rate.rule_key} / {rate.verification_status} / {rate.source_reference} <RuleBadge worst={rate.verification_status} />
              </div>
            </div>
          )}
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={busy} onClick={save}>
              Save
            </button>
            <button
              className={btn}
              onClick={() => {
                setForm(null)
                setEditId('')
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            {['Name', 'Kind', 'HSN / SAC', 'UQC', 'Sales ledger', 'Purchase ledger', 'ITC cat.', 'RCM cat.', 'Active', ''].map((h) => (
              <th key={h} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(items.data ?? []).map((i) => {
            const name = (id: string | null) => ledgers.data?.find((l) => l.id === id)?.name ?? ''
            return (
              <tr key={i.id} className={i.is_active ? '' : 'text-slate-400'}>
                <td className={td}>{i.name}</td>
                <td className={td}>{i.item_kind}</td>
                <td className={`${td} font-mono`}>{i.hsn_sac}</td>
                <td className={td}>{i.uqc}</td>
                <td className={td}>{name(i.sales_ledger_id)}</td>
                <td className={td}>{name(i.purchase_ledger_id)}</td>
                <td className={td}>{i.default_itc_category_key ?? ''}</td>
                <td className={td}>{i.default_rcm_category_key ?? ''}</td>
                <td className={td}>{i.is_active ? 'Yes' : 'No'}</td>
                <td className={td}>
                  <button className={btn} onClick={() => edit(i)}>
                    Edit
                  </button>
                </td>
              </tr>
            )
          })}
          {items.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={10}>
                No items yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Page>
  )
}
