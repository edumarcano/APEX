import { useEffect, useState } from 'react'
import {
  DEFAULT_SYSTEM_DIAGNOSTICS,
  type SystemDiagnostics,
  type TelemetryPayload,
} from '../types/telemetry'

export type ApexDataState = {
  data: TelemetryPayload | null
  status: 'idle' | 'loading' | 'success' | 'error'
  error: string | null
  diagnostics: SystemDiagnostics
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

function getNumericField(
  source: Record<string, unknown>,
  key: string,
): number | null {
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function mapDiagnosticsRecord(
  source: Record<string, unknown>,
): SystemDiagnostics {
  return {
    cpu: getNumericField(source, 'cpu'),
    ram: getNumericField(source, 'ram'),
    disk: getNumericField(source, 'disk'),
  }
}

/**
 * Variable Typography Engine - Telemetry Extractor
 * Parses the integer Fahrenheit token out of the raw atmospheric string.
 * Format: "Current temperature is {temp} degrees with {condition}."
 */
export function resolvePipelineTemperatureF(weatherReport: string | undefined | null): number | null {
  if (!weatherReport) return null

  const tempMatch = weatherReport.match(/Current temperature is\s+(-?\d+)\s+degrees/)
  if (!tempMatch) return null

  const parsedTemp = parseInt(tempMatch[1], 10)
  return isNaN(parsedTemp) ? null : parsedTemp
}

/**
 * Variable Typography Engine - Description Extractor
 * Isolates the atmospheric condition clause, stripping structural padding.
 * Format: "Current temperature is {temp} degrees with {condition}."
 */
export function resolveWeatherDetail(weatherReport: string | undefined | null): string {
  if (!weatherReport) return 'No Atmospheric Data'

  const conditionMatch = weatherReport.match(/with\s+([^.]+)/)
  if (!conditionMatch) return weatherReport

  return conditionMatch[1].trim()
}

export function useApexData(): ApexDataState {
  const [state, setState] = useState<Omit<ApexDataState, 'diagnostics'>>({
    data: null,
    status: 'idle',
    error: null,
  })
  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics>({
    ...DEFAULT_SYSTEM_DIAGNOSTICS,
  })

  useEffect(() => {
    let cancelled = false

    const pollDiagnostics = async (): Promise<void> => {
      try {
        const response = await fetch(
          'http://127.0.0.1:8000/api/v1/diagnostics',
        )

        if (!response.ok || cancelled) return

        let body: unknown = null
        try {
          body = await response.json()
        } catch {
          return
        }

        if (cancelled || !body || typeof body !== 'object') return

        setDiagnostics(mapDiagnosticsRecord(body as Record<string, unknown>))
      } catch {
        return
      }
    }

    void pollDiagnostics()
    const intervalId = window.setInterval(() => {
      void pollDiagnostics()
    }, 1000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [])

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
        const weatherReport = getStringField(telemetryRecord, 'weather')
        const mergedData: TelemetryPayload = {
          briefing: typeof payload.briefing === 'string' ? payload.briefing : '',
          weather: weatherReport,
          temperatureF: resolvePipelineTemperatureF(weatherReport),
          weatherDetail: resolveWeatherDetail(weatherReport),
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

  return { ...state, diagnostics }
}
