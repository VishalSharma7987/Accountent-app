import { useState, type ReactNode } from 'react'
import { api } from '../api'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, inputErr, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure, RuleError } from '../lib/apiError'
import { groupByArea, type PartyArea } from '../lib/phase2'
import { asFailure, useLoad } from '../lib/useLoad'
import type { MsmeCategory, Party, PartyBody, PartyNature } from '../types'

interface Form {
  gstin: string
  pan: string
  state_code: string
  credit_days: string
  msme_category: MsmeCategory
  udyam_no: string
  msme_written_agreement: boolean
  bill_wise: boolean
}

const toForm = (p: Party): Form => ({
  gstin: p.gstin ?? '',
  pan: p.pan ?? '',
  state_code: p.state_code ?? '',
  credit_days: p.credit_days === null || p.credit_days === undefined ? '' : String(p.credit_days),
  msme_category: p.msme_category,
  udyam_no: p.udyam_no ?? '',
  msme_written_agreement: p.msme_written_agreement,
  bill_wise: p.bill_wise,
})

const orNull = (s: string) => (s.trim() === '' ? null : s.trim())

function toBody(f: Form): PartyBody {
  const days = f.credit_days.trim()
  // typed as is: a fraction or a negative number is sent and refused by the server (P-06), not corrected here
  const credit_days = days === '' ? null : Number(days)
  return {
    gstin: orNull(f.gstin),
    pan: orNull(f.pan),
    state_code: orNull(f.state_code),
    credit_days: credit_days !== null && Number.isNaN(credit_days) ? null : credit_days,
    msme_category: f.msme_category,
    udyam_no: orNull(f.udyam_no),
    msme_written_agreement: f.msme_written_agreement,
    bill_wise: f.bill_wise,
  }
}

function Area({ errors, area }: { errors: Partial<Record<PartyArea, RuleError[]>>; area: PartyArea }) {
  const list = errors[area]
  if (!list) return null
  return (
    <div className="text-xs text-red-700">
      {list.map((e, i) => (
        <div key={i}>
          <span className="font-mono">{e.rule_id}</span> {e.message}
        </div>
      ))}
    </div>
  )
}

function Box({ area, errors, children }: { area: PartyArea; errors: Partial<Record<PartyArea, RuleError[]>>; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      {children}
      <Area errors={errors} area={area} />
    </div>
  )
}

