import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  AgentMessage as TelemetryAgentMessage,
  AgentStatus,
  AgentKey,
  CloudEffort,
  LocalLoadedModelStatus,
  LocalSettingsAgent,
  LocalContextUsage,
  LocalToolScope,
  AgentAvailabilityStatus,
  AgentPricingMetadata,
  AgentStatusSource,
  AgentStability,
  ToolOutputItem,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const AGENT_QUERY_ENDPOINT = API_ENDPOINTS.cortexQuery
const AGENT_PROFILES_ENDPOINT = API_ENDPOINTS.agents
const AGENT_LOCAL_UNLOAD_ENDPOINT = API_ENDPOINTS.cortexLocalModelUnload
const AGENT_LOCAL_LOAD_ENDPOINT = API_ENDPOINTS.cortexLocalModelLoad
const AGENT_POLL_INTERVAL_MS = 4000
const AGENT_POLL_INTERVAL_QUERYING_MS = 1000

export type { AgentKey, AgentStatus, ToolOutputItem } from '../types/telemetry'

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
  metadata?: AgentQueryMetadata
}

export interface ToolTraceItem {
  name: string
  status: string
  duration_ms: number
  origin?: 'apex' | 'provider'
  billable_units?: number | null
}

export interface AgentCitation {
  title: string | null
  uri: string | null
  snippet: string | null
  source: string | null
}

