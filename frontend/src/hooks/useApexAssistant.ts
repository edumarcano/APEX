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
  ProfilePricingMetadata,
  ProfileStatusSource,
  ProfileStability,
  ToolOutputItem,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const AGENT_QUERY_ENDPOINT = API_ENDPOINTS.agentQuery
const AGENT_PROFILES_ENDPOINT = API_ENDPOINTS.agentProfiles
const AGENT_LOCAL_UNLOAD_ENDPOINT = API_ENDPOINTS.agentLocalUnload
const AGENT_LOCAL_LOAD_ENDPOINT = API_ENDPOINTS.agentLocalLoad
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
  tool_trace?: ToolTraceItem[]
  metadata?: AssistantQueryMetadata
}

export interface ToolTraceItem {
  name: string
  status: string
  duration_ms: number
  origin?: 'apex' | 'provider'
  billable_units?: number | null
}

export interface AssistantCitation {
  title: string | null
  uri: string | null
  snippet: string | null
  source: string | null
}

export interface AssistantQueryMetadata {
  profile: {
    key: AssistantProfile
    version: string | null
    provider: string | null
    configuredModel: string | null
    resolvedModel: string | null
    requestedEffort: CloudEffort | null
    resolvedEffort: string | null
  } | null
  usage: {
    inputTokens: number | null
    cachedInputTokens: number | null
    reasoningTokens: number | null
    outputTokens: number | null
    totalTokens: number | null
  } | null
  timing: {
    totalMs: number | null
    providerMs: number | null
    apexToolMs: number | null
  } | null
  cost: {
    tokenCost: number | null
    hostedToolCost: number | null
    totalCost: number | null
    currency: string
    pricingVersion: string | null
    completeness: string | null
  } | null
  citations: AssistantCitation[]
}

