// Pure helpers for the inventory screens. No stock valuation or costing here: that is the server's job.
import type { JournalBody, JournalStatus, JournalType, NegativeMode, ReasonCode, ValuationMethod } from '../api/inventory'

export const METHODS: { value: ValuationMethod; label: string }[] = [
  { value: 'fifo', label: 'FIFO' },
  { value: 'wa_periodic', label: 'Weighted average (periodic)' },
  { value: 'wa_moving', label: 'Weighted average (moving, after every receipt)' },
]
export const NEGATIVE_MODES: { value: NegativeMode; label: string }[] = [
  { value: 'block', label: 'Block (a sale that makes stock negative is refused)' },
  { value: 'warn', label: 'Warn (allowed, shown as a warning)' },
]
export const REASONS: { value: ReasonCode; label: string }[] = [
  { value: 'damage', label: 'Damage' },
  { value: 'expiry', label: 'Expiry' },
  { value: 'theft', label: 'Theft' },
  { value: 'loss', label: 'Loss' },
  { value: 'sample', label: 'Sample' },
  { value: 'other', label: 'Other (note required)' },
]

export const methodLabel = (m: string | null | undefined) => METHODS.find((x) => x.value === m)?.label ?? m ?? ''

/** A quantity as typed: plain positive number with at most 3 decimals (S-02). The server decides everything else. */
export function isQuantity(text: string, allowZero = false): boolean {
  const t = text.trim()
  if (!/^\d+(\.\d{1,3})?$/.test(t)) return false
  return allowZero || Number(t) > 0
}
/** An amount as typed: plain number with at most 2 decimals. */
export function isMoney(text: string): boolean {
  return /^\d+(\.\d{1,2})?$/.test(text.trim())
}
/** Strip commas and spaces a user may paste into a number box. */
export const cleanNumber = (text: string) => text.replace(/[,\s]/g, '')

export interface JournalDraftLine {
  item_id: string
  from_godown_id: string
  to_godown_id: string
  quantity: string
}
export const blankJournalLine = (): JournalDraftLine => ({ item_id: '', from_godown_id: '', to_godown_id: '', quantity: '' })

export interface JournalDraft {
  journal_type: JournalType
  journal_date: string
  narration: string
  reason_code: ReasonCode | ''
  reason_note: string
  lines: JournalDraftLine[]
}

/** Problems visible before sending (the server re-checks everything: S-02, S-03, S-07, S-10). Empty = ready. */
export function journalProblems(d: JournalDraft): string[] {
  const out: string[] = []
  if (!d.journal_date) out.push('Choose the journal date.')
  if (!d.narration.trim()) out.push('Narration is required.')
  if (d.journal_type === 'write_off') {
    if (!d.reason_code) out.push('Choose the write-off reason.')
    if (d.reason_code === 'other' && !d.reason_note.trim()) out.push('Reason "Other" needs a note.')
  }
  if (d.lines.length === 0) out.push('Add at least one line.')
  d.lines.forEach((l, i) => {
    const n = i + 1
    if (!l.item_id) out.push(`Line ${n}: choose the item.`)
    if (!l.from_godown_id) out.push(`Line ${n}: choose the ${d.journal_type === 'transfer' ? 'from godown' : 'godown'}.`)
    if (d.journal_type === 'transfer') {
      if (!l.to_godown_id) out.push(`Line ${n}: choose the to godown.`)
      else if (l.to_godown_id === l.from_godown_id) out.push(`Line ${n}: from and to godown are the same.`)
    }
    if (!isQuantity(l.quantity)) out.push(`Line ${n}: quantity must be above zero with at most 3 decimals.`)
  })
  return out
}

export function journalBody(d: JournalDraft): JournalBody {
  return {
    journal_type: d.journal_type,
    journal_date: d.journal_date,
    narration: d.narration.trim(),
    ...(d.journal_type === 'write_off' ? { reason_code: d.reason_code || null, reason_note: d.reason_note.trim() || null } : {}),
    lines: d.lines.map((l) => ({
      item_id: l.item_id,
      from_godown_id: l.from_godown_id,
      to_godown_id: d.journal_type === 'transfer' ? l.to_godown_id : null,
      quantity: l.quantity.trim(),
    })),
  }
}

/** Which buttons a journal may show for its status (the server enforces the same: 409 journal_state). */
export function journalActions(status: JournalStatus): ('edit' | 'delete' | 'approve' | 'post' | 'reverse')[] {
  switch (status) {
    case 'draft':
      return ['edit', 'delete', 'approve']
    case 'approved':
      return ['post']
    case 'posted':
      return ['reverse']
    default:
      return []
  }
}

/** Draft rows of the NRV grid -> request rows: a blank value deletes the saved NRV; a value needs a basis note (S-15). */
export function nrvRows(
  drafts: Record<string, { nrv: string; note: string }>,
): { rows: { item_id: string; nrv_per_unit: string | null; basis_note: string }[]; problems: string[] } {
  const rows: { item_id: string; nrv_per_unit: string | null; basis_note: string }[] = []
  const problems: string[] = []
  for (const [id, d] of Object.entries(drafts)) {
    const v = cleanNumber(d.nrv)
    if (v === '') {
      rows.push({ item_id: id, nrv_per_unit: null, basis_note: '' })
      continue
    }
    if (!isMoney(v)) problems.push(`NRV "${d.nrv}" must be a number with at most 2 decimals.`)
    else if (!d.note.trim()) problems.push(`NRV ${v} needs a basis note.`)
    rows.push({ item_id: id, nrv_per_unit: v, basis_note: d.note.trim() })
  }
  return { rows, problems }
}

/** The AS 2 write-down is shown as the server sent it; this only tells whether any row has one. */
export const hasWriteDown = (rows: { write_down: string }[]) => rows.some((r) => Number(r.write_down) > 0)
