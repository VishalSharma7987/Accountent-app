import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Amount, ErrorBox, Field, LedgerPicker, Notice, Page, btn, btnDanger, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import { today } from '../lib/dates'
import type { ApiFailure } from '../lib/apiError'
import { formatInr, sumAmounts } from '../lib/money'
import { bookItemId, cashBankLedgers, matchBody, tickTotals, toggleId } from '../lib/phase2'
import { asFailure, useLoad } from '../lib/useLoad'
import type { AutoMatchResult, StatementLine } from '../types'

const nz = (v: string) => (v === '0.00' ? '' : formatInr(v))

export default function Reconciliation() {
  const { clientId } = useClient()
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ledgers:${clientId}`)
  const [bankId, setBankId] = useState('')
  const [asOn, setAsOn] = useState(today())
  const data = useLoad(clientId && bankId && asOn ? () => api.unmatched(clientId, bankId, asOn) : null, `unmatched:${clientId}:${bankId}:${asOn}`)
  const [bankTicks, setBankTicks] = useState<string[]>([])
  const [bookTicks, setBookTicks] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [auto, setAuto] = useState<AutoMatchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [counter, setCounter] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<{ bank_line_id: string; voucher_id: string }[]>([])
  const [matchedLines, setMatchedLines] = useState<StatementLine[] | null>(null)

  const d = data.data
  const ticked = useMemo(() => {
    const bank = (d?.bank ?? []).filter((b) => bankTicks.includes(b.line_id))
    const book = (d?.book ?? []).filter((b) => bookTicks.includes(bookItemId(b)))
    return { bank, book, totals: tickTotals(bank, book) }
  }, [d, bankTicks, bookTicks])

  if (!clientId) return <Page title="Bank reconciliation">Select a client first.</Page>

  const refresh = () => {
    setBankTicks([])
    setBookTicks([])
    setMatchedLines(null)
    data.reload()
  }
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

  const match = () =>
    act(async () => {
      await api.createMatch(clientId, bankId, { ...matchBody(bankTicks, d?.book ?? [], bookTicks), ...(note.trim() ? { note: note.trim() } : {}) })
      setNotice('Matched.')
      setNote('')
      refresh()
    })
  const autoMatch = () =>
    act(async () => {
      setAuto(await api.autoMatch(clientId, bankId, asOn))
      refresh()
    })
  const showMatched = () =>
    act(async () => {
      const statements = await api.listStatements(clientId, bankId)
      const all = await Promise.all(statements.map((s) => api.statementLines(s.id)))
      setMatchedLines(all.flat().filter((l) => l.match_id))
    })
  const unmatch = (matchId: string) =>
    act(async () => {
      if (!window.confirm('Unmatch this group? The items go back to the unmatched lists.')) return
      await api.deleteMatch(clientId, matchId)
      setNotice('Unmatched.')
      refresh()
    })
  const makeDrafts = () =>
    act(async () => {
      const items = Object.entries(counter)
        .filter(([, v]) => v)
        .map(([bank_line_id, counter_ledger_id]) => ({ bank_line_id, counter_ledger_id }))
      const out = await api.bankOnlyDrafts(clientId, bankId, items)
      setDrafts(out.created)
      setCounter({})
      refresh()
    })

  const tickSuggestion = (bankIds: string[], bookIds: string[]) => {
    setBankTicks(bankIds)
    setBookTicks(bookIds)
  }

  const groups = new Map<string, StatementLine[]>()
  for (const l of matchedLines ?? []) groups.set(l.match_id as string, [...(groups.get(l.match_id as string) ?? []), l])

  const t = ticked.totals
  const bankRows = d?.bank ?? []

  return (
    <Page title="Bank reconciliation">
      <div className="flex flex-wrap items-end gap-2 rounded border border-slate-300 bg-white p-3">
        <Field label="Bank ledger">
          <select className={input} value={bankId} onChange={(e) => { setBankId(e.target.value); setBankTicks([]); setBookTicks([]); setMatchedLines(null) }}>
            <option value="">(choose bank)</option>
            {cashBankLedgers(ledgers.data ?? [], true).map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="As on">
          <input type="date" className={input} value={asOn} onChange={(e) => setAsOn(e.target.value)} />
        </Field>
        <button className={btnPrimary} disabled={!bankId || busy} onClick={autoMatch}>
          Auto-match
        </button>
        <button className={btn} disabled={!bankId || busy} onClick={showMatched}>
          Show matched groups
        </button>
        <Link className={btn} to="/brs">
          BRS report
        </Link>
      </div>
      <ErrorBox error={error ?? data.error ?? ledgers.error} />
      {notice && <Notice>{notice}</Notice>}
      {auto && (
        <Notice>
          Auto-match: {auto.matched_groups} groups matched ({auto.matched_bank_lines} bank lines, {auto.matched_book_items} book items);{' '}
          {auto.suggestions_left} suggestions left for you to decide.
        </Notice>
      )}

      {d && (
        <>
          <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded border border-slate-300 bg-white px-3 py-2 text-sm">
            <span>
              Ticked bank: <strong className="tabular-nums">{formatInr(t.bank)}</strong> ({ticked.bank.length})
            </span>
            <span>
              Ticked books: <strong className="tabular-nums">{formatInr(t.book)}</strong> ({ticked.book.length})
            </span>
            <span className={t.ties ? 'font-semibold text-green-700' : 'font-semibold text-red-600'}>
              {t.ties ? 'Ties' : ticked.bank.length + ticked.book.length === 0 ? 'Nothing ticked' : `Difference ${formatInr(t.difference)}`}
            </span>
            <input className={input} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className={btnPrimary} disabled={!t.ties || busy} onClick={match} title="The server checks the match again before saving">
              Match selected
            </button>
            <button className={btn} disabled={bankTicks.length + bookTicks.length === 0} onClick={() => tickSuggestion([], [])}>
              Clear ticks
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            <div>
              <h2 className="mb-1 text-sm font-semibold">Bank statement lines not matched ({bankRows.length})</h2>
              <table className="w-full border-collapse bg-white">
                <thead>
                  <tr>
                    <th className={th}></th>
                    <th className={th}>Date</th>
                    <th className={th}>Description</th>
                    <th className={thR}>Debit (out)</th>
                    <th className={thR}>Credit (in)</th>
                    <th className={th + ' w-52'}>Counter ledger (draft)</th>
                  </tr>
                </thead>
                <tbody>
                  {bankRows.map((b) => (
                    <tr key={b.line_id} className={bankTicks.includes(b.line_id) ? 'bg-blue-50' : ''}>
                      <td className={td}>
                        <input type="checkbox" aria-label={`tick bank line ${b.description}`} checked={bankTicks.includes(b.line_id)} onChange={() => setBankTicks((x) => toggleId(x, b.line_id))} />
                      </td>
                      <td className={td}>{b.txn_date}</td>
                      <td className={td}>
                        {b.description} <span className="text-xs text-slate-500">{b.reference}</span>
                      </td>
                      <td className={tdR}>{nz(b.debit)}</td>
                      <td className={tdR}>{nz(b.credit)}</td>
                      <td className={td}>
                        <LedgerPicker ledgers={ledgers.data ?? []} value={counter[b.line_id] ?? ''} onChange={(v) => setCounter((c) => ({ ...c, [b.line_id]: v }))} placeholder="(none)" />
                      </td>
                    </tr>
                  ))}
                  {bankRows.length === 0 && (
                    <tr>
                      <td className={td} colSpan={6}>
                        No unmatched bank lines.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <div className="mt-1 flex items-center gap-2">
                <button className={btn} disabled={busy || Object.values(counter).filter(Boolean).length === 0} onClick={makeDrafts}>
                  Create draft vouchers for bank-only items
                </button>
                <span className="text-xs text-slate-500">Drafts only: nothing is approved or posted. Pick the counter ledger on each row first.</span>
              </div>
              {drafts.length > 0 && (
                <Notice>
                  Draft vouchers created:{' '}
                  {drafts.map((x, i) => (
                    <span key={x.voucher_id}>
                      {i > 0 && ', '}
                      <Link className="underline" to={`/vouchers/${x.voucher_id}`}>
                        draft {i + 1}
                      </Link>
                    </span>
                  ))}
                  . Review, approve and post them in Vouchers.
                </Notice>
              )}
            </div>

            <div>
              <h2 className="mb-1 text-sm font-semibold">Book items not matched ({d.book.length})</h2>
              <table className="w-full border-collapse bg-white">
                <thead>
                  <tr>
                    <th className={th}></th>
                    <th className={th}>Date</th>
                    <th className={th}>Voucher</th>
                    <th className={th}>Narration / reference</th>
                    <th className={thR}>Debit (in)</th>
                    <th className={thR}>Credit (out)</th>
                  </tr>
                </thead>
                <tbody>
                  {d.book.map((b) => {
                    const id = bookItemId(b)
                    return (
                      <tr key={id} className={bookTicks.includes(id) ? 'bg-blue-50' : ''}>
                        <td className={td}>
                          <input type="checkbox" aria-label={`tick book item ${b.voucher_number ?? 'opening'}`} checked={bookTicks.includes(id)} onChange={() => setBookTicks((x) => toggleId(x, id))} />
                        </td>
                        <td className={td}>{b.date}</td>
                        <td className={td}>{b.voucher_number ?? '(opening item)'}</td>
                        <td className={td}>
                          {b.narration} <span className="text-xs text-slate-500">{b.reference_no}</span>
                        </td>
                        <td className={tdR}>{nz(b.debit)}</td>
                        <td className={tdR}>{nz(b.credit)}</td>
                      </tr>
                    )
                  })}
                  {d.book.length === 0 && (
                    <tr>
                      <td className={td} colSpan={6}>
                        No unmatched book items.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <h2 className="text-sm font-semibold">Suggestions ({d.suggestions.length})</h2>
          <ul className="space-y-1 text-sm">
            {d.suggestions.map((s, i) => (
              <li key={i} className="flex items-center gap-2 rounded border border-slate-200 bg-white px-2 py-1">
                <span className="flex-1">
                  {s.reason} <span className="text-xs text-slate-500">({s.bank_line_ids.length} bank, {s.book_item_ids.length} book)</span>
                </span>
                <button className={btn} onClick={() => tickSuggestion(s.bank_line_ids, s.book_item_ids)}>
                  Tick these
                </button>
              </li>
            ))}
            {d.suggestions.length === 0 && <li className="text-slate-500">No suggestions.</li>}
          </ul>
        </>
      )}

      {matchedLines && (
        <>
          <h2 className="text-sm font-semibold">Matched groups ({groups.size})</h2>
          <table className="w-full border-collapse bg-white">
            <thead>
              <tr>
                <th className={th}>Group</th>
                <th className={th}>Bank lines</th>
                <th className={thR}>Debit (out)</th>
                <th className={thR}>Credit (in)</th>
                <th className={th}></th>
              </tr>
            </thead>
            <tbody>
              {[...groups.entries()].map(([id, lines]) => (
                <tr key={id}>
                  <td className={td + ' font-mono text-xs'}>{id.slice(0, 8)}</td>
                  <td className={td}>{lines.map((l) => `${l.txn_date} ${l.description}`).join('; ')}</td>
                  <td className={tdR}>
                    <Amount value={sumAmounts(lines.map((l) => l.debit)).total} />
                  </td>
                  <td className={tdR}>
                    <Amount value={sumAmounts(lines.map((l) => l.credit)).total} />
                  </td>
                  <td className={td}>
                    <button className={btnDanger} disabled={busy} onClick={() => unmatch(id)}>
                      Unmatch
                    </button>
                  </td>
                </tr>
              ))}
              {groups.size === 0 && (
                <tr>
                  <td className={td} colSpan={5}>
                    No matched groups.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </Page>
  )
}

