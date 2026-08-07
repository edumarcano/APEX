import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCortex } from './useCortex'

describe('useCortex', () => {
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

    const { result } = renderHook(() => useCortex(false, 'acinonyx'))

    await act(async () => {
      await result.current.queryAgent('first question', 'acinonyx')
    })
    await act(async () => {
      await result.current.queryAgent('second question', 'acinonyx')
    })

    expect(queryBodies).toHaveLength(2)
    expect(queryBodies[0].history).toEqual([])
    expect(queryBodies[0].history_partition).toBe('acinonyx')
    expect(queryBodies[1].history).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'agent', content: 'answer 1', tool_outputs: [] },
    ])
    expect(result.current.cortexHistory).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'agent', content: 'answer 1', tool_outputs: [] },
      { role: 'user', content: 'second question' },
      { role: 'agent', content: 'answer 2', tool_outputs: [] },
    ])
  })

  it('captures the session identifier and normalized response observability', async () => {
    let queryBody: Record<string, unknown> | null = null
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'POST') {
        queryBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return new Response(JSON.stringify({
          answer: 'Observed response.',
          agent_used: {
            key: 'panthera',
            version: '7.4',
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

    const { result } = renderHook(() => useCortex(false, 'panthera'))
    await act(async () => {
      await result.current.queryAgent('inspect', 'panthera', { sessionId: 'cortex-session-1' })
    })

    expect(queryBody).toMatchObject({ session_id: 'cortex-session-1' })
    const response = result.current.cortexHistory[1]
    expect(response.metadata?.agent?.resolvedModel).toBe('gpt-5.6-luna')
    expect(response.metadata?.usage?.totalTokens).toBe(20)
    expect(response.metadata?.citations[0]?.uri).toBe('https://example.test')
    expect(response.tool_trace?.[0]).toMatchObject({ name: 'search', origin: 'apex' })
  })

  it('adds the user turn immediately and keeps it when the request fails', async () => {
    let rejectRequest: ((reason?: unknown) => void) | null = null
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
      if (init?.method !== 'POST') {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
      }
      return new Promise<Response>((_resolve, reject) => {
        rejectRequest = reject
      })
    })
    const { result } = renderHook(() => useCortex(false, 'panthera'))

    let pending: Promise<void>
    act(() => {
      pending = result.current.queryAgent('Keep this question', 'panthera')
    })
    expect(result.current.cortexHistory).toEqual([{ role: 'user', content: 'Keep this question' }])
    expect(result.current.isCortexQuerying).toBe(true)

    await act(async () => {
      rejectRequest?.(new Error('Network unavailable'))
      await pending
    })

    expect(result.current.cortexHistory).toEqual([{ role: 'user', content: 'Keep this question' }])
    expect(result.current.cortexError).toContain('Network unavailable')
  })

  it('uses an empty history immediately after starting a new session', async () => {
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

    const { result } = renderHook(() => useCortex(false, 'panthera'))
    await act(async () => {
      await result.current.queryAgent('old question', 'panthera', {
        sessionId: 'old-session',
      })
    })

    act(() => {
      result.current.clearCortexSession('panthera')
    })
    expect(result.current.cortexHistory).toEqual([])

    await act(async () => {
      await result.current.queryAgent('new question', 'panthera', {
        sessionId: 'new-session',
      })
    })

    expect(queryBodies[1]).toMatchObject({
      history: [],
      session_id: 'new-session',
    })
  })
})
