import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiFailure } from './apiError'

export interface Loaded<T> {
  data: T | null
  error: ApiFailure | null
  loading: boolean
  reload: () => void
}

/** Load data when `key` changes (use null to skip). Stale answers are ignored. */
export function useLoad<T>(load: (() => Promise<T>) | null, key: string): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)
  const loadRef = useRef(load)
  loadRef.current = load
  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    const fn = loadRef.current
    if (!fn) {
      setData(null)
      return
    }
    let current = true
    setLoading(true)
    setError(null)
    fn()
      .then((d) => {
        if (current) setData(d)
      })
      .catch((e: unknown) => {
        if (current) setError(e instanceof ApiFailure ? e : new ApiFailure(0, 'error', String(e)))
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [key, tick])

  return { data, error, loading, reload }
}

/** Turn any thrown value into an ApiFailure for display. */
export function asFailure(e: unknown): ApiFailure {
  return e instanceof ApiFailure ? e : new ApiFailure(0, 'error', e instanceof Error ? e.message : String(e))
}
