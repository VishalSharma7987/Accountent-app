import { useState } from 'react'
import { downloadFile, finalApi, type ExportStatement } from '../api/final'
import { ErrorBox, Field, Page, btn, btnPrimary, input } from '../components/ui'
import { useClient } from '../context'
import type { ApiFailure } from '../lib/apiError'
import { asFailure } from '../lib/useLoad'
import { fyLabel } from '../tds/lib'
import { FySelect, NoClient, Row, Section, useFy } from './common'
import { exportFileName } from './lib'

const ALL: { key: ExportStatement; label: string; firmOnly?: boolean; nonCompany?: boolean }[] = [
  { key: 'trading', label: 'Trading account', nonCompany: true },
  { key: 'profit_loss', label: 'Profit and Loss' },
  { key: 'balance_sheet', label: 'Balance Sheet' },
  { key: 'cash_flow', label: 'Cash Flow Statement' },
  { key: 'appropriation', label: 'Appropriation account', firmOnly: true },
]

/** Small export buttons for one statement; used beside a statement on screen. */
export function ExportButtons({ fyId, statements, layout = 'vertical' }: { fyId: string; statements: ExportStatement[]; layout?: 'vertical' | 'horizontal' }) {
  const { clientId, client } = useClient()
  const { years } = useFy()
  const [error, setError] = useState<ApiFailure | null>(null)
  const fy = years.find((y) => y.id === fyId)
  const go = async (format: 'xlsx' | 'pdf') => {
    setError(null)
    try {
      await downloadFile(finalApi.exportPath(clientId), exportFileName(client?.name ?? 'client', fy ? fyLabel(fy) : '', format), finalApi.exportQuery({ financial_year_id: fyId, format, statements, layout }))
    } catch (e) {
      setError(asFailure(e))
    }
  }
  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <button className={btn} disabled={!fyId} onClick={() => go('xlsx')}>
          Export to Excel
        </button>
        <button className={btn} disabled={!fyId} onClick={() => go('pdf')}>
          Export to PDF
        </button>
      </div>
      <ErrorBox error={error} />
    </div>
  )
}

/** Excel and PDF export of the chosen statements with the ledger drill-down; blocked while a statement has an error finding (F-71). */
export default function ExportScreen() {
  const { clientId, client } = useClient()
  const { years, fy, fyId, setFyId } = useFy()
  const isCompany = client?.entity_type === 'company'
  const isFirm = client?.entity_type === 'partnership' || client?.entity_type === 'llp'
  const available = ALL.filter((s) => (!s.firmOnly || isFirm) && (!s.nonCompany || !isCompany))
  const [picked, setPicked] = useState<ExportStatement[] | null>(null)
  const [layout, setLayout] = useState<'vertical' | 'horizontal'>('vertical')
  const [format, setFormat] = useState<'xlsx' | 'pdf'>('xlsx')
  const [error, setError] = useState<ApiFailure | null>(null)
  const [busy, setBusy] = useState(false)
  if (!clientId)
    return (
      <Page title="Export final accounts">
        <NoClient />
      </Page>
    )
  const chosen = (picked ?? available.map((s) => s.key)).filter((k) => available.some((s) => s.key === k))
  const toggle = (k: ExportStatement) => setPicked(chosen.includes(k) ? chosen.filter((x) => x !== k) : [...chosen, k])
  const go = async () => {
    setError(null)
    setBusy(true)
    try {
      await downloadFile(
        finalApi.exportPath(clientId),
        exportFileName(client?.name ?? 'client', fy ? fyLabel(fy) : '', format),
        finalApi.exportQuery({ financial_year_id: fyId, format, statements: chosen, layout }),
      )
    } catch (e) {
      setError(asFailure(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Page title="Export final accounts">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <Field label="File">
          <select className={input} value={format} onChange={(e) => setFormat(e.target.value as 'xlsx' | 'pdf')}>
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="pdf">PDF</option>
          </select>
        </Field>
        <Field label="Layout">
          <select className={input} value={layout} onChange={(e) => setLayout(e.target.value as 'vertical' | 'horizontal')}>
            <option value="vertical">Vertical</option>
            <option value="horizontal">Horizontal (T-form)</option>
          </select>
        </Field>
      </Row>
      <Section title="Statements to include">
        <div className="flex flex-wrap gap-4 text-sm">
          {available.map((s) => (
            <label key={s.key} className="flex items-center gap-1">
              <input type="checkbox" checked={chosen.includes(s.key)} onChange={() => toggle(s.key)} /> {s.label}
            </label>
          ))}
        </div>
        <p className="text-xs text-slate-600">
          {isCompany ? 'A company exports the Schedule III statements with their notes. ' : ''}Every sheet or page carries the client, financial year, basis, engine version and the verification status of the law rules used (pending is printed). Each line lists its ledgers with amounts. The export is refused while a statement has an error finding (F-71).
        </p>
        <button className={btnPrimary} disabled={!fyId || chosen.length === 0 || busy} onClick={go}>
          {busy ? 'Preparing...' : `Download ${format === 'xlsx' ? 'Excel' : 'PDF'}`}
        </button>
      </Section>
      <ErrorBox error={error} />
    </Page>
  )
}
