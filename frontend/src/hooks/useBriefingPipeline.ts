import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  ConnectorHealthEntry,
  PipelineState,
  SynthesisLiveState,
  SynthesisProfile,
  SynthesisProvider,
  SystemState,
  TtsEngine,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'
import { resolvePipelineTemperatureF, resolveWeatherCondition, resolveWeatherDetail } from '../lib/weatherTelemetry'

const STATUS_ENDPOINT = API_ENDPOINTS.status

export type BriefingPipelineState = {
  status: SystemState
  error: string | null
  briefing: string
  weather: string
  temperatureF: number | null
  weatherDetail: string
  weatherCondition: ReturnType<typeof resolveWeatherCondition>
  sports: string
  news: string
  email: string
  calendar: string
  insights: string[]
  confidenceScore: number
  failedConnectors: string[]
  connectorHealth: ConnectorHealthEntry[]
  pipelineState: PipelineState | null
  isPipelinePolling: boolean
  isSpeaking: boolean
  active_tts_engine: TtsEngine
  system_load_throttled: boolean
  synthesisProvider: SynthesisProvider | null
  synthesisProfile: SynthesisProfile | null
  synthesisFallbackReason: string | null
  demoModeActive: boolean
  devModeActive: boolean
}

export type UseBriefingPipelineReturn = BriefingPipelineState & {
  triggerSynthesis: () => Promise<void>
  resetBriefing: () => void
}

const VALID_TTS_ENGINES: readonly TtsEngine[] = ['google', 'kokoro', 'pyttsx3']
const VALID_SYNTHESIS_PROVIDERS: readonly SynthesisProvider[] = ['gemini', 'ollama', 'raw', 'demo']
const VALID_SYNTHESIS_PROFILES: readonly SynthesisProfile[] = ['comet', 'lynx', 'acinonyx', 'neofelis']

function parseEnum<T extends string>(value: unknown, values: readonly T[]): T | null {
  return typeof value === 'string' && values.includes(value as T) ? (value as T) : null
}

function parseTtsEngine(value: unknown): TtsEngine {
  if (typeof value === 'string' && VALID_TTS_ENGINES.includes(value as TtsEngine)) {
    return value as TtsEngine
  }
  return 'google'
}

function errorMessageFromBody(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  return typeof detail === 'string' ? detail : null
}

function getStringField(source: Record<string, unknown>, key: string, fallback = ''): string {
  const value = source[key]
  return typeof value === 'string' ? value : fallback
}

function parseConnectorHealth(raw: unknown): ConnectorHealthEntry[] {
  if (!Array.isArray(raw)) {
    return []
  }
  const entries: ConnectorHealthEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    if (typeof row.name !== 'string' || typeof row.status !== 'string') continue
    entries.push({
      name: row.name,
      status: row.status as ConnectorHealthEntry['status'],
      freshness:
        typeof row.freshness === 'string' ? (row.freshness as ConnectorHealthEntry['freshness']) : undefined,
      reason_code: typeof row.reason_code === 'string' ? row.reason_code : undefined,
      observed_at: typeof row.observed_at === 'string' ? row.observed_at : null,
    })
  }
  return entries
}

