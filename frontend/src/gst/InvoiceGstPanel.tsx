import { useEffect, useRef, useState } from 'react'
import { gstApi, type GstIn, type GstPreview, type GstVoucherBody, type Registration } from '../api/gst'
import { Amount, Field, LedgerPicker, btn, input, td, tdR, th, thR } from '../components/ui'
import { asFailure } from '../lib/useLoad'
import type { LedgerRow } from '../types'
import { blankGstItem, previewBody, SUPPLY_CATEGORIES } from './lib'

export interface InvoicePanelProps {
  clientId: string
  registrations: Registration[]
  ledgers: LedgerRow[]
  /** voucher header fields (the panel never edits these) */
  base: Omit<GstVoucherBody, 'gst'>
  value: GstIn
  onChange: (v: GstIn) => void
  /** called with every server preview so the parent can show or block on errors */
  onPreview?: (p: GstPreview | null) => void
  readOnly?: boolean
}

/**
 * Invoice-mode panel: registration, place of supply, item grid, and a READ-ONLY tax preview.
 * The tax lines come from POST /vouchers/gst-preview on every change; nothing is calculated here (G-14).
 */
export function InvoiceGstPanel({ clientId, registrations, ledgers, base, value, onChange, onPreview, readOnly }: InvoicePanelProps) {
  const [preview, setPreview] = useState<GstPreview | null>(null)
  const [failure, setFailure] = useState('')
  const [loading, setLoading] = useState(false)
  const onPreviewRef = useRef(onPreview)
  onPreviewRef.current = onPreview
  const purchase = base.voucher_type === 'purchase' || base.voucher_type === 'debit_note'
  const note = base.voucher_type === 'credit_note' || base.voucher_type === 'debit_note'

  const body = previewBody(base, value)
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
      gstApi
        .gstPreview(clientId, JSON.parse(sig) as GstVoucherBody)
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

  const set = (patch: Partial<GstIn>) => onChange({ ...value, ...patch })
  const setItem = (i: number, patch: Partial<GstIn['items'][number]>) =>
    set({ items: value.items.map((it, k) => (k === i ? { ...it, ...patch } : it)) })
  const itemErrors = (n: number) => (preview?.errors ?? []).filter((e) => e.details?.item_line_no === n)
  const headerErrors = (preview?.errors ?? []).filter((e) => !e.details?.item_line_no)

  return (
    <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="GST registration">
          <select className={input} disabled={readOnly} value={value.gst_registration_id} onChange={(e) => set({ gst_registration_id: e.target.value })}>
            <option value="">(choose)</option>
            {registrations
              .filter((r) => r.is_active)
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.gstin} {r.state_name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Document">
          <select className={input} disabled={readOnly} value={value.document_kind} onChange={(e) => set({ document_kind: e.target.value as GstIn['document_kind'] })}>
            <option value="tax_invoice">Tax invoice</option>
            <option value="bill_of_supply">Bill of supply</option>
            <option value="self_invoice">Self invoice (RCM)</option>
          </select>
        </Field>
        <Field label="Supply category">
          <select className={input} disabled={readOnly} value={value.supply_category} onChange={(e) => set({ supply_category: e.target.value })}>
            {SUPPLY_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Place of supply (state code)">
          <input className={`${input} w-16`} disabled={readOnly} value={value.place_of_supply} maxLength={2} onChange={(e) => set({ place_of_supply: e.target.value.trim() })} />
        </Field>
        <Field label={purchase ? "Supplier's invoice date" : 'Invoice date'}>
          <input type="date" className={input} disabled={readOnly} value={value.invoice_date} onChange={(e) => set({ invoice_date: e.target.value })} />
        </Field>
        <Field label="Counterparty GSTIN (blank = party's)">
          <input className={`${input} w-44 font-mono uppercase`} disabled={readOnly} value={value.counterparty_gstin ?? ''} onChange={(e) => set({ counterparty_gstin: e.target.value.trim().toUpperCase() || null })} />
        </Field>
      </div>
      {note && (
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Original invoice no">
            <input className={input} disabled={readOnly} value={value.original_invoice_no ?? ''} onChange={(e) => set({ original_invoice_no: e.target.value || null })} />
          </Field>
          <Field label="Original invoice date">
            <input type="date" className={input} disabled={readOnly} value={value.original_invoice_date ?? ''} onChange={(e) => set({ original_invoice_date: e.target.value || null })} />
          </Field>
          <Field label="Reason">
            <input className={`${input} w-64`} disabled={readOnly} value={value.note_reason ?? ''} onChange={(e) => set({ note_reason: e.target.value || null })} />
          </Field>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr>
              {['#', 'Description', 'HSN / SAC', 'UQC', 'Ledger'].map((h) => (
                <th key={h} className={th}>
                  {h}
                </th>
              ))}
              {['Qty', 'Rate', 'Discount'].map((h) => (
                <th key={h} className={thR}>
                  {h}
                </th>
              ))}
              {purchase && <th className={th}>ITC category / RCM</th>}
              <th className={thR}>Taxable</th>
              <th className={th}>Tax (from server)</th>
              <th className={th} />
            </tr>
          </thead>
          <tbody>
            {value.items.map((it, i) => {
              const out = preview?.gst.items.find((x) => x.item_line_no === i + 1)
              const errs = itemErrors(i + 1)
              return (
                <tr key={i} className={errs.length ? 'bg-red-50' : ''}>
                  <td className={td}>{i + 1}</td>
                  <td className={td}>
                    <input className={`${input} w-44`} disabled={readOnly} value={it.description} onChange={(e) => setItem(i, { description: e.target.value })} />
                  </td>
                  <td className={td}>
                    <input className={`${input} w-24 font-mono`} disabled={readOnly} value={it.hsn_sac} onChange={(e) => setItem(i, { hsn_sac: e.target.value.trim() })} />
                  </td>
                  <td className={td}>
                    <input className={`${input} w-16 uppercase`} disabled={readOnly} value={it.uqc ?? ''} onChange={(e) => setItem(i, { uqc: e.target.value.toUpperCase() || null })} />
                  </td>
                  <td className={`${td} min-w-44`}>
                    <LedgerPicker ledgers={ledgers} value={it.ledger_id} onChange={(id) => setItem(i, { ledger_id: id })} invalid={errs.length > 0 && !it.ledger_id} />
                  </td>
                  {(['quantity', 'unit_rate', 'discount'] as const).map((f) => (
                    <td key={f} className={td}>
                      <input className={`${input} w-24 text-right`} disabled={readOnly} value={it[f]} onChange={(e) => setItem(i, { [f]: e.target.value.trim() })} />
                    </td>
                  ))}
                  {purchase && (
                    <td className={td}>
                      <input className={`${input} w-28`} placeholder="ITC cat." disabled={readOnly} value={it.itc_category_key ?? ''} onChange={(e) => setItem(i, { itc_category_key: e.target.value || null })} />{' '}
                      <input className={`${input} w-28`} placeholder="RCM cat." disabled={readOnly} value={it.rcm_category_key ?? ''} onChange={(e) => setItem(i, { rcm_category_key: e.target.value || null })} />
                      <label className="ml-1 text-xs" title="Exception to blocked credit claimed (needs a note)">
                        <input type="checkbox" disabled={readOnly} checked={it.itc_exception_claimed} onChange={(e) => setItem(i, { itc_exception_claimed: e.target.checked })} /> exception
                      </label>
                      {it.itc_exception_claimed && (
                        <input className={`${input} w-40`} placeholder="Exception note" disabled={readOnly} value={it.itc_exception_note ?? ''} onChange={(e) => setItem(i, { itc_exception_note: e.target.value || null })} />
                      )}
                    </td>
                  )}
                  <td className={tdR}>{out ? <Amount value={out.taxable_value} /> : ''}</td>
                  <td className={`${td} text-xs`}>
                    {out && (
                      <>
                        {out.treatment} {out.gst_rate}%{out.rate_is_default ? ' (default rate)' : ''}
                        {out.rcm ? ' RCM' : ''}
                        {out.tax_in_cost ? ' tax in cost' : ''}
                        <br />
                        {(['cgst', 'sgst', 'igst', 'cess'] as const)
                          .filter((h) => out[h] !== '0.00')
                          .map((h) => `${h.toUpperCase()} ${out[h]}`)
                          .join('  ')}
                      </>
                    )}
                    {errs.map((e, k) => (
                      <div key={k} className="text-red-700">
                        <span className="font-mono">{e.rule_id}</span> {e.message}
                      </div>
                    ))}
                  </td>
                  <td className={td}>
                    {!readOnly && value.items.length > 1 && (
                      <button className={btn} onClick={() => set({ items: value.items.filter((_, k) => k !== i) })}>
                        x
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
        <button className={btn} onClick={() => set({ items: [...value.items, blankGstItem()] })}>
          Add item
        </button>
      )}

      {failure && <div className="rounded border border-red-300 bg-red-50 px-3 py-1 text-sm text-red-800">{failure}</div>}
      {headerErrors.length > 0 && (
        <ul className={`list-disc rounded border border-red-300 bg-red-50 py-1 pl-6 pr-3 text-sm text-red-800`}>
          {headerErrors.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
      {preview && preview.gst.warnings.length > 0 && (
        <ul className="list-disc rounded border border-amber-300 bg-amber-50 py-1 pl-6 pr-3 text-sm text-amber-900">
          {preview.gst.warnings.map((w, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{w.rule_id}</span> {w.message}
              {w.item_line_no ? ` (item ${w.item_line_no})` : ''}
            </li>
          ))}
        </ul>
      )}
      {preview && (
        <div className="space-y-1">
          <h3 className="text-xs font-semibold text-slate-700">
            Ledger lines the server will post (read-only){loading ? ' ...' : ''}
          </h3>
          <table className="border-collapse">
            <thead>
              <tr>
                <th className={th}>Ledger</th>
                <th className={th}>Role</th>
                <th className={thR}>Debit</th>
                <th className={thR}>Credit</th>
              </tr>
            </thead>
            <tbody>
              {preview.lines.map((l, i) => (
                <tr key={i}>
                  <td className={td}>{l.ledger_name}</td>
                  <td className={`${td} text-xs text-slate-600`}>{l.gst_role}</td>
                  <td className={tdR}>{l.debit !== '0.00' ? <Amount value={l.debit} /> : ''}</td>
                  <td className={tdR}>{l.credit !== '0.00' ? <Amount value={l.credit} /> : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-sm">
            Invoice value <b>{<Amount value={preview.gst.invoice_value} />}</b>, round off <Amount value={preview.gst.invoice_round_off} />
            {preview.gst.has_rcm && ' (includes reverse charge)'}
          </div>
        </div>
      )}
      {!body && !readOnly && <div className="text-xs text-slate-500">The tax preview appears once the registration, place of supply, and one item (HSN, ledger, quantity, rate) are filled in.</div>}
    </div>
  )
}
