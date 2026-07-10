import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  ActiveReminder,
  AgentCloudProfile,
  ApexDataState,
  AssistantProfile,
  PipelineState,
  SynthesisLiveState,
  SynthesisProfile,
  SynthesisProvider,
  SynthesisStrategy,
  SystemState,
  TelemetryPayload,
  TtsEngine,
  WeatherConditionArchetype,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const STATUS_ENDPOINT = API_ENDPOINTS.status
const REMINDERS_ENDPOINT = API_ENDPOINTS.reminders
const REMINDERS_READ_ENDPOINT = API_ENDPOINTS.remindersRead
const CONFIG_ENDPOINT = API_ENDPOINTS.config

export type { ApexDataState } from '../types/telemetry'

export type UseApexDataReturn = ApexDataState & {
  refreshReminders: () => Promise<void>
  markReminderAsRead: (id: number) => Promise<void>
  triggerSynthesis: () => Promise<void>
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

function assembleRemindersTelemetry(records: ReminderRecord[]): string {
  if (records.length === 0) {
    return 'No pending reminders.'
  }

  const notes = records.map((record) => record.note).join(', ')
  return `Pending Reminders: ${notes}`
}

function createStandbyTelemetryPayload(
  activeReminders: ActiveReminder[],
  reminders: string,
  defaultProfile?: AssistantProfile,
): TelemetryPayload {
  return {
    briefing: '',
    weather: '',
    temperatureF: null,
    weatherDetail: '',
    sports: '',
    news: '',
    email: '',
    calendar: '',
    reminders,
    activeReminders,
    confidenceScore: 100.0,
    failedConnectors: [],
    ...(defaultProfile !== undefined ? { defaultProfile } : {}),
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

const VALID_TTS_ENGINES: readonly TtsEngine[] = ['google', 'kokoro', 'pyttsx3']
const VALID_AGENT_PROFILES: readonly AgentCloudProfile[] = ['comet', 'nova', 'pulsar']
const VALID_SYNTHESIS_PROVIDERS: readonly SynthesisProvider[] = ['gemini', 'ollama', 'raw', 'demo']
const VALID_SYNTHESIS_PROFILES: readonly SynthesisProfile[] = ['comet', 'lynx', 'acinonyx', 'neofelis']
const VALID_SYNTHESIS_STRATEGIES: readonly SynthesisStrategy[] = ['llm', 'slm', 'raw', 'demo']

function parseEnum<T extends string>(value: unknown, values: readonly T[]): T | null {
  return typeof value === 'string' && values.includes(value as T) ? value as T : null
}

function parseDefaultProfile(value: unknown): AgentCloudProfile | undefined {
  if (typeof value === 'string' && VALID_AGENT_PROFILES.includes(value as AgentCloudProfile)) {
    return value as AgentCloudProfile
  }
  return undefined
}

function parseTtsEngine(value: unknown): TtsEngine {
  if (typeof value === 'string' && VALID_TTS_ENGINES.includes(value as TtsEngine)) {
    return value as TtsEngine
  }
  return 'google'
}

function parsePipelineStatus(body: unknown): PipelineState | null {
  if (!body || typeof body !== 'object') {
    return null
  }

  const record = body as Record<string, unknown>
  if (typeof record.step !== 'number' || typeof record.label !== 'string') {
    return null
  }

  const rawSynthesis = record.synthesis
  let synthesis: SynthesisLiveState | null = null
  if (rawSynthesis && typeof rawSynthesis === 'object') {
    const item = rawSynthesis as Record<string, unknown>
    const phase = typeof item.phase === 'string' ? item.phase : 'idle'
    if (['idle', 'loading', 'ready', 'generating', 'fallback', 'complete'].includes(phase)) {
      synthesis = {
        phase: phase as SynthesisLiveState['phase'],
        provider: parseEnum(item.provider, VALID_SYNTHESIS_PROVIDERS),
        profile: parseEnum(item.profile, VALID_SYNTHESIS_PROFILES),
        loading: item.loading === true,
        fallback_reason: typeof item.fallback_reason === 'string' ? item.fallback_reason : null,
      }
    }
  }
  return {
    step: record.step,
    label: record.label,
    timestamp: typeof record.timestamp === 'string' ? record.timestamp : '',
    is_speaking: record.is_speaking === true,
    active_tts_engine: parseTtsEngine(record.active_tts_engine),
    system_load_throttled: record.system_load_throttled === true,
    synthesis,
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
 * Micro-climate archetype resolver for per-condition Weather card icons.
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

function isSynthesisGuarded(status: SystemState, isPipelinePolling: boolean): boolean {
  return status === 'loading' || isPipelinePolling
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
    demoModeActive: false,
    devModeActive: false,
    confidenceScore: 100.0,
    failedConnectors: [],
    active_tts_engine: 'google',
    system_load_throttled: false,
    askApexEnabled: true,
    synthesisStrategy: 'llm',
    synthesisProvider: 'gemini',
    synthesisProfile: 'comet',
    synthesisFallbackReason: null,
  })

  const stateRef = useRef(state)
  stateRef.current = state

  const synthesisAbortRef = useRef<AbortController | null>(null)

  const applyReminderRecords = useCallback((records: ReminderRecord[]): void => {
    const activeReminders = records.map((record) => ({ id: record.id, note: record.note }))
    const reminders = assembleRemindersTelemetry(records)

    setState((prev) => ({
      ...prev,
      activeReminders,
      data: prev.data
        ? {
            ...prev.data,
            activeReminders,
            reminders,
          }
        : createStandbyTelemetryPayload(activeReminders, reminders, prev.defaultProfile),
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
      const reminders = assembleRemindersTelemetry(nextRecords)

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
        const reminders = assembleRemindersTelemetry(nextRecords)

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

  const triggerSynthesis = useCallback(async (): Promise<void> => {
    const { status, isPipelinePolling } = stateRef.current
    if (isSynthesisGuarded(status, isPipelinePolling)) {
      return
    }

    synthesisAbortRef.current?.abort()
    const controller = new AbortController()
    synthesisAbortRef.current = controller
    const { signal } = controller

    setState((prev) => ({
      ...prev,
      status: 'loading',
      error: null,
      pipelineState: null,
      isSpeaking: false,
    }))

    try {
      const response = await fetch(API_ENDPOINTS.trigger, {
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

      const payload = body as {
        briefing?: unknown
        telemetry?: unknown
        metadata?: unknown
        digest?: unknown
      }
      const digest = (body as { digest?: unknown })?.digest
      const d = digest && typeof digest === 'object' ? (digest as Record<string, unknown>) : {}
      const insights = Array.isArray(d.insights) ? d.insights.map(String) : []
      const confidenceScore = typeof d.confidence_score === 'number' ? d.confidence_score : 100.0
      const rawFailedConnectors = Array.isArray(d.failed_connectors) ? d.failed_connectors : []
      const failedConnectors = rawFailedConnectors.map(String)
      const telemetry = payload.telemetry
      const metadata =
        payload.metadata && typeof payload.metadata === 'object'
          ? (payload.metadata as Record<string, unknown>)
          : null
      const demoModeActive = metadata?.demo_mode_active === true
      const devModeActive = metadata?.dev_mode_active === true
      const active_tts_engine = parseTtsEngine(metadata?.active_tts_engine)
      const system_load_throttled = metadata?.system_load_throttled === true
      const synthesisProvider = parseEnum(metadata?.synthesis_provider, VALID_SYNTHESIS_PROVIDERS)
      const synthesisProfile = parseEnum(metadata?.synthesis_profile, VALID_SYNTHESIS_PROFILES)
      const synthesisFallbackReason =
        typeof metadata?.synthesis_fallback_reason === 'string'
          ? metadata.synthesis_fallback_reason
          : null

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

      const activeReminders = reminderRecords.map((record) => ({ id: record.id, note: record.note }))
      const reminders = assembleRemindersTelemetry(reminderRecords)

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
        confidenceScore,
        failedConnectors,
        digest: { insights },
      }

      setState((prev) => ({
        ...prev,
        data: mergedData,
        status: 'success',
        error: null,
        activeReminders,
        demoModeActive,
        devModeActive,
        confidenceScore,
        failedConnectors,
        active_tts_engine,
        system_load_throttled,
        synthesisProvider,
        synthesisProfile,
        synthesisFallbackReason,
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
  }, [])

  useEffect(() => {
    if (stateRef.current.status !== 'idle') {
      return undefined
    }

    const controller = new AbortController()
    const { signal } = controller

    void (async (): Promise<void> => {
      try {
        const [remindersResp, configResp] = await Promise.all([
          fetch(REMINDERS_ENDPOINT, { signal }),
          fetch(CONFIG_ENDPOINT, { signal }),
        ])

        if (signal.aborted) {
          return
        }

        let defaultProfile: AgentCloudProfile | undefined
        let askApexEnabled: boolean | undefined
        let demoModeActive: boolean | undefined
        let devModeActive: boolean | undefined
        let synthesisStrategy: SynthesisStrategy | undefined
        let synthesisProfile: SynthesisProfile | null | undefined
        if (configResp.ok) {
          try {
            const configBody: unknown = await configResp.json()
            if (configBody && typeof configBody === 'object') {
              const body = configBody as {
                default_profile?: unknown
                ask_apex_enabled?: unknown
                demo_mode_active?: unknown
                dev_mode_active?: unknown
                synthesis_strategy?: unknown
                synthesis_profile?: unknown
              }
              defaultProfile = parseDefaultProfile(body.default_profile)
              if (typeof body.ask_apex_enabled === 'boolean') {
                askApexEnabled = body.ask_apex_enabled
              }
              if (typeof body.demo_mode_active === 'boolean') {
                demoModeActive = body.demo_mode_active
              }
              if (typeof body.dev_mode_active === 'boolean') {
                devModeActive = body.dev_mode_active
              }
              synthesisStrategy = parseEnum(body.synthesis_strategy, VALID_SYNTHESIS_STRATEGIES) ?? undefined
              synthesisProfile = parseEnum(body.synthesis_profile, VALID_SYNTHESIS_PROFILES)
            }
          } catch {
            // Config hydration is best-effort; preserve dormant idle state on parse failure.
          }
        }

        const modePatch = {
          ...(demoModeActive !== undefined ? { demoModeActive } : {}),
          ...(devModeActive !== undefined ? { devModeActive } : {}),
        }

        if (!remindersResp.ok) {
          if (
            defaultProfile !== undefined ||
            askApexEnabled !== undefined ||
            demoModeActive !== undefined ||
            devModeActive !== undefined ||
            synthesisStrategy !== undefined
          ) {
            setState((prev) => {
              if (prev.status !== 'idle') {
                return prev
              }

              return {
                ...prev,
                defaultProfile,
                ...(askApexEnabled !== undefined ? { askApexEnabled } : {}),
                ...modePatch,
                ...(synthesisStrategy !== undefined ? { synthesisStrategy } : {}),
                ...(synthesisProfile !== undefined ? { synthesisProfile } : {}),
                synthesisProvider:
                  synthesisStrategy === 'raw'
                    ? 'raw'
                    : synthesisStrategy === 'demo'
                      ? 'demo'
                      : synthesisStrategy === 'slm'
                        ? 'ollama'
                        : prev.synthesisProvider,
                data: prev.data
                  ? {
                      ...prev.data,
                      defaultProfile,
                      ...(askApexEnabled !== undefined ? { askApexEnabled } : {}),
                    }
                  : createStandbyTelemetryPayload([], 'No pending reminders.', defaultProfile),
              }
            })
          }
          return
        }

        const body: unknown = await remindersResp.json()
        const records = parseReminderRecords(body)

        if (signal.aborted) {
          return
        }

        const activeReminders = records.map((record) => ({ id: record.id, note: record.note }))
        const reminders = assembleRemindersTelemetry(records)

        setState((prev) => {
          if (prev.status !== 'idle') {
            return prev
          }

          return {
            ...prev,
            status: 'idle',
            activeReminders,
            ...(defaultProfile !== undefined ? { defaultProfile } : {}),
            ...(askApexEnabled !== undefined ? { askApexEnabled } : {}),
            ...modePatch,
            ...(synthesisStrategy !== undefined ? { synthesisStrategy } : {}),
            ...(synthesisProfile !== undefined ? { synthesisProfile } : {}),
            synthesisProvider:
              synthesisStrategy === 'raw'
                ? 'raw'
                : synthesisStrategy === 'demo'
                  ? 'demo'
                  : synthesisStrategy === 'slm'
                    ? 'ollama'
                    : prev.synthesisProvider,
            data: prev.data
              ? {
                  ...prev.data,
                  activeReminders,
                  reminders,
                  ...(defaultProfile !== undefined ? { defaultProfile } : {}),
                  ...(askApexEnabled !== undefined ? { askApexEnabled } : {}),
                }
              : createStandbyTelemetryPayload(activeReminders, reminders, defaultProfile),
          }
        })
      } catch (err) {
        if (
          signal.aborted ||
          (err instanceof DOMException && err.name === 'AbortError')
        ) {
          return
        }
        // Standby reminder fetch is best-effort; preserve dormant idle state on failure.
      }
    })()

    return () => {
      controller.abort()
    }
  }, [])

  useEffect(() => {
    return () => {
      synthesisAbortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (state.status === 'idle') {
      return undefined
    }

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
  // eslint-disable-next-line react-hooks/exhaustive-deps -- The polling transition is keyed to public lifecycle state only.
  }, [state.status, state.pipelineState?.step])

  return { ...state, refreshReminders, markReminderAsRead, triggerSynthesis }
}
