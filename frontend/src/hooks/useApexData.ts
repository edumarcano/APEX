import { useCallback, useEffect, useState } from 'react'

import type {
  ActiveReminder,
  ApexDataState,
  PipelineState,
  TelemetryPayload,
  WeatherConditionArchetype,
} from '../types/telemetry'

const API_BASE = 'http://127.0.0.1:8000'
const STATUS_ENDPOINT = `${API_BASE}/api/v1/status`
const REMINDERS_ENDPOINT = `${API_BASE}/api/v1/reminders`
const REMINDERS_READ_ENDPOINT = `${API_BASE}/api/v1/reminders/read`

export type { ApexDataState } from '../types/telemetry'

export type UseApexDataReturn = ApexDataState & {
  refreshReminders: () => Promise<void>
  markReminderAsRead: (id: number) => Promise<void>
}

type ReminderRecord = {
  id: number
  note: string
}

function parseReminderRecords(body: unknown): ReminderRecord[] {
  if (!Array.isArray(body)) {
    return []
  }

  const records: ReminderRecord[] = []
  for (const entry of body) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as { id?: unknown; note?: unknown }
    if (typeof row.id !== 'number' || typeof row.note !== 'string') continue
    records.push({ id: row.id, note: row.note })
  }
  return records
}

function toActiveReminders(records: ReminderRecord[]): ActiveReminder[] {
  return records.map((record) => ({ id: record.id, note: record.note }))
}

function assembleRemindersTelemetry(records: ReminderRecord[]): string {
  if (records.length === 0) {
    return 'No pending reminders.'
  }

  const notes = records.map((record) => record.note).join(', ')
  return `Pending Reminders: ${notes}`
}

