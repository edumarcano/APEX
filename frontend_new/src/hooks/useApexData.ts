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
        const response = await fetch('/api/v1/trigger', {
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

        const telemetry = (body as { telemetry?: TelemetryPayload }).telemetry
        if (!telemetry) {
          setState({
            data: null,
            status: 'error',
            error: 'Invalid response: missing telemetry',
          })
          return
        }

        setState({
          data: telemetry,
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
