import { useCallback, useEffect, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'

export interface ToolRoutingStatus {
  mode: string
  model_key: string
  installed: boolean
  verified: boolean
  loaded: boolean
  state: string
  reason: string | null
}

export function useToolRoutingStatus(open = true): ToolRoutingStatus | null {
  const [status, setStatus] = useState<ToolRoutingStatus | null>(null)

  const refresh = useCallback(async () => {
    if (!open) return
    try {
      const response = await fetch(API_ENDPOINTS.cortexToolRoutingStatus)
      if (!response.ok) {
        return
      }
      const body = (await response.json()) as ToolRoutingStatus
      setStatus(body)
    } catch {
      setStatus(null)
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const timer = window.setTimeout(() => void refresh(), 0)
    return () => window.clearTimeout(timer)
  }, [open, refresh])

  return status
}
