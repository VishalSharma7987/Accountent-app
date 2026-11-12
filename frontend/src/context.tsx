import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { api } from './api'
import type { ClientDetail, ClientSummary } from './types'
import { useLoad } from './lib/useLoad'

const CLIENT_KEY = 'ledgermind.client'

interface ClientCtx {
  clients: ClientSummary[]
  clientId: string
  setClientId: (id: string) => void
  client: ClientDetail | null
  reloadClients: () => void
  /** latest financial year of the selected client (the one screens default to) */
  latestYear: ClientDetail['financial_years'][number] | null
}

const Ctx = createContext<ClientCtx | null>(null)

function remembered(): string {
  try {
    return localStorage.getItem(CLIENT_KEY) ?? ''
  } catch {
    return ''
  }
}

export function ClientProvider({ children }: { children: ReactNode }) {
  const list = useLoad(() => api.listClients(), 'clients')
  const [chosenId, setClientIdState] = useState(remembered)
  const clients = useMemo(() => list.data ?? [], [list.data])
  // the remembered client if it still exists, else the first one (derived, not stored)
  const clientId = clients.some((c) => c.id === chosenId) ? chosenId : (clients[0]?.id ?? '')

  const detail = useLoad(clientId ? () => api.getClient(clientId) : null, `client:${clientId}`)
  const years = detail.data?.financial_years ?? []
  const latestYear = years.length ? [...years].sort((a, b) => a.start_date.localeCompare(b.start_date))[years.length - 1] : null

  const setClientId = (id: string) => {
    setClientIdState(id)
    try {
      localStorage.setItem(CLIENT_KEY, id)
    } catch {
      /* not remembered */
    }
  }

  return (
    <Ctx.Provider value={{ clients, clientId, setClientId, client: detail.data, reloadClients: list.reload, latestYear }}>
      {children}
    </Ctx.Provider>
  )
}

export function useClient(): ClientCtx {
  const value = useContext(Ctx)
  if (!value) throw new Error('useClient outside ClientProvider')
  return value
}
