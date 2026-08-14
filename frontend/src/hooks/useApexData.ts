import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  ActiveReminder,
  ApexDataState,
  AgentInitialSelection,
  AgentKey,
  CloudEffort,
  ConnectorHealthEntry,
  PipelineState,
  SynthesisLiveState,
  SynthesisAgent,
  SynthesisProvider,
  SynthesisStrategy,
  SystemState,
  TelemetryPayload,
  TtsEngine,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'
import { isAgentKey } from '../lib/agents'
import {
  resolvePipelineTemperatureF,
  resolveWeatherCondition,
  resolveWeatherDetail,
} from '../lib/weatherTelemetry'

const STATUS_ENDPOINT = API_ENDPOINTS.status
const REMINDERS_ENDPOINT = API_ENDPOINTS.reminders
const REMINDERS_COMPLETE_ENDPOINT = API_ENDPOINTS.remindersComplete
const CONFIG_ENDPOINT = API_ENDPOINTS.config

export type { ApexDataState } from '../types/telemetry'

export type UseApexDataReturn = ApexDataState & {
  refreshReminders: () => Promise<void>
  createReminder: (text: string) => Promise<'synced' | 'pending' | 'unknown'>
  markReminderAsRead: (id: string) => Promise<void>
  syncReminders: (ids: string[]) => Promise<Array<{ id: string; outcome: string }>>
  dismissUnknownReminder: (id: string) => Promise<void>
  triggerSynthesis: () => Promise<void>
  applyBootSettings: (next: {
    agentQueriesEnabled: boolean
    agentInitialSelection: AgentInitialSelection
    marketEnabled: boolean
  }) => void
}

type ReminderRecord = {
  id: string
  note: string
  source: 'todo' | 'local'
  sync_state: 'synced' | 'pending' | 'unknown'
}

type ReminderEnvelope = {
  items: ReminderRecord[]
  source_state: 'live' | 'stale' | 'unavailable'
  cache_timestamp: string | null
  pending_sync_count: number
}

function parseReminderEnvelope(body: unknown): ReminderEnvelope | null {
  if (!body || typeof body !== 'object') {
    return null
  }
  const envelope = body as Record<string, unknown>
  if (!Array.isArray(envelope.items) || !['live', 'stale', 'unavailable'].includes(String(envelope.source_state))) return null
  if (envelope.cache_timestamp !== null && typeof envelope.cache_timestamp !== 'string') return null
  if (typeof envelope.pending_sync_count !== 'number') return null

  const records: ReminderRecord[] = []
  for (const entry of envelope.items) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as { id?: unknown; note?: unknown; source?: unknown; sync_state?: unknown }
    if (
      typeof row.id !== 'string' || typeof row.note !== 'string' ||
      (row.source !== 'todo' && row.source !== 'local') ||
      !['synced', 'pending', 'unknown'].includes(String(row.sync_state))
    ) continue
    records.push({ id: row.id, note: row.note, source: row.source as ReminderRecord['source'], sync_state: row.sync_state as ReminderRecord['sync_state'] })
  }
  return {
    items: records,
    source_state: envelope.source_state as ReminderEnvelope['source_state'],
    cache_timestamp: envelope.cache_timestamp as string | null,
    pending_sync_count: envelope.pending_sync_count,
  }
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
  defaultAgent?: AgentKey,
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
    connectorHealth: [],
    ...(defaultAgent !== undefined ? { defaultAgent } : {}),
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
const VALID_SYNTHESIS_PROVIDERS: readonly SynthesisProvider[] = [
  'gemini',
  'ollama',
  'llama_cpp',
  'openai',
  'xai',
  'raw',
  'demo',
]
const VALID_SYNTHESIS_PROFILES: readonly SynthesisAgent[] = [
  'panthera',
  'apodemus',
]
const VALID_SYNTHESIS_STRATEGIES: readonly SynthesisStrategy[] = ['cloud', 'local', 'raw', 'demo']
const VALID_CLOUD_EFFORTS: readonly CloudEffort[] = ['light', 'focused', 'extended']

