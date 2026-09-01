import type { BriefingMode } from '../types/settings'
import type {
  AgentAvailabilityStatus,
  AgentKey,
  AgentStability,
  AgentStatus,
  BriefingTargetStatus,
  CloudEffort,
  HostedTool,
  LocalRuntime,
  ModelCatalogEntry,
} from '../types/telemetry'

export const AGENT_KEYS = ['apex'] as const satisfies readonly AgentKey[]

export function agentShortName(displayName: string): string {
  return displayName.replace(/^Apex\s+/i, '')
}

/** True for any selectable Cortex Agent key. */
export function isAgentKey(value: unknown): value is AgentKey {
  return value === 'apex'
}

/** True when the operator may switch HUD focus to this Agent identity. */
export function isAgentIdentitySelectable(_agent: Pick<AgentStatus, 'key'>): boolean {
  return isAgentKey(_agent.key)
}

/** True when the selected model's cloud provider can run verification. */
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
  if (tokens >= 1_000_000) {
    return '1M'
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
  if (mode === 'structured') {
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

const REASONING_RANK: readonly CloudEffort[] = [
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
]

export function resolveLowestReasoningEffort(
  options: readonly CloudEffort[] | null | undefined,
): CloudEffort | null {
  if (!options || options.length === 0) return null
  for (const candidate of REASONING_RANK) {
    if (options.includes(candidate)) return candidate
  }
  return options[0] ?? null
}

export interface HomeQueryOverrides {
  agent: AgentKey
  modelId: string
  effort: CloudEffort | null
  contextWindow: number | null
  localReasoningMode: 'none' | null
}

export function resolveHomeQueryOverrides(
  modelEntry: ModelCatalogEntry | null | undefined,
): HomeQueryOverrides {
  if (!modelEntry || modelEntry.runtime === 'local') {
    const modelId = modelEntry?.model_id ?? 'gemma-4-E2B-Q4_K_M.gguf'
    const contextWindow = modelEntry?.provider === 'ollama' ? 4096 : 16384
    return {
      agent: 'apex',
      modelId,
      effort: null,
      contextWindow,
      localReasoningMode: 'none',
    }
  }

  const effort = resolveLowestReasoningEffort(modelEntry.reasoning_options)
  return {
    agent: 'apex',
    modelId: modelEntry.model_id,
    effort,
    contextWindow: null,
    localReasoningMode: null,
  }
}