export default function Parties() {
  const { clientId } = useClient()
  const [nature, setNature] = useState<'' | PartyNature>('')
  const parties = useLoad(clientId ? () => api.listParties(clientId, nature || undefined) : null, `parties:${clientId}:${nature}`)
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [editing, setEditing] = useState<{ ledgerId: string; name: string; nature: string } | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [errors, setErrors] = useState<RuleError[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [newLedger, setNewLedger] = useState('')

  if (!clientId) return <Page title="Parties">Select a client first.</Page>

  const known = new Set((parties.data ?? []).map((p) => p.ledger_id))
  const candidates = (ledgers.data ?? []).filter(
    (l) => l.is_active && (l.group_name === 'Sundry Debtors' || l.group_name === 'Sundry Creditors') && !known.has(l.id),
  )

  const open = (p: Party) => {
    setEditing({ ledgerId: p.ledger_id, name: p.ledger_name, nature: p.nature })
    setForm(toForm(p))
    setErrors([])
    setError(null)
    setNotice('')
  }
  const openNew = (ledgerId: string) => {
    const l = (ledgers.data ?? []).find((x) => x.id === ledgerId)
    if (!l) return
    setEditing({ ledgerId, name: l.name, nature: l.group_name === 'Sundry Debtors' ? 'debtor' : 'creditor' })
    setForm(
      toForm({
        ledger_id: ledgerId,
        ledger_name: l.name,
        nature: 'debtor',
        gstin: null,
        pan: null,
        state_code: null,
        credit_days: null,
        msme_category: 'none',
        udyam_no: null,
        msme_written_agreement: false,
        bill_wise: false,
      }),
    )
    setErrors([])
    setError(null)
    setNotice('')
  }

  const save = async () => {
    if (!editing || !form) return
    setBusy(true)
    setError(null)
    setErrors([])
    setNotice('')
    try {
      await api.saveParty(clientId, editing.ledgerId, toBody(form))
      setNotice(`Saved ${editing.name}.`)
      setNewLedger('')
      parties.reload()
    } catch (e) {
      const f = asFailure(e)
      setError(f)
      setErrors(f.ruleErrors)
    } finally {
      setBusy(false)
    }
  }

  const by = groupByArea(errors)
  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f))
  const cls = (area: PartyArea) => (by[area] ? inputErr : input)

  return (
    <Page title="Parties (debtors and creditors)">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Show">
          <select className={input} value={nature} onChange={(e) => setNature(e.target.value as '' | PartyNature)}>
            <option value="">All parties</option>
            <option value="debtor">Debtors (customers)</option>
            <option value="creditor">Creditors (suppliers)</option>
          </select>
        </Field>
        <Field label="Set up a ledger as a party">
          <select
            className={input}
            value={newLedger}
            onChange={(e) => {
              setNewLedger(e.target.value)
              if (e.target.value) openNew(e.target.value)
            }}
          >
            <option value="">(choose a debtor / creditor ledger)</option>
            {candidates.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} ({l.group_name})
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ErrorBox error={parties.error ?? ledgers.error} />

      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Party</th>
            <th className={th}>Type</th>
            <th className={th}>GSTIN</th>
            <th className={th}>PAN</th>
            <th className={th}>State</th>
            <th className={th}>Credit days</th>
            <th className={th}>MSME</th>
            <th className={th}>Bill-wise</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(parties.data ?? []).map((p) => (
            <tr key={p.ledger_id} className={editing?.ledgerId === p.ledger_id ? 'bg-blue-50' : ''}>
              <td className={td}>{p.ledger_name}</td>
              <td className={td}>{p.nature === 'debtor' ? 'Debtor' : 'Creditor'}</td>
              <td className={td}>{p.gstin}</td>
              <td className={td}>{p.pan}</td>
              <td className={td}>{p.state_code}</td>
              <td className={td}>{p.credit_days}</td>
              <td className={td}>{p.msme_category === 'none' ? '' : `${p.msme_category} ${p.udyam_no ?? ''}`}</td>
              <td className={td}>{p.bill_wise ? 'Yes' : ''}</td>
              <td className={td}>
                <button className={btn} onClick={() => open(p)}>
                  Edit
                </button>
              </td>
            </tr>
          ))}
          {parties.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={9}>
                No parties yet. Pick a debtor or creditor ledger above to set it up.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {editing && form && (
        <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
          <div className="font-semibold">
            {editing.name} <span className="text-xs font-normal text-slate-500">({editing.nature})</span>
          </div>
          {notice && <Notice>{notice}</Notice>}
          <ErrorBox error={error && error.ruleErrors.length === 0 ? error : null} />
          <Area errors={by} area="general" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Box area="gstin" errors={by}>
              <Field label="GSTIN">
                <input className={cls('gstin')} value={form.gstin} onChange={(e) => set({ gstin: e.target.value.toUpperCase() })} />
              </Field>
            </Box>
            <Box area="pan" errors={by}>
              <Field label="PAN">
                <input className={cls('pan')} value={form.pan} onChange={(e) => set({ pan: e.target.value.toUpperCase() })} />
              </Field>
            </Box>
            <Box area="state_code" errors={by}>
              <Field label="State code (2 digits)">
                <input className={cls('state_code')} value={form.state_code} onChange={(e) => set({ state_code: e.target.value })} />
              </Field>
            </Box>
            <Box area="credit_days" errors={by}>
              <Field label="Credit days">
                <input className={cls('credit_days')} inputMode="numeric" value={form.credit_days} onChange={(e) => set({ credit_days: e.target.value })} />
              </Field>
            </Box>
            <Box area="msme" errors={by}>
              <Field label="MSME category">
                <select className={cls('msme')} value={form.msme_category} onChange={(e) => set({ msme_category: e.target.value as MsmeCategory })}>
                  <option value="none">Not MSME</option>
                  <option value="micro">Micro</option>
                  <option value="small">Small</option>
                  <option value="medium">Medium</option>
                </select>
              </Field>
            </Box>
            <Box area="msme" errors={{}}>
              <Field label="Udyam no (UDYAM-XX-00-0000000)">
                <input className={cls('msme')} value={form.udyam_no} onChange={(e) => set({ udyam_no: e.target.value.toUpperCase() })} />
              </Field>
            </Box>
            <label className="flex items-center gap-2 pt-4 text-sm">
              <input type="checkbox" checked={form.msme_written_agreement} onChange={(e) => set({ msme_written_agreement: e.target.checked })} />
              Written agreement with the supplier
            </label>
            <Box area="bill_wise" errors={by}>
              <label className="flex items-center gap-2 pt-4 text-sm">
                <input type="checkbox" checked={form.bill_wise} onChange={(e) => set({ bill_wise: e.target.checked })} />
                Bill-wise (track bills)
              </label>
            </Box>
          </div>
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={busy} onClick={save}>
              Save party
            </button>
            <button
              className={btn}
              onClick={() => {
                setEditing(null)
                setForm(null)
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </Page>
  )
}
