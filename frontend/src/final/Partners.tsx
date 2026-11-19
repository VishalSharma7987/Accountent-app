import { useEffect, useState } from 'react'
import { finalApi, type TermsRow } from '../api/final'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, tdR, th, thR } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { FySelect, LedgerSelect, NoClient, Problems, Row, Section, useFy, useLedgers } from './common'
import { buildTermsRows, termsText } from './lib'

/** Final accounts setup: system ledger roles, partners (partnership / LLP) and the deed terms of each year. */
export default function Partners() {
  const { clientId, client } = useClient()
  const { years, fyId, setFyId } = useFy()
  const { ledgers } = useLedgers()
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const [name, setName] = useState('')
  const [capital, setCapital] = useState('')
  const [current, setCurrent] = useState('')
  const [rows, setRows] = useState<TermsRow[] | null>(null)
  const partners = useLoad(clientId ? () => finalApi.listPartners(clientId) : null, `final-partners:${clientId}`)
  const roles = useLoad(clientId ? () => finalApi.listRoles(clientId) : null, `final-roles:${clientId}`)
  const terms = useLoad(clientId && fyId ? () => finalApi.getTerms(clientId, fyId) : null, `final-terms:${clientId}:${fyId}`)
  useEffect(() => setRows(null), [fyId, clientId])
  if (!clientId)
    return (
      <Page title="Final accounts setup">
        <NoClient />
      </Page>
    )
  const isFirm = client?.entity_type === 'partnership' || client?.entity_type === 'llp'
  const act = async (fn: () => Promise<unknown>, done: string, after?: () => void) => {
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
      after?.()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const shown: TermsRow[] =
    rows ??
    (terms.data?.rows ?? []).map((r) => ({
      partner_id: r.partner_id,
      name: r.name,
      profit_share_percent: r.profit_share_percent,
      interest_on_capital_rate: r.interest_on_capital_rate,
      interest_on_drawings_rate: r.interest_on_drawings_rate,
      remuneration_annual: r.remuneration_annual,
      deed_reference: r.deed_reference,
    }))
  const edit = (i: number, patch: Partial<TermsRow>) => setRows(shown.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const saveTerms = () => {
    const r = buildTermsRows(shown)
    setProblems(r.problems)
    if (r.problems.length > 0) return
    void act(() => finalApi.putTerms(clientId, fyId, r.rows), 'Deed terms saved.', () => {
      setRows(null)
      terms.reload()
    })
  }

  return (
    <Page title="Final accounts setup: ledgers, partners, deed terms">
      <ErrorBox error={error ?? partners.error ?? roles.error ?? terms.error} />
      {notice && <Notice>{notice}</Notice>}
      <Section title="System ledgers and their roles">
        <p className="text-xs text-slate-600">
          The adjustments, depreciation and closing entries post to ledgers that carry a role (Trading account, Profit and Loss, Depreciation and so on). Create the missing ones once; you can point a role to another ledger below.
        </p>
        <Row>
          <FySelect years={years} value={fyId} onChange={setFyId} />
          <button className={btnPrimary} disabled={!fyId} onClick={() => act(() => finalApi.setupLedgers(clientId, fyId), 'System ledgers are ready.', () => roles.reload())}>
            Create missing system ledgers
          </button>
        </Row>
        <table className="border-collapse">
          <thead>
            <tr>
              <th className={th}>Role</th>
              <th className={th}>Ledger</th>
            </tr>
          </thead>
          <tbody>
            {(roles.data ?? []).map((r) => (
              <tr key={r.role}>
                <td className={td}>{r.role.replace(/_/g, ' ')}</td>
                <td className={td}>
                  <LedgerSelect
                    ledgers={ledgers}
                    value={r.ledger_id}
                    className="w-72"
                    onChange={(id) => id && id !== r.ledger_id && void act(() => finalApi.putRole(clientId, r.role, id), `Role ${r.role.replace(/_/g, ' ')} changed.`, () => roles.reload())}
                  />
                </td>
              </tr>
            ))}
            {(roles.data ?? []).length === 0 && (
              <tr>
                <td className={td} colSpan={2}>
                  No roles set yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Section>

      {!isFirm && <p className="text-sm text-slate-600">Partners and deed terms apply to partnership and LLP clients. This client is a {client?.entity_type}.</p>}
      {isFirm && (
        <>
          <Section title="Partners">
            <Row>
              <Field label="Partner name">
                <input className={`${input} w-56`} value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Capital ledger">
                <LedgerSelect ledgers={ledgers} value={capital} onChange={setCapital} groups={['capital_account']} className="w-64" />
              </Field>
              <Field label="Current / profit ledger (optional)">
                <LedgerSelect ledgers={ledgers} value={current} onChange={setCurrent} groups={['capital_account']} className="w-64" blank="(same as capital)" />
              </Field>
              <button
                className={btnPrimary}
                disabled={!name.trim() || !capital}
                onClick={() =>
                  act(() => finalApi.addPartner(clientId, { name: name.trim(), capital_ledger_id: capital, current_ledger_id: current || null }), 'Partner added.', () => {
                    setName('')
                    setCapital('')
                    setCurrent('')
                    partners.reload()
                    terms.reload()
                  })
                }
              >
                Add partner
              </button>
            </Row>
            <table className="min-w-full border-collapse">
              <thead>
                <tr>
                  <th className={th}>Partner</th>
                  <th className={th}>Capital ledger</th>
                  <th className={th}>Current ledger</th>
                  <th className={th}>Status</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {(partners.data ?? []).map((p) => (
                  <tr key={p.id}>
                    <td className={td}>{p.name}</td>
                    <td className={td}>{ledgers.find((l) => l.id === p.capital_ledger_id)?.name ?? ''}</td>
                    <td className={td}>{ledgers.find((l) => l.id === p.current_ledger_id)?.name ?? ''}</td>
                    <td className={td}>{p.is_active ? 'Active' : 'Inactive'}</td>
                    <td className={td}>
                      <button className={btn} onClick={() => act(() => finalApi.updatePartner(clientId, p.id, { is_active: !p.is_active }), 'Partner updated.', () => partners.reload())}>
                        {p.is_active ? 'Make inactive' : 'Make active'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Partnership deed terms for the year">
            <p className="text-xs text-slate-600">
              Rates and remuneration are the deed values, not law. A deed reference is required whenever a deed value is entered. Profit shares must total 100 (F-62); the server checks the total when you save.
            </p>
            <Row>
              <FySelect years={years} value={fyId} onChange={setFyId} />
            </Row>
            <Problems items={problems} />
            <table className="min-w-full border-collapse">
              <thead>
                <tr>
                  <th className={th}>Partner</th>
                  <th className={thR}>Profit share %</th>
                  <th className={thR}>Interest on capital %</th>
                  <th className={thR}>Interest on drawings %</th>
                  <th className={thR}>Remuneration (annual)</th>
                  <th className={th}>Deed reference</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={r.partner_id}>
                    <td className={td}>{r.name}</td>
                    <td className={tdR}>
                      <input className={`${input} w-24 text-right`} value={termsText(r.profit_share_percent)} onChange={(e) => edit(i, { profit_share_percent: e.target.value })} />
                    </td>
                    <td className={tdR}>
                      <input className={`${input} w-24 text-right`} value={termsText(r.interest_on_capital_rate)} onChange={(e) => edit(i, { interest_on_capital_rate: e.target.value })} />
                    </td>
                    <td className={tdR}>
                      <input className={`${input} w-24 text-right`} value={termsText(r.interest_on_drawings_rate)} onChange={(e) => edit(i, { interest_on_drawings_rate: e.target.value })} />
                    </td>
                    <td className={tdR}>
                      <input className={`${input} w-32 text-right`} value={termsText(r.remuneration_annual)} onChange={(e) => edit(i, { remuneration_annual: e.target.value })} />
                    </td>
                    <td className={td}>
                      <input className={`${input} w-56`} value={termsText(r.deed_reference)} onChange={(e) => edit(i, { deed_reference: e.target.value })} />
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr>
                    <td className={td} colSpan={6}>
                      Add the partners first.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="flex items-center gap-3">
              <button className={btnPrimary} disabled={shown.length === 0 || !fyId} onClick={saveTerms}>
                Save deed terms
              </button>
              {terms.data && (
                <span className={`text-sm ${terms.data.share_ok ? 'text-green-700' : 'text-red-700'}`}>
                  Saved profit shares total {terms.data.share_total}% {terms.data.share_ok ? '(100, correct)' : '(must be 100.0000, F-62)'}
                </span>
              )}
            </div>
          </Section>
        </>
      )}
    </Page>
  )
}
