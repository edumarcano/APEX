import { describe, expect, it } from 'vitest'

import {
  AGENT_KEYS,
  canVerifyCloudProvider,
  formatContextWindowLabel,
  formatReasoningLabel,
  isAgentKey,
  isFelisKey,
  isPantheraKey,
  providerDisplayName,
  resolveBriefingModeAvailability,
  usesSandboxHistory,
} from './agents'
import type { BriefingTargetStatus } from '../types/telemetry'

describe('agents helpers', () => {
  it('exposes only Panthera and Felis agent keys', () => {
    expect(AGENT_KEYS).toEqual(['panthera', 'felis'])
    expect(isFelisKey('felis')).toBe(true)
    expect(isPantheraKey('panthera')).toBe(true)
    expect(isAgentKey('panthera')).toBe(true)
    expect(isAgentKey('felis')).toBe(true)
    expect(isAgentKey('lynx')).toBe(false)
    expect(isAgentKey('apodemus')).toBe(false)
    expect(isAgentKey('unknown')).toBe(false)
  })

  it('labels providers for display without changing their technical IDs', () => {
    expect(providerDisplayName('llama_cpp')).toBe('llama.cpp')
    expect(providerDisplayName('ollama')).toBe('Ollama')
    expect(providerDisplayName('gemini')).toBe('Google')
    expect(providerDisplayName('openrouter')).toBe('OpenRouter')
    expect(providerDisplayName('xai')).toBe('SpaceXAI')
  })

  it('formats known context windows compactly', () => {
    expect(formatContextWindowLabel(8192)).toBe('8K')
    expect(formatContextWindowLabel(32768)).toBe('32K')
    expect(formatContextWindowLabel(131072)).toBe('132K')
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

  it('allows cloud verification only when Panthera is not disabled', () => {
    expect(
      canVerifyCloudProvider({
        key: 'panthera',
        runtime: 'cloud',
        status: 'configured',
      }),
    ).toBe(true)
    expect(
      canVerifyCloudProvider({
        key: 'panthera',
        runtime: 'cloud',
        status: 'disabled',
      }),
    ).toBe(false)
    expect(
      canVerifyCloudProvider({
        key: 'felis',
        runtime: 'local',
        status: 'available',
      }),
    ).toBe(false)
  })

  it('uses briefing targets as the sole source of model-mode availability', () => {
    const panthera: BriefingTargetStatus = {
      mode: 'panthera',
      label: 'Apex Panthera',
      description: 'Cloud briefing',
      model_id: 'gpt-5.6-luna',
      model_display_name: 'GPT-5.6 Luna',
      provider: 'openai',
      runtime: 'cloud',
      status: 'configured',
      reason: 'Credentials configured',
      pricing: null,
    }

    expect(resolveBriefingModeAvailability('structured_digest')).toEqual({
      status: 'available',
      reason: null,
    })
    expect(resolveBriefingModeAvailability('panthera', [panthera])).toEqual({
      status: 'configured',
      reason: 'Credentials configured',
    })
    expect(resolveBriefingModeAvailability('felis', [panthera])).toEqual({
      status: 'unknown',
      reason: 'Mode status unavailable',
    })
  })
})
