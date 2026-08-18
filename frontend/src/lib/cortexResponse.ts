import type { AgentKey, CloudEffort, LocalContextUsage, ToolOutputItem, ToolSelectionDiagnostics } from '../types/telemetry'

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
  agent: { key: AgentKey; version: string | null; provider: string | null; configuredModel: string | null; resolvedModel: string | null; requestedEffort: CloudEffort | null; resolvedEffort: string | null } | null
  usage: { inputTokens: number | null; cachedInputTokens: number | null; reasoningTokens: number | null; outputTokens: number | null; totalTokens: number | null } | null
  timing: { totalMs: number | null; providerMs: number | null; apexToolMs: number | null } | null
  cost: { tokenCost: number | null; hostedToolCost: number | null; totalCost: number | null; currency: string; pricingVersion: string | null; completeness: string | null } | null
  citations: AgentCitation[]
  grounding: { searchSuggestionsHtml: string | null } | null
  toolSelection: ToolSelectionDiagnostics | null
}

export interface AgentMessage {
  role: 'user' | 'agent'
  content: string
  tool_outputs?: ToolOutputItem[]
  tool_trace?: ToolTraceItem[]
  metadata?: AgentQueryMetadata
}

export interface AgentQueryResponseBody {
  answer?: string
  tool_trace?: ToolTraceItem[]
  tool_outputs?: ToolOutputItem[]
  error?: string | null
  local_context_usage?: LocalContextUsage | null
  metadata?: AgentQueryMetadata
}

const asRecord = (value: unknown): Record<string, unknown> | null => value && typeof value === 'object' ? value as Record<string, unknown> : null
const nullableString = (value: unknown): string | null => typeof value === 'string' ? value : null
const nullableNumber = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null

export function parseAgentQueryResponse(body: unknown): AgentQueryResponseBody {
  const record = asRecord(body) ?? {}
  // The conversation-turn API keeps response telemetry flat for its durable
  // message contract, while older callers may still provide a nested
  // `metadata` envelope. Normalize both shapes before parsing the display
  // metadata used by CortexWorkspace.
  const metadataRecord = asRecord(record.metadata) ?? (
    record.agent_used !== undefined || record.usage !== undefined || record.timing !== undefined ||
    record.cost_estimate !== undefined || record.citations !== undefined || record.grounding !== undefined ||
    record.resolved_tool_selection !== undefined
      ? {
          agent: record.agent_used,
          usage: record.usage,
          timing: record.timing,
          cost: record.cost_estimate,
          citations: record.citations,
          grounding: record.grounding,
          tool_selection: record.resolved_tool_selection,
        }
      : null
  )
  const agentRecord = asRecord(metadataRecord?.agent)
  const usageRecord = asRecord(metadataRecord?.usage)
  const timingRecord = asRecord(metadataRecord?.timing)
  const costRecord = asRecord(metadataRecord?.cost)
  const groundingRecord = asRecord(metadataRecord?.grounding)
  const citations = Array.isArray(metadataRecord?.citations) ? metadataRecord.citations.map(asRecord).filter((item): item is Record<string, unknown> => item !== null).map((item) => ({ title: nullableString(item.title), uri: nullableString(item.uri), snippet: nullableString(item.snippet), source: nullableString(item.source) })) : []
  const trace = Array.isArray(record.tool_trace) ? record.tool_trace.map(asRecord).filter((item): item is Record<string, unknown> => item !== null).flatMap((item): ToolTraceItem[] => typeof item.name === 'string' && typeof item.status === 'string' && typeof item.duration_ms === 'number' ? [{ name: item.name, status: item.status, duration_ms: item.duration_ms, ...(item.origin === 'apex' || item.origin === 'provider' ? { origin: item.origin } : {}), ...(nullableNumber(item.billable_units) !== null ? { billable_units: nullableNumber(item.billable_units) } : {}) }] : []) : []
  const outputs = Array.isArray(record.tool_outputs) ? record.tool_outputs.map(asRecord).filter((item): item is Record<string, unknown> => item !== null).flatMap((item): ToolOutputItem[] => typeof item.name === 'string' && typeof item.status === 'string' && typeof item.duration_ms === 'number' ? [{ name: item.name, status: item.status, duration_ms: item.duration_ms, output: item.output }] : []) : []
  const local = asRecord(record.local_context_usage)
  const local_context_usage = local && typeof local.estimated_prompt_tokens === 'number' && typeof local.context_window === 'number' && typeof local.history_messages_dropped === 'number' ? { estimated_prompt_tokens: local.estimated_prompt_tokens, peak_prompt_tokens: nullableNumber(local.peak_prompt_tokens), context_window: local.context_window, history_messages_dropped: local.history_messages_dropped } : null
  const metadata: AgentQueryMetadata | undefined = metadataRecord ? {
    agent: agentRecord && (agentRecord.key === 'panthera' || agentRecord.key === 'felis') ? { key: agentRecord.key, version: nullableString(agentRecord.version), provider: nullableString(agentRecord.provider), configuredModel: nullableString(agentRecord.configured_model), resolvedModel: nullableString(agentRecord.resolved_model), requestedEffort: nullableString(agentRecord.requested_effort) as CloudEffort | null, resolvedEffort: nullableString(agentRecord.resolved_effort) } : null,
    usage: usageRecord ? { inputTokens: nullableNumber(usageRecord.input_tokens), cachedInputTokens: nullableNumber(usageRecord.cached_input_tokens), reasoningTokens: nullableNumber(usageRecord.reasoning_tokens), outputTokens: nullableNumber(usageRecord.output_tokens), totalTokens: nullableNumber(usageRecord.total_tokens) } : null,
    timing: timingRecord ? { totalMs: nullableNumber(timingRecord.total_ms), providerMs: nullableNumber(timingRecord.provider_ms), apexToolMs: nullableNumber(timingRecord.apex_tool_ms) } : null,
    cost: costRecord ? { tokenCost: nullableNumber(costRecord.token_cost), hostedToolCost: nullableNumber(costRecord.hosted_tool_cost), totalCost: nullableNumber(costRecord.total_cost), currency: nullableString(costRecord.currency) ?? 'USD', pricingVersion: nullableString(costRecord.pricing_version), completeness: nullableString(costRecord.completeness) } : null,
    citations, grounding: groundingRecord ? { searchSuggestionsHtml: nullableString(groundingRecord.search_suggestions_html) } : null,
    toolSelection: asRecord(metadataRecord.tool_selection) as ToolSelectionDiagnostics | null,
  } : undefined
  return { ...(typeof record.answer === 'string' ? { answer: record.answer } : {}), tool_trace: trace, tool_outputs: outputs, ...(typeof record.error === 'string' || record.error === null ? { error: record.error as string | null } : {}), local_context_usage, ...(metadata ? { metadata } : {}) }
}
