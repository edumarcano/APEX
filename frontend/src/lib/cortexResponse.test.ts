import { describe, expect, it } from 'vitest'

import { parseAgentQueryResponse } from './cortexResponse'

describe('parseAgentQueryResponse', () => {
  it('restores metrics from the flat conversation-turn response shape', () => {
    const parsed = parseAgentQueryResponse({
      answer: 'Ready.',
      agent_used: {
        key: 'apex',
        provider: 'openrouter',
        configured_model: 'deepseek/deepseek-v4-flash-0731',
        resolved_model: 'deepseek/deepseek-v4-flash-0731',
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

    expect(parsed.metadata?.agent?.key).toBe('apex')
    expect(parsed.metadata?.usage?.totalTokens).toBe(150)
    expect(parsed.metadata?.timing?.totalMs).toBe(820)
    expect(parsed.metadata?.cost?.totalCost).toBe(0.01)
    expect(parsed.metadata?.toolSelection?.selected_schema_tokens).toBe(123)
  })

  it('continues to parse the nested metadata shape', () => {
    const parsed = parseAgentQueryResponse({
      metadata: {
        agent: { key: 'apex' },
        usage: { total_tokens: 12 },
      },
    })

    expect(parsed.metadata?.agent?.key).toBe('apex')
    expect(parsed.metadata?.usage?.totalTokens).toBe(12)
  })

  it('parses top-level agent property for in-flight streaming responses', () => {
    const parsed = parseAgentQueryResponse({
      agent: { key: 'apex' },
      answer: 'Streaming text...',
    })

    expect(parsed.metadata?.agent?.key).toBe('apex')
    expect(parsed.metadata?.usage).toBeNull()
  })
})
