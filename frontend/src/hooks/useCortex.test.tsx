import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCortex } from './useCortex'

const conversation = { id: '00000000-0000-4000-8000-000000000001', active_leaf_message_id: null, messages: [] }

describe('useCortex', () => {
  afterEach(() => vi.restoreAllMocks())

  it('hydrates a durable conversation and submits IDs instead of history', async () => {
    const turnBodies: Record<string, unknown>[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([conversation]))
      if (url.endsWith(conversation.id) && !init?.method) return new Response(JSON.stringify(conversation))
      if (url.endsWith('/turns')) {
        turnBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        return new Response(JSON.stringify({
          conversation_id: conversation.id, user_message_id: '00000000-0000-4000-8000-000000000002',
          agent_message_id: '00000000-0000-4000-8000-000000000003', active_leaf_message_id: '00000000-0000-4000-8000-000000000003',
          message_status: 'completed', answer: 'Durable answer.', agent_used: { key: 'panthera', provider: 'openai', configured_model: 'gpt-5.6-luna', resolved_model: 'gpt-5.6-luna' }, tool_outputs: [], tool_trace: [],
        }))
      }
      return new Response(JSON.stringify([]))
    })
    const { result } = renderHook(() => useCortex(false))
    await waitFor(() => expect(result.current.cortexConversationId).toBe(conversation.id))
    await act(async () => { await result.current.queryAgent('inspect', 'panthera') })
    expect(turnBodies[0]).toMatchObject({ prompt: 'inspect' })
    expect(turnBodies[0]).not.toHaveProperty('history')
    expect(turnBodies[0]).not.toHaveProperty('history_partition')
    expect(result.current.cortexHistory.map((message) => message.content)).toEqual(['inspect', 'Durable answer.'])
  })

  it('keeps an optimistic user message when a durable turn fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([conversation]))
      if (url.endsWith(conversation.id) && !init?.method) return new Response(JSON.stringify(conversation))
      if (url.endsWith('/turns')) throw new Error('Network unavailable')
      return new Response(JSON.stringify([]))
    })
    const { result } = renderHook(() => useCortex(false))
    await waitFor(() => expect(result.current.cortexConversationId).toBe(conversation.id))
    await act(async () => { await result.current.queryAgent('Keep this question', 'panthera') })
    expect(result.current.cortexHistory).toEqual([{ role: 'user', content: 'Keep this question' }])
    expect(result.current.cortexError).toContain('Network unavailable')
  })

  it('creates a distinct durable conversation for a new session', async () => {
    let created = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([conversation]))
      if (url.endsWith(conversation.id) && !init?.method) return new Response(JSON.stringify(conversation))
      if (url.endsWith('/conversations') && init?.method === 'POST') {
        created += 1
        return new Response(JSON.stringify({ id: '00000000-0000-4000-8000-000000000002' }), { status: 201 })
      }
      return new Response(JSON.stringify([]))
    })
    const { result } = renderHook(() => useCortex(false))
    await waitFor(() => expect(result.current.cortexConversationId).toBe(conversation.id))
    act(() => result.current.clearCortexSession())
    await waitFor(() => expect(created).toBe(1))
    expect(result.current.cortexHistory).toEqual([])
  })
})
