import { useEffect, useState } from 'react'
import type { TelemetryPayload } from '../types/telemetry'

export type ApexDataState = {
  data: TelemetryPayload | null
  status: 'idle' | 'loading' | 'success' | 'error'
  error: string | null
}

function errorMessageFromBody(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  return null
}

function getStringField(
  source: Record<string, unknown>,
  key: string,
  fallback = '',
): string {
  const value = source[key]
  return typeof value === 'string' ? value : fallback
}

export function useApexData(): ApexDataState {
  const [state, setState] = useState<ApexDataState>({
    data: null,
    status: 'idle',
    error: null,
  })

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller

    setState((prev) => ({
      ...prev,
      status: 'loading',
      error: null,
    }))

    void (async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/v1/trigger', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
          signal,
        })

        let body: unknown = null
        try {
          body = await response.json()
        } catch {
          body = null
        }

        if (signal.aborted) return

        if (!response.ok) {
          const fromBody = errorMessageFromBody(body)
          setState({
            data: null,
            status: 'error',
            error:
              fromBody ??
              (response.statusText || `Request failed with status ${response.status}`),
          })
          return
        }

        if (!body || typeof body !== 'object') {
          setState({
            data: null,
            status: 'error',
            error: 'Invalid response: missing payload body',
          })
          return
        }

        const payload = body as { briefing?: unknown; telemetry?: unknown }
        const telemetry = payload.telemetry

        if (!telemetry || typeof telemetry !== 'object') {
          setState({
            data: null,
            status: 'error',
            error: 'Invalid response: missing telemetry',
          })
          return
        }

        const telemetryRecord = telemetry as Record<string, unknown>
        const mergedData: TelemetryPayload = {
          briefing: typeof payload.briefing === 'string' ? payload.briefing : '',
          weather: getStringField(telemetryRecord, 'weather'),
          sports: getStringField(telemetryRecord, 'sports'),
          news: getStringField(telemetryRecord, 'news'),
          email: getStringField(telemetryRecord, 'email'),
          calendar: getStringField(telemetryRecord, 'calendar'),
          reminders: getStringField(telemetryRecord, 'reminders'),
        }

        setState({
          data: mergedData,
          status: 'success',
          error: null,
        })
      } catch (err) {
        if (
          signal.aborted ||
          (err instanceof DOMException && err.name === 'AbortError')
        ) {
          return
        }

        setState({
          data: null,
          status: 'error',
          error: err instanceof Error ? err.message : 'Unknown error',
        })
      }
    })()

    return () => {
      controller.abort()
    }
  }, [])

  return state
}
