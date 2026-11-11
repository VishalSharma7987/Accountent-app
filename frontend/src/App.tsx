import { useEffect, useState } from 'react'

type Health = { status: string; db: string }

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/health')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<Health>
      })
      .then(setHealth)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-semibold">LedgerMind AI</h1>
      <p className="mt-4 text-sm text-slate-600">Backend health</p>
      <table className="mt-2 w-full border border-slate-300 text-sm">
        <tbody>
          <tr className="border-b border-slate-300">
            <td className="p-2 font-medium">API</td>
            <td className="p-2">{error ? `unreachable (${error})` : (health?.status ?? 'checking…')}</td>
          </tr>
          <tr>
            <td className="p-2 font-medium">Database</td>
            <td className="p-2">{health?.db ?? '—'}</td>
          </tr>
        </tbody>
      </table>
    </main>
  )
}

export default App
