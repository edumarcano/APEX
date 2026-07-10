import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AgentMessage as TelemetryAgentMessage,
  AgentProfileStatus,
  AssistantProfile,
  LoadedOllamaModelStatus,
  ProfileAvailabilityStatus,
  ProfileStability,
  ToolOutputItem,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const AGENT_QUERY_ENDPOINT = API_ENDPOINTS.agentQuery
const AGENT_PROFILES_ENDPOINT = API_ENDPOINTS.agentProfiles
const AGENT_LOCAL_UNLOAD_ENDPOINT = API_ENDPOINTS.agentLocalUnload
const PROFILE_POLL_INTERVAL_MS = 4000
const PROFILE_POLL_INTERVAL_QUERYING_MS = 1000

export type { AssistantProfile, AgentProfileStatus, ToolOutputItem } from '../types/telemetry'

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  thought_signature?: string | null
}

export interface ToolResult {
  id: string
  name: string
  output: unknown
}

export interface AgentMessage extends TelemetryAgentMessage {
  tool_calls?: ToolCall[]
  tool_results?: ToolResult[]
}

export interface ToolTraceItem {
  name: string
  status: string
  duration_ms: number
}

interface AgentQueryResponseBody {
  answer?: string
  tool_trace?: ToolTraceItem[]
  tool_outputs?: ToolOutputItem[]
  error?: string | null
}

const VALID_ASSISTANT_PROFILES: readonly AssistantProfile[] = [
  'comet',
  'nova',
  'pulsar',
  'lynx',
  'acinonyx',
  'neofelis',
]

const VALID_PROFILE_STATUSES: readonly ProfileAvailabilityStatus[] = [
  'available',
  'unknown',
  'disabled',
  'ollama_unreachable',
  'model_not_installed',
  'insufficient_ram',
  'cpu_overloaded',
]

const VALID_PROVIDERS: readonly AgentProfileStatus['provider'][] = ['ollama', 'gemini']
const VALID_PROFILE_STABILITY: readonly ProfileStability[] = ['stable', 'preview']

function isAssistantProfile(value: unknown): value is AssistantProfile {
  return (
    typeof value === 'string' &&
    (VALID_ASSISTANT_PROFILES as readonly string[]).includes(value)
  )
}

function isProfileAvailabilityStatus(value: unknown): value is ProfileAvailabilityStatus {
  return (
    typeof value === 'string' &&
    (VALID_PROFILE_STATUSES as readonly string[]).includes(value)
  )
}

function isProvider(value: unknown): value is AgentProfileStatus['provider'] {
  return typeof value === 'string' && (VALID_PROVIDERS as readonly string[]).includes(value)
}

function isProfileStability(value: unknown): value is ProfileStability {
  return (
    typeof value === 'string' &&
    (VALID_PROFILE_STABILITY as readonly string[]).includes(value)
  )
}

function parseNullableString(value: unknown): string | null {
  if (typeof value === 'string') {
    return value
  }
  if (value === null || value === undefined) {
    return null
  }
  return null
}

function parseNullableFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (value === null || value === undefined) {
    return null
  }
  return null
}

function parseLoadedOllamaModelStatus(value: unknown): LoadedOllamaModelStatus | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const name = record.name
  const model = record.model

  if (typeof name !== 'string' || typeof model !== 'string') {
    return null
  }

  return {
    name,
    model,
    size_bytes: parseNullableFiniteNumber(record.size_bytes),
    size_vram_bytes: parseNullableFiniteNumber(record.size_vram_bytes),
    processor: parseNullableString(record.processor),
    context: parseNullableString(record.context),
    expires_at: parseNullableString(record.expires_at),
  }
}

function parseAgentProfileStatus(value: unknown): AgentProfileStatus | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const key = record.key
  const displayName = record.display_name
  const provider = record.provider
  const tier = record.tier
  const stability = record.stability
  const status = record.status

  if (!isAssistantProfile(key)) {
    return null
  }
  if (typeof displayName !== 'string') {
    return null
  }
  if (!isProvider(provider)) {
    return null
  }
  if (typeof tier !== 'string') {
    return null
  }
  if (!isProfileStability(stability)) {
    return null
  }
  if (!isProfileAvailabilityStatus(status)) {
    return null
  }

  return {
    key,
    display_name: displayName,
    provider,
    tier,
    stability,
    thinking_level: parseNullableString(record.thinking_level),
    status,
    active: typeof record.active === 'boolean' ? record.active : false,
    loading: typeof record.loading === 'boolean' ? record.loading : false,
    reason: parseNullableString(record.reason),
    idle_unload_remaining_seconds: parseNullableFiniteNumber(record.idle_unload_remaining_seconds),
    loaded_model: parseLoadedOllamaModelStatus(record.loaded_model),
  }
}

