import type {
  AgentKey,
  AgentStatus,
  CloudSettingsAgent,
  LocalSettingsAgent,
} from '../types/telemetry'

export const LOCAL_AGENT_KEYS = ['sorex', 'mus'] as const

const CLOUD_SETTINGS_AGENT_KEYS = [
  'panthera',
  'neofelis',
  'delphinus',
  'orcinus',
] as const satisfies readonly CloudSettingsAgent[]

export function isLocalAgentKey(value: unknown): value is LocalSettingsAgent {
  return value === 'sorex' || value === 'mus'
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

export function isLocalAgentStatus(agent: Pick<AgentStatus, 'runtime'>): boolean {
  return agent.runtime === 'local'
}

export function providerDisplayName(provider: AgentStatus['provider']): string {
  if (provider === 'ollama') {
    return 'Ollama'
  }
  if (provider === 'openai') {
    return 'OpenAI'
  }
  if (provider === 'xai') {
    return 'xAI'
  }
  return 'Gemini'
}

export function runtimeForAgentKey(agent: AgentKey): 'local' | 'cloud' {
  return isLocalAgentKey(agent) ? 'local' : 'cloud'
}
