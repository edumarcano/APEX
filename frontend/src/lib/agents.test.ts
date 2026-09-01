import { describe, expect, it } from 'vitest'

import {
  AGENT_KEYS,
  canVerifyCloudProvider,
  formatContextWindowLabel,
  formatReasoningLabel,
  isAgentKey,
  providerDisplayName,
  resolveBriefingModeAvailability,
  resolveHomeQueryOverrides,
  resolveLowestReasoningEffort,
  usesSandboxHistory,
} from './agents'
import type { BriefingTargetStatus, ModelCatalogEntry } from '../types/telemetry'

describe('agents helpers', () => {
  it('exposes only the singular Apex Agent key', () => {
    expect(AGENT_KEYS).toEqual(['apex'])
    expect(isAgentKey('apex')).toBe(true)
    expect(isAgentKey('unknown')).toBe(false)
  })

  it('labels providers for display without changing their technical IDs', () => {
    expect(providerDisplayName('llama_cpp')).toBe('llama.cpp')
    expect(providerDisplayName('ollama')).toBe('Ollama')
    expect(providerDisplayName('gemini')).toBe('Google')
    expect(providerDisplayName('openrouter')).toBe('OpenRouter')
  })

  it('formats known context windows compactly', () => {
    expect(formatContextWindowLabel(8192)).toBe('8K')
    expect(formatContextWindowLabel(32768)).toBe('32K')
    expect(formatContextWindowLabel(131072)).toBe('132K')
    expect(formatContextWindowLabel(1048576)).toBe('1M')
    expect(formatContextWindowLabel(1310720)).toBe('1M')
    expect(formatContextWindowLabel(null)).toBeNull()
  })

  it('humanizes model reasoning options without changing canonical value meaning', () => {
    expect(formatReasoningLabel('none')).toBe('None')
    expect(formatReasoningLabel('minimal')).toBe('Minimal')
    expect(formatReasoningLabel('low')).toBe('Low')
    expect(formatReasoningLabel('medium')).toBe('Medium')
    expect(formatReasoningLabel('high')).toBe('High')
    expect(formatReasoningLabel('xhigh')).toBe('Extra High')
    expect(formatReasoningLabel('max')).toBe('Max')
    expect(formatReasoningLabel(null)).toBe('')
  })

  it('uses sandbox history only in DEV_MODE with sandbox enabled', () => {
    expect(usesSandboxHistory(false, true)).toBe(false)
    expect(usesSandboxHistory(true, false)).toBe(false)
    expect(usesSandboxHistory(true, true)).toBe(true)
  })

  it('allows cloud verification only for an enabled cloud model', () => {
    expect(
      canVerifyCloudProvider({
        key: 'apex',
        runtime: 'cloud',
        status: 'configured',
      }),
    ).toBe(true)
    expect(
      canVerifyCloudProvider({
        key: 'apex',
        runtime: 'cloud',
        status: 'disabled',
      }),
    ).toBe(false)
    expect(
      canVerifyCloudProvider({
        key: 'apex',
        runtime: 'local',
        status: 'available',
      }),
    ).toBe(false)
  })

  it('uses briefing targets as the sole source of model-mode availability', () => {
    const focused: BriefingTargetStatus = {
      mode: 'focused',
      label: 'Focused',
      description: 'Cloud briefing',
      model_id: 'gpt-5.6-luna',
      model_display_name: 'GPT-5.6 Luna',
      provider: 'openai',
      runtime: 'cloud',
      status: 'configured',
      reason: 'Credentials configured',
      pricing: null,
    }

    expect(resolveBriefingModeAvailability('structured')).toEqual({
      status: 'available',
      reason: null,
    })
    expect(resolveBriefingModeAvailability('focused', [focused])).toEqual({
      status: 'configured',
      reason: 'Credentials configured',
    })
    expect(resolveBriefingModeAvailability('flash', [focused])).toEqual({
      status: 'unknown',
      reason: 'Mode status unavailable',
    })
  })

  it('resolves lowest reasoning effort preference correctly', () => {
    expect(resolveLowestReasoningEffort(['none', 'low', 'high', 'max'])).toBe('none')
    expect(resolveLowestReasoningEffort(['minimal', 'low', 'medium', 'high'])).toBe('minimal')
    expect(resolveLowestReasoningEffort(['low', 'medium', 'high'])).toBe('low')
    expect(resolveLowestReasoningEffort(['medium', 'high'])).toBe('medium')
    expect(resolveLowestReasoningEffort(['high', 'max'])).toBe('high')
    expect(resolveLowestReasoningEffort(null)).toBeNull()
    expect(resolveLowestReasoningEffort([])).toBeNull()
  })

  it('resolves home query overrides for cloud and local models', () => {
    const cloudEntry: ModelCatalogEntry = {
      model_id: 'deepseek/deepseek-v4-flash-0731',
      display_name: 'DeepSeek V4 Flash',
      provider: 'openrouter',
      runtime: 'cloud',
      stability: 'stable',
      reasoning_options: ['none', 'low', 'high', 'max'],
      default_reasoning: 'high',
      hosted_capabilities: [],
    }
    expect(resolveHomeQueryOverrides(cloudEntry)).toEqual({
      agent: 'apex',
      modelId: 'deepseek/deepseek-v4-flash-0731',
      effort: 'none',
      contextWindow: null,
      localReasoningMode: null,
    })

    const localEntry: ModelCatalogEntry = {
      model_id: 'gemma-4-E2B-Q4_K_M.gguf',
      display_name: 'Gemma 4 E2B',
      provider: 'llama_cpp',
      runtime: 'local',
      stability: 'stable',
      reasoning_options: null,
      default_reasoning: null,
      maximum_context_window: 131072,
      hosted_capabilities: [],
    }
    expect(resolveHomeQueryOverrides(localEntry)).toEqual({
      agent: 'apex',
      modelId: 'gemma-4-E2B-Q4_K_M.gguf',
      effort: null,
      contextWindow: 16384,
      localReasoningMode: 'none',
    })
  })
})
