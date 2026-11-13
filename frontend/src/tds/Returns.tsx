import { useState } from 'react'
import { tdsApi, downloadFile, type CertificateData, type ReturnKind, type SavedCertificate } from '../api/tds'
import { ErrorBox, Field, Notice, Page, btn, btnPrimary, input, td, th } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure, useLoad } from '../lib/useLoad'
import { DataView, FySelect, NoClient, QuarterSelect, Row, RuleBadge, Tabs, Warnings, useFy } from './common'
import { CERT_KINDS, certLabel } from './lib'

const KINDS: { value: ReturnKind; label: string }[] = [
  { value: 'non_salary_resident', label: 'Non-salary, resident (26Q / 140)' },
  { value: 'salary', label: 'Salary (24Q / 138)' },
  { value: 'tcs', label: 'TCS (27EQ / 143)' },
]

/** Quarterly return working (the tool's own structure, not the official statement file) and certificate data. */
export default function Returns() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const [quarter, setQuarter] = useState<number | ''>(1)
  const [tab, setTab] = useState<'working' | 'certificates'>('working')
  if (!clientId) return <Page title="TDS returns"><NoClient /></Page>
  return (
    <Page title="TDS return workings and certificates">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <QuarterSelect value={quarter} onChange={setQuarter} />
      </Row>
      <Tabs
        tabs={[
          { key: 'working', label: 'Return working' },
          { key: 'certificates', label: 'Certificates' },
        ]}
        value={tab}
        onChange={setTab}
      />
      {!fyId || quarter === '' ? null : tab === 'working' ? <Working clientId={clientId} fyId={fyId} quarter={quarter} /> : <Certificates clientId={clientId} fyId={fyId} quarter={quarter} />}
    </Page>
  )
}

