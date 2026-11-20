import { useState } from 'react'
import { api } from '../api'
import { aiApi, type NarrationSuggestion } from '../api/ai'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th, tdR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { formatInr } from '../lib/money'
import { cashBankLedgers } from '../lib/phase2'
import { asFailure, useLoad } from '../lib/useLoad'
import { NoClient } from './common'

const STATUS_TEXT: Record<NarrationSuggestion['status'], string> = {
  none: 'No suggestion: no earlier entry has this narration.',
  suggested: 'Suggested',
  ambiguous: 'Ambiguous: earlier entries went to different ledgers. Choose yourself.',
  llm_blocked: 'No rule found, and the language model is switched off for this client.',
}

/** Suggested ledgers for bank statement lines. Advice only: nothing is booked or applied until a person accepts, and booking stays in the bank flow. */
export default function Narration() {
  const { clientId } = useClient()
  const [bank, setBank] = useState('')
  const [statementId, setStatementId] = useState('')
  const [shown, setShown] = useState<Record<string, NarrationSuggestion | 'done'>>({})
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const ledgers = useLoad(clientId ? () => api.listLedgers(clientId) : null, `ai-nar-ledgers:${clientId}`)
  const statements = useLoad(clientId && bank ? () => api.listStatements(clientId, bank) : null, `ai-nar-statements:${clientId}:${bank}`)
  const lines = useLoad(statementId ? () => api.statementLines(statementId) : null, `ai-nar-lines:${statementId}`)
  const rules = useLoad(clientId ? () => aiApi.listNarrationRules(clientId) : null, `ai-nar-rules:${clientId}`)
  if (!clientId)
    return (
      <Page title="Narration suggestions">
        <NoClient />
      </Page>
    )
  const banks = cashBankLedgers(ledgers.data ?? [], true)
  const run = async (fn: () => Promise<void>) => {
    setError(null)
    setNotice('')
    try {
      await fn()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <Page title="Narration suggestions">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Bank ledger">
          <select className={input} value={bank} onChange={(e) => { setBank(e.target.value); setStatementId(''); setShown({}) }}>
            <option value="">(choose)</option>
            {banks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Imported statement">
          <select className={input} value={statementId} onChange={(e) => { setStatementId(e.target.value); setShown({}) }}>
            <option value="">(choose)</option>
            {(statements.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.file_name} ({s.period_from} to {s.period_to})
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ErrorBox error={error ?? ledgers.error ?? statements.error ?? lines.error} />
      {notice && <Notice>{notice}</Notice>}
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Date</th>
            <th className={th}>Narration</th>
            <th className={th}>Debit</th>
            <th className={th}>Credit</th>
            <th className={th}>Suggested ledger</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(lines.data ?? []).map((l) => {
            const s = shown[l.id]
            return (
              <tr key={l.id}>
                <td className={td}>{l.txn_date}</td>
                <td className={td}>{l.description}</td>
                <td className={tdR}>{l.debit !== '0.00' ? formatInr(l.debit) : ''}</td>
                <td className={tdR}>{l.credit !== '0.00' ? formatInr(l.credit) : ''}</td>
                <td className={td}>
                  {s === 'done' && 'Decision recorded.'}
                  {s && s !== 'done' && (
                    <div className="space-y-0.5">
                      {s.suggestion ? (
                        <>
                          <div>
                            <b>{s.suggestion.ledger_name}</b> <span className="text-xs text-slate-500">({s.suggestion.source === 'rule' ? 'learned rule' : 'language model'})</span>
                          </div>
                          <div className="text-xs text-slate-600">{s.suggestion.reason}</div>
                        </>
                      ) : (
                        <div className="text-slate-600">{STATUS_TEXT[s.status]}</div>
                      )}
                      {s.ambiguous.length > 0 && <div className="text-xs text-slate-600">Earlier: {s.ambiguous.map((a) => `${a.ledger_name} (${a.count})`).join(', ')}</div>}
                    </div>
                  )}
                </td>
                <td className={td}>
                  {!s && (
                    <button className={btn} onClick={() => run(async () => { const r = await aiApi.suggestion(clientId, l.id); setShown({ ...shown, [l.id]: r }) })}>
                      Suggest
                    </button>
                  )}
                  {s && s !== 'done' && s.suggestion && (
                    <>
                      <button
                        className={btnPrimary}
                        onClick={() => run(async () => { await aiApi.acceptSuggestion(clientId, s.suggestion!.id); setShown({ ...shown, [l.id]: 'done' }); setNotice('Accepted: the rule is remembered. Book the entry in the bank flow; nothing was posted.'); rules.reload() })}
                      >
                        Accept
                      </button>{' '}
                      <button className={btn} onClick={() => run(async () => { await aiApi.rejectSuggestion(clientId, s.suggestion!.id); setShown({ ...shown, [l.id]: 'done' }) })}>
                        Reject
                      </button>
                    </>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <ErrorBox error={rules.error} />
      <table className="w-full border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Learned rule: narration</th>
            <th className={th}>Direction</th>
            <th className={th}>Ledger</th>
            <th className={th}>Approved</th>
            <th className={th}>Active</th>
          </tr>
        </thead>
        <tbody>
          {(rules.data ?? []).map((r) => (
            <tr key={r.id}>
              <td className={td}>{r.narration_key}</td>
              <td className={td}>{r.direction}</td>
              <td className={td}>{r.ledger_name}</td>
              <td className={td}>{r.approved_count}</td>
              <td className={td}>
                <input type="checkbox" aria-label={`Rule ${r.narration_key} active`} checked={r.is_active} onChange={(e) => run(async () => { await aiApi.setNarrationRule(clientId, r.id, e.target.checked); rules.reload() })} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Page>
  )
}