function parseEnum<T extends string>(value: unknown, values: readonly T[]): T | null {
  return typeof value === 'string' && values.includes(value as T) ? value as T : null
}

function parseAgentInitialSelection(value: unknown): AgentInitialSelection | undefined {
  if (!value || typeof value !== 'object') {
    return undefined
  }
  const record = value as Record<string, unknown>
  const runtime = record.runtime
  const agent = record.agent
  if (runtime !== 'cloud' && runtime !== 'local') {
    return undefined
  }
  if (!isAgentKey(agent)) {
    return undefined
  }
  const effort =
    record.effort === null || record.effort === undefined
      ? null
      : parseEnum(record.effort, VALID_CLOUD_EFFORTS)
  if (record.effort !== null && record.effort !== undefined && effort === null) {
    return undefined
  }
  return {
    runtime,
    agent,
    effort,
  }
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
        agent: parseEnum(item.agent, VALID_SYNTHESIS_PROFILES),
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

export { resolvePipelineTemperatureF, resolveWeatherCondition, resolveWeatherDetail } from '../lib/weatherTelemetry'

async function fetchReminderEnvelope(): Promise<ReminderEnvelope | null> {
  const response = await fetch(REMINDERS_ENDPOINT)
  if (!response.ok) {
    return null
  }

  const body: unknown = await response.json()
  return parseReminderEnvelope(body)
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
        typeof row.freshness === 'string'
          ? (row.freshness as ConnectorHealthEntry['freshness'])
          : undefined,
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
    connectorHealth: [],
    active_tts_engine: 'google',
    system_load_throttled: false,
    agentQueriesEnabled: true,
    marketEnabled: true,
    synthesisStrategy: 'cloud',
    synthesisProvider: 'openai',
    synthesisAgent: 'panthera',
    synthesisFallbackReason: null,
  })

  const stateRef = useRef(state)
  stateRef.current = state

  const synthesisAbortRef = useRef<AbortController | null>(null)

  const applyReminderRecords = useCallback((records: ReminderRecord[], sourceState?: ApexDataState['reminderSourceState']): void => {
    const activeReminders = records.map((record) => ({ ...record }))
    const reminders = assembleRemindersTelemetry(records)

    setState((prev) => ({
      ...prev,
      activeReminders,
      ...(sourceState ? { reminderSourceState: sourceState } : {}),
      data: prev.data
        ? {
            ...prev.data,
            activeReminders,
            reminders,
          }
        : createStandbyTelemetryPayload(activeReminders, reminders, prev.defaultAgent),
    }))
  }, [])

  const applyBootSettings = useCallback(
    (next: {
      agentQueriesEnabled: boolean
      agentInitialSelection: AgentInitialSelection
      marketEnabled: boolean
    }): void => {
      setState((prev) => ({
        ...prev,
        agentQueriesEnabled: next.agentQueriesEnabled,
        defaultAgent: next.agentInitialSelection.agent,
        agentInitialSelection: next.agentInitialSelection,
        marketEnabled: next.marketEnabled,
        data: prev.data
          ? {
              ...prev.data,
              agentQueriesEnabled: next.agentQueriesEnabled,
              defaultAgent: next.agentInitialSelection.agent,
            }
          : prev.data,
      }))
    },
    [],
  )

  const refreshReminders = useCallback(async (): Promise<void> => {
    try {
      const envelope = await fetchReminderEnvelope()
      if (envelope) applyReminderRecords(envelope.items, envelope.source_state)
    } catch {
      // Reminder refresh is best-effort; preserve existing HUD state on failure.
    }
  }, [applyReminderRecords])

  const createReminder = useCallback(
    async (text: string): Promise<'synced' | 'pending' | 'unknown'> => {
      const response = await fetch(REMINDERS_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })

      if (!response.ok) {
        throw new Error(`Create reminder failed with status ${response.status}`)
      }
      const body: unknown = await response.json()
      const outcome = body && typeof body === 'object'
        ? (body as { outcome?: unknown }).outcome
        : null
      await refreshReminders()
      return outcome === 'synced' || outcome === 'pending' || outcome === 'unknown'
        ? outcome
        : 'pending'
    },
    [refreshReminders],
  )

  const markReminderAsRead = useCallback(async (id: string): Promise<void> => {
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
      const nextRecords: ReminderRecord[] = nextActiveReminders.map((reminder) => ({ ...reminder }))
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
      const response = await fetch(REMINDERS_COMPLETE_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
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

        const restored = [...prev.activeReminders, removedReminder!].sort((a, b) => a.id.localeCompare(b.id))
        const nextRecords: ReminderRecord[] = restored.map((reminder) => ({ ...reminder }))
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

  const syncReminders = useCallback(async (ids: string[]): Promise<Array<{ id: string; outcome: string }>> => {
    const response = await fetch(API_ENDPOINTS.remindersSync, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    if (!response.ok) throw new Error(`Reminder sync failed with status ${response.status}`)
    const body: unknown = await response.json()
    await refreshReminders()
    if (!body || typeof body !== 'object' || !Array.isArray((body as { items?: unknown }).items)) return []
    return (body as { items: unknown[] }).items.flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const row = item as { id?: unknown; outcome?: unknown }
      return typeof row.id === 'string' && typeof row.outcome === 'string'
        ? [{ id: row.id, outcome: row.outcome }]
        : []
    })
  }, [refreshReminders])

  const dismissUnknownReminder = useCallback(async (id: string): Promise<void> => {
    const response = await fetch(API_ENDPOINTS.remindersDismiss, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    })
    if (!response.ok) throw new Error(`Reminder dismissal failed with status ${response.status}`)
    await refreshReminders()
  }, [refreshReminders])

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
      const synthesisAgent = parseEnum(metadata?.synthesis_agent, VALID_SYNTHESIS_PROFILES)
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
        reminderRecords = (await fetchReminderEnvelope())?.items ?? []
      } catch {
        reminderRecords = []
      }

      const activeReminders = reminderRecords.map((record) => ({ ...record }))
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
        connectorHealth,
        digest: { insights, connector_health: connectorHealth },
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
        connectorHealth,
        active_tts_engine,
        system_load_throttled,
        synthesisProvider,
        synthesisAgent,
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

        let defaultAgent: AgentKey | undefined
        let agentInitialSelection: AgentInitialSelection | undefined
        let agentQueriesEnabled: boolean | undefined
        let marketEnabled: boolean | undefined
        let demoModeActive: boolean | undefined
        let devModeActive: boolean | undefined
        let briefingDefaultMode: ApexDataState['briefingDefaultMode']
        let voiceMode: ApexDataState['voiceMode']
        let synthesisStrategy: SynthesisStrategy | undefined
        let synthesisAgent: SynthesisAgent | null | undefined
        if (configResp.ok) {
          try {
            const configBody: unknown = await configResp.json()
            if (configBody && typeof configBody === 'object') {
              const body = configBody as {
                default_agent?: unknown
                agent_initial_selection?: unknown
                ask_apex_enabled?: unknown
                market_enabled?: unknown
                demo_mode_active?: unknown
                dev_mode_active?: unknown
                briefing_default_mode?: unknown
                voice_mode?: unknown
                synthesis_strategy?: unknown
                synthesis_agent?: unknown
              }
              agentInitialSelection = parseAgentInitialSelection(
                body.agent_initial_selection,
              )
              if (agentInitialSelection) {
                defaultAgent = agentInitialSelection.agent
              } else {
                defaultAgent = isAgentKey(body.default_agent)
                  ? body.default_agent
                  : undefined
              }
              if (typeof body.ask_apex_enabled === 'boolean') {
                agentQueriesEnabled = body.ask_apex_enabled
              }
              if (typeof body.market_enabled === 'boolean') {
                marketEnabled = body.market_enabled
              }
              if (typeof body.demo_mode_active === 'boolean') {
                demoModeActive = body.demo_mode_active
              }
              if (typeof body.dev_mode_active === 'boolean') {
                devModeActive = body.dev_mode_active
              }
              briefingDefaultMode = parseEnum(body.briefing_default_mode, [
                'panthera',
                'apodemus',
                'structured_digest',
              ] as const) ?? undefined
              voiceMode = parseEnum(body.voice_mode, ['off', 'manual', 'automatic'] as const) ?? undefined
              synthesisStrategy = parseEnum(body.synthesis_strategy, VALID_SYNTHESIS_STRATEGIES) ?? undefined
              synthesisAgent = parseEnum(body.synthesis_agent, VALID_SYNTHESIS_PROFILES)
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
            defaultAgent !== undefined ||
            agentInitialSelection !== undefined ||
            agentQueriesEnabled !== undefined ||
            marketEnabled !== undefined ||
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
                defaultAgent,
                ...(agentInitialSelection !== undefined
                  ? { agentInitialSelection }
                  : {}),
                ...(agentQueriesEnabled !== undefined ? { agentQueriesEnabled } : {}),
                ...(marketEnabled !== undefined ? { marketEnabled } : {}),
                ...(briefingDefaultMode !== undefined ? { briefingDefaultMode } : {}),
                ...(voiceMode !== undefined ? { voiceMode } : {}),
                ...modePatch,
                ...(synthesisStrategy !== undefined ? { synthesisStrategy } : {}),
                ...(synthesisAgent !== undefined ? { synthesisAgent } : {}),
                synthesisProvider:
                  synthesisStrategy === 'raw'
                    ? 'raw'
                    : synthesisStrategy === 'demo'
                      ? 'demo'
                      : synthesisStrategy === 'local'
                        ? 'llama_cpp'
                        : prev.synthesisProvider,
                data: prev.data
                  ? {
                      ...prev.data,
                      defaultAgent,
                      ...(agentQueriesEnabled !== undefined ? { agentQueriesEnabled } : {}),
                    }
                  : createStandbyTelemetryPayload([], 'No pending reminders.', defaultAgent),
              }
            })
          }
          return
        }

        const body: unknown = await remindersResp.json()
        const reminderEnvelope = parseReminderEnvelope(body)
        const records = reminderEnvelope?.items ?? []

        if (signal.aborted) {
          return
        }

        const activeReminders = records.map((record) => ({ ...record }))
        const reminders = assembleRemindersTelemetry(records)

        setState((prev) => {
          if (prev.status !== 'idle') {
            return prev
          }

          return {
            ...prev,
            status: 'idle',
            activeReminders,
            ...(reminderEnvelope ? { reminderSourceState: reminderEnvelope.source_state } : {}),
            ...(defaultAgent !== undefined ? { defaultAgent } : {}),
            ...(agentInitialSelection !== undefined
              ? { agentInitialSelection }
              : {}),
            ...(agentQueriesEnabled !== undefined ? { agentQueriesEnabled } : {}),
            ...(marketEnabled !== undefined ? { marketEnabled } : {}),
            ...(briefingDefaultMode !== undefined ? { briefingDefaultMode } : {}),
            ...(voiceMode !== undefined ? { voiceMode } : {}),
            ...modePatch,
            ...(synthesisStrategy !== undefined ? { synthesisStrategy } : {}),
            ...(synthesisAgent !== undefined ? { synthesisAgent } : {}),
            synthesisProvider:
              synthesisStrategy === 'raw'
                ? 'raw'
                : synthesisStrategy === 'demo'
                  ? 'demo'
                  : synthesisStrategy === 'local'
                    ? 'llama_cpp'
                    : prev.synthesisProvider,
            data: prev.data
              ? {
                  ...prev.data,
                  activeReminders,
                  reminders,
                  ...(defaultAgent !== undefined ? { defaultAgent } : {}),
                  ...(agentQueriesEnabled !== undefined ? { agentQueriesEnabled } : {}),
                }
              : createStandbyTelemetryPayload(activeReminders, reminders, defaultAgent),
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

  return {
    ...state,
    refreshReminders,
    createReminder,
    markReminderAsRead,
    syncReminders,
    dismissUnknownReminder,
    triggerSynthesis,
    applyBootSettings,
  }
}
