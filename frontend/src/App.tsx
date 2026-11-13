import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { API_BASE, getUser, setUser } from './api'
import Sidebar from './components/Sidebar'
import { input } from './components/ui'
import { findNav } from './lib/nav'
import { ClientProvider, useClient } from './context'
import Bank from './screens/Bank'
import Brs from './screens/Brs'
import CashBook from './screens/CashBook'
import Clients from './screens/Clients'
import ImportScreen from './screens/ImportScreen'
import Ledgers from './screens/Ledgers'
import MsmeDue from './screens/MsmeDue'
import OpeningBills from './screens/OpeningBills'
import Outstanding from './screens/Outstanding'
import Parties from './screens/Parties'
import Periods from './screens/Periods'
import Reconciliation from './screens/Reconciliation'
import Statement from './screens/Statement'
import TrialBalance from './screens/TrialBalance'
import VoucherEntry from './screens/VoucherEntry'
import VoucherList from './screens/VoucherList'
import InvoiceEntry from './gst/InvoiceEntry'
import Items from './gst/Items'
import ItcRegister from './gst/ItcRegister'
import Recon2b from './gst/Recon2b'
import Registrations from './gst/Registrations'
import Returns from './gst/Returns'
import Rules from './gst/Rules'
import Workings from './gst/Workings'

function Shell() {
  const { clients, clientId, setClientId, latestYear } = useClient()
  const [user, setUserState] = useState(getUser())
  const [health, setHealth] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((h: { status: string; db: string }) => setHealth(`API ${h.status}, database ${h.db}`))
      .catch(() => setHealth('API not reachable'))
  }, [])

  const { pathname } = useLocation()
  const found = findNav(pathname)
  const year = latestYear ? `FY ${latestYear.start_date.slice(0, 4)}-${latestYear.end_date.slice(2, 4)}` : ''

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-4 border-b border-slate-200 bg-white px-4 text-sm">
          <div className="min-w-0 flex-1 truncate text-slate-500">
            {found ? (
              <>
                {found.group.label} / <span className="font-medium text-slate-800">{found.item.label}</span>
              </>
            ) : (
              'LedgerMind AI'
            )}
          </div>
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            Client
            <select className={input} value={clientId} onChange={(e) => setClientId(e.target.value)}>
              {clients.length === 0 && <option value="">(none yet)</option>}
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          {year && <span className="text-xs font-medium text-slate-600">{year}</span>}
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            Your name (X-User)
            <input
              className={input}
              value={user}
              placeholder="e.g. Anita"
              onChange={(e) => {
                setUserState(e.target.value)
                setUser(e.target.value)
              }}
            />
          </label>
          <span className="text-xs text-slate-500">{health}</span>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto p-4">
        {!user.trim() && (
          <div className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Enter your name in the box at the top: it is recorded in the audit log with every change.
          </div>
        )}
        <Routes>
          <Route path="/" element={<Navigate to="/clients" replace />} />
          <Route path="/clients" element={<Clients />} />
          <Route path="/ledgers" element={<Ledgers />} />
          <Route path="/vouchers" element={<VoucherList />} />
          <Route path="/vouchers/new" element={<VoucherEntry key="new" />} />
          <Route path="/vouchers/:id" element={<VoucherEntry />} />
          <Route path="/statement" element={<Statement />} />
          <Route path="/trial-balance" element={<TrialBalance />} />
          <Route path="/periods" element={<Periods />} />
          <Route path="/import" element={<ImportScreen />} />
          <Route path="/parties" element={<Parties />} />
          <Route path="/opening-bills" element={<OpeningBills />} />
          <Route path="/outstanding" element={<Outstanding />} />
          <Route path="/cash-book" element={<CashBook />} />
          <Route path="/msme" element={<MsmeDue />} />
          <Route path="/bank" element={<Bank />} />
          <Route path="/reconciliation" element={<Reconciliation />} />
          <Route path="/brs" element={<Brs />} />
          <Route path="/gst/registrations" element={<Registrations />} />
          <Route path="/gst/items" element={<Items />} />
          <Route path="/gst/invoice" element={<InvoiceEntry />} />
          <Route path="/gst/itc" element={<ItcRegister />} />
          <Route path="/gst/2b" element={<Recon2b />} />
          <Route path="/gst/gstr1" element={<Returns key="gstr1" kind="gstr1" />} />
          <Route path="/gst/gstr3b" element={<Returns key="gstr3b" kind="gstr3b" />} />
          <Route path="/gst/tie-out" element={<Returns key="tie-out" kind="tie-out" />} />
          <Route path="/gst/composition" element={<Returns key="composition" kind="composition" />} />
          <Route path="/gst/workings" element={<Workings />} />
          <Route path="/gst/rules" element={<Rules />} />
        </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ClientProvider>
        <Shell />
      </ClientProvider>
    </BrowserRouter>
  )
}
