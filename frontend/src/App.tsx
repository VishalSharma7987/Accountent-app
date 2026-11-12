import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { API_BASE, getUser, setUser } from './api'
import { input } from './components/ui'
import { ClientProvider, useClient } from './context'
import Clients from './screens/Clients'
import ImportScreen from './screens/ImportScreen'
import Ledgers from './screens/Ledgers'
import Periods from './screens/Periods'
import Statement from './screens/Statement'
import TrialBalance from './screens/TrialBalance'
import VoucherEntry from './screens/VoucherEntry'
import VoucherList from './screens/VoucherList'

const NAV: [string, string][] = [
  ['/clients', 'Clients'],
  ['/ledgers', 'Ledgers'],
  ['/vouchers/new', 'New voucher'],
  ['/vouchers', 'Vouchers'],
  ['/statement', 'Ledger statement'],
  ['/trial-balance', 'Trial Balance'],
  ['/periods', 'Periods'],
  ['/import', 'Excel import'],
]

function Shell() {
  const { clients, clientId, setClientId } = useClient()
  const [user, setUserState] = useState(getUser())
  const [health, setHealth] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((h: { status: string; db: string }) => setHealth(`API ${h.status}, database ${h.db}`))
      .catch(() => setHealth('API not reachable'))
  }, [])

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <aside className="w-48 shrink-0 space-y-3 border-r border-slate-300 bg-white p-3">
        <div className="text-base font-bold">LedgerMind AI</div>
        <label className="flex flex-col gap-0.5 text-xs text-slate-600">
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
        <label className="flex flex-col gap-0.5 text-xs text-slate-600">
          Your name (sent as X-User)
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
        <nav className="flex flex-col gap-0.5 text-sm">
          {NAV.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/vouchers' || to === '/vouchers/new'}
              className={({ isActive }) => `rounded px-2 py-1 ${isActive ? 'bg-blue-700 text-white' : 'hover:bg-slate-100'}`}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="text-xs text-slate-500">{health}</div>
      </aside>
      <main className="min-w-0 flex-1 p-4">
        {!user.trim() && (
          <div className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Enter your name in the box on the left: it is recorded in the audit log with every change.
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
        </Routes>
      </main>
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
