import type {
  AgentKey,
  AgentRuntime,
  AgentStability,
  AgentStatus,
  HostedTool,
  LocalRuntime,
  ModelCatalogEntry,
} from '../types/telemetry'

export const AGENT_KEYS = ['panthera', 'lynx'] as const satisfies readonly AgentKey[]

export function isPantheraKey(value: unknown): value is 'panthera' {
  return value === 'panthera'
}

export function isLynxKey(value: unknown): value is 'lynx' {
  return value === 'lynx'
}

export function isLocalAgentKey(value: unknown): value is 'lynx' {
  return value === 'lynx'
}

export function isCloudAgentKey(value: unknown): value is 'panthera' {
  return value === 'panthera'
}

/** True for any selectable Cortex Agent key. */
export function isAgentKey(value: unknown): value is AgentKey {
  return isPantheraKey(value) || isLynxKey(value)
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

/** Compact label for known context-window sizes (e.g. 8192 → 8K). */
export function formatContextWindowLabel(
  tokens: number | null | undefined,
): string | null {
  if (typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens <= 0) {
    return null
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
  return isLynxKey(agent) ? 'local' : 'cloud'
}

export function resolveModelCatalog(
  agentStatus: AgentStatus | undefined,
): ModelCatalogEntry[] {
  if (!agentStatus) return []
  if (agentStatus.model_catalog && agentStatus.model_catalog.length > 0) {
    return agentStatus.model_catalog
  }
  return [
    {
      model_id: agentStatus.configured_model,
      display_name: agentStatus.configured_model,
      provider: agentStatus.provider,
      runtime: agentStatus.runtime,
      stability: agentStatus.model_stability ?? agentStatus.stability,
      pricing: agentStatus.pricing,
      supports_effort: Boolean(agentStatus.effort_options?.length),
      default_effort: agentStatus.default_effort,
      effort_options: agentStatus.effort_options,
      context_options: agentStatus.context_window_options,
      default_context_window: agentStatus.default_context_window,
      high_resource_context_options: agentStatus.context_window_high_resource_options,
      maximum_context_window: agentStatus.context_window,
      reasoning_modes: agentStatus.reasoning_mode_options,
      default_reasoning_mode: agentStatus.default_reasoning_mode,
      hosted_capabilities: [],
    },
  ]
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
  if (!stability) {
    return null
  }
  if (stability === 'stable') {
    return 'Stable'
  }
  if (stability === 'preview') {
    return 'Preview'
  }
  return 'Experimental'
}
