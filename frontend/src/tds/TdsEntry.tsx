import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { tdsApi, type TdsItemIn, type TdsPreview } from '../api/tds'
import { ErrorBox, Field, LedgerPicker, Page, btnPrimary, input } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'
import { useNatures } from './hooks'
import { TdsPanel } from './TdsPanel'
import { blankTdsItem, previewBody } from './lib'

const TYPES = [
  { value: 'payment', label: 'Payment (Dr party / Cr bank)' },
  { value: 'purchase', label: 'Purchase (Dr expense / Cr party)' },
  { value: 'journal', label: 'Journal (Dr expense / Cr party)' },
]

/** Voucher entry with the TDS block. Saves a DRAFT; approve and post from the Vouchers screen. */
export default function TdsEntry() {
  const { clientId } = useClient()
  const navigate = useNavigate()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [type, setType] = useState('payment')
  const [date, setDate] = useState(today())
  const [reference, setReference] = useState('')
  const [narration, setNarration] = useState('')
  const [counter, setCounter] = useState('')
  const [items, setItems] = useState<TdsItemIn[]>([blankTdsItem()])
  const [preview, setPreview] = useState<TdsPreview | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)
  const eventDate = items.map((i) => i.payment_date || i.credit_date || '').filter(Boolean).sort()[0]
  const natures = useNatures(eventDate || date)

  if (!clientId) return <Page title="TDS voucher"><NoClient /></Page>
  const base = { voucher_type: type, voucher_date: date, narration, reference_no: reference || null, party_ledger_id: null }
  const blocked = !!preview && preview.errors.length > 0
  const body = previewBody(base, items, counter)

  const save = async () => {
    if (!body) return
    setBusy(true)
    setError(null)
    try {
      const out = await tdsApi.createTdsVoucher(clientId, body)
      navigate(`/vouchers/${out.voucher_id}`)
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page title="Voucher with TDS">
      <p className="text-xs text-slate-600">Type the gross amounts. The TDS payable line and the reduced party / bank line are built by the server and shown read-only; a tax amount, rate or ledger cannot be typed (T-05). Narration is required (V-09).</p>
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
        <Field label={type === 'payment' ? 'Bank / cash ledger' : 'Expense / asset ledger'}>
          <div className="w-56">
            <LedgerPicker ledgers={ledgers.data ?? []} value={counter} onChange={setCounter} placeholder={type === 'payment' ? 'Bank' : 'Expense'} />
          </div>
        </Field>
        <Field label="Reference no (supplier's bill no for a purchase)">
          <input className={input} value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="Narration">
          <input className={`${input} w-72`} value={narration} onChange={(e) => setNarration(e.target.value)} />
        </Field>
      </div>
      <TdsPanel clientId={clientId} base={base} counterLedgerId={counter} natures={natures.options} items={items} onChange={setItems} onPreview={setPreview} />
      <ErrorBox error={error} />
      <button className={btnPrimary} disabled={busy || blocked || !preview || !narration.trim()} onClick={save}>
        Save draft
      </button>
      {blocked && <span className="ml-2 text-sm text-red-700">Fix the errors above first.</span>}
    </Page>
  )
}
