import { useCallback, useEffect, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import { parseLlamaCppServerStatusResponse } from '../lib/settings'
import type { LlamaCppServerStatusResponse } from '../types/settings'

const POLL_INTERVAL_MS = 2000

export interface LlamaCppStatusState {
  status: LlamaCppServerStatusResponse | null
  loading: boolean
  unavailable: boolean
  refresh: () => Promise<void>
}

export function useLlamaCppStatus(open: boolean): LlamaCppStatusState {
  const [status, setStatus] = useState<LlamaCppServerStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [unavailable, setUnavailable] = useState(false)

  const refresh = useCallback(async () => {
    if (!open) return
    setLoading(true)
    try {
      const response = await fetch(API_ENDPOINTS.llamaCppStatus)
      if (!response.ok) throw new Error('llama.cpp status unavailable')
      const parsed = parseLlamaCppServerStatusResponse(await response.json())
      if (!parsed) throw new Error('Malformed llama.cpp status')
      setStatus(parsed)
      setUnavailable(false)
    } catch {
      setUnavailable(true)
    } finally {
      setLoading(false)
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const initial = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [open, refresh])

  return { status, loading, unavailable, refresh }
}
