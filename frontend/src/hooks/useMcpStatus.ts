import { useCallback, useEffect, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import { parseMcpStatusResponse } from '../lib/settings'
import type { McpStatusResponse } from '../types/settings'

const POLL_INTERVAL_MS = 3000

export interface McpStatusState {
  status: McpStatusResponse | null
  loading: boolean
  unavailable: boolean
  refresh: () => Promise<void>
}

export function useMcpStatus(open: boolean): McpStatusState {
  const [status, setStatus] = useState<McpStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [unavailable, setUnavailable] = useState(false)

  const refresh = useCallback(async () => {
    if (!open) return
    setLoading(true)
    try {
      const response = await fetch(API_ENDPOINTS.mcpStatus)
      if (!response.ok) throw new Error('MCP status unavailable')
      const parsed = parseMcpStatusResponse(await response.json())
      if (!parsed) throw new Error('Malformed MCP status')
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
