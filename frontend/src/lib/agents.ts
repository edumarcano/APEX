import type {
  AgentKey,
  CloudEffort,
  HostedTool,
  LocalReasoningMode,
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

export function providerDisplayName(provider: string | null | undefined): string {
  if (provider === 'llama_cpp') {
    return 'llama.cpp'
  }
  if (provider === 'openrouter') {
    return 'OpenRouter'
  }
  if (provider === 'gemini') {
    return 'Google AI Studio'
  }
  return provider || 'Provider'
}

export function formatAgentPricing(entry: ModelCatalogEntry | null | undefined): string {
  if (!entry?.pricing) {
    if (entry?.runtime === 'local') return 'Local · No provider charge'
    return 'Standard pricing'
  }
  const { billing_basis, input_per_million, output_per_million } = entry.pricing
  if (billing_basis === 'local') return 'Local · No provider charge'
  return `$${input_per_million.toFixed(2)}/M in · $${output_per_million.toFixed(2)}/M out`
}

export function runtimeDisplayName(runtime?: LocalRuntime): string {
  return runtime === 'llama_cpp' ? 'llama.cpp' : 'llama.cpp'
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

/** Local wire values (`none` | `focused`) use Cortex-facing labels (None / High). */
export function formatLocalReasoningLabel(mode: string | null | undefined): string {
  if (!mode) return ''
  switch (mode.trim().toLowerCase()) {
    case 'none':
      return 'None'
    case 'focused':
      return 'High'
    default:
      return formatReasoningLabel(mode)
  }
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

export interface AgentTurnOverrides {
  agent: AgentKey
  modelId: string
  effort: CloudEffort | null
  contextWindow: number | null
  localReasoningMode: LocalReasoningMode | null
}

export interface AgentTurnPreferences {
  effort: CloudEffort
  contextWindow: number
  localReasoningMode: LocalReasoningMode
}

export function resolveAgentTurnOverrides(
  modelEntry: ModelCatalogEntry | null | undefined,
  preferences: AgentTurnPreferences,
): AgentTurnOverrides {
  if (!modelEntry || modelEntry.runtime === 'local') {
    const modelId = modelEntry?.model_id ?? 'gemma-4-E2B-Q4_K_M.gguf'
    return {
      agent: 'apex',
      modelId,
      effort: null,
      contextWindow: preferences.contextWindow,
      localReasoningMode: preferences.localReasoningMode,
    }
  }

  return {
    agent: 'apex',
    modelId: modelEntry.model_id,
    effort: preferences.effort,
    contextWindow: null,
    localReasoningMode: null,
  }
}
