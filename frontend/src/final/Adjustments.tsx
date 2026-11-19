import { useState } from 'react'
import { finalApi, type AdjCreated, type AdjPreview } from '../api/final'
import { Amount, ErrorBox, Field, Notice, Page, StatusBadge, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import type { VoucherStatus } from '../types'
import { FySelect, Findings, LedgerSelect, NoClient, Problems, Row, VoucherLink, useFy, useLedgers } from './common'
import { ADJ_TYPES, EMPTY_ADJ, adjLabel, adjMeta, buildAdjustmentBody, type AdjForm } from './lib'

const EXPENSE_GROUPS = ['purchase_accounts', 'direct_expenses', 'indirect_expenses']
const INCOME_GROUPS = ['sales_accounts', 'direct_incomes', 'indirect_incomes']

/** Year-end adjustment helpers. Each one creates a DRAFT journal through the voucher service: approve and post it like any voucher. */
export default function Adjustments() {
  const { clientId, client } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const { ledgers } = useLedgers()
  const [form, setForm] = useState<AdjForm>(EMPTY_ADJ)
  const [preview, setPreview] = useState<AdjPreview | null>(null)
  const [created, setCreated] = useState<AdjCreated | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const list = useLoad(clientId && fyId ? () => finalApi.listAdjustments(clientId, { financial_year_id: fyId }) : null, `final-adj:${clientId}:${fyId}`)
  const partners = useLoad(clientId ? () => finalApi.listPartners(clientId) : null, `final-partners:${clientId}`)
  if (!clientId)
    return (
      <Page title="Year-end adjustments">
        <NoClient />
      </Page>
    )
  const meta = adjMeta(form.adj_type)
  const isFirm = client?.entity_type === 'partnership' || client?.entity_type === 'llp'
  const types = ADJ_TYPES.filter((t) => !t.firmOnly || isFirm)
  const set = (patch: Partial<AdjForm>) => {
    setForm({ ...form, ...patch })
    setPreview(null)
    setCreated(null)
  }
  const debitGroups = form.adj_type === 'outstanding_expense' || form.adj_type === 'provision' ? EXPENSE_GROUPS : form.adj_type === 'income_in_advance' ? INCOME_GROUPS : undefined
  const creditGroups = form.adj_type === 'prepaid_expense' ? EXPENSE_GROUPS : form.adj_type === 'accrued_income' ? INCOME_GROUPS : undefined

  const build = () => {
    setError(null)
    setNotice('')
    const r = buildAdjustmentBody(form)
    setProblems(r.problems)
    return r.body
  }
  const doPreview = async () => {
    const body = build()
    if (!body) return
    try {
      setPreview(await finalApi.previewAdjustment(clientId, body))
    } catch (e) {
      setPreview(null)
      setError(asFailure(e))
    }
  }
  const doCreate = async () => {
    const body = build()
    if (!body) return
    try {
      const done = await finalApi.createAdjustment(clientId, body)
      setCreated(done)
      setPreview(null)
      setNotice('Draft journal created. Approve and post it from the voucher screen.')
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const remove = async (id: string) => {
    setError(null)
    try {
      await finalApi.deleteAdjustment(clientId, id)
      list.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const duplicate = error?.code === 'adjustment_duplicate'

  return (
    <Page title="Year-end adjustments">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
      </Row>
      <p className="text-xs text-slate-600">
        Each helper makes a draft Journal voucher; nothing is posted here. Interest, remuneration and the doubtful-debt provision are computed by the server from the ledgers and the deed terms: you do not type their amounts.
      </p>
      <div className="space-y-3 rounded border border-slate-300 bg-white p-3">
        <Row>
          <Field label="Adjustment">
            <select className={input} value={form.adj_type} onChange={(e) => set({ ...EMPTY_ADJ, as_on_date: form.as_on_date, adj_type: e.target.value as AdjForm['adj_type'] })}>
              <option value="">(choose)</option>
              {types.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="As on date">
            <input type="date" className={input} value={form.as_on_date} min={fy?.start_date} max={fy?.end_date} onChange={(e) => set({ as_on_date: e.target.value })} />
          </Field>
          {meta?.amount && (
            <Field label="Amount">
              <input className={`${input} w-32 text-right`} value={form.amount} inputMode="decimal" onChange={(e) => set({ amount: e.target.value })} />
            </Field>
          )}
          {meta?.rate && (
            <Field label="Provision rate %">
              <input className={`${input} w-24 text-right`} value={form.rate_percent} inputMode="decimal" onChange={(e) => set({ rate_percent: e.target.value })} />
            </Field>
          )}
          {meta?.partner && (
            <Field label="Partner">
              <select className={input} value={form.partner_id} onChange={(e) => set({ partner_id: e.target.value })}>
                <option value="">(choose partner)</option>
                {(partners.data ?? [])
                  .filter((p) => p.is_active)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </Field>
          )}
          {meta?.months && (
            <Field label="Months (1-12, blank = 12)">
              <input className={`${input} w-20 text-right`} value={form.months} inputMode="numeric" onChange={(e) => set({ months: e.target.value })} />
            </Field>
          )}
        </Row>
        {meta && <p className="text-xs text-slate-600">{meta.hint}</p>}
        {meta?.twoLedgers && (
          <Row>
            <Field label="Debit ledger">
              <LedgerSelect ledgers={ledgers} value={form.debit_ledger_id} onChange={(id) => set({ debit_ledger_id: id })} groups={debitGroups} className="w-72" />
            </Field>
            <Field label="Credit ledger">
              <LedgerSelect ledgers={ledgers} value={form.credit_ledger_id} onChange={(id) => set({ credit_ledger_id: id })} groups={creditGroups} className="w-72" />
            </Field>
          </Row>
        )}
        {meta?.party && (
          <Row>
            <Field label={meta.party === 'debtor' ? 'Debtor' : 'Partner drawings ledger'}>
              <LedgerSelect
                ledgers={ledgers}
                value={form.party_ledger_id}
                onChange={(id) => set({ party_ledger_id: id })}
                groups={meta.party === 'debtor' ? ['sundry_debtors'] : ['capital_account']}
                className="w-72"
              />
            </Field>
          </Row>
        )}
        <Row>
          <Field label="Basis note (required)">
            <input className={`${input} w-[28rem]`} value={form.basis_note} onChange={(e) => set({ basis_note: e.target.value })} />
          </Field>
          <Field label="Auto-reverse on (optional, next year)">
            <input type="date" className={input} value={form.auto_reverse_on} onChange={(e) => set({ auto_reverse_on: e.target.value })} />
          </Field>
        </Row>
        {duplicate && (
          <Row>
            <Field label="Reason for a repeat adjustment (F-10)">
              <input className={`${input} w-[28rem]`} value={form.duplicate_reason} onChange={(e) => set({ duplicate_reason: e.target.value })} />
            </Field>
          </Row>
        )}
        <div className="flex gap-2">
          <button className={btn} disabled={!form.adj_type} onClick={doPreview}>
            Preview journal
          </button>
          <button className={btnPrimary} disabled={!form.adj_type} onClick={doCreate}>
            Create draft journal
          </button>
        </div>
      </div>
      <Problems items={problems} />
      <ErrorBox error={error ?? list.error} />
      {notice && <Notice>{notice}</Notice>}
      {created && (
        <Notice>
          Draft journal created for <Amount value={created.amount} />. <VoucherLink id={created.voucher_id} label="Open the draft voucher" />
          {created.auto_reverse_voucher_id && (
            <>
              {' '}
              | <VoucherLink id={created.auto_reverse_voucher_id} label="Open the auto-reversal draft" />
            </>
          )}
        </Notice>
      )}
      {preview && (
        <div className="space-y-2 rounded border border-slate-300 bg-white p-3">
          <div className="text-sm">
            Computed amount: <b><Amount value={preview.amount} /></b>
          </div>
          <div className="text-xs text-slate-600">{preview.narration}</div>
          <Findings findings={preview.findings} />
          <table className="border-collapse">
            <thead>
              <tr>
                <th className={th}>Ledger</th>
                <th className={thR}>Debit</th>
                <th className={thR}>Credit</th>
              </tr>
            </thead>
            <tbody>
              {preview.lines.map((l, i) => (
                <tr key={i}>
                  <td className={td}>{l.ledger_name}</td>
                  <td className={tdR}>{Number(l.debit) > 0 ? <Amount value={l.debit} /> : ''}</td>
                  <td className={tdR}>{Number(l.credit) > 0 ? <Amount value={l.credit} /> : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2 className="text-sm font-semibold">Adjustments of this year</h2>
      <table className="min-w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Date</th>
            <th className={th}>Type</th>
            <th className={thR}>Amount</th>
            <th className={th}>Basis</th>
            <th className={th}>Voucher</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((a) => (
            <tr key={a.id}>
              <td className={td}>{a.as_on_date}</td>
              <td className={td}>{adjLabel(a.adj_type)}</td>
              <td className={tdR}>
                <Amount value={a.amount} />
              </td>
              <td className={td}>{a.basis_note}</td>
              <td className={td}>
                <StatusBadge status={a.voucher_status as VoucherStatus} /> <VoucherLink id={a.voucher_id} label={a.voucher_number ?? 'draft'} />
              </td>
              <td className={td}>
                {a.voucher_status === 'draft' && (
                  <button className={btnDanger} onClick={() => remove(a.id)}>
                    Delete draft
                  </button>
                )}
              </td>
            </tr>
          ))}
          {(list.data ?? []).length === 0 && (
            <tr>
              <td className={td} colSpan={6}>
                No adjustments in this year yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Page>
  )
}