interface AgentQueryResponseBody {
  answer?: string
  tool_trace?: ToolTraceItem[]
  tool_outputs?: ToolOutputItem[]
  error?: string | null
  local_context_usage?: LocalContextUsage | null
  metadata?: AssistantQueryMetadata
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
  'configured',
  'verifying',
  'verified',
  'unauthorized',
  'model_unavailable',
  'rate_limited',
  'quota_exhausted',
  'billing_blocked',
  'provider_unreachable',
  'provider_error',
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
const VALID_PROFILE_STATUS_SOURCES: readonly ProfileStatusSource[] = ['configuration', 'verification', 'request', 'runtime']

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

function parseProfilePricing(value: unknown): ProfilePricingMetadata {
  const fallback: ProfilePricingMetadata = {
    currency: 'USD', pricing_version: 'unknown', billing_basis: 'standard',
    input_per_million: 0, output_per_million: 0, cached_input_per_million: null,
    long_context_threshold_tokens: null, long_context_input_per_million: null,
    long_context_output_per_million: null, long_context_cached_input_per_million: null,
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fallback
  const record = value as Record<string, unknown>
  const billingBasis = record.billing_basis
  if (
    record.currency !== 'USD' || typeof record.pricing_version !== 'string' ||
    (billingBasis !== 'free_tier' && billingBasis !== 'standard' && billingBasis !== 'local') ||
    typeof record.input_per_million !== 'number' || typeof record.output_per_million !== 'number'
  ) return fallback
  return {
    currency: 'USD', pricing_version: record.pricing_version, billing_basis: billingBasis,
    input_per_million: record.input_per_million, output_per_million: record.output_per_million,
    cached_input_per_million: parseNullableFiniteNumber(record.cached_input_per_million),
    long_context_threshold_tokens: parseNullableFiniteNumber(record.long_context_threshold_tokens),
    long_context_input_per_million: parseNullableFiniteNumber(record.long_context_input_per_million),
    long_context_output_per_million: parseNullableFiniteNumber(record.long_context_output_per_million),
    long_context_cached_input_per_million: parseNullableFiniteNumber(record.long_context_cached_input_per_million),
  }
}

function parseAgentProfileStatus(value: unknown): AgentProfileStatus | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const key = record.key
  const displayName = record.display_name
  const description = record.description
  const configuredModel = record.configured_model
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
  if (typeof description !== 'string' || typeof configuredModel !== 'string') {
    return null
  }
  const nativeToolsRecord = record.native_tools
  if (
    !nativeToolsRecord ||
    typeof nativeToolsRecord !== 'object' ||
    Array.isArray(nativeToolsRecord) ||
    !Object.values(nativeToolsRecord).every((value) => typeof value === 'boolean')
  ) {
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
    description,
    configured_model: configuredModel,
    native_tools: nativeToolsRecord as Record<string, boolean>,
    provider,
    version,
    sort_order: typeof record.sort_order === 'number' && Number.isInteger(record.sort_order) && record.sort_order >= 0 ? record.sort_order : 0,
    capabilities: Array.isArray(record.capabilities) && record.capabilities.every((item) => typeof item === 'string') ? record.capabilities : [],
    mode,
    tier,
    stability,
    effort_options: effortOptions,
    default_effort: defaultEffort,
    status,
    status_source: isProfileStatusSource(record.status_source) ? record.status_source : 'configuration',
    status_checked_at: parseNullableString(record.status_checked_at),
    provider_account_tier: parseNullableString(record.provider_account_tier),
    pricing: parseProfilePricing(record.pricing),
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

  return {
    name,
    status,
    duration_ms: durationMs,
    ...(record.origin === 'apex' || record.origin === 'provider'
      ? { origin: record.origin }
      : {}),
    ...(typeof record.billable_units === 'number' && Number.isFinite(record.billable_units)
      ? { billable_units: record.billable_units }
      : {}),
  }
}

function isProfileStatusSource(value: unknown): value is ProfileStatusSource {
  return typeof value === 'string' && (VALID_PROFILE_STATUS_SOURCES as readonly string[]).includes(value)
}

function parseMetricRecord(value: unknown, keys: readonly string[]): Record<string, number | null> | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  return Object.fromEntries(
    keys.map((key) => [key, parseNullableFiniteNumber(record[key])]),
  )
}

function parseQueryMetadata(record: Record<string, unknown>): AssistantQueryMetadata | undefined {
  const profileRecord = record.profile_used && typeof record.profile_used === 'object'
    ? record.profile_used as Record<string, unknown>
    : null
  const profile = profileRecord && isAssistantProfile(profileRecord.key)
    ? {
        key: profileRecord.key,
        version: parseNullableString(profileRecord.version),
        provider: parseNullableString(profileRecord.provider),
        configuredModel: parseNullableString(profileRecord.configured_model),
        resolvedModel: parseNullableString(profileRecord.resolved_model),
        requestedEffort: isCloudEffort(profileRecord.requested_effort)
          ? profileRecord.requested_effort
          : null,
        resolvedEffort: parseNullableString(profileRecord.resolved_effort),
      }
    : null
  const usage = parseMetricRecord(record.usage, [
    'input_tokens', 'cached_input_tokens', 'reasoning_tokens', 'output_tokens', 'total_tokens',
  ])
  const timing = parseMetricRecord(record.timing, ['total_ms', 'provider_ms', 'apex_tool_ms'])
  const costRecord = record.cost_estimate && typeof record.cost_estimate === 'object'
    ? record.cost_estimate as Record<string, unknown>
    : null
  const citations = Array.isArray(record.citations)
    ? record.citations.flatMap((citation): AssistantCitation[] => {
        if (!citation || typeof citation !== 'object') return []
        const item = citation as Record<string, unknown>
        return [{
          title: parseNullableString(item.title),
          uri: parseNullableString(item.uri),
          snippet: parseNullableString(item.snippet),
          source: parseNullableString(item.source),
        }]
      })
    : []

  if (!profile && !usage && !timing && !costRecord && citations.length === 0) {
    return undefined
  }

  return {
    profile,
    usage: usage ? {
      inputTokens: usage.input_tokens,
      cachedInputTokens: usage.cached_input_tokens,
      reasoningTokens: usage.reasoning_tokens,
      outputTokens: usage.output_tokens,
      totalTokens: usage.total_tokens,
    } : null,
    timing: timing ? {
      totalMs: timing.total_ms,
      providerMs: timing.provider_ms,
      apexToolMs: timing.apex_tool_ms,
    } : null,
    cost: costRecord ? {
      tokenCost: parseNullableFiniteNumber(costRecord.token_cost),
      hostedToolCost: parseNullableFiniteNumber(costRecord.hosted_tool_cost),
      totalCost: parseNullableFiniteNumber(costRecord.total_cost),
      currency: typeof costRecord.currency === 'string' ? costRecord.currency : 'USD',
      pricingVersion: parseNullableString(costRecord.pricing_version),
      completeness: parseNullableString(costRecord.completeness),
    } : null,
    citations,
  }
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

  return {
    answer,
    tool_trace,
    tool_outputs,
    error,
    local_context_usage,
    metadata: parseQueryMetadata(record),
  }
}

function isAcinonyxProfile(profile: AssistantProfile): boolean {
  return profile === 'acinonyx'
}

export interface UseApexAssistantResult {
  assistantHistory: AgentMessage[]
  isAssistantQuerying: boolean
  activeQueryProfile: AssistantProfile | null
  isAssistantOpen: boolean
  assistantLatestTrace: ToolTraceItem[]
  assistantError: string | null
  assistantContextUsage: LocalContextUsage | null
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  isLocalModelActionPending: boolean
  verifyingCloudProfile: AssistantProfile | null
  queryAssistant: (
    prompt: string,
    profile: AssistantProfile,
    context?: {
      snapshotId?: string | null
      briefingId?: number | null
      toolScope?: LocalToolScope | null
      effort?: CloudEffort | null
      sessionId?: string | null
    },
  ) => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  loadLocalModel: (profile: Extract<AssistantProfile, 'mus' | 'sorex'>) => Promise<boolean>
  verifyCloudProfile: (profile: Exclude<AssistantProfile, 'mus' | 'sorex'>) => Promise<boolean>
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
  const [activeQueryProfile, setActiveQueryProfile] = useState<AssistantProfile | null>(null)
  const [isAssistantOpen, setAssistantOpen] = useState(false)
  const [assistantLatestTrace, setAssistantLatestTrace] = useState<ToolTraceItem[]>([])
  const [assistantError, setAssistantError] = useState<string | null>(null)
  const [assistantContextUsage, setAssistantContextUsage] =
    useState<LocalContextUsage | null>(null)
  const [profilesStatus, setProfilesStatus] = useState<AgentProfileStatus[]>([])
  const [profilesStatusHydrated, setProfilesStatusHydrated] = useState(false)
  const [isLocalModelActionPending, setIsLocalModelActionPending] = useState(false)
  const [verifyingCloudProfile, setVerifyingCloudProfile] = useState<AssistantProfile | null>(null)

