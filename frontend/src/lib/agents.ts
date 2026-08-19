import type { BriefingMode } from '../types/settings'
import type {
  AgentAvailabilityStatus,
  AgentKey,
  AgentRuntime,
  AgentStability,
  AgentStatus,
  BriefingTargetStatus,
  HostedTool,
  LocalRuntime,
  ModelCatalogEntry,
} from '../types/telemetry'

export const AGENT_KEYS = ['panthera', 'felis'] as const satisfies readonly AgentKey[]

export function isPantheraKey(value: unknown): value is 'panthera' {
  return value === 'panthera'
}

export function isFelisKey(value: unknown): value is 'felis' {
  return value === 'felis'
}

export function isLocalAgentKey(value: unknown): value is 'felis' {
  return value === 'felis'
}

export function isCloudAgentKey(value: unknown): value is 'panthera' {
  return value === 'panthera'
}

/** True for any selectable Cortex Agent key. */
export function isAgentKey(value: unknown): value is AgentKey {
  return isPantheraKey(value) || isFelisKey(value)
}

/** True when the operator may switch HUD focus to this Agent identity. */
export function isAgentIdentitySelectable(_agent: Pick<AgentStatus, 'key'>): boolean {
  return isAgentKey(_agent.key)
}

/** True when Panthera cloud verification can run for the current route. */
export function canVerifyCloudProvider(
  agent: Pick<AgentStatus, 'key' | 'runtime' | 'status'>,
): boolean {
  return agent.runtime === 'cloud' && agent.status !== 'disabled'
}

export function isLocalAgentStatus(agent: Pick<AgentStatus, 'runtime'>): boolean {
  return agent.runtime === 'local'
}

export function providerDisplayName(provider: string | null | undefined): string {
  if (provider === 'ollama') {
    return 'Ollama'
  }
  if (provider === 'llama_cpp') {
    return 'llama.cpp'
  }
  if (provider === 'openai') {
    return 'OpenAI'
  }
  if (provider === 'openrouter') {
    return 'OpenRouter'
  }
  if (provider === 'xai') {
    return 'SpaceXAI'
  }
  if (provider === 'gemini') {
    return 'Google'
  }
  return provider || 'Provider'
}

export function runtimeDisplayName(runtime: LocalRuntime): string {
  return runtime === 'ollama' ? 'Ollama' : 'llama.cpp'
}

/** Compact label for known context-window sizes (e.g. 8192 → 8K, 1048576 → 1M). */
export function formatContextWindowLabel(
  tokens: number | null | undefined,
): string | null {
  if (typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens <= 0) {
    return null
  }
  if (tokens % 1048576 === 0) {
    return `${tokens / 1048576}M`
  }
  if (tokens % 1000000 === 0) {
    return `${tokens / 1000000}M`
  }
  if (tokens === 131072) {
    return '132K'
  }
  if (tokens % 1024 === 0) {
    return `${tokens / 1024}K`
  }
  if (tokens % 1000 === 0) {
    return `${tokens / 1000}K`
  }
  return String(tokens)
}

export function runtimeForAgentKey(agent: AgentKey): AgentRuntime {
  return isLocalAgentKey(agent) ? 'local' : 'cloud'
}

/** Humanize reasoning level without changing its canonical meaning. */
export function formatReasoningLabel(option: string | null | undefined): string {
  if (!option) return ''
  switch (option.trim().toLowerCase()) {
    case 'none':
      return 'None'
    case 'minimal':
      return 'Minimal'
    case 'low':
      return 'Low'
    case 'medium':
      return 'Medium'
    case 'high':
      return 'High'
    case 'xhigh':
    case 'extra_high':
    case 'extra high':
      return 'Extra High'
    case 'max':
      return 'Max'
    default:
      return option.charAt(0).toUpperCase() + option.slice(1)
  }
}

export function resolveModelCatalog(
  agentStatus: AgentStatus | undefined,
): ModelCatalogEntry[] {
  if (!agentStatus?.model_catalog) return []
  return agentStatus.model_catalog
}

export function findModelCatalogEntry(
  modelId: string,
  catalog: readonly ModelCatalogEntry[],
): ModelCatalogEntry | null {
  return catalog.find((entry) => entry.model_id === modelId) ?? null
}

export function hostedCapabilitiesForModel(
  modelId: string,
  catalog: readonly ModelCatalogEntry[],
): HostedTool[] {
  return findModelCatalogEntry(modelId, catalog)?.hosted_capabilities ?? []
}

export function usesSandboxHistory(
  devModeActive: boolean,
  sandboxMode: boolean,
): boolean {
  return devModeActive && sandboxMode
}

export function stabilityLabel(stability: AgentStability | null | undefined): string | null {
  if (!stability || stability === 'stable') {
    return null
  }
  if (stability === 'preview') {
    return 'Preview'
  }
  return 'Experimental'
}

export interface BriefingModeAvailability {
  status: AgentAvailabilityStatus
  reason: string | null
}

export function resolveBriefingModeAvailability(
  mode: BriefingMode,
  targets?: BriefingTargetStatus[],
): BriefingModeAvailability {
  if (mode === 'structured_digest') {
    return { status: 'available', reason: null }
  }
  if (targets && targets.length > 0) {
    const target = targets.find((entry) => entry.mode === mode)
    if (target) {
      return { status: target.status, reason: target.reason }
    }
  }
  return { status: 'unknown', reason: 'Mode status unavailable' }
}