function remindersFromRecords(records: ReminderRecord[]): {
  activeReminders: ActiveReminder[]
  reminders: string
} {
  const activeReminders = toActiveReminders(records)
  return {
    activeReminders,
    reminders: assembleRemindersTelemetry(records),
  }
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

function parsePipelineStatus(body: unknown): PipelineState | null {
  if (!body || typeof body !== 'object') {
    return null
  }

  const record = body as Record<string, unknown>
  if (typeof record.step !== 'number' || typeof record.label !== 'string') {
    return null
  }

  return {
    step: record.step,
    label: record.label,
    timestamp: typeof record.timestamp === 'string' ? record.timestamp : '',
    is_speaking: record.is_speaking === true,
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
      .split(' ')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
}

/**
 * Micro-climate archetype resolver for scoped Weather card glow and border theming.
 * Matches condition tokens in the atmospheric detail clause (case-insensitive).
 */
export function resolveWeatherCondition(detail: string): WeatherConditionArchetype | null {
  const normalized = detail.trim().toLowerCase()
  if (!normalized) return null

  if (normalized.includes('thunderstorm')) return 'thunderstorm'
  if (
    normalized.includes('rain') ||
    normalized.includes('drizzle') ||
    normalized.includes('shower')
  ) {
    return 'rain'
  }
  if (normalized.includes('cloud') || normalized.includes('overcast')) return 'clouds'
  if (normalized.includes('clear')) {
    const hour = new Date().getHours()
    if (hour < 6 || hour >= 18) return 'clear_night'
    return 'clear_day'
  }

  return null
}

async function fetchUnreadReminderRecords(): Promise<ReminderRecord[]> {
  const response = await fetch(REMINDERS_ENDPOINT)
  if (!response.ok) {
    return []
  }

  const body: unknown = await response.json()
  return parseReminderRecords(body)
}

export function useApexData(): UseApexDataReturn {
  const [state, setState] = useState<ApexDataState>({
    data: null,
    status: 'idle',
    error: null,
    pipelineState: null,
    isPipelinePolling: false,
    isSpeaking: false,
    activeReminders: [],
  })

  const applyReminderRecords = useCallback((records: ReminderRecord[]): void => {
    const { activeReminders, reminders } = remindersFromRecords(records)

    setState((prev) => ({
      ...prev,
      activeReminders,
      data: prev.data
        ? {
            ...prev.data,
            activeReminders,
            reminders,
          }
        : prev.data,
    }))
  }, [])

  const refreshReminders = useCallback(async (): Promise<void> => {
    try {
      const records = await fetchUnreadReminderRecords()
      applyReminderRecords(records)
    } catch {
      // Reminder refresh is best-effort; preserve existing HUD state on failure.
    }
  }, [applyReminderRecords])

  const markReminderAsRead = useCallback(async (id: number): Promise<void> => {
    let removedReminder: ActiveReminder | undefined

    setState((prev) => {
      const target = prev.activeReminders.find((reminder) => reminder.id === id)
      if (!target) {
        return prev
      }

      removedReminder = target
      const nextActiveReminders = prev.activeReminders.filter(
        (reminder) => reminder.id !== id,
      )
      const nextRecords: ReminderRecord[] = nextActiveReminders.map((reminder) => ({
        id: reminder.id,
        note: reminder.note,
      }))
      const { reminders } = remindersFromRecords(nextRecords)

      return {
        ...prev,
        activeReminders: nextActiveReminders,
        data: prev.data
          ? {
              ...prev.data,
              activeReminders: nextActiveReminders,
              reminders,
            }
          : prev.data,
      }
    })

    if (!removedReminder) {
      return
    }

    try {
      const response = await fetch(REMINDERS_READ_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [id] }),
      })

      if (!response.ok) {
        throw new Error(`Mark read failed with status ${response.status}`)
      }
    } catch (error) {
      console.warn('Failed to mark reminder as read; restoring local state.', error)

      setState((prev) => {
        if (prev.activeReminders.some((reminder) => reminder.id === id)) {
          return prev
        }

        const restored = [...prev.activeReminders, removedReminder!].sort(
          (a, b) => a.id - b.id,
        )
        const nextRecords: ReminderRecord[] = restored.map((reminder) => ({
          id: reminder.id,
          note: reminder.note,
        }))
        const { reminders } = remindersFromRecords(nextRecords)

        return {
          ...prev,
          activeReminders: restored,
          data: prev.data
            ? {
                ...prev.data,
                activeReminders: restored,
                reminders,
              }
            : prev.data,
        }
      })
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
            isSpeaking: false,
            activeReminders: [],
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
            isSpeaking: false,
            activeReminders: [],
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
            isSpeaking: false,
            activeReminders: [],
          }))

          return
        }

        const telemetryRecord = telemetry as Record<string, unknown>
        const weatherReport = getStringField(telemetryRecord, 'weather')

        let reminderRecords: ReminderRecord[] = []
        try {
          reminderRecords = await fetchUnreadReminderRecords()
        } catch {
          reminderRecords = []
        }

        const { activeReminders, reminders } = remindersFromRecords(reminderRecords)

        const weatherDetail = resolveWeatherDetail(weatherReport)

        const mergedData: TelemetryPayload = {
          briefing: typeof payload.briefing === 'string' ? payload.briefing : '',
          weather: weatherReport,
          temperatureF: resolvePipelineTemperatureF(weatherReport),
          weatherDetail,
          weatherCondition: resolveWeatherCondition(weatherDetail),
          sports: getStringField(telemetryRecord, 'sports'),
          news: getStringField(telemetryRecord, 'news'),
          email: getStringField(telemetryRecord, 'email'),
          calendar: getStringField(telemetryRecord, 'calendar'),
          reminders,
          activeReminders,
        }

        setState((prev) => ({
          ...prev,
          data: mergedData,
          status: 'success',
          error: null,
          activeReminders,
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
          isSpeaking: false,
          activeReminders: [],
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

    if (
      state.status === 'success' &&
      state.pipelineState === null &&
      !state.isPipelinePolling
    ) {
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
            isPipelinePolling: false,
            isSpeaking: false,
          }))
          return
        }

        if (!response.ok) {
          return
        }

        const body: unknown = await response.json()
        const payload = parsePipelineStatus(body)
        if (!payload) {
          return
        }

        setState((prev) => ({
          ...prev,
          pipelineState: payload,
          isSpeaking: payload.is_speaking,
          isPipelinePolling:
            prev.status === 'loading' || prev.status === 'success',
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

  return { ...state, refreshReminders, markReminderAsRead }
}
