import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { RunRecord, RunStatus } from '../types/runs'

const ACTIVE_POLL_INTERVAL_MS = 1_500
const IDLE_POLL_INTERVAL_MS = 10_000

export const ACTIVE_RUN_STATUSES: ReadonlySet<RunStatus> = new Set(['queued', 'running', 'cancelling'])

export function isRunActive(status: RunStatus): boolean {
  return ACTIVE_RUN_STATUSES.has(status)
}

export interface UseCortexRunsOptions {
  conversationId?: string | null
  pollingEnabled?: boolean
  limit?: number
}

export interface UseCortexRunsResult {
  runs: RunRecord[]
  activeRuns: RunRecord[]
  selectedRunId: string | null
  selectedRun: RunRecord | null
  loading: boolean
  error: string | null
  selectRun: (runId: string | null) => void
  activeConversationRun: (conversationId?: string | null) => RunRecord | null
  cancelRun: (runId: string) => Promise<boolean>
  refreshRuns: () => Promise<void>
}

export function useCortexRuns({
  conversationId = null,
  pollingEnabled = true,
  limit = 25,
}: UseCortexRunsOptions = {}): UseCortexRunsResult {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [selectedRunIdState, setSelectedRunIdState] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchGenerationRef = useRef(0)
  const activeRunsCountRef = useRef(0)

  const refreshRuns = useCallback(async (): Promise<void> => {
    const generation = ++fetchGenerationRef.current
    setLoading(true)
    try {
      const response = await fetch(API_ENDPOINTS.cortexRuns({ limit }))
      if (!response.ok) {
        if (generation === fetchGenerationRef.current) {
          setError(`HTTP ${response.status}`)
        }
        return
      }
      const data = (await response.json()) as RunRecord[]
      if (generation !== fetchGenerationRef.current) return
      setRuns(Array.isArray(data) ? data : [])
      setError(null)
    } catch (err) {
      if (generation === fetchGenerationRef.current) {
        const message = err instanceof Error ? err.message : 'Failed to fetch cortex runs'
        setError(message)
      }
    } finally {
      if (generation === fetchGenerationRef.current) {
        setLoading(false)
      }
    }
  }, [limit])

  // Initial load
  useEffect(() => {
    queueMicrotask(() => void refreshRuns())
  }, [refreshRuns])

  const activeRuns = useMemo(() => runs.filter((r) => isRunActive(r.status)), [runs])

  useEffect(() => {
    activeRunsCountRef.current = activeRuns.length
  }, [activeRuns.length])

  // Dynamic polling & focus listener
  useEffect(() => {
    if (!pollingEnabled) return

    let cancelled = false
    let timer: number | undefined

    const scheduleNext = () => {
      if (cancelled) return
      const interval = activeRunsCountRef.current > 0 ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS
      timer = window.setTimeout(async () => {
        if (cancelled) return
        if (!document.hidden) {
          await refreshRuns()
        }
        scheduleNext()
      }, interval)
    }

    const onFocus = () => {
      if (!cancelled) {
        void refreshRuns()
      }
    }

    window.addEventListener('focus', onFocus)
    scheduleNext()

    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [pollingEnabled, refreshRuns])

  const activeConversationRun = useCallback(
    (targetConversationId?: string | null): RunRecord | null => {
      const targetId = targetConversationId ?? conversationId
      if (!targetId) return null
      return runs.find((r) => r.conversation_id === targetId && isRunActive(r.status)) ?? null
    },
    [conversationId, runs],
  )

  const selectedRun = useMemo(() => {
    if (selectedRunIdState) {
      const matched = runs.find((r) => r.id === selectedRunIdState)
      if (matched) return matched
    }
    if (conversationId) {
      const activeForConv = runs.find((r) => r.conversation_id === conversationId && isRunActive(r.status))
      if (activeForConv) return activeForConv
    }
    return runs[0] ?? null
  }, [selectedRunIdState, conversationId, runs])

  const selectedRunId = selectedRun?.id ?? null

  const cancelRun = useCallback(
    async (runId: string): Promise<boolean> => {
      try {
        const response = await fetch(API_ENDPOINTS.cortexRunCancel(runId), {
          method: 'POST',
        })
        if (!response.ok) return false
        await refreshRuns()
        return true
      } catch (err) {
        console.warn(`[useCortexRuns] Cancel run failed: ${err instanceof Error ? err.message : 'Unknown error'}`)
        return false
      }
    },
    [refreshRuns],
  )

  return {
    runs,
    activeRuns,
    selectedRunId,
    selectedRun,
    loading,
    error,
    selectRun: setSelectedRunIdState,
    activeConversationRun,
    cancelRun,
    refreshRuns,
  }
}
