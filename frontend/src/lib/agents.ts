import type {
  AgentKey,
  AgentStatus,
  CloudSettingsAgent,
  LocalSettingsAgent,
} from '../types/telemetry'

export const LOCAL_AGENT_KEYS = [
  'sorex',
  'mus',
  'apodemus',
  'neotoma',
  'unnamed-experimental-agent',
] as const

const CLOUD_SETTINGS_AGENT_KEYS = [
  'panthera',
  'neofelis',
  'delphinus',
  'orcinus',
] as const satisfies readonly CloudSettingsAgent[]

export function isLocalAgentKey(value: unknown): value is LocalSettingsAgent {
  return (
    value === 'sorex' ||
    value === 'mus' ||
    value === 'apodemus' ||
    value === 'neotoma' ||
    value === 'unnamed-experimental-agent'
  )
}

export function isCloudAgentKey(
  value: unknown,
): value is CloudSettingsAgent | 'acinonyx' {
  return (
    value === 'acinonyx' ||
    value === 'panthera' ||
    value === 'neofelis' ||
    value === 'delphinus' ||
    value === 'orcinus'
  )
}

export function isCloudSettingsAgentKey(value: unknown): value is CloudSettingsAgent {
  return (CLOUD_SETTINGS_AGENT_KEYS as readonly string[]).includes(String(value))
}

/** True for any selectable Cortex Agent key, including DEV_MODE Acinonyx. */
export function isAgentKey(value: unknown): value is AgentKey {
  return isLocalAgentKey(value) || isCloudAgentKey(value)
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

export function runtimeForAgentKey(agent: AgentKey): 'local' | 'cloud' {
  return isLocalAgentKey(agent) ? 'local' : 'cloud'
}
