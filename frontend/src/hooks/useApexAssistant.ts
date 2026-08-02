import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  AgentMessage as TelemetryAgentMessage,
  AgentProfileStatus,
  AssistantProfile,
  CloudEffort,
  LoadedOllamaModelStatus,
  LocalContextUsage,
  LocalToolScope,
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
  local_context_usage?: LocalContextUsage | null
}

const VALID_ASSISTANT_PROFILES: readonly AssistantProfile[] = [
  'panthera',
  'neofelis',
  'delphinus',
  'orcinus',
  'sorex',
  'mus',
  'acinonyx',
]

const VALID_PROFILE_STATUSES: readonly ProfileAvailabilityStatus[] = [
  'available',
  'busy',
  'unknown',
  'disabled',
  'ollama_unreachable',
  'model_not_installed',
  'insufficient_ram',
  'cpu_overloaded',
]

const VALID_PROVIDERS: readonly AgentProfileStatus['provider'][] = [
  'ollama',
  'gemini',
  'openai',
  'xai',
]

const VALID_PROFILE_MODES: readonly AgentProfileStatus['mode'][] = ['cloud', 'local']

const VALID_CLOUD_EFFORTS: readonly CloudEffort[] = ['light', 'focused', 'extended']

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

function isProfileMode(value: unknown): value is AgentProfileStatus['mode'] {
  return typeof value === 'string' && (VALID_PROFILE_MODES as readonly string[]).includes(value)
}

