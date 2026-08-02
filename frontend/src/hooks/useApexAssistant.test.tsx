import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useApexAssistant } from './useApexAssistant'

describe('useApexAssistant', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps Acinonyx history in its explicit sandbox partition', async () => {
    const queryBodies: Record<string, unknown>[] = []
    let answerNumber = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'POST') {
        queryBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>)
        answerNumber += 1
        return new Response(JSON.stringify({ answer: `answer ${answerNumber}` }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })

    const { result } = renderHook(() => useApexAssistant(false, 'acinonyx'))

    await act(async () => {
      await result.current.queryAssistant('first question', 'acinonyx')
    })
    await act(async () => {
      await result.current.queryAssistant('second question', 'acinonyx')
    })

    expect(queryBodies).toHaveLength(2)
    expect(queryBodies[0].history).toEqual([])
    expect(queryBodies[0].history_partition).toBe('acinonyx')
    expect(queryBodies[1].history).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'model', content: 'answer 1', tool_outputs: [] },
    ])
    expect(result.current.assistantHistory).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'model', content: 'answer 1', tool_outputs: [] },
      { role: 'user', content: 'second question' },
      { role: 'model', content: 'answer 2', tool_outputs: [] },
    ])
  })

  it('captures the session identifier and normalized response observability', async () => {
    let queryBody: Record<string, unknown> | null = null
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'POST') {
        queryBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return new Response(JSON.stringify({
          answer: 'Observed response.',
          profile_used: {
            key: 'panthera',
            version: '2.0',
            provider: 'openai',
            configured_model: 'gpt-5.6-luna',
            resolved_model: 'gpt-5.6-luna',
            resolved_effort: 'medium',
          },
          usage: { input_tokens: 12, output_tokens: 8, total_tokens: 20 },
          timing: { total_ms: 120, provider_ms: 110, apex_tool_ms: 10 },
          cost_estimate: { total_cost: 0.002, currency: 'USD', pricing_version: '2026-08' },
          citations: [{ title: 'Source', uri: 'https://example.test', source: 'google_search' }],
          tool_trace: [{ name: 'search', status: 'ok', duration_ms: 10, origin: 'apex' }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })

    const { result } = renderHook(() => useApexAssistant(false, 'panthera'))
    await act(async () => {
      await result.current.queryAssistant('inspect', 'panthera', { sessionId: 'cortex-session-1' })
    })

    expect(queryBody).toMatchObject({ session_id: 'cortex-session-1' })
    const response = result.current.assistantHistory[1]
    expect(response.metadata?.profile?.resolvedModel).toBe('gpt-5.6-luna')
    expect(response.metadata?.usage?.totalTokens).toBe(20)
    expect(response.metadata?.citations[0]?.uri).toBe('https://example.test')
    expect(response.tool_trace?.[0]).toMatchObject({ name: 'search', origin: 'apex' })
  })
})
