import type {
  AgentKey,
  AgentRuntime,
  AgentStability,
  AgentStatus,
  CloudProvider,
  HostedTool,
  LocalRuntime,
  ModelCatalogEntry,
} from '../types/telemetry'

export const AGENT_KEYS = ['panthera', 'lynx'] as const satisfies readonly AgentKey[]

export const PANTHERA_PROVIDERS = ['openai', 'gemini', 'xai'] as const satisfies readonly CloudProvider[]
export const LYNX_RUNTIMES = ['ollama', 'llama_cpp'] as const satisfies readonly LocalRuntime[]

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
  return String(tokens)
}

export function runtimeForAgentKey(agent: AgentKey): AgentRuntime {
  return isLynxKey(agent) ? 'local' : 'cloud'
}

export function resolveModelCatalog(
  agentStatus: AgentStatus | undefined,
): ModelCatalogEntry[] {
  return agentStatus?.model_catalog ?? []
}

export function providersForCatalog(
  catalog: readonly ModelCatalogEntry[],
): CloudProvider[] {
  const available = new Set(
    catalog
      .filter((entry) => entry.runtime === 'cloud')
      .map((entry) => entry.provider as CloudProvider),
  )
  return PANTHERA_PROVIDERS.filter((provider) => available.has(provider))
}

export function runtimesForCatalog(
  catalog: readonly ModelCatalogEntry[],
): LocalRuntime[] {
  const available = new Set(
    catalog
      .filter((entry) => entry.runtime === 'local')
      .map((entry) => entry.provider as LocalRuntime),
  )
  return LYNX_RUNTIMES.filter((runtime) => available.has(runtime))
}

export function modelsForPantheraProvider(
  provider: CloudProvider,
  catalog: readonly ModelCatalogEntry[],
): ModelCatalogEntry[] {
  return catalog.filter(
    (entry) => entry.runtime === 'cloud' && entry.provider === provider,
  )
}

export function modelsForLynxRuntime(
  runtime: LocalRuntime,
  catalog: readonly ModelCatalogEntry[],
): ModelCatalogEntry[] {
  return catalog.filter(
    (entry) => entry.runtime === 'local' && entry.provider === runtime,
  )
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

export function defaultModelForPantheraProvider(
  provider: CloudProvider,
  catalog: readonly ModelCatalogEntry[],
): string | null {
  return modelsForPantheraProvider(provider, catalog)[0]?.model_id ?? null
}

export function defaultModelForLynxRuntime(
  runtime: LocalRuntime,
  catalog: readonly ModelCatalogEntry[],
): string | null {
  return modelsForLynxRuntime(runtime, catalog)[0]?.model_id ?? null
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
