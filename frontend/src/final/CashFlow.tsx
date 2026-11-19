import { finalApi } from '../api/final'
import { ErrorBox, Page } from '../components/ui'
import { useClient } from '../context'
import { useLoad } from '../lib/useLoad'
import { ExportButtons } from './Export'
import { FySelect, NoClient, Row, StatementView, useFy } from './common'

/** Cash Flow Statement (AS 3, indirect method). Blocked by the server when the closing cash does not agree with the Balance Sheet (F-50). */
export default function CashFlow() {
  const { clientId } = useClient()
  const { years, fyId, setFyId } = useFy()
  const cf = useLoad(clientId && fyId ? () => finalApi.cashFlow(clientId, fyId) : null, `final-cf:${clientId}:${fyId}`)
  if (!clientId)
    return (
      <Page title="Cash Flow Statement">
        <NoClient />
      </Page>
    )
  return (
    <Page title="Cash Flow Statement">
      <Row>
        <FySelect years={years} value={fyId} onChange={setFyId} />
        <ExportButtons fyId={fyId} statements={['cash_flow']} />
      </Row>
      <ErrorBox error={cf.error} />
      {cf.error?.code === 'statement_blocked' && <div className="text-sm text-slate-600">The cash flow does not reconcile to the Balance Sheet cash and bank (F-50). Resolve the findings above, then reload.</div>}
      {cf.data && <StatementView s={cf.data} />}
    </Page>
  )
}
