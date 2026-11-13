import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { NAV_GROUPS, findNav, toggleGroup } from '../lib/nav'

const OPEN_KEY = 'ledgermind.nav.open'
const NARROW_KEY = 'ledgermind.nav.narrow'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* not remembered */
  }
}
function storedOpen(): string[] {
  try {
    const v: unknown = JSON.parse(read(OPEN_KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export default function Sidebar() {
  const { pathname } = useLocation()
  const activeId = findNav(pathname)?.group.id
  const [open, setOpen] = useState<string[]>(() => {
    const o = storedOpen()
    return activeId && !o.includes(activeId) ? [...o, activeId] : o
  })
  const [narrow, setNarrow] = useState(() => read(NARROW_KEY) === '1')

  // the group of the page you navigate to opens by itself
  useEffect(() => {
    if (activeId) setOpen((o) => (o.includes(activeId) ? o : [...o, activeId]))
  }, [activeId])

  const toggle = (id: string) => {
    const next = toggleGroup(open, id)
    setOpen(next)
    write(OPEN_KEY, JSON.stringify(next))
  }
  const setNarrowMode = (value: boolean) => {
    write(NARROW_KEY, value ? '1' : '0')
    setNarrow(value)
  }
  const onHeader = (id: string) => {
    if (!narrow) return toggle(id)
    // icon-only mode: widen the sidebar and show that group
    setNarrowMode(false)
    if (!open.includes(id)) toggle(id)
  }

  return (
    <aside
      className={`flex h-screen shrink-0 flex-col border-r border-slate-200 bg-white ${narrow ? 'w-14' : 'w-56'}`}
      aria-label="Main navigation"
    >
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 px-3">
        {!narrow && <span className="text-base font-bold text-blue-700">LedgerMind AI</span>}
        <button
          type="button"
          onClick={() => setNarrowMode(!narrow)}
          aria-label={narrow ? 'Expand sidebar' : 'Collapse sidebar'}
          title={narrow ? 'Expand sidebar' : 'Collapse sidebar'}
          className="rounded px-1.5 py-0.5 text-slate-500 hover:bg-slate-100"
        >
          {narrow ? '»' : '«'}
        </button>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto py-2 text-sm">
        {NAV_GROUPS.map((g) => {
          const isOpen = open.includes(g.id) && !narrow
          const isActive = g.id === activeId
          return (
            <div key={g.id}>
              <button
                type="button"
                aria-expanded={isOpen}
                aria-controls={`nav-${g.id}`}
                title={g.label}
                onClick={() => onHeader(g.id)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left font-medium hover:bg-slate-100 ${
                  isActive ? 'text-blue-700' : 'text-slate-700'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs font-bold ${
                    isActive ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {g.icon}
                </span>
                {!narrow && (
                  <>
                    <span className="min-w-0 flex-1 truncate">{g.label}</span>
                    <span aria-hidden="true" className={`text-xs text-slate-400 transition-transform ${isOpen ? 'rotate-90' : ''}`}>
                      ▸
                    </span>
                  </>
                )}
              </button>
              {isOpen && (
                <ul id={`nav-${g.id}`} className="pb-1">
                  {g.items.map((it) => (
                    <li key={it.to}>
                      <NavLink
                        to={it.to}
                        end={it.end}
                        className={({ isActive: a }) =>
                          `block border-l-2 py-1 pl-10 pr-3 ${
                            a ? 'border-blue-700 bg-blue-50 font-medium text-blue-700' : 'border-transparent text-slate-600 hover:bg-slate-100'
                          }`
                        }
                      >
                        {it.label}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
