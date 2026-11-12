import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { ReversePanel } from '../components/ReversePanel'
import { today } from '../lib/dates'
import { Amount, ErrorBox, Field, LedgerPicker, Notice, Page, StatusBadge, btn, btnDanger, btnPrimary, input, inputErr, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { ApiFailure, errorsForLine, voucherLevelErrors, type RuleError } from '../lib/apiError'
import { subtractAmounts, sumAmounts, isNilAmount } from '../lib/money'
import { asFailure, useLoad } from '../lib/useLoad'
import { VOUCHER_TYPES, type Voucher, type VoucherIn, type VoucherType } from '../types'

interface LineState {
  ledger_id: string
  debit: string
  credit: string
}
const blankLine = (): LineState => ({ ledger_id: '', debit: '', credit: '' })

export default function VoucherEntry() {
  const { id } = useParams()
  const { clientId } = useClient()
  const navigate = useNavigate()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const loaded = useLoad(id ? () => api.getVoucher(id) : null, `voucher:${id ?? 'new'}`)

  const [voucherType, setVoucherType] = useState<VoucherType>('payment')
  const [date, setDate] = useState(today())
  const [narration, setNarration] = useState('')
  const [reference, setReference] = useState('')
  const [party, setParty] = useState('')
  const [override, setOverride] = useState('')
  const [lines, setLines] = useState<LineState[]>([blankLine(), blankLine()])
  const [ruleErrors, setRuleErrors] = useState<RuleError[]>([])
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const lastDebit = useRef<HTMLInputElement>(null)

  const voucher: Voucher | null = loaded.data
  const readOnly = voucher !== null && voucher.status !== 'draft'

  // fill the form from the loaded voucher
  useEffect(() => {
    if (!voucher) return
    setVoucherType(voucher.voucher_type)
    setDate(voucher.voucher_date)
    setNarration(voucher.narration)
    setReference(voucher.reference_no ?? '')
    setParty(voucher.party_ledger_id ?? '')
    setOverride(voucher.duplicate_override_reason ?? '')
    setLines(voucher.lines.map((l) => ({ ledger_id: l.ledger_id, debit: nonZero(l.debit), credit: nonZero(l.credit) })))
    setDirty(false)
    setRuleErrors([])
  }, [voucher])

  const debit = useMemo(() => sumAmounts(lines.map((l) => l.debit)), [lines])
  const credit = useMemo(() => sumAmounts(lines.map((l) => l.credit)), [lines])
  const difference = subtractAmounts(debit.total, credit.total)

  if (!clientId) return <Page title="Voucher">Select a client first.</Page>

  const touch = () => {
    setDirty(true)
    setNotice('')
  }
  const setLine = (i: number, patch: Partial<LineState>) => {
    setLines((ls) => ls.map((l, k) => (k === i ? { ...l, ...patch } : l)))
    touch()
  }
  const addLine = () => {
    setLines((ls) => [...ls, blankLine()])
    touch()
  }
  const removeLine = (i: number) => {
    setLines((ls) => (ls.length > 1 ? ls.filter((_, k) => k !== i) : ls))
    touch()
  }

  const body = (): VoucherIn => ({
    voucher_type: voucherType,
    voucher_date: date,
    narration,
    reference_no: reference || null,
    party_ledger_id: party || null,
    duplicate_override_reason: override || null,
    lines: lines.map((l) => ({ ledger_id: l.ledger_id, debit: l.debit.trim() || null, credit: l.credit.trim() || null })),
  })

  const fail = (e: unknown) => {
    const f = asFailure(e)
    setError(f)
    setRuleErrors(f.ruleErrors)
  }

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setRuleErrors([])
    setNotice('')
    try {
      await work()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    act(async () => {
      if (voucher) {
        await api.updateVoucher(voucher.id, body())
        setNotice('Draft saved.')
        setDirty(false)
        loaded.reload()
      } else {
        const out = await api.createVoucher(clientId, body())
        navigate(`/vouchers/${out.voucher_id}`)
      }
    })

  const approve = () =>
    act(async () => {
      if (!voucher || !window.confirm('Approve this voucher?')) return
      await api.approveVoucher(voucher.id)
      setNotice('Approved.')
      loaded.reload()
    })
  const post = () =>
    act(async () => {
      if (!voucher || !window.confirm('Post this voucher? A posted voucher cannot be edited; only reversed.')) return
      const out = await api.postVoucher(voucher.id)
      setNotice(`Posted as ${out.voucher_number}.`)
      loaded.reload()
    })
  const back = () =>
    act(async () => {
      if (!voucher) return
      await api.returnToDraft(voucher.id)
      setNotice('Returned to draft.')
      loaded.reload()
    })
  const remove = () =>
    act(async () => {
      if (!voucher || !window.confirm('Delete this draft?')) return
      await api.deleteVoucher(voucher.id)
      navigate('/vouchers')
    })

  const hasDuplicate = ruleErrors.some((e) => e.rule_id === 'V-10')
  const topErrors = voucherLevelErrors(ruleErrors)
  const title = voucher ? `Voucher ${voucher.voucher_number ?? '(draft)'}` : 'New voucher'
  const activeLedgers = ledgers.data ?? []

  return (
    <Page
      title={title}
      actions={
        voucher && (
          <span className="flex items-center gap-2">
            <StatusBadge status={voucher.status} />
            <Link className={btn} to="/vouchers">
              Back to list
            </Link>
          </span>
        )
      }
    >
      <ErrorBox error={error && error.ruleErrors.length === 0 ? error : null} />
      {topErrors.length > 0 && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          <ul className="list-disc pl-5">
            {topErrors.map((e, i) => (
              <li key={i}>
                <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notice && <Notice>{notice}</Notice>}
      {loaded.error && <ErrorBox error={loaded.error} />}

      <div className="grid grid-cols-2 gap-2 rounded border border-slate-300 bg-white p-3 md:grid-cols-5">
        <Field label="Type">
          <select className={input} value={voucherType} disabled={readOnly} onChange={(e) => { setVoucherType(e.target.value as VoucherType); touch() }}>
            {VOUCHER_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Date">
          <input type="date" className={input} value={date} disabled={readOnly} onChange={(e) => { setDate(e.target.value); touch() }} />
        </Field>
        <Field label="Reference no (bill / cheque / UTR)">
          <input className={input} value={reference} disabled={readOnly} onChange={(e) => { setReference(e.target.value); touch() }} />
        </Field>
        <Field label="Party ledger">
          <LedgerPicker ledgers={activeLedgers} value={party} onChange={(v) => { setParty(v); touch() }} placeholder="(none)" />
        </Field>
        <Field label="Narration *">
          <input className={input} value={narration} disabled={readOnly} onChange={(e) => { setNarration(e.target.value); touch() }} />
        </Field>
      </div>

      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th + ' w-10'}>#</th>
            <th className={th}>Ledger</th>
            <th className={thR + ' w-44'}>Debit</th>
            <th className={thR + ' w-44'}>Credit</th>
            <th className={th + ' w-10'}></th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => {
            const errs = errorsForLine(ruleErrors, i + 1)
            return (
              <FragmentRow key={i}>
                <tr>
                  <td className={td}>{i + 1}</td>
                  <td className={td}>
                    {readOnly ? (
                      voucher?.lines[i]?.ledger_name
                    ) : (
                      <LedgerPicker ledgers={activeLedgers} value={l.ledger_id} invalid={errs.length > 0} onChange={(v) => setLine(i, { ledger_id: v })} />
                    )}
                  </td>
                  <td className={tdR}>
                    {readOnly ? (
                      <Amount value={nonZero(l.debit)} />
                    ) : (
                      <input
                        ref={i === lines.length - 1 ? lastDebit : undefined}
                        className={(errs.length ? inputErr : input) + ' w-full text-right'}
                        value={l.debit}
                        aria-label={`line ${i + 1} debit`}
                        inputMode="decimal"
                        onChange={(e) => setLine(i, { debit: e.target.value })}
                      />
                    )}
                  </td>
                  <td className={tdR}>
                    {readOnly ? (
                      <Amount value={nonZero(l.credit)} />
                    ) : (
                      <input
                        className={(errs.length ? inputErr : input) + ' w-full text-right'}
                        value={l.credit}
                        aria-label={`line ${i + 1} credit`}
                        inputMode="decimal"
                        onChange={(e) => setLine(i, { credit: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && i === lines.length - 1) {
                            e.preventDefault()
                            addLine()
                            setTimeout(() => document.querySelector<HTMLInputElement>(`input[aria-label="line ${lines.length + 1} debit"]`)?.focus(), 0)
                          }
                        }}
                      />
                    )}
                  </td>
                  <td className={td}>
                    {!readOnly && (
                      <button type="button" className="text-slate-400 hover:text-red-600" onClick={() => removeLine(i)} aria-label={`remove line ${i + 1}`}>
                        ×
                      </button>
                    )}
                  </td>
                </tr>
                {errs.length > 0 && (
                  <tr>
                    <td></td>
                    <td colSpan={4} className="px-2 pb-1 text-xs text-red-700">
                      {errs.map((e, k) => (
                        <div key={k}>
                          <span className="font-mono">{e.rule_id}</span> {e.message}
                        </div>
                      ))}
                    </td>
                  </tr>
                )}
              </FragmentRow>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="bg-slate-50 font-semibold">
            <td className={td}></td>
            <td className={td + ' text-right'}>Total</td>
            <td className={tdR}>
              <Amount value={debit.total} />
            </td>
            <td className={tdR}>
              <Amount value={credit.total} />
            </td>
            <td className={td}></td>
          </tr>
          <tr>
            <td></td>
            <td className="px-2 py-1 text-right text-sm">Difference (display only)</td>
            <td colSpan={2} className={`px-2 py-1 text-right text-sm tabular-nums ${isNilAmount(difference) ? 'text-green-700' : 'font-semibold text-red-600'}`}>
              <Amount value={difference} />
              {(debit.invalid || credit.invalid) && <span className="ml-2 text-xs text-amber-700">some amounts are not readable</span>}
            </td>
            <td></td>
          </tr>
        </tfoot>
      </table>

      {!readOnly && (
        <div className="flex flex-wrap items-end gap-2">
          <button type="button" className={btn} onClick={addLine}>
            + Add line
          </button>
          {hasDuplicate && (
            <Field label="Possible duplicate — reason to save anyway">
              <input className={input + ' w-80'} value={override} onChange={(e) => setOverride(e.target.value)} />
            </Field>
          )}
          <button className={btnPrimary} disabled={busy} onClick={save}>
            Save draft
          </button>
          {voucher && (
            <>
              <button className={btn} disabled={busy || dirty} onClick={approve} title={dirty ? 'Save the draft first' : ''}>
                Approve
              </button>
              <button className={btnDanger} disabled={busy} onClick={remove}>
                Delete draft
              </button>
            </>
          )}
        </div>
      )}

      {voucher?.status === 'approved' && (
        <div className="flex gap-2">
          <button className={btnPrimary} disabled={busy} onClick={post}>
            Post
          </button>
          <button className={btn} disabled={busy} onClick={back}>
            Return to draft (to edit)
          </button>
        </div>
      )}
      {voucher?.status === 'posted' && <ReversePanel voucherId={voucher.id} number={voucher.voucher_number} onDone={(rid) => navigate(`/vouchers/${rid}`)} />}
      {voucher?.status === 'reversed' && voucher.reversed_by_voucher_id && (
        <div className="text-sm">
          Reversed by <Link className="text-blue-700 underline" to={`/vouchers/${voucher.reversed_by_voucher_id}`}>this voucher</Link>.
        </div>
      )}
      {voucher?.reverses_voucher_id && (
        <div className="text-sm">
          Reversal of <Link className="text-blue-700 underline" to={`/vouchers/${voucher.reverses_voucher_id}`}>this voucher</Link>.
        </div>
      )}
      {voucher && (
        <div className="text-xs text-slate-500">
          Created by {voucher.created_by}
          {voucher.approved_by && ` · approved by ${voucher.approved_by}`}
          {voucher.posted_by && ` · posted by ${voucher.posted_by}`}
        </div>
      )}
    </Page>
  )
}

function FragmentRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

function nonZero(amount: string): string {
  return isNilAmount(amount) ? '' : amount
}
