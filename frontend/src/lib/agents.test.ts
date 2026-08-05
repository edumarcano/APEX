import { describe, expect, it } from 'vitest'

import {
  formatContextWindowLabel,
  isLocalAgentKey,
  LOCAL_AGENT_KEYS,
  providerDisplayName,
} from './agents'

describe('agents helpers', () => {
  it('includes Apodemus among local Agents', () => {
    expect(LOCAL_AGENT_KEYS).toEqual(['sorex', 'mus', 'apodemus'])
    expect(isLocalAgentKey('apodemus')).toBe(true)
    expect(isLocalAgentKey('panthera')).toBe(false)
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
