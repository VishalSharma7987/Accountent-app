import { useMemo, useRef, useState, type ReactNode } from 'react'
import type { ApiFailure } from '../lib/apiError'
import { formatBalance, formatInr } from '../lib/money'
import type { Balance, LedgerRow, VoucherStatus } from '../types'

export const input = 'rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none'
export const inputErr = 'rounded border border-red-500 bg-red-50 px-2 py-1 text-sm focus:outline-none'
export const btn =
  'rounded border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 disabled:hover:bg-white'
export const btnPrimary =
  'rounded border border-blue-700 bg-blue-700 px-3 py-1 text-sm text-white hover:bg-blue-800 disabled:opacity-50'
export const btnDanger =
  'rounded border border-red-700 bg-white px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50'
export const th = 'border-b border-slate-300 bg-slate-100 px-2 py-1 text-left text-xs font-semibold text-slate-700'
export const thR = th + ' text-right'
export const td = 'border-b border-slate-200 px-2 py-1 text-sm'
export const tdR = td + ' text-right tabular-nums'

export function Page({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">{title}</h1>
        <div className="flex gap-2">{actions}</div>
      </div>
      {children}
    </section>
  )
}

export function ErrorBox({ error }: { error: ApiFailure | null }) {
  if (!error) return null
  return (
    <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
      <div>{error.message}</div>
      {error.ruleErrors.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {error.ruleErrors.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-xs">{e.rule_id}</span> {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Notice({ children }: { children: ReactNode }) {
  return <div className="rounded border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800">{children}</div>
}

const BADGE: Record<VoucherStatus, string> = {
  draft: 'bg-slate-200 text-slate-800',
  approved: 'bg-amber-200 text-amber-900',
  posted: 'bg-green-200 text-green-900',
  reversed: 'bg-red-200 text-red-900',
}
export function StatusBadge({ status }: { status: VoucherStatus }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${BADGE[status]}`}>{status}</span>
}

export function Amount({ value }: { value: string | null | undefined }) {
  return <span className="tabular-nums">{formatInr(value)}</span>
}

export function BalanceText({ balance, danger }: { balance: Balance; danger?: boolean }) {
  return <span className={`tabular-nums ${danger ? 'font-semibold text-red-600' : ''}`}>{formatBalance(balance)}</span>
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-xs text-slate-600">
      {label}
      {children}
    </label>
  )
}

/** Type-ahead ledger search. Keyboard: type, Arrow Up/Down, Enter to pick, Escape to close. */
export function LedgerPicker({
  ledgers,
  value,
  onChange,
  invalid,
  placeholder = 'Ledger',
}: {
  ledgers: LedgerRow[]
  value: string
  onChange: (id: string) => void
  invalid?: boolean
  placeholder?: string
}) {
  const selected = ledgers.find((l) => l.id === value)
  const [text, setText] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const box = useRef<HTMLInputElement>(null)
  const shown = text ?? selected?.name ?? ''
  const matches = useMemo(() => {
    const needle = (text ?? '').trim().toLowerCase()
    return ledgers.filter((l) => l.is_active && (needle === '' || l.name.toLowerCase().includes(needle))).slice(0, 8)
  }, [ledgers, text])

  const pick = (l: LedgerRow) => {
    onChange(l.id)
    setText(null)
    setOpen(false)
  }

  return (
    <div className="relative">
      <input
        ref={box}
        className={`${invalid ? inputErr : input} w-full`}
        value={shown}
        placeholder={placeholder}
        onChange={(e) => {
          setText(e.target.value)
          setOpen(true)
          setActive(0)
          if (e.target.value === '') onChange('')
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setOpen(true)
            setActive((a) => Math.min(a + 1, matches.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActive((a) => Math.max(a - 1, 0))
          } else if (e.key === 'Enter' && open && matches[active]) {
            e.preventDefault()
            pick(matches[active])
          } else if (e.key === 'Escape') {
            setOpen(false)
            setText(null)
          }
        }}
      />
      {open && matches.length > 0 && (
        <ul className="absolute z-20 mt-0.5 max-h-56 w-full overflow-auto rounded border border-slate-300 bg-white shadow">
          {matches.map((l, i) => (
            <li
              key={l.id}
              className={`cursor-pointer px-2 py-1 text-sm ${i === active ? 'bg-blue-100' : ''}`}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(l)
              }}
            >
              {l.name} <span className="text-xs text-slate-500">{l.group_name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