function resolveSyncHealthScore(digest: Record<string, unknown>): number {
  if (typeof digest.sync_health_score === 'number') {
    return digest.sync_health_score
  }
  if (typeof digest.confidence_score === 'number') {
    return digest.confidence_score
  }
  return 100.0
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

function isSynthesisGuarded(status: SystemState, isPipelinePolling: boolean): boolean {
  return status === 'loading' || isPipelinePolling
}

const INITIAL_STATE: BriefingPipelineState = {
  status: 'idle',
  error: null,
  briefing: '',
  weather: '',
  temperatureF: null,
  weatherDetail: '',
  weatherCondition: null,
  sports: '',
  news: '',
  email: '',
  calendar: '',
  insights: [],
  confidenceScore: 100.0,
  failedConnectors: [],
  connectorHealth: [],
  pipelineState: null,
  isPipelinePolling: false,
  isSpeaking: false,
  active_tts_engine: 'google',
  system_load_throttled: false,
  synthesisProvider: null,
  synthesisProfile: null,
  synthesisFallbackReason: null,
  demoModeActive: false,
  devModeActive: false,
}

export function useBriefingPipeline(): UseBriefingPipelineReturn {
  const [state, setState] = useState<BriefingPipelineState>(INITIAL_STATE)

  const stateRef = useRef(state)
  stateRef.current = state

  const synthesisAbortRef = useRef<AbortController | null>(null)

  const resetBriefing = useCallback((): void => {
    synthesisAbortRef.current?.abort()
    setState(INITIAL_STATE)
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
          status: 'error',
          error: fromBody ?? (response.statusText || `Request failed with status ${response.status}`),
          isPipelinePolling: false,
          isSpeaking: false,
        }))
        return
      }

      if (!body || typeof body !== 'object') {
        setState((prev) => ({
          ...prev,
          status: 'error',
          error: 'Invalid response: missing payload body',
          isPipelinePolling: false,
          isSpeaking: false,
        }))
        return
      }

      const payload = body as {
        briefing?: unknown
        telemetry?: unknown
        metadata?: unknown
        digest?: unknown
      }
      const digest = payload.digest
      const d = digest && typeof digest === 'object' ? (digest as Record<string, unknown>) : {}
      const insights = Array.isArray(d.insights) ? d.insights.map(String) : []
      const confidenceScore = resolveSyncHealthScore(d)
      const connectorHealth = parseConnectorHealth(d.connector_health)
      const rawFailedConnectors = Array.isArray(d.failed_connectors) ? d.failed_connectors : []
      const failedConnectors =
        rawFailedConnectors.length > 0
          ? rawFailedConnectors.map(String)
          : connectorHealth
              .filter((entry) => entry.status === 'unavailable')
              .map((entry) => (entry.name === 'f1' || entry.name === 'football' ? 'sports' : entry.name))
              .filter((name, index, all) => all.indexOf(name) === index)

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
        typeof metadata?.synthesis_fallback_reason === 'string' ? metadata.synthesis_fallback_reason : null

      if (!telemetry || typeof telemetry !== 'object') {
        setState((prev) => ({
          ...prev,
          status: 'error',
          error: 'Invalid response: missing telemetry',
          isPipelinePolling: false,
          isSpeaking: false,
        }))
        return
      }

      const telemetryRecord = telemetry as Record<string, unknown>
      const weatherReport = getStringField(telemetryRecord, 'weather')
      const weatherDetail = resolveWeatherDetail(weatherReport)

      setState((prev) => ({
        ...prev,
        status: 'success',
        error: null,
        briefing: typeof payload.briefing === 'string' ? payload.briefing : '',
        weather: weatherReport,
        temperatureF: resolvePipelineTemperatureF(weatherReport),
        weatherDetail,
        weatherCondition: resolveWeatherCondition(weatherDetail),
        sports: getStringField(telemetryRecord, 'sports'),
        news: getStringField(telemetryRecord, 'news'),
        email: getStringField(telemetryRecord, 'email'),
        calendar: getStringField(telemetryRecord, 'calendar'),
        insights,
        confidenceScore,
        failedConnectors,
        connectorHealth,
        demoModeActive,
        devModeActive,
        active_tts_engine,
        system_load_throttled,
        synthesisProvider,
        synthesisProfile,
        synthesisFallbackReason,
      }))
    } catch (err) {
      if (signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
        return
      }

      setState((prev) => ({
        ...prev,
        status: 'error',
        error: err instanceof Error ? err.message : 'Unknown error',
        isPipelinePolling: false,
        isSpeaking: false,
      }))
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

    if (state.status === 'success' && state.pipelineState === null && !state.isPipelinePolling) {
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
          isPipelinePolling: prev.status === 'loading' || prev.status === 'success',
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

  return { ...state, triggerSynthesis, resetBriefing }
}
