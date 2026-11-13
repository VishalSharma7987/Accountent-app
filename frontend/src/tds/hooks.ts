import { tdsApi } from '../api/tds'
import { useLoad } from '../lib/useLoad'

export interface NatureOption {
  key: string
  label: string
}

/** Natures of payment from the rule table in force on a date (the accountant chooses; nothing is inferred). */
export function useNatures(on?: string) {
  const data = useLoad(() => tdsApi.ruleTable('natures', { on }), `tds-natures:${on ?? ''}`)
  const options: NatureOption[] = (data.data?.rows ?? []).map((r) => ({
    key: String(r.nature_key ?? r.key ?? ''),
    label: `${String(r.description ?? r.nature_key ?? '')}${r.kind === 'tcs' ? ' (TCS)' : ''}`,
  }))
  return { ...data, options }
}