function isCloudEffort(value: unknown): value is CloudEffort {
  return typeof value === 'string' && (VALID_CLOUD_EFFORTS as readonly string[]).includes(value)
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

function parseCloudEffortList(value: unknown): CloudEffort[] | null {
  if (value === null || value === undefined) {
    return null
  }
  if (!Array.isArray(value)) {
    return null
  }
  const parsed = value.filter(isCloudEffort)
  return parsed.length === value.length ? parsed : null
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
  const version = record.version
  const mode = record.mode
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
  if (typeof version !== 'string') {
    return null
  }
  if (!isProfileMode(mode)) {
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

  const effortOptions = parseCloudEffortList(record.effort_options)
  if (record.effort_options !== undefined && record.effort_options !== null && effortOptions === null) {
    return null
  }
  const defaultEffort =
    record.default_effort === null || record.default_effort === undefined
      ? null
      : isCloudEffort(record.default_effort)
        ? record.default_effort
        : null
  if (
    record.default_effort !== undefined &&
    record.default_effort !== null &&
    defaultEffort === null
  ) {
    return null
  }

  return {
    key,
    display_name: displayName,
    provider,
    version,
    mode,
    tier,
    stability,
    effort_options: effortOptions,
    default_effort: defaultEffort,
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

  const usageRecord =
    record.local_context_usage && typeof record.local_context_usage === 'object'
      ? (record.local_context_usage as Record<string, unknown>)
      : null
  const local_context_usage =
    usageRecord &&
    typeof usageRecord.estimated_prompt_tokens === 'number' &&
    typeof usageRecord.context_window === 'number' &&
    typeof usageRecord.history_messages_dropped === 'number'
      ? {
          estimated_prompt_tokens: usageRecord.estimated_prompt_tokens,
          peak_prompt_tokens: parseNullableFiniteNumber(usageRecord.peak_prompt_tokens),
          context_window: usageRecord.context_window,
          history_messages_dropped: usageRecord.history_messages_dropped,
        }
      : null

  return { answer, tool_trace, tool_outputs, error, local_context_usage }
}

function isAcinonyxProfile(profile: AssistantProfile): boolean {
  return profile === 'acinonyx'
}

export interface UseApexAssistantResult {
  assistantHistory: AgentMessage[]
  isAssistantQuerying: boolean
  isAssistantOpen: boolean
  assistantLatestTrace: ToolTraceItem[]
  assistantError: string | null
  assistantContextUsage: LocalContextUsage | null
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  queryAssistant: (
    prompt: string,
    profile: AssistantProfile,
    context?: {
      snapshotId?: string | null
      briefingId?: number | null
      toolScope?: LocalToolScope | null
      effort?: CloudEffort | null
    },
  ) => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  clearAssistantChat: (profile?: AssistantProfile) => void
  resetAssistantSession: () => void
  setAssistantOpen: (open: boolean) => void
}

export function useApexAssistant(
  profilesPollingEnabled = false,
  activeProfile: AssistantProfile = 'panthera',
): UseApexAssistantResult {
  const [productionHistory, setProductionHistory] = useState<AgentMessage[]>([])
  const [acinonyxHistory, setAcinonyxHistory] = useState<AgentMessage[]>([])
  const [isAssistantQuerying, setIsAssistantQuerying] = useState(false)
  const [isAssistantOpen, setAssistantOpen] = useState(false)
  const [assistantLatestTrace, setAssistantLatestTrace] = useState<ToolTraceItem[]>([])
  const [assistantError, setAssistantError] = useState<string | null>(null)
  const [assistantContextUsage, setAssistantContextUsage] =
    useState<LocalContextUsage | null>(null)
  const [profilesStatus, setProfilesStatus] = useState<AgentProfileStatus[]>([])
  const [profilesStatusHydrated, setProfilesStatusHydrated] = useState(false)

  const productionHistoryRef = useRef<AgentMessage[]>([])

  useEffect(() => {
    productionHistoryRef.current = productionHistory
  }, [productionHistory])

  const assistantHistory = useMemo(
    () => (isAcinonyxProfile(activeProfile) ? acinonyxHistory : productionHistory),
    [activeProfile, acinonyxHistory, productionHistory],
  )

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
    async (
      prompt: string,
      profile: AssistantProfile,
      context?: {
        snapshotId?: string | null
        briefingId?: number | null
        toolScope?: LocalToolScope | null
        effort?: CloudEffort | null
      },
    ): Promise<void> => {
      const trimmedPrompt = prompt.trim()
      if (!trimmedPrompt) {
        return
      }

      const useAcinonyxStore = isAcinonyxProfile(profile)
      const priorHistory = useAcinonyxStore ? [] : productionHistoryRef.current

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
            history: priorHistory,
            ...(context?.effort ? { effort: context.effort } : {}),
            ...(context?.snapshotId ? { snapshot_id: context.snapshotId } : {}),
            ...(context?.briefingId != null ? { briefing_id: context.briefingId } : {}),
            ...(context?.toolScope ? { tool_scope: context.toolScope } : {}),
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

        if (useAcinonyxStore) {
          // Acinonyx is intentionally single-turn: show only the latest exchange.
          setAcinonyxHistory([userMsg, modelMsg])
        } else {
          setProductionHistory((prev) => [...prev, userMsg, modelMsg])
        }
        setAssistantLatestTrace(body.tool_trace ?? [])
        setAssistantContextUsage(body.local_context_usage ?? null)

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
        void fetchProfilesStatus()
      }
    },
    [fetchProfilesStatus],
  )

  const clearAssistantChat = useCallback((profile?: AssistantProfile): void => {
    const target = profile ?? activeProfile
    if (isAcinonyxProfile(target)) {
      setAcinonyxHistory([])
    } else {
      setProductionHistory([])
    }
    setAssistantLatestTrace([])
    setAssistantError(null)
    setAssistantContextUsage(null)
  }, [activeProfile])

  const resetAssistantSession = useCallback((): void => {
    setProductionHistory([])
    setAcinonyxHistory([])
    setAssistantLatestTrace([])
    setAssistantError(null)
    setAssistantContextUsage(null)
    setAssistantOpen(false)
  }, [])

  return {
    assistantHistory,
    isAssistantQuerying,
    isAssistantOpen,
    assistantLatestTrace,
    assistantError,
    assistantContextUsage,
    profilesStatus,
    profilesStatusHydrated,
    queryAssistant,
    unloadLocalModel,
    clearAssistantChat,
    resetAssistantSession,
    setAssistantOpen,
  }
}