export interface AgentQueryMetadata {
  agent: {
    key: AgentKey
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
  citations: AgentCitation[]
}

interface AgentQueryResponseBody {
  answer?: string
  tool_trace?: ToolTraceItem[]
  tool_outputs?: ToolOutputItem[]
  error?: string | null
  local_context_usage?: LocalContextUsage | null
  metadata?: AgentQueryMetadata
}

const VALID_AGENT_KEYS: readonly AgentKey[] = [
  'panthera',
  'neofelis',
  'delphinus',
  'orcinus',
  'sorex',
  'mus',
  'acinonyx',
]

const VALID_AGENT_STATUSES: readonly AgentAvailabilityStatus[] = [
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

const VALID_PROVIDERS: readonly AgentStatus['provider'][] = [
  'ollama',
  'gemini',
  'openai',
  'xai',
]

const VALID_AGENT_RUNTIMES: readonly AgentStatus['runtime'][] = ['cloud', 'local']

const VALID_CLOUD_EFFORTS: readonly CloudEffort[] = ['light', 'focused', 'extended']

const VALID_AGENT_STABILITY: readonly AgentStability[] = ['stable', 'preview']
const VALID_AGENT_STATUS_SOURCES: readonly AgentStatusSource[] = ['configuration', 'verification', 'request', 'runtime']

function isAgentKey(value: unknown): value is AgentKey {
  return (
    typeof value === 'string' &&
    (VALID_AGENT_KEYS as readonly string[]).includes(value)
  )
}

function isAgentAvailabilityStatus(value: unknown): value is AgentAvailabilityStatus {
  return (
    typeof value === 'string' &&
    (VALID_AGENT_STATUSES as readonly string[]).includes(value)
  )
}

function isProvider(value: unknown): value is AgentStatus['provider'] {
  return typeof value === 'string' && (VALID_PROVIDERS as readonly string[]).includes(value)
}

function isAgentRuntime(value: unknown): value is AgentStatus['runtime'] {
  return typeof value === 'string' && (VALID_AGENT_RUNTIMES as readonly string[]).includes(value)
}

function isCloudEffort(value: unknown): value is CloudEffort {
  return typeof value === 'string' && (VALID_CLOUD_EFFORTS as readonly string[]).includes(value)
}

function isAgentStability(value: unknown): value is AgentStability {
  return (
    typeof value === 'string' &&
    (VALID_AGENT_STABILITY as readonly string[]).includes(value)
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

function parseLocalLoadedModelStatus(value: unknown): LocalLoadedModelStatus | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const record = value as Record<string, unknown>
  const name = record.name
  const model = record.model
  const provider = record.provider === undefined ? 'ollama' : record.provider
  const state = record.state === undefined ? 'loaded' : record.state

  if (typeof name !== 'string' || typeof model !== 'string') {
    return null
  }
  if (provider !== 'ollama') {
    return null
  }
  if (
    state !== 'unloaded' &&
    state !== 'loading' &&
    state !== 'loaded' &&
    state !== 'sleeping' &&
    state !== 'failed' &&
    state !== 'unknown'
  ) {
    return null
  }

  return {
    provider,
    name,
    model,
    state,
    context_window: parseNullableFiniteNumber(record.context_window),
    size_bytes: parseNullableFiniteNumber(record.size_bytes),
    size_vram_bytes: parseNullableFiniteNumber(record.size_vram_bytes),
    processor: parseNullableString(record.processor),
    context: parseNullableString(record.context),
    expires_at: parseNullableString(record.expires_at),
  }
}

function parseAgentPricing(value: unknown): AgentPricingMetadata {
  const fallback: AgentPricingMetadata = {
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

function parseAgentStatus(value: unknown): AgentStatus | null {
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
  const mode = record.runtime
  const tier = record.tier
  const stability = record.stability
  const status = record.status

  if (!isAgentKey(key)) {
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
  if (!isAgentRuntime(mode)) {
    return null
  }
  if (typeof tier !== 'string') {
    return null
  }
  if (!isAgentStability(stability)) {
    return null
  }
  if (!isAgentAvailabilityStatus(status)) {
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
    runtime: mode,
    tier,
    stability,
    effort_options: effortOptions,
    default_effort: defaultEffort,
    status,
    status_source: isAgentStatusSource(record.status_source) ? record.status_source : 'configuration',
    status_checked_at: parseNullableString(record.status_checked_at),
    provider_account_tier: parseNullableString(record.provider_account_tier),
    pricing: parseAgentPricing(record.pricing),
    active: typeof record.active === 'boolean' ? record.active : false,
    loading: typeof record.loading === 'boolean' ? record.loading : false,
    reason: parseNullableString(record.reason),
    idle_unload_remaining_seconds: parseNullableFiniteNumber(record.idle_unload_remaining_seconds),
    loaded_model: parseLocalLoadedModelStatus(record.loaded_model),
  }
}

function parseAgentStatusList(body: unknown): AgentStatus[] {
  if (!Array.isArray(body)) {
    return []
  }

  return body
    .map(parseAgentStatus)
    .filter((item): item is AgentStatus => item !== null)
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

function isAgentStatusSource(value: unknown): value is AgentStatusSource {
  return typeof value === 'string' && (VALID_AGENT_STATUS_SOURCES as readonly string[]).includes(value)
}

function parseMetricRecord(value: unknown, keys: readonly string[]): Record<string, number | null> | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  return Object.fromEntries(
    keys.map((key) => [key, parseNullableFiniteNumber(record[key])]),
  )
}

function parseQueryMetadata(record: Record<string, unknown>): AgentQueryMetadata | undefined {
  const agentRecord = record.agent_used && typeof record.agent_used === 'object'
    ? record.agent_used as Record<string, unknown>
    : null
  const agent = agentRecord && isAgentKey(agentRecord.key)
    ? {
        key: agentRecord.key,
        version: parseNullableString(agentRecord.version),
        provider: parseNullableString(agentRecord.provider),
        configuredModel: parseNullableString(agentRecord.configured_model),
        resolvedModel: parseNullableString(agentRecord.resolved_model),
        requestedEffort: isCloudEffort(agentRecord.requested_effort)
          ? agentRecord.requested_effort
          : null,
        resolvedEffort: parseNullableString(agentRecord.resolved_effort),
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
    ? record.citations.flatMap((citation): AgentCitation[] => {
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

  if (!agent && !usage && !timing && !costRecord && citations.length === 0) {
    return undefined
  }

  return {
    agent,
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

function isAcinonyxAgent(agent: AgentKey): boolean {
  return agent === 'acinonyx'
}

export interface UseCortexResult {
  cortexHistory: AgentMessage[]
  isCortexQuerying: boolean
  activeQueryAgent: AgentKey | null
  cortexLatestTrace: ToolTraceItem[]
  cortexError: string | null
  cortexContextUsage: LocalContextUsage | null
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isLocalModelActionPending: boolean
  verifyingCloudAgent: AgentKey | null
  refreshAgentsStatus: () => Promise<void>
  queryAgent: (
    prompt: string,
    agent: AgentKey,
    context?: {
      snapshotId?: string | null
      briefingId?: number | null
      toolScope?: LocalToolScope | null
      effort?: CloudEffort | null
      sessionId?: string | null
    },
  ) => Promise<void>
  unloadLocalModel: () => Promise<boolean>
  loadLocalModel: (agent: LocalSettingsAgent) => Promise<boolean>
  verifyCloudAgent: (agent: Exclude<AgentKey, LocalSettingsAgent>) => Promise<boolean>
  clearCortexSession: (agent?: AgentKey) => void
  resetCortexSession: () => void
}

export function useCortex(
  agentsPollingEnabled = false,
  activeAgent: AgentKey = 'panthera',
): UseCortexResult {
  const [productionHistory, setProductionHistory] = useState<AgentMessage[]>([])
  const [acinonyxHistory, setAcinonyxHistory] = useState<AgentMessage[]>([])
  const [isCortexQuerying, setIsCortexQuerying] = useState(false)
  const [activeQueryAgent, setActiveQueryAgent] = useState<AgentKey | null>(null)
  const [cortexLatestTrace, setCortexLatestTrace] = useState<ToolTraceItem[]>([])
  const [cortexError, setCortexError] = useState<string | null>(null)
  const [cortexContextUsage, setCortexContextUsage] =
    useState<LocalContextUsage | null>(null)
  const [agentsStatus, setAgentsStatus] = useState<AgentStatus[]>([])
  const [agentsStatusHydrated, setAgentsStatusHydrated] = useState(false)
  const [isLocalModelActionPending, setIsLocalModelActionPending] = useState(false)
  const [verifyingCloudAgent, setVerifyingCloudAgent] = useState<AgentKey | null>(null)

  const productionHistoryRef = useRef<AgentMessage[]>([])
  const acinonyxHistoryRef = useRef<AgentMessage[]>([])

  useEffect(() => {
    productionHistoryRef.current = productionHistory
  }, [productionHistory])

  useEffect(() => {
    acinonyxHistoryRef.current = acinonyxHistory
  }, [acinonyxHistory])

  const cortexHistory = useMemo(
    () => (isAcinonyxAgent(activeAgent) ? acinonyxHistory : productionHistory),
    [activeAgent, acinonyxHistory, productionHistory],
  )

  // Mirrors isCortexQuerying for the poll loop without restarting it on
  // every query state transition.
  const isCortexQueryingRef = useRef(false)

  const fetchAgentsStatus = useCallback(async (): Promise<void> => {
    try {
      const response = await fetch(AGENT_PROFILES_ENDPOINT)
      if (!response.ok) {
        console.warn(
          `[useCortex] Agent status fetch failed (${response.status}); retaining prior state.`,
        )
        return
      }

      const body: unknown = await response.json()
      const parsed = parseAgentStatusList(body)
      setAgentsStatus(parsed)
      setAgentsStatusHydrated(true)
    } catch (fetchError) {
      const message =
        fetchError instanceof Error ? fetchError.message : 'Unknown agent fetch error'
      console.warn(`[useCortex] Agent status fetch error: ${message}`)
    }
  }, [])

  const shouldPollAgents = agentsPollingEnabled

  useEffect(() => {
    if (!shouldPollAgents) {
      return
    }

    let cancelled = false
    let timeoutId: number | undefined

    const pollLoop = async (): Promise<void> => {
      if (cancelled) {
        return
      }

      if (!document.hidden) {
        await fetchAgentsStatus()
      }

      if (!cancelled) {
        const intervalMs = isCortexQueryingRef.current
          ? AGENT_POLL_INTERVAL_QUERYING_MS
          : AGENT_POLL_INTERVAL_MS
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
  }, [shouldPollAgents, fetchAgentsStatus])

  useEffect(() => {
    if (!isCortexQuerying || !shouldPollAgents) {
      return
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Immediate sync keeps local model loading state visible at query start.
    void fetchAgentsStatus()
  }, [isCortexQuerying, shouldPollAgents, fetchAgentsStatus])

  const unloadLocalModel = useCallback(async (): Promise<boolean> => {
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
    try {
      const response = await fetch(AGENT_LOCAL_UNLOAD_ENDPOINT, {
        method: 'POST',
      })

      if (!response.ok) {
        console.warn(
          `[useCortex] Local model unload failed (${response.status}).`,
        )
        return false
      }

      await fetchAgentsStatus()
      return true
    } catch (fetchError) {
      const message =
        fetchError instanceof Error ? fetchError.message : 'Unknown unload error'
      console.warn(`[useCortex] Local model unload error: ${message}`)
      return false
    } finally {
      setIsLocalModelActionPending(false)
    }
  }, [fetchAgentsStatus, isLocalModelActionPending])

  const loadLocalModel = useCallback(async (
    agent: LocalSettingsAgent,
  ): Promise<boolean> => {
    if (isLocalModelActionPending) return false
    setIsLocalModelActionPending(true)
    try {
      const response = await fetch(AGENT_LOCAL_LOAD_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent }),
      })
      if (!response.ok) {
        console.warn(`[useCortex] Local model load failed (${response.status}).`)
        return false
      }
      await fetchAgentsStatus()
      return true
    } catch (fetchError) {
      const message = fetchError instanceof Error ? fetchError.message : 'Unknown load error'
      console.warn(`[useCortex] Local model load error: ${message}`)
      return false
    } finally {
      setIsLocalModelActionPending(false)
    }
  }, [fetchAgentsStatus, isLocalModelActionPending])

  const verifyCloudAgent = useCallback(async (
    agent: Exclude<AgentKey, LocalSettingsAgent>,
  ): Promise<boolean> => {
    if (verifyingCloudAgent) return false
    setVerifyingCloudAgent(agent)
    try {
      const response = await fetch(API_ENDPOINTS.agentVerify(agent), { method: 'POST' })
      if (!response.ok) return false
      await fetchAgentsStatus()
      return true
    } catch {
      return false
    } finally {
      setVerifyingCloudAgent(null)
    }
  }, [fetchAgentsStatus, verifyingCloudAgent])

  const queryAgent = useCallback(
    async (
      prompt: string,
      agent: AgentKey,
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

      const useAcinonyxStore = isAcinonyxAgent(agent)
      const priorHistory = useAcinonyxStore
        ? acinonyxHistoryRef.current
        : productionHistoryRef.current

      isCortexQueryingRef.current = true
      setIsCortexQuerying(true)
      setActiveQueryAgent(agent)
      setCortexError(null)

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
            agent,
            history: priorHistory,
            history_partition: isAcinonyxAgent(agent)
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
          setCortexError(message)
          return
        }

        const body = parseAgentQueryResponse(await response.json())
        const answer = body.answer ?? ''
        const modelMsg: AgentMessage = {
          role: 'agent',
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
        setCortexLatestTrace(body.tool_trace ?? [])
        setCortexContextUsage(body.local_context_usage ?? null)

        if (body.error) {
          setCortexError(body.error)
        }
      } catch (fetchError) {
        const message =
          fetchError instanceof Error
            ? fetchError.message
            : 'Failed to reach APEX.'
        setCortexError(message)
      } finally {
        isCortexQueryingRef.current = false
        setIsCortexQuerying(false)
        setActiveQueryAgent(null)
        void fetchAgentsStatus()
      }
    },
    [fetchAgentsStatus],
  )

  const clearCortexSession = useCallback((agent?: AgentKey): void => {
    const target = agent ?? activeAgent
    if (isAcinonyxAgent(target)) {
      setAcinonyxHistory([])
    } else {
      setProductionHistory([])
    }
    setCortexLatestTrace([])
    setCortexError(null)
    setCortexContextUsage(null)
  }, [activeAgent])

  const resetCortexSession = useCallback((): void => {
    setProductionHistory([])
    setAcinonyxHistory([])
    setCortexLatestTrace([])
    setCortexError(null)
    setCortexContextUsage(null)
  }, [])

  return {
    cortexHistory,
    isCortexQuerying,
    activeQueryAgent,
    cortexLatestTrace,
    cortexError,
    cortexContextUsage,
    agentsStatus,
    agentsStatusHydrated,
    isLocalModelActionPending,
    verifyingCloudAgent,
    refreshAgentsStatus: fetchAgentsStatus,
    queryAgent,
    unloadLocalModel,
    loadLocalModel,
    verifyCloudAgent,
    clearCortexSession,
    resetCortexSession,
  }
}
