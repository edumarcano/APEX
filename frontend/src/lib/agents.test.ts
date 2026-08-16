import { describe, expect, it } from 'vitest'

import {
  AGENT_KEYS,
  defaultModelForPantheraProvider,
  formatContextWindowLabel,
  isAgentKey,
  isLynxKey,
  isPantheraKey,
  modelsForPantheraProvider,
  providerDisplayName,
  providersForCatalog,
  usesSandboxHistory,
} from './agents'
import type { ModelCatalogEntry } from '../types/telemetry'

const TEST_CATALOG: ModelCatalogEntry[] = [
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
]

describe('agents helpers', () => {
  it('exposes only Panthera and Lynx agent keys', () => {
    expect(AGENT_KEYS).toEqual(['panthera', 'lynx'])
    expect(isLynxKey('lynx')).toBe(true)
    expect(isPantheraKey('panthera')).toBe(true)
    expect(isAgentKey('panthera')).toBe(true)
    expect(isAgentKey('lynx')).toBe(true)
    expect(isAgentKey('apodemus')).toBe(false)
    expect(isAgentKey('unknown')).toBe(false)
  })

  it('labels providers for display without changing their technical IDs', () => {
    expect(providerDisplayName('llama_cpp')).toBe('llama.cpp')
    expect(providerDisplayName('ollama')).toBe('Ollama')
    expect(providerDisplayName('gemini')).toBe('Google')
    expect(providerDisplayName('xai')).toBe('SpaceXAI')
  })

  it('filters Panthera models by provider from the backend catalog', () => {
    expect(modelsForPantheraProvider('openai', TEST_CATALOG).map((model) => model.model_id)).toContain('gpt-5.6-luna')
    expect(modelsForPantheraProvider('gemini', TEST_CATALOG).map((model) => model.model_id)).toContain('gemini-3.6-flash')
    expect(defaultModelForPantheraProvider('xai', TEST_CATALOG)).toBeNull()
  })

  it('derives selectable providers from the catalog', () => {
    expect(providersForCatalog(TEST_CATALOG)).toEqual(['openai', 'gemini'])
  })

  it('formats known context windows compactly', () => {
    expect(formatContextWindowLabel(8192)).toBe('8K')
    expect(formatContextWindowLabel(32768)).toBe('32K')
    expect(formatContextWindowLabel(131072)).toBe('132K')
    expect(formatContextWindowLabel(null)).toBeNull()
  })

  it('uses sandbox history only in DEV_MODE with sandbox enabled', () => {
    expect(usesSandboxHistory(false, true)).toBe(false)
    expect(usesSandboxHistory(true, false)).toBe(false)
    expect(usesSandboxHistory(true, true)).toBe(true)
  })
})
