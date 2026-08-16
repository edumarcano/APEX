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

interface ModelCatalogSeed {
  model_id: string
  display_name: string
  provider: CloudProvider | LocalRuntime
  runtime: AgentRuntime
  stability: AgentStability
  hosted_capabilities: HostedTool[]
  dev_only?: boolean
}

const MODEL_CATALOG_SEED: readonly ModelCatalogSeed[] = [
  {
    model_id: 'gpt-5.6-luna',
    display_name: 'GPT-5.6 Luna',
    provider: 'openai',
    runtime: 'cloud',
    stability: 'stable',
    hosted_capabilities: [],
  },
  {
    model_id: 'gemini-3.6-flash',
    display_name: 'Gemini 3.6 Flash',
    provider: 'gemini',
    runtime: 'cloud',
    stability: 'stable',
    hosted_capabilities: ['google_search', 'google_maps'],
  },
  {
    model_id: 'gemini-3.5-flash-lite',
    display_name: 'Gemini 3.5 Flash Lite',
    provider: 'gemini',
    runtime: 'cloud',
    stability: 'experimental',
    hosted_capabilities: [],
    dev_only: true,
  },
  {
    model_id: 'grok-4.3',
    display_name: 'Grok 4.3',
    provider: 'xai',
    runtime: 'cloud',
    stability: 'stable',
    hosted_capabilities: ['x_search'],
    dev_only: true,
  },
  {
    model_id: 'grok-4.5',
    display_name: 'Grok 4.5',
    provider: 'xai',
    runtime: 'cloud',
    stability: 'stable',
    hosted_capabilities: ['x_search'],
    dev_only: true,
  },
  {
    model_id: 'qwen3:1.7b',
    display_name: 'Qwen3 1.7B',
    provider: 'ollama',
    runtime: 'local',
    stability: 'stable',
    hosted_capabilities: [],
    dev_only: true,
  },
  {
    model_id: 'qwen3:4b-instruct',
    display_name: 'Qwen3 4B Instruct',
    provider: 'ollama',
    runtime: 'local',
    stability: 'stable',
    hosted_capabilities: [],
    dev_only: true,
  },
  {
    model_id: 'gemma-4-E2B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E2B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'stable',
    hosted_capabilities: [],
  },
  {
    model_id: 'gemma-4-E4B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E4B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'preview',
    hosted_capabilities: [],
  },
  {
    model_id: 'Qwen3.5-4B-Q4_K_M.gguf',
    display_name: 'Qwen3.5 4B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'experimental',
    hosted_capabilities: [],
    dev_only: true,
  },
]

function toCatalogEntry(seed: ModelCatalogSeed): ModelCatalogEntry {
  return {
    model_id: seed.model_id,
    display_name: seed.display_name,
    provider: seed.provider,
    runtime: seed.runtime,
    stability: seed.stability,
    hosted_capabilities: [...seed.hosted_capabilities],
  }
}

function visibleCatalog(devMode = false): ModelCatalogEntry[] {
  return MODEL_CATALOG_SEED
    .filter((entry) => !entry.dev_only || devMode)
    .map(toCatalogEntry)
}

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
  devMode = false,
): ModelCatalogEntry[] {
  if (agentStatus?.model_catalog && agentStatus.model_catalog.length > 0) {
    return agentStatus.model_catalog
  }
  const runtime = agentStatus?.runtime ?? runtimeForAgentKey(agentStatus?.key ?? 'panthera')
  return visibleCatalog(devMode).filter((entry) => entry.runtime === runtime)
}

export function modelsForPantheraProvider(
  provider: CloudProvider,
  devMode = false,
  catalog = visibleCatalog(devMode),
): ModelCatalogEntry[] {
  return catalog.filter(
    (entry) => entry.runtime === 'cloud' && entry.provider === provider,
  )
}

export function modelsForLynxRuntime(
  runtime: LocalRuntime,
  devMode = false,
  catalog = visibleCatalog(devMode),
): ModelCatalogEntry[] {
  return catalog.filter(
    (entry) => entry.runtime === 'local' && entry.provider === runtime,
  )
}

export function findModelCatalogEntry(
  modelId: string,
  devMode = false,
): ModelCatalogEntry | null {
  return visibleCatalog(devMode).find((entry) => entry.model_id === modelId) ?? null
}

export function hostedCapabilitiesForModel(
  modelId: string,
  devMode = false,
): HostedTool[] {
  return findModelCatalogEntry(modelId, devMode)?.hosted_capabilities ?? []
}

export function defaultModelForPantheraProvider(
  provider: CloudProvider,
  devMode = false,
): string {
  const models = modelsForPantheraProvider(provider, devMode)
  return models[0]?.model_id ?? 'gpt-5.6-luna'
}

export function defaultModelForLynxRuntime(
  runtime: LocalRuntime,
  devMode = false,
): string {
  const models = modelsForLynxRuntime(runtime, devMode)
  return models[0]?.model_id ?? 'gemma-4-E2B-Q4_K_M.gguf'
}

export function usesSandboxHistory(
  devModeActive: boolean,
  sandboxMode: boolean,
): boolean {
  return devModeActive && sandboxMode
}
