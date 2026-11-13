import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { gstApi, type GstIn, type GstPreview } from '../api/gst'
import { ErrorBox, Field, LedgerPicker, Notice, Page, btnPrimary, input } from '../components/ui'
import type { TdsItemIn } from '../api/tds'
import { useClient } from '../context'
import { today } from '../lib/dates'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { InvoiceGstPanel } from './InvoiceGstPanel'
import { InvoiceStockPanel } from '../inventory/InvoiceStockPanel'
import { useRegistrations } from './common'
import { blankGstItem } from './lib'
import { TdsPanel } from '../tds/TdsPanel'
import { useNatures } from '../tds/hooks'
import { blankTdsItem, selectableNatures } from '../tds/lib'

const TYPES = [
  { value: 'sales', label: 'Sales' },
  { value: 'purchase', label: 'Purchase' },
  { value: 'credit_note', label: 'Credit note' },
  { value: 'debit_note', label: 'Debit note' },
]

/** Invoice-mode voucher entry: header + InvoiceGstPanel. Saves a DRAFT; approve and post from the Vouchers screen. */
export default function InvoiceEntry() {
  const { clientId } = useClient()
  const navigate = useNavigate()
  const { active } = useRegistrations()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [type, setType] = useState('sales')
  const [date, setDate] = useState(today())
  const [party, setParty] = useState('')
  const [reference, setReference] = useState('')
  const [narration, setNarration] = useState('')
  const [gst, setGst] = useState<GstIn>({
    gst_registration_id: '',
    document_kind: 'tax_invoice',
    supply_category: 'b2b',
    place_of_supply: '',
    invoice_date: today(),
    counterparty_gstin: null,
    items: [blankGstItem()],
  })
  const [preview, setPreview] = useState<GstPreview | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [tdsItems, setTdsItems] = useState<TdsItemIn[]>([blankTdsItem()])
  const natures = useNatures(date)

  if (!clientId) return <Page title="GST invoice">Select a client first.</Page>

  // sales: the invoice date is the voucher date (the server enforces it; this only keeps the two in step)
  const effective: GstIn = type === 'sales' ? { ...gst, invoice_date: date } : gst
  const base = { voucher_type: type, voucher_date: date, narration, reference_no: reference || null, party_ledger_id: party || null }
  const blocked = !!preview && preview.errors.length > 0

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice('')
    try {
      const typedTds = tdsItems.filter((i) => i.deductee_ledger_id || i.nature_key || i.amount)
      const out = await gstApi.createGstVoucher(clientId, { ...base, gst: effective, ...(type === 'purchase' && typedTds.length > 0 ? { tds: { items: typedTds.map((i) => ({ ...i, manual_tax: i.manual_tax || null })) } } : {}) })
      navigate(`/vouchers/${out.voucher_id}`)
    } catch (e) {
      setError(asFailure(e))
      setNotice('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page title="GST invoice (invoice mode)">
      <p className="text-xs text-slate-600">Enter the items only. The tax, party and round-off lines are built by the server and shown read-only; tax amounts cannot be typed (G-14).</p>
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-300 bg-white p-3">
        <Field label="Type">
          <select className={input} value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Voucher date">
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Party">
          <div className="w-56">
            <LedgerPicker ledgers={ledgers.data ?? []} value={party} onChange={setParty} placeholder="Customer / supplier" />
          </div>
        </Field>
        <Field label={type === 'sales' ? 'Invoice no (optional)' : "Supplier's bill no"}>
          <input className={input} value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="Narration">
          <input className={`${input} w-72`} value={narration} onChange={(e) => setNarration(e.target.value)} />
        </Field>
      </div>
      <InvoiceGstPanel clientId={clientId} registrations={active} ledgers={ledgers.data ?? []} base={base} value={effective} onChange={setGst} onPreview={setPreview} />
      <InvoiceStockPanel clientId={clientId} voucherType={type} voucherDate={date} value={gst} onChange={setGst} />
      {type === 'purchase' && (
        <TdsPanel clientId={clientId} base={base} counterLedgerId="" natures={selectableNatures(natures.options)} items={tdsItems} onChange={setTdsItems} gst={effective} />
      )}
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
      <button className={btnPrimary} disabled={busy || blocked || !preview} onClick={save}>
        Save draft
      </button>
      {blocked && <span className="ml-2 text-sm text-red-700">Fix the errors above first.</span>}
    </Page>
  )
}