  const productionHistoryRef = useRef<AgentMessage[]>([])
  const acinonyxHistoryRef = useRef<AgentMessage[]>([])

  useEffect(() => {
    productionHistoryRef.current = productionHistory
  }, [productionHistory])

  useEffect(() => {
    acinonyxHistoryRef.current = acinonyxHistory
  }, [acinonyxHistory])

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
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
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
    } finally {
      setIsLocalModelActionPending(false)
    }
  }, [fetchProfilesStatus, isLocalModelActionPending])

  const loadLocalModel = useCallback(async (
    profile: Extract<AssistantProfile, 'mus' | 'sorex'>,
  ): Promise<boolean> => {
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
    try {
      const response = await fetch(AGENT_LOCAL_LOAD_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile }),
      })
      if (!response.ok) {
        console.warn(`[useApexAssistant] Local model load failed (${response.status}).`)
        return false
      }
      await fetchProfilesStatus()
      return true
    } catch (fetchError) {
      const message = fetchError instanceof Error ? fetchError.message : 'Unknown load error'
      console.warn(`[useApexAssistant] Local model load error: ${message}`)
      return false
    } finally {
      setIsLocalModelActionPending(false)
    }
  }, [fetchProfilesStatus, isLocalModelActionPending])

  const verifyCloudProfile = useCallback(async (
    profile: Exclude<AssistantProfile, 'mus' | 'sorex'>,
  ): Promise<boolean> => {
    if (verifyingCloudProfile) return false
    setVerifyingCloudProfile(profile)
    try {
      const response = await fetch(API_ENDPOINTS.agentProfileVerify(profile), { method: 'POST' })
      if (!response.ok) return false
      await fetchProfilesStatus()
      return true
    } catch {
      return false
    } finally {
      setVerifyingCloudProfile(null)
    }
  }, [fetchProfilesStatus, verifyingCloudProfile])

  const queryAssistant = useCallback(
    async (
      prompt: string,
      profile: AssistantProfile,
      context?: {
        snapshotId?: string | null
        briefingId?: number | null
        toolScope?: LocalToolScope | null
        effort?: CloudEffort | null
        sessionId?: string | null
      },
    ): Promise<void> => {
      const trimmedPrompt = prompt.trim()
      if (!trimmedPrompt) {
        return
      }

      const useAcinonyxStore = isAcinonyxProfile(profile)
      const priorHistory = useAcinonyxStore
        ? acinonyxHistoryRef.current
        : productionHistoryRef.current

      isAssistantQueryingRef.current = true
      setIsAssistantQuerying(true)
      setActiveQueryProfile(profile)
      setAssistantOpen(true)
      setAssistantError(null)

      const userMsg: AgentMessage = { role: 'user', content: trimmedPrompt }
      if (useAcinonyxStore) {
        setAcinonyxHistory((prev) => [...prev, userMsg])
      } else {
        setProductionHistory((prev) => [...prev, userMsg])
      }

      try {
        const response = await fetch(AGENT_QUERY_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: trimmedPrompt,
            profile,
            history: priorHistory,
            history_partition: isAcinonyxProfile(profile)
              ? 'acinonyx'
              : 'production',
            ...(context?.effort ? { effort: context.effort } : {}),
            ...(context?.snapshotId ? { snapshot_id: context.snapshotId } : {}),
            ...(context?.briefingId != null ? { briefing_id: context.briefingId } : {}),
            ...(context?.toolScope ? { tool_scope: context.toolScope } : {}),
            ...(context?.sessionId ? { session_id: context.sessionId } : {}),
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
          ...(body.tool_trace && body.tool_trace.length > 0
            ? { tool_trace: body.tool_trace }
            : {}),
          ...(body.metadata ? { metadata: body.metadata } : {}),
        }

        if (useAcinonyxStore) {
          setAcinonyxHistory((prev) => [...prev, modelMsg])
        } else {
          setProductionHistory((prev) => [...prev, modelMsg])
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
        setActiveQueryProfile(null)
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
    activeQueryProfile,
    isAssistantOpen,
    assistantLatestTrace,
    assistantError,
    assistantContextUsage,
    profilesStatus,
    profilesStatusHydrated,
    isLocalModelActionPending,
    verifyingCloudProfile,
    queryAssistant,
    unloadLocalModel,
    loadLocalModel,
    verifyCloudProfile,
    clearAssistantChat,
    resetAssistantSession,
    setAssistantOpen,
  }
}
