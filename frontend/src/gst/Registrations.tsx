import { useState } from 'react'
import { api } from '../api'
import { gstApi, type Registration, type RegistrationBody } from '../api/gst'
import { ErrorBox, Field, LedgerPicker, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { useGstinCheck } from './common'
import { LEDGER_ROLES, missingRoles } from './lib'

interface Form {
  gstin: string
  registration_type: 'regular' | 'composition'
  return_frequency: 'monthly' | 'qrmp'
  composition_category: string
  trade_name: string
  effective_from: string
  effective_to: string
  is_active: boolean
}
const blank = (): Form => ({
  gstin: '',
  registration_type: 'regular',
  return_frequency: 'monthly',
  composition_category: '',
  trade_name: '',
  effective_from: today(),
  effective_to: '',
  is_active: true,
})

export default function Registrations() {
  const { clientId } = useClient()
  const regs = useLoad(clientId ? () => gstApi.listRegistrations(clientId) : null, `gst-regs:${clientId}`)
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [editing, setEditing] = useState<Registration | null>(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState<Form>(blank())
  const [roles, setRoles] = useState<Record<string, string>>({})
  const [rolesFor, setRolesFor] = useState<Registration | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const check = useGstinCheck(adding ? form.gstin : '', form.effective_from)

  if (!clientId) return <Page title="GST registrations">Select a client first.</Page>

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
  const body = (): RegistrationBody => ({
    ...(adding ? { gstin: form.gstin.trim().toUpperCase() } : {}),
    registration_type: form.registration_type,
    return_frequency: form.registration_type === 'regular' ? form.return_frequency : undefined,
    composition_category:
      form.registration_type === 'composition' ? ((form.composition_category || null) as Registration['composition_category']) : null,
    trade_name: form.trade_name.trim() || undefined,
    effective_from: form.effective_from,
    effective_to: form.effective_to || null,
    is_active: form.is_active,
  })
  const save = () =>
    act(async () => {
      if (adding) await gstApi.createRegistration(clientId, body())
      else if (editing) await gstApi.updateRegistration(clientId, editing.id, body())
      setAdding(false)
      setEditing(null)
      setNotice('Registration saved.')
      regs.reload()
    })
  const startEdit = (r: Registration) => {
    setAdding(false)
    setEditing(r)
    setForm({
      gstin: r.gstin,
      registration_type: r.registration_type,
      return_frequency: r.return_frequency ?? 'monthly',
      composition_category: r.composition_category ?? '',
      trade_name: r.trade_name ?? '',
      effective_from: r.effective_from,
      effective_to: r.effective_to ?? '',
      is_active: r.is_active,
    })
  }
  const openRoles = (r: Registration) => {
    setRolesFor(r)
    setRoles(Object.fromEntries(Object.entries(r.ledger_roles).map(([k, v]) => [k, v.ledger_id])))
  }
  const saveRoles = () =>
    act(async () => {
      if (!rolesFor) return
      const filled = Object.fromEntries(Object.entries(roles).filter(([, v]) => v))
      await gstApi.setLedgerRoles(clientId, rolesFor.id, filled)
      setNotice('Ledger roles saved.')
      setRolesFor(null)
      regs.reload()
    })

  const showForm = adding || editing
  return (
    <Page
      title="GST registrations"
      actions={
        <button
          className={btnPrimary}
          onClick={() => {
            setEditing(null)
            setForm(blank())
            setAdding(true)
          }}
        >
          Add registration
        </button>
      }
    >
      <ErrorBox error={error ?? regs.error} />
      {notice && <Notice>{notice}</Notice>}

      {showForm && (
        <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="GSTIN (state code is read from it)">
              <input
                className={`${input} w-48 font-mono uppercase`}
                value={form.gstin}
                disabled={!adding}
                onChange={(e) => setForm({ ...form, gstin: e.target.value })}
              />
            </Field>
            <Field label="Type">
              <select className={input} value={form.registration_type} onChange={(e) => setForm({ ...form, registration_type: e.target.value as Form['registration_type'] })}>
                <option value="regular">Regular</option>
                <option value="composition">Composition</option>
              </select>
            </Field>
            {form.registration_type === 'regular' ? (
              <Field label="Return frequency">
                <select className={input} value={form.return_frequency} onChange={(e) => setForm({ ...form, return_frequency: e.target.value as Form['return_frequency'] })}>
                  <option value="monthly">Monthly</option>
                  <option value="qrmp">Quarterly (QRMP)</option>
                </select>
              </Field>
            ) : (
              <Field label="Composition category">
                <select className={input} value={form.composition_category} onChange={(e) => setForm({ ...form, composition_category: e.target.value })}>
                  <option value="">(choose)</option>
                  <option value="manufacturer">Manufacturer</option>
                  <option value="trader">Trader</option>
                  <option value="restaurant">Restaurant</option>
                  <option value="service_provider">Service provider</option>
                </select>
              </Field>
            )}
            <Field label="Trade name">
              <input className={`${input} w-48`} value={form.trade_name} onChange={(e) => setForm({ ...form, trade_name: e.target.value })} />
            </Field>
            <Field label="Effective from">
              <input type="date" className={input} value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
            </Field>
            <Field label="Effective to (closes it)">
              <input type="date" className={input} value={form.effective_to} onChange={(e) => setForm({ ...form, effective_to: e.target.value })} />
            </Field>
            <label className="flex items-center gap-1 text-xs text-slate-600">
              <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active
            </label>
          </div>
          {adding && check.result && (
            <div className={`text-sm ${check.result.valid ? 'text-green-800' : 'text-red-700'}`}>
              {check.result.valid ? `Valid GSTIN: ${check.result.state_name} (${check.result.state_code}), PAN ${check.result.pan}` : null}
              {check.result.errors.map((e) => (
                <div key={e.rule_id + e.message}>
                  <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
                </div>
              ))}
              {!check.result.valid && check.result.expected_check_char && (
                <div className="text-xs text-slate-600">Expected last character: {check.result.expected_check_char}</div>
              )}
            </div>
          )}
          {adding && check.failure && <div className="text-sm text-red-700">{check.failure}</div>}
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={busy} onClick={save}>
              Save
            </button>
            <button
              className={btn}
              onClick={() => {
                setAdding(false)
                setEditing(null)
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
            {['GSTIN', 'State', 'Type', 'Frequency / category', 'Trade name', 'Effective', 'Active', 'Ledger roles', ''].map((h) => (
              <th key={h} className={th}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(regs.data ?? []).map((r) => {
            const missing = missingRoles(r)
            return (
              <tr key={r.id} className={r.is_active ? '' : 'text-slate-400'}>
                <td className={`${td} font-mono`}>{r.gstin}</td>
                <td className={td}>
                  {r.state_name} ({r.state_code})
                </td>
                <td className={td}>{r.registration_type}</td>
                <td className={td}>{r.registration_type === 'composition' ? (r.composition_category ?? '-') : r.return_frequency}</td>
                <td className={td}>{r.trade_name ?? ''}</td>
                <td className={td}>
                  {r.effective_from} to {r.effective_to ?? 'open'}
                </td>
                <td className={td}>{r.is_active ? 'Yes' : 'No'}</td>
                <td className={td}>
                  {missing.length === 0 ? (
                    'All mapped'
                  ) : (
                    <span className="text-amber-800">{missing.length} not mapped</span>
                  )}
                </td>
                <td className={td}>
                  <button className={btn} onClick={() => startEdit(r)}>
                    Edit
                  </button>{' '}
                  <button className={btn} onClick={() => openRoles(r)}>
                    Map ledgers
                  </button>
                </td>
              </tr>
            )
          })}
          {regs.data?.length === 0 && (
            <tr>
              <td className={td} colSpan={9}>
                No GST registration yet. Add the client's GSTIN to begin.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {rolesFor && (
        <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
          <h2 className="text-sm font-semibold">Ledger roles for {rolesFor.gstin}</h2>
          <p className="text-xs text-slate-600">Tax and round-off postings go to these ledgers. Create the ledgers first under Masters / Ledgers.</p>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {LEDGER_ROLES.filter((r) => (rolesFor.registration_type === 'composition' ? r.key.startsWith('composition_') || r.key === 'round_off' : !r.key.startsWith('composition_'))).map((r) => (
              <Field key={r.key} label={r.label}>
                <LedgerPicker ledgers={ledgers.data ?? []} value={roles[r.key] ?? ''} onChange={(id) => setRoles({ ...roles, [r.key]: id })} />
              </Field>
            ))}
          </div>
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={busy} onClick={saveRoles}>
              Save roles
            </button>
            <button className={btn} onClick={() => setRolesFor(null)}>
              Close
            </button>
          </div>
        </div>
      )}
    </Page>
  )
}
