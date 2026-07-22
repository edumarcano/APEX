import { useCallback, useRef, useState } from 'react'

import type { ConnectorHealthEntry, ConnectorHealthStatus, ConnectorFreshness, TelemetryModuleEntry, TelemetrySnapshot } from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const TELEMETRY_REFRESH_ENDPOINT = API_ENDPOINTS.telemetryRefresh
const TELEMETRY_LATEST_ENDPOINT = API_ENDPOINTS.telemetryLatest

export type ModuleRefreshState = Record<string, boolean>

export type UseTelemetrySnapshotReturn = {
  snapshot: TelemetrySnapshot | null
  isRefreshingAll: boolean
  refreshingConnectors: Set<string>
  error: string | null
  refreshAll: (opts?: { force?: boolean }) => Promise<TelemetrySnapshot | null>
  refreshConnector: (name: string, opts?: { force?: boolean }) => Promise<TelemetrySnapshot | null>
  loadLatest: () => Promise<TelemetrySnapshot | null>
  clear: () => void
}

const VALID_CONNECTOR_STATUSES: readonly ConnectorHealthStatus[] = [
  'healthy',
  'degraded',
  'unavailable',
  'disabled',
]

const VALID_FRESHNESS: readonly ConnectorFreshness[] = ['live', 'fresh_cache', 'stale', 'none']

function parseConnectorHealth(raw: unknown): ConnectorHealthEntry[] {
  if (!Array.isArray(raw)) {
    return []
  }
  const entries: ConnectorHealthEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    if (typeof row.name !== 'string' || typeof row.status !== 'string') continue
    if (!VALID_CONNECTOR_STATUSES.includes(row.status as ConnectorHealthStatus)) continue
    entries.push({
      name: row.name,
      status: row.status as ConnectorHealthStatus,
      freshness:
        typeof row.freshness === 'string' && VALID_FRESHNESS.includes(row.freshness as ConnectorFreshness)
          ? (row.freshness as ConnectorFreshness)
          : undefined,
      reason_code: typeof row.reason_code === 'string' ? row.reason_code : undefined,
      observed_at: typeof row.observed_at === 'string' ? row.observed_at : null,
    })
  }
  return entries
}

function parseModuleEntry(raw: unknown): TelemetryModuleEntry | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  if (typeof row.name !== 'string' || typeof row.status !== 'string') return null
  if (!VALID_CONNECTOR_STATUSES.includes(row.status as ConnectorHealthStatus)) return null

  return {
    name: row.name,
    status: row.status as ConnectorHealthStatus,
    freshness:
      typeof row.freshness === 'string' && VALID_FRESHNESS.includes(row.freshness as ConnectorFreshness)
        ? (row.freshness as ConnectorFreshness)
        : 'none',
    reason_code: typeof row.reason_code === 'string' ? row.reason_code : '',
    observed_at: typeof row.observed_at === 'string' ? row.observed_at : null,
    display_text: typeof row.display_text === 'string' ? row.display_text : '',
    data: row.data && typeof row.data === 'object' ? (row.data as Record<string, unknown>) : {},
  }
}

function parseModules(raw: unknown): Record<string, TelemetryModuleEntry> {
  if (!raw || typeof raw !== 'object') return {}
  const modules: Record<string, TelemetryModuleEntry> = {}
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const parsed = parseModuleEntry(value)
    if (parsed) {
      modules[key] = parsed
    }
  }
  return modules
}

function parseTelemetrySnapshot(body: unknown): TelemetrySnapshot | null {
  if (!body || typeof body !== 'object') {
    return null
  }

  const record = body as Record<string, unknown>
  if (typeof record.snapshot_id !== 'string' || typeof record.collected_at !== 'string') {
    return null
  }

  return {
    snapshot_id: record.snapshot_id,
    collected_at: record.collected_at,
    modules: parseModules(record.modules),
    sync_health_score: typeof record.sync_health_score === 'number' ? record.sync_health_score : 100.0,
    connector_health: parseConnectorHealth(record.connector_health),
    failed_connectors: Array.isArray(record.failed_connectors) ? record.failed_connectors.map(String) : [],
  }
}

export function useTelemetrySnapshot(): UseTelemetrySnapshotReturn {
  const [snapshot, setSnapshot] = useState<TelemetrySnapshot | null>(null)
  const [isRefreshingAll, setIsRefreshingAll] = useState(false)
  const [refreshingConnectors, setRefreshingConnectors] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  const inFlightRef = useRef(false)

  const runRefresh = useCallback(
    async (connectors: string[] | null, opts?: { force?: boolean }): Promise<TelemetrySnapshot | null> => {
      if (inFlightRef.current) {
        setError('A telemetry refresh is already in progress')
        return null
      }

      inFlightRef.current = true
      setError(null)

      if (connectors === null) {
        setIsRefreshingAll(true)
      } else {
        setRefreshingConnectors((prev) => {
          const next = new Set(prev)
          for (const name of connectors) next.add(name)
          return next
        })
      }

      try {
        const response = await fetch(TELEMETRY_REFRESH_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...(connectors !== null ? { connectors } : {}),
            ...(opts?.force ? { force: true } : {}),
          }),
        })

        if (response.status === 409) {
          setError('A telemetry refresh is already in progress')
          return null
        }

        let body: unknown = null
        try {
          body = await response.json()
        } catch {
          body = null
        }

        if (!response.ok) {
          const message =
            body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string'
              ? (body as { detail: string }).detail
              : `Telemetry refresh failed with status ${response.status}`
          setError(message)
          return null
        }

        const parsed = parseTelemetrySnapshot(body)
        if (!parsed) {
          setError('Invalid telemetry snapshot response')
          return null
        }

        setSnapshot(parsed)
        return parsed
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown telemetry refresh error')
        return null
      } finally {
        inFlightRef.current = false
        if (connectors === null) {
          setIsRefreshingAll(false)
        } else {
          setRefreshingConnectors((prev) => {
            const next = new Set(prev)
            for (const name of connectors) next.delete(name)
            return next
          })
        }
      }
    },
    [],
  )

  const refreshAll = useCallback(
    (opts?: { force?: boolean }): Promise<TelemetrySnapshot | null> => runRefresh(null, opts),
    [runRefresh],
  )

  const refreshConnector = useCallback(
    (name: string, opts?: { force?: boolean }): Promise<TelemetrySnapshot | null> => runRefresh([name], opts),
    [runRefresh],
  )

  const loadLatest = useCallback(async (): Promise<TelemetrySnapshot | null> => {
    setError(null)
    try {
      const response = await fetch(TELEMETRY_LATEST_ENDPOINT)
      if (!response.ok) {
        return null
      }

      const body: unknown = await response.json()
      const parsed = parseTelemetrySnapshot(body)
      if (parsed) {
        setSnapshot(parsed)
      }
      return parsed
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown telemetry load error')
      return null
    }
  }, [])

  const clear = useCallback((): void => {
    setSnapshot(null)
    setError(null)
  }, [])

  return {
    snapshot,
    isRefreshingAll,
    refreshingConnectors,
    error,
    refreshAll,
    refreshConnector,
    loadLatest,
    clear,
  }
}
