import { useCallback, useEffect, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type {
  ActivityMailboxState,
  ActivityMailboxStatusResponse,
} from '../types/settings'

const POLL_INTERVAL_MS = 15_000
const STATES: readonly ActivityMailboxState[] = [
  'disabled',
  'demo_mode',
  'not_configured',
  'client_unavailable',
  'client_disabled',
  'client_not_permitted',
  'client_partition_mismatch',
  'folder_unavailable',
  'ready',
  'scan_error',
]

function parseStatus(value: unknown): ActivityMailboxStatusResponse | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const status = value as Record<string, unknown>
  if (typeof status.enabled !== 'boolean' ||
    typeof status.state !== 'string' || !STATES.includes(status.state as ActivityMailboxState) ||
    (status.folder_available !== null && typeof status.folder_available !== 'boolean') ||
    typeof status.client_registered !== 'boolean' ||
    typeof status.client_enabled !== 'boolean' ||
    typeof status.client_can_submit !== 'boolean' ||
    typeof status.client_partition_matches !== 'boolean' ||
    (status.last_scan_at !== null && typeof status.last_scan_at !== 'string') ||
    typeof status.last_imported_count !== 'number' ||
    (status.last_error !== null && typeof status.last_error !== 'string')) return null
  return status as unknown as ActivityMailboxStatusResponse
}

export function useActivityMailboxStatus(open: boolean) {
  const [status, setStatus] = useState<ActivityMailboxStatusResponse | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  const refresh = useCallback(async (): Promise<void> => {
    if (!open) return
    try {
      const response = await fetch(API_ENDPOINTS.activityMailboxStatus)
      if (!response.ok) throw new Error('Mailbox status unavailable')
      const parsed = parseStatus(await response.json())
      if (!parsed) throw new Error('Malformed mailbox status')
      setStatus(parsed)
      setUnavailable(false)
    } catch {
      setUnavailable(true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const initial = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [open, refresh])

  return { status, unavailable, refresh }
}