function Working({ clientId, fyId, quarter }: { clientId: string; fyId: string; quarter: number }) {
  const [kind, setKind] = useState<ReturnKind>('non_salary_resident')
  const w = useLoad(() => tdsApi.returnWorking(clientId, { financial_year_id: fyId, quarter, return_kind: kind }), `tds-rw:${clientId}:${fyId}:${quarter}:${kind}`)
  const saved = useLoad(() => tdsApi.listReturnWorkings(clientId, { financial_year_id: fyId, quarter, return_kind: kind }), `tds-rws:${clientId}:${fyId}:${quarter}:${kind}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null)
    setNotice('')
    try {
      await fn()
      setNotice(done)
      saved.reload()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  const data = w.data
  return (
    <div className="space-y-3">
      <Row>
        <Field label="Return">
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value as ReturnKind)}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <button className={btnPrimary} disabled={!data || data.errors.length > 0} onClick={() => run(() => tdsApi.saveReturnWorking(clientId, { financial_year_id: fyId, quarter, return_kind: kind }), 'Working saved as a new version.')}>
          Save working (new version)
        </button>
        {data?.rule_status && <RuleBadge status={data.rule_status} />}
      </Row>
      <ErrorBox error={error ?? w.error} />
      {notice && <Notice>{notice}</Notice>}
      {data && (
        <>
          <div className="text-sm">
            Form <b>{data.form_no}</b> <span className="text-slate-600">({data.form_status})</span>, TAN <b>{data.tan ?? 'missing'}</b>, period {data.period}
          </div>
          {data.errors.length > 0 && (
            <ul className="list-disc rounded border border-red-300 bg-red-50 py-2 pl-7 pr-3 text-sm text-red-800">
              {data.errors.map((e, i) => (
                <li key={i}>
                  <span className="font-mono text-xs">{e.rule_id} </span>
                  {e.message}
                </li>
              ))}
            </ul>
          )}
          <Warnings items={data.warnings} />
          <DataView name="Deductee rows" value={data.deductee_rows} />
          <DataView name="Challan rows" value={data.challan_rows} />
          <DataView name="Totals" value={data.totals} />
        </>
      )}
      <div className="text-sm font-semibold">Saved versions</div>
      <table className="border-collapse bg-white">
        <thead>
          <tr>
            <th className={th}>Version</th>
            <th className={th}>Status</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody>
          {(saved.data ?? []).map((s) => (
            <tr key={s.id}>
              <td className={td}>{s.version}</td>
              <td className={td}>{String(s.status ?? (s.is_final ? 'final' : 'draft'))}</td>
              <td className={td}>
                <button className={btn} onClick={() => run(() => tdsApi.finaliseWorking(s.id), 'Version finalised; its challans are now locked.')}>
                  Finalise (locks challans)
                </button>{' '}
                <button className={btn} onClick={() => run(() => downloadFile(`/tds/return-workings/${s.id}/export.xlsx`, `tds-working-v${s.version}.xlsx`), 'Exported.')}>
                  Excel
                </button>{' '}
                <button className={btn} onClick={() => run(() => downloadFile(`/tds/return-workings/${s.id}/export.json`, `tds-working-v${s.version}.json`), 'Exported.')}>
                  JSON
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-600">The export is the working in this tool's own structure. The official statement file for filing is not produced here.</p>
    </div>
  )
}

function Certificates({ clientId, fyId, quarter }: { clientId: string; fyId: string; quarter: number }) {
  const deductees = useLoad(() => tdsApi.listDeductees(clientId), `tds-ded:${clientId}:`)
  const [ledgerId, setLedgerId] = useState('')
  const [kindKey, setKindKey] = useState(CERT_KINDS[0].value)
  const [preview, setPreview] = useState<CertificateData | null>(null)
  const saved = useLoad(() => tdsApi.listCertificates(clientId, { financial_year_id: fyId, quarter }), `tds-certs-saved:${clientId}:${fyId}:${quarter}`)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [notice, setNotice] = useState('')
  const q = { deductee_ledger_id: ledgerId, financial_year_id: fyId, quarter, certificate_kind: kindKey }
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
    <div className="space-y-3">
      <Row>
        <Field label="Deductee">
          <select className={`${input} w-64`} value={ledgerId} onChange={(e) => { setLedgerId(e.target.value); setPreview(null) }}>
            <option value="">(choose)</option>
            {(deductees.data ?? []).map((d) => (
              <option key={d.ledger_id} value={d.ledger_id}>
                {d.ledger_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Certificate">
          <select className={input} value={kindKey} onChange={(e) => setKindKey(e.target.value)}>
            {CERT_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <button className={btn} disabled={!ledgerId} onClick={() => run(async () => setPreview(await tdsApi.certificatePreview(clientId, q)))}>
          Preview data
        </button>
        <button
          className={btnPrimary}
          disabled={!preview}
          onClick={() =>
            run(async () => {
              const out = await tdsApi.saveCertificate(clientId, q)
              setNotice(`Saved as version ${out.version}.`)
              saved.reload()
            })
          }
        >
          Save snapshot
        </button>
      </Row>
      <ErrorBox error={error} />
      {notice && <Notice>{notice}</Notice>}
      {preview && (
        <div className="space-y-2">
          <div className="text-sm">
            {certLabel(kindKey)}, form <b>{preview.form_no}</b>. Deductor {preview.deductor.name} (TAN {preview.deductor.tan ?? 'missing'}); deductee {preview.deductee.name} (PAN {preview.deductee.pan ?? 'missing'}).
          </div>
          <DataView name="Items" value={preview.items} />
          <DataView name="Challans" value={preview.challans} />
          <DataView value={{ total_deducted: preview.total_deducted, total_deposited: preview.total_deposited }} />
        </div>
      )}
      <div className="text-sm font-semibold">Saved certificate snapshots</div>
      {(saved.data ?? []).map((s) => (
        <SavedCert key={s.id} clientId={clientId} s={s} onChanged={saved.reload} />
      ))}
      {saved.data?.length === 0 && <div className="text-sm text-slate-500">None yet for this quarter.</div>}
    </div>
  )
}

function SavedCert({ clientId, s, onChanged }: { clientId: string; s: SavedCertificate; onChanged: () => void }) {
  const [no, setNo] = useState(String(s.certificate_no ?? ''))
  const [issued, setIssued] = useState(String(s.issued_on ?? ''))
  const [error, setError] = useState<ApiFailure | null>(null)
  const save = async () => {
    setError(null)
    try {
      await tdsApi.updateCertificate(clientId, s.id, { certificate_no: no, issued_on: issued })
      onChanged()
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-2">
      <Row>
        <span className="text-sm">
          {String(s.deductee_name ?? '')} version {s.version}
        </span>
        <Field label="Certificate no">
          <input className={`${input} w-36`} value={no} onChange={(e) => setNo(e.target.value)} />
        </Field>
        <Field label="Issued on">
          <input type="date" className={input} value={issued} onChange={(e) => setIssued(e.target.value)} />
        </Field>
        <button className={btn} onClick={save}>
          Save number and date
        </button>
        <button className={btn} onClick={() => downloadFile(`/clients/${clientId}/tds/certificates/${s.id}/export.xlsx`, `tds-certificate-${s.version}.xlsx`).catch((e: unknown) => setError(asFailure(e)))}>
          Excel
        </button>
      </Row>
      <ErrorBox error={error} />
    </div>
  )
}