function parseAgentProfileStatusList(body: unknown): AgentProfileStatus[] {
  if (!Array.isArray(body)) {
    return []
  }

  return body
    .map(parseAgentProfileStatus)
    .filter((item): item is AgentProfileStatus => item !== null)
}

function parseToolTraceItem(value: unknown): ToolTraceItem | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const name = typeof record.name === 'string' ? record.name : null
  const status = typeof record.status === 'string' ? record.status : null
  const durationMs =
    typeof record.duration_ms === 'number' && Number.isFinite(record.duration_ms)
      ? record.duration_ms
      : null

  if (!name || !status || durationMs === null) {
    return null
  }

  return { name, status, duration_ms: durationMs }
}

function parseToolOutputItem(value: unknown): ToolOutputItem | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const name = typeof record.name === 'string' ? record.name : null
  const status = typeof record.status === 'string' ? record.status : null
  const durationMs =
    typeof record.duration_ms === 'number' && Number.isFinite(record.duration_ms)
      ? record.duration_ms
      : null

  if (!name || !status || durationMs === null || !('output' in record)) {
    return null
  }

  return {
    name,
    status,
    duration_ms: durationMs,
    output: record.output,
  }
}

function parseAgentQueryResponse(body: unknown): AgentQueryResponseBody {
  if (!body || typeof body !== 'object') {
    return {}
  }

  const record = body as Record<string, unknown>
  const answer = typeof record.answer === 'string' ? record.answer : undefined
  const error =
    typeof record.error === 'string'
      ? record.error
      : record.error === null
        ? null
        : undefined

  const rawTrace = Array.isArray(record.tool_trace) ? record.tool_trace : []
  const tool_trace = rawTrace
    .map(parseToolTraceItem)
    .filter((item): item is ToolTraceItem => item !== null)

  const rawOutputs = Array.isArray(record.tool_outputs) ? record.tool_outputs : []
  const tool_outputs = rawOutputs
    .map(parseToolOutputItem)
    .filter((item): item is ToolOutputItem => item !== null)

  return { answer, tool_trace, tool_outputs, error }
}

export interface UseApexAssistantResult {
  assistantHistory: AgentMessage[]
  isAssistantQuerying: boolean
  isAssistantOpen: boolean
  assistantLatestTrace: ToolTraceItem[]
  assistantError: string | null
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  queryAssistant: (prompt: string, profile: AssistantProfile) => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  clearAssistantChat: () => void
  resetAssistantSession: () => void
  setAssistantOpen: (open: boolean) => void
}

