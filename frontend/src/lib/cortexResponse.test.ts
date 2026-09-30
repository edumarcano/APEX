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

  it('parses canonical grounding and citations with context and tool diagnostics', () => {
    const parsed = parseAgentQueryResponse({
      citations: [{ title: 'Map', uri: 'https://example.test/map', snippet: 'Place', source: 'google_maps' }],
      grounding: { search_suggestions_html: '<a>Search</a>' },
      context_references: [{ namespace: 'personal', source_type: 'note', source_id: 'n1', locator: 'line 1', status: 'ready' }],
      context_usage: { estimated_tokens: 21, truncated: false },
      local_context_usage: { estimated_prompt_tokens: 34, context_window: 4096, history_messages_dropped: 0 },
      tool_trace: [{ name: 'lookup', status: 'ok', duration_ms: 8 }],
      tool_outputs: [{ name: 'lookup', status: 'ok', duration_ms: 8, output: { count: 1 } }],
    })

    expect(parsed.metadata?.citations).toEqual([{ title: 'Map', uri: 'https://example.test/map', snippet: 'Place', source: 'google_maps' }])
    expect(parsed.metadata?.grounding?.searchSuggestionsHtml).toBe('<a>Search</a>')
    expect(parsed.context_references).toHaveLength(1)
    expect(parsed.context_usage?.estimated_tokens).toBe(21)
    expect(parsed.local_context_usage?.estimated_prompt_tokens).toBe(34)
    expect(parsed.tool_trace).toHaveLength(1)
    expect(parsed.tool_outputs).toHaveLength(1)
  })

  it('ignores retired metadata envelopes, alternate agent properties, and camel-case grounding fields', () => {
    const parsed = parseAgentQueryResponse({
      metadata: { agent: { key: 'apex' }, usage: { total_tokens: 12 }, timing: { total_ms: 4 } },
      agent: { key: 'apex' },
      grounding: { searchSuggestionsHtml: '<a>Old</a>' },
    })

    expect(parsed.metadata?.agent).toBeNull()
    expect(parsed.metadata?.usage).toBeNull()
    expect(parsed.metadata?.timing).toBeNull()
    expect(parsed.metadata?.toolSelection).toBeNull()
    expect(parsed.metadata?.grounding?.searchSuggestionsHtml).toBeNull()
  })

  it('treats malformed flat records and arrays as absent metadata without losing valid response fields', () => {
    const parsed = parseAgentQueryResponse({
      answer: 'Still here.',
      agent_used: [],
      usage: ['bad'],
      timing: null,
      cost_estimate: [],
      grounding: [],
      citations: [null, [], { title: 'Valid' }],
      context_usage: [],
      context_references: [[], { namespace: 'personal', source_type: 'note', source_id: 'n2', locator: 'line 2' }],
      tool_outputs: [[], { name: 'lookup', status: 'ok', duration_ms: 3, output: 'done' }],
    })

    expect(parsed.answer).toBe('Still here.')
    expect(parsed.metadata?.agent).toBeNull()
    expect(parsed.metadata?.usage).toBeNull()
    expect(parsed.metadata?.timing).toBeNull()
    expect(parsed.metadata?.cost).toBeNull()
    expect(parsed.metadata?.grounding).toBeNull()
    expect(parsed.metadata?.citations).toEqual([{ title: 'Valid', uri: null, snippet: null, source: null }])
    expect(parsed.context_usage).toBeNull()
    expect(parsed.context_references).toHaveLength(1)
    expect(parsed.tool_outputs).toHaveLength(1)
  })

  it('ignores arrays as response objects', () => {
    const parsed = parseAgentQueryResponse([{ answer: 'not a response object' }])
    expect(parsed.answer).toBeUndefined()
    expect(parsed.tool_trace).toEqual([])
    expect(parsed.tool_outputs).toEqual([])
  })
})
