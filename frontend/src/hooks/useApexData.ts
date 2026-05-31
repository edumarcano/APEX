import { useCallback, useEffect, useState } from 'react'

import type { PipelineState, TelemetryPayload } from '../types/telemetry'

const API_BASE = 'http://127.0.0.1:8000'
const STATUS_ENDPOINT = `${API_BASE}/api/v1/status`
const REMINDERS_ENDPOINT = `${API_BASE}/api/v1/reminders`
const PIPELINE_COMPLETE_STEP = 4

export type ApexDataState = {
  data: TelemetryPayload | null
  status: 'idle' | 'loading' | 'success' | 'error'
  error: string | null
  pipelineState: PipelineState | null
  isPipelinePolling: boolean
}

export type UseApexDataReturn = ApexDataState & {
  refreshReminders: () => Promise<void>
}

type ReminderRecord = {
  id: number
  note: string
}

function assembleRemindersTelemetry(records: ReminderRecord[]): string {
  if (records.length === 0) {
    return 'No pending reminders.'
  }

  const notes = records.map((record) => record.note).join(', ')
  return `Pending Reminders: ${notes}`
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



export function useApexData(): UseApexDataReturn {
  const [state, setState] = useState<ApexDataState>({
    data: null,
    status: 'idle',
    error: null,
    pipelineState: null,
    isPipelinePolling: false,
  })

  const refreshReminders = useCallback(async (): Promise<void> => {
    try {
      const response = await fetch(REMINDERS_ENDPOINT)

      if (!response.ok) {
        return
      }

      const records = (await response.json()) as ReminderRecord[]
      if (!Array.isArray(records)) {
        return
      }

      const remindersTelemetry = assembleRemindersTelemetry(records)

      setState((prev) => {
        if (!prev.data) {
          return prev
        }

        return {
          ...prev,
          data: {
            ...prev.data,
            reminders: remindersTelemetry,
          },
        }
      })
    } catch {
      // Reminder refresh is best-effort; preserve existing HUD state on failure.
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

        const response = await fetch(`${API_BASE}/api/v1/trigger`, {

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

          setState((prev) => ({
            ...prev,
            data: null,
            status: 'error',
            error:
              fromBody ??
              (response.statusText || `Request failed with status ${response.status}`),
            isPipelinePolling: false,
          }))

          return

        }



        if (!body || typeof body !== 'object') {

          setState((prev) => ({
            ...prev,
            data: null,
            status: 'error',
            error: 'Invalid response: missing payload body',
            isPipelinePolling: false,
          }))

          return

        }



        const payload = body as { briefing?: unknown; telemetry?: unknown }

        const telemetry = payload.telemetry



        if (!telemetry || typeof telemetry !== 'object') {

          setState((prev) => ({
            ...prev,
            data: null,
            status: 'error',
            error: 'Invalid response: missing telemetry',
            isPipelinePolling: false,
          }))

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



        setState((prev) => ({
          ...prev,
          data: mergedData,
          status: 'success',
          error: null,
        }))

      } catch (err) {

        if (

          signal.aborted ||

          (err instanceof DOMException && err.name === 'AbortError')

        ) {

          return

        }



        setState((prev) => ({
          ...prev,
          data: null,
          status: 'error',
          error: err instanceof Error ? err.message : 'Unknown error',
          isPipelinePolling: false,
        }))

      }

    })()



    return () => {

      controller.abort()

    }

  }, [])



  useEffect(() => {
    if (state.status === 'error') {
      setState((prev) => ({
        ...prev,
        isPipelinePolling: false,
      }))
      return undefined
    }

    const pipelineComplete =
      state.pipelineState != null &&
      state.pipelineState.step >= PIPELINE_COMPLETE_STEP

    if (pipelineComplete) {
      setState((prev) => ({
        ...prev,
        isPipelinePolling: false,
      }))
      return undefined
    }

    let cancelled = false

    const fetchPipelineStatus = async (): Promise<void> => {
      try {
        const response = await fetch(STATUS_ENDPOINT)

        if (cancelled) return

        if (response.status === 404) {
          setState((prev) => ({
            ...prev,
            pipelineState: null,
            isPipelinePolling: prev.status === 'loading',
          }))
          return
        }

        if (!response.ok) {
          return
        }

        const payload = (await response.json()) as PipelineState
        const pipelineComplete = payload.step >= PIPELINE_COMPLETE_STEP

        setState((prev) => ({
          ...prev,
          pipelineState: payload,
          isPipelinePolling:
            prev.status === 'loading' ||
            (!pipelineComplete && prev.status === 'success'),
        }))
      } catch {
        if (!cancelled) {
          setState((prev) => ({
            ...prev,
            pipelineState: null,
            isPipelinePolling: prev.status === 'loading',
          }))
        }
      }
    }

    setState((prev) => ({
      ...prev,
      isPipelinePolling: true,
    }))

    void fetchPipelineStatus()

    const intervalId = window.setInterval(() => {
      void fetchPipelineStatus()
    }, 500)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [state.status, state.pipelineState?.step])

  return { ...state, refreshReminders }
}

