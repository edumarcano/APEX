import { describe, expect, it } from 'vitest'

import {
  formatContextWindowLabel,
  isAgentKey,
  isLocalAgentKey,
  LOCAL_AGENT_KEYS,
  providerDisplayName,
} from './agents'

describe('agents helpers', () => {
  it('includes llama.cpp Agents among local Agents', () => {
    expect(LOCAL_AGENT_KEYS).toEqual(['sorex', 'mus', 'apodemus', 'neotoma'])
    expect(isLocalAgentKey('apodemus')).toBe(true)
    expect(isLocalAgentKey('neotoma')).toBe(true)
    expect(isLocalAgentKey('panthera')).toBe(false)
  })

  it('accepts Apodemus as a boot-time Agent selection key', () => {
    expect(isAgentKey('apodemus')).toBe(true)
    expect(isAgentKey('mus')).toBe(true)
    expect(isAgentKey('panthera')).toBe(true)
    expect(isAgentKey('acinonyx')).toBe(true)
    expect(isAgentKey('unknown')).toBe(false)
  })

  it('labels llama.cpp providers for display', () => {
    expect(providerDisplayName('llama_cpp')).toBe('llama.cpp')
    expect(providerDisplayName('ollama')).toBe('Ollama')
  })

  it('formats known context windows compactly', () => {
    expect(formatContextWindowLabel(8192)).toBe('8K')
    expect(formatContextWindowLabel(32768)).toBe('32K')
    expect(formatContextWindowLabel(null)).toBeNull()
  })
})