export function useApexAssistant(profilesPollingEnabled = false): UseApexAssistantResult {
  const [assistantHistory, setAssistantHistory] = useState<AgentMessage[]>([])
  const [isAssistantQuerying, setIsAssistantQuerying] = useState(false)
  const [isAssistantOpen, setAssistantOpen] = useState(false)
  const [assistantLatestTrace, setAssistantLatestTrace] = useState<ToolTraceItem[]>([])
  const [assistantError, setAssistantError] = useState<string | null>(null)
  const [profilesStatus, setProfilesStatus] = useState<AgentProfileStatus[]>([])
  const [profilesStatusHydrated, setProfilesStatusHydrated] = useState(false)

  // Mirrors isAssistantQuerying for the poll loop without restarting it on
  // every query state transition.
  const isAssistantQueryingRef = useRef(false)

  const fetchProfilesStatus = useCallback(async (): Promise<void> => {
    try {
      const response = await fetch(AGENT_PROFILES_ENDPOINT)
      if (!response.ok) {
        console.warn(
          `[useApexAssistant] Profile status fetch failed (${response.status}); retaining prior state.`,
        )
        return
      }

      const body: unknown = await response.json()
      const parsed = parseAgentProfileStatusList(body)
      setProfilesStatus(parsed)
      setProfilesStatusHydrated(true)
    } catch (fetchError) {
      const message =
        fetchError instanceof Error ? fetchError.message : 'Unknown profile fetch error'
      console.warn(`[useApexAssistant] Profile status fetch error: ${message}`)
    }
  }, [])

  const shouldPollProfiles = profilesPollingEnabled || isAssistantOpen

  useEffect(() => {
    if (!shouldPollProfiles) {
      return
    }

    let cancelled = false
    let timeoutId: number | undefined

    // Self-scheduling loop: the next poll is armed only after the current
    // request settles, so slow backend responses can never stack requests.
    // Polls continue during queries (faster interval) so the HUD can observe
    // local-model loading → active transitions mid-request.
    const pollLoop = async (): Promise<void> => {
      if (cancelled) {
        return
      }

      if (!document.hidden) {
        await fetchProfilesStatus()
      }

      if (!cancelled) {
        const intervalMs = isAssistantQueryingRef.current
          ? PROFILE_POLL_INTERVAL_QUERYING_MS
          : PROFILE_POLL_INTERVAL_MS
        timeoutId = window.setTimeout(() => {
          void pollLoop()
        }, intervalMs)
      }
    }

    void pollLoop()

    return () => {
      cancelled = true
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId)
      }
    }
  }, [shouldPollProfiles, fetchProfilesStatus])

  // Kick an immediate profile poll when a query starts so the HUD can
  // observe local-model loading without waiting for the next interval.
  useEffect(() => {
    if (!isAssistantQuerying || !shouldPollProfiles) {
      return
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Immediate sync keeps local model loading state visible at query start.
    void fetchProfilesStatus()
  }, [isAssistantQuerying, shouldPollProfiles, fetchProfilesStatus])

  const unloadLocalModel = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch(AGENT_LOCAL_UNLOAD_ENDPOINT, {
        method: 'POST',
      })

      if (!response.ok) {
        console.warn(
          `[useApexAssistant] Local model unload failed (${response.status}).`,
        )
        return false
      }

      await fetchProfilesStatus()
      return true
    } catch (fetchError) {
      const message =
        fetchError instanceof Error ? fetchError.message : 'Unknown unload error'
      console.warn(`[useApexAssistant] Local model unload error: ${message}`)
      return false
    }
  }, [fetchProfilesStatus])

  const queryAssistant = useCallback(
    async (prompt: string, profile: AssistantProfile): Promise<void> => {
      const trimmedPrompt = prompt.trim()
      if (!trimmedPrompt) {
        return
      }

      isAssistantQueryingRef.current = true
      setIsAssistantQuerying(true)
      setAssistantOpen(true)
      setAssistantError(null)

      const userMsg: AgentMessage = { role: 'user', content: trimmedPrompt }

      try {
        const response = await fetch(AGENT_QUERY_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: trimmedPrompt,
            profile,
            history: assistantHistory,
          }),
        })

        if (!response.ok) {
          let message = `Agent query failed (${response.status})`
          try {
            const errorBody: unknown = await response.json()
            if (
              errorBody &&
              typeof errorBody === 'object' &&
              'detail' in errorBody &&
              typeof (errorBody as { detail?: unknown }).detail === 'string'
            ) {
              message = (errorBody as { detail: string }).detail
            }
          } catch {
            // Keep default message when error body is not JSON.
          }
          setAssistantError(message)
          return
        }

        const body = parseAgentQueryResponse(await response.json())
        const answer = body.answer ?? ''
        const modelMsg: AgentMessage = {
          role: 'model',
          content: answer,
          tool_outputs: body.tool_outputs,
        }

        setAssistantHistory((prev) => [...prev, userMsg, modelMsg])
        setAssistantLatestTrace(body.tool_trace ?? [])

        if (body.error) {
          setAssistantError(body.error)
        }
      } catch (fetchError) {
        const message =
          fetchError instanceof Error
            ? fetchError.message
            : 'Failed to reach APEX.'
        setAssistantError(message)
      } finally {
        isAssistantQueryingRef.current = false
        setIsAssistantQuerying(false)
        // Resync active-model and idle-countdown badges now that the
        // generation has settled.
        void fetchProfilesStatus()
      }
    },
    [assistantHistory, fetchProfilesStatus],
  )

  const clearAssistantChat = useCallback((): void => {
    setAssistantHistory([])
    setAssistantLatestTrace([])
    setAssistantError(null)
  }, [])

  const resetAssistantSession = useCallback((): void => {
    clearAssistantChat()
    setAssistantOpen(false)
  }, [clearAssistantChat])

  return {
    assistantHistory,
    isAssistantQuerying,
    isAssistantOpen,
    assistantLatestTrace,
    assistantError,
    profilesStatus,
    profilesStatusHydrated,
    queryAssistant,
    unloadLocalModel,
    clearAssistantChat,
    resetAssistantSession,
    setAssistantOpen,
  }
}
