import { useState } from 'react'
import { finalApi, type CloseCheck } from '../api/final'
import { Amount, ErrorBox, Field, Notice, Page, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { detailLines, type ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, NoClient, Row, Section, VoucherLink, useFy } from './common'
import { blockingItems } from './lib'

/** Year-end close: prerequisite checklist, preview, close, reopen with a reason. The server creates, posts and locks everything in one transaction. */
export default function YearEnd() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [createNext, setCreateNext] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [reason, setReason] = useState('')
  const status = useLoad(clientId && fyId ? () => finalApi.closeStatus(clientId, fyId) : null, `final-closestatus:${clientId}:${fyId}`)
  const check = useLoad<CloseCheck>(clientId && fyId && status.data?.status !== 'closed' ? () => finalApi.closeCheck(clientId, fyId) : null, `final-closecheck:${clientId}:${fyId}:${status.data?.status ?? ''}`)
  if (!clientId)
    return (
      <Page title="Year-end close">
        <NoClient />
      </Page>
    )
  const st = status.data
  const closed = st?.status === 'closed'
  const c = check.data
  const blockers = blockingItems(c?.items ?? [])
  const needNext = !!c && !c.next_financial_year.exists
  const doClose = async () => {
    setError(null)
    setNotice('')
    try {
      const r = await finalApi.close(clientId, fyId, createNext)
      setNotice(`Year closed. Net profit ${r.net_profit}. The three closing vouchers are posted and the periods are locked.`)
      setConfirm(false)
      status.reload()
      check.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const doReopen = async () => {
    if (!st?.close_id) return
    setError(null)
    setNotice('')
    try {
      await finalApi.reopen(clientId, st.close_id, reason.trim())
      setNotice('Year reopened: the closing vouchers are reversed and the periods are unlocked.')
      setReason('')
      status.reload()
      check.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Year-end close">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        {st && (
          <span className={`rounded border px-2 py-0.5 text-sm font-medium ${closed ? 'border-green-300 bg-green-50 text-green-800' : 'border-slate-300 bg-slate-50'}`}>
            Status: {st.status}
          </span>
        )}
      </Row>
      <ErrorBox error={error ?? status.error ?? check.error} />
      {error?.code === 'close_blocked' && <CloseList details={error.details} />}
      {notice && <Notice>{notice}</Notice>}

      {closed && st && (
        <Section title="This year is closed">
          <div className="text-sm">
            Closed by {st.closed_by} on {st.closed_at?.slice(0, 10)}. Net profit <b><Amount value={st.net_profit} /></b>.
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            {Object.entries(st.voucher_ids ?? {}).map(([k, id]) => (
              <VoucherLink key={k} id={id} label={`${k.replace(/_/g, ' ')} journal`} />
            ))}
          </div>
          <Row>
            <Field label="Reason for reopening (required)">
              <input className={`${input} w-[28rem]`} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <button className={btnDanger} disabled={reason.trim() === ''} onClick={doReopen}>
              Reopen the year
            </button>
          </Row>
          <p className="text-xs text-slate-600">Reopening reverses the closing journals and removes the carried-forward openings. It is refused when the next year already has postings (F-64).</p>
        </Section>
      )}
      {st?.status === 'reopened' && (
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Reopened by {st.reopened_by} on {st.reopened_at?.slice(0, 10)}: {st.reopen_reason}
        </div>
      )}

      {!closed && c && (
        <>
          <Section title="1. Prerequisites (F-60)">
            <ul className="space-y-1 text-sm">
              {c.items.map((i, k) => (
                <li key={k} className={i.ok ? 'text-green-800' : 'text-red-800'}>
                  <span className="mr-1 inline-block w-10 font-semibold">{i.ok ? 'OK' : 'FIX'}</span>
                  <span className="font-mono text-xs">{i.rule_id}</span> {i.message}
                  {!i.ok && <CloseList details={i.details} />}
                </li>
              ))}
            </ul>
            <button className={btn} onClick={() => check.reload()}>
              Check again
            </button>
          </Section>
          <Section title="2. Preview of what the close will do">
            <div className="text-sm">
              Net profit of the year: <b><Amount value={c.net_profit} /></b>
            </div>
            {c.appropriation_preview.length > 0 && (
              <table className="border-collapse">
                <thead>
                  <tr>
                    <th className={th}>Appropriation to</th>
                    <th className={thR}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {c.appropriation_preview.map((a) => (
                    <tr key={a.ledger_id}>
                      <td className={td}>{a.name}</td>
                      <td className={tdR}>
                        <Amount value={a.amount} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {c.vouchers_preview.map((v, i) => (
              <div key={i} className="rounded border border-slate-200 p-2">
                <div className="text-sm font-medium">
                  {v.step.replace(/_/g, ' ')} journal, {v.voucher_date}, ref {v.reference_no}
                </div>
                <table className="border-collapse">
                  <tbody>
                    {v.lines.map((l, j) => (
                      <tr key={j}>
                        <td className={td}>{l.ledger_name}</td>
                        <td className={tdR}>{Number(l.debit) > 0 ? <Amount value={l.debit} /> : ''}</td>
                        <td className={tdR}>{Number(l.credit) > 0 ? <Amount value={l.credit} /> : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
            <div className="text-sm text-slate-700">
              Carried forward to the next year: {c.carry_preview.ledger_count} ledger opening balances (Dr <Amount value={c.carry_preview.total_debit} />, Cr <Amount value={c.carry_preview.total_credit} />), {c.carry_preview.bills_count} open bills, {c.carry_preview.stock_items} stock items, {c.carry_preview.it_blocks} income-tax blocks.
            </div>
          </Section>
          <Section title="3. Close the year">
            {needNext && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={createNext} onChange={(e) => setCreateNext(e.target.checked)} /> The next financial year does not exist: create it (with its 12 periods)
              </label>
            )}
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> I have reviewed the statements and want to post the closing journals and lock this year
            </label>
            <button className={btnPrimary} disabled={!confirm || !c.ready || blockers.length > 0 || (needNext && !createNext)} onClick={doClose}>
              Close the year
            </button>
            {!c.ready && <div className="text-sm text-red-700">The year cannot be closed until every prerequisite above is OK.</div>}
          </Section>
        </>
      )}
    </Page>
  )
}

function CloseList({ details }: { details: unknown }) {
  const rows = detailLines(details)
  if (rows.length === 0) return null
  return (
    <ul className="ml-12 list-disc pl-5 text-xs">
      {rows.slice(0, 20).map((r, i) => (
        <li key={i}>{r}</li>
      ))}
      {rows.length > 20 && <li>and {rows.length - 20} more</li>}
    </ul>
  )
}
