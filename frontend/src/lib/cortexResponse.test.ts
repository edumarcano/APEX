import { describe, expect, it } from 'vitest'

import { parseAgentQueryResponse } from './cortexResponse'

describe('parseAgentQueryResponse', () => {
  it('restores metrics from the flat conversation-turn response shape', () => {
    const parsed = parseAgentQueryResponse({
      answer: 'Ready.',
      agent_used: {
        key: 'cloud',
        provider: 'gemini',
        configured_model: 'gemini-2.5-pro',
        resolved_model: 'gemini-2.5-pro',
      },
      usage: { input_tokens: 120, output_tokens: 30, total_tokens: 150 },
      timing: { total_ms: 820, provider_ms: 700, apex_tool_ms: 40 },
      cost_estimate: {
        token_cost: 0.01,
        hosted_tool_cost: 0,
        total_cost: 0.01,
        currency: 'USD',
        pricing_version: 'v1',
        completeness: 'complete',
      },
      resolved_tool_selection: {
        offered_tool_names: ['search_apex_docs'],
        selected_schema_tokens: 123,
        rejected_tools: [],
      },
    })

    expect(parsed.metadata?.agent?.key).toBe('cloud')
    expect(parsed.metadata?.usage?.totalTokens).toBe(150)
    expect(parsed.metadata?.timing?.totalMs).toBe(820)
    expect(parsed.metadata?.cost?.totalCost).toBe(0.01)
    expect(parsed.metadata?.toolSelection?.selected_schema_tokens).toBe(123)
  })

  it('continues to parse the nested metadata shape', () => {
    const parsed = parseAgentQueryResponse({
      metadata: {
        agent: { key: 'local' },
        usage: { total_tokens: 12 },
      },
    })

    expect(parsed.metadata?.agent?.key).toBe('local')
    expect(parsed.metadata?.usage?.totalTokens).toBe(12)
  })
})
