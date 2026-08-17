import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCortex } from './useCortex'

const conversation = {
  id: '00000000-0000-4000-8000-000000000001',
  agent: 'panthera',
  selected_tool_names: [],
  tool_profile_id: null,
  active_leaf_message_id: null,
  messages: [],
}

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
    let detailRequests = 0
    const failedDetail = {
      ...conversation,
      active_leaf_message_id: '00000000-0000-4000-8000-000000000003',
      messages: [
        {
          id: '00000000-0000-4000-8000-000000000002',
          conversation_id: conversation.id,
          parent_message_id: null,
          role: 'user',
          content: 'Keep this question',
          status: 'completed',
          created_at: '2026-08-17T00:00:00Z',
          updated_at: '2026-08-17T00:00:00Z',
        },
        {
          id: '00000000-0000-4000-8000-000000000003',
          conversation_id: conversation.id,
          parent_message_id: '00000000-0000-4000-8000-000000000002',
          role: 'agent',
          content: '',
          status: 'failed',
          response_metadata: { error: 'Durable turn failed.' },
          created_at: '2026-08-17T00:00:01Z',
          updated_at: '2026-08-17T00:00:01Z',
        },
      ],
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([conversation]))
      if (url.endsWith(conversation.id) && !init?.method) {
        detailRequests += 1
        return new Response(JSON.stringify(detailRequests === 1 ? conversation : failedDetail))
      }
      if (url.endsWith('/turns')) throw new Error('Network unavailable')
      return new Response(JSON.stringify([]))
    })
    const { result } = renderHook(() => useCortex(false))
    await waitFor(() => expect(result.current.cortexConversationId).toBe(conversation.id))
    await act(async () => { await result.current.queryAgent('Keep this question', 'panthera') })
    expect(result.current.cortexHistory[0]).toEqual({ role: 'user', content: 'Keep this question' })
    expect(result.current.cortexError).toContain('Network unavailable')
    expect(detailRequests).toBe(2)
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

  it('hydrates conversation preferences and sends nullable profile patches', async () => {
    const patchBodies: Record<string, unknown>[] = []
    const detail = {
      ...conversation,
      agent: 'felis',
      selected_tool_names: ['tool_a'],
      tool_profile_id: 'profile_a',
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([detail]))
      if (url.endsWith(detail.id) && init?.method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>)
        return new Response(JSON.stringify(detail))
      }
      if (url.endsWith(detail.id) && !init?.method) return new Response(JSON.stringify(detail))
      return new Response(JSON.stringify([]))
    })
    const { result } = renderHook(() => useCortex(false))
    await waitFor(() => expect(result.current.conversationPreferences?.agent).toBe('felis'))
    await act(async () => {
      await result.current.patchConversation({ toolProfileId: null })
    })
    expect(patchBodies).toEqual([{ tool_profile_id: null }])
  })

  it('serializes preference patches and keeps the latest queued update', async () => {
    const patchBodies: Record<string, unknown>[] = []
    let releaseFirstPatch!: () => void
    const firstPatchReleased = new Promise<void>((resolve) => { releaseFirstPatch = resolve })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([conversation]))
      if (url.endsWith(conversation.id) && init?.method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>)
        if (patchBodies.length === 1) await firstPatchReleased
        return new Response(JSON.stringify(conversation))
      }
      if (url.endsWith(conversation.id) && !init?.method) return new Response(JSON.stringify(conversation))
      return new Response(JSON.stringify([]))
    })
    const { result } = renderHook(() => useCortex(false))
    await waitFor(() => expect(result.current.conversationPreferences?.agent).toBe('panthera'))

    const first = result.current.patchConversation({ selectedToolNames: ['old_tool'] })
    await waitFor(() => expect(patchBodies).toHaveLength(1))
    const second = result.current.patchConversation({ selectedToolNames: ['new_tool'] })
    releaseFirstPatch()
    await act(async () => { await Promise.all([first, second]) })

    expect(patchBodies).toEqual([
      { selected_tool_names: ['old_tool'] },
      { selected_tool_names: ['new_tool'] },
    ])
  })

  it('clears query indicators when a partition change invalidates an active turn', async () => {
    let releaseTurn!: (response: Response) => void
    const pendingTurn = new Promise<Response>((resolve) => { releaseTurn = resolve })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/conversations') && !init?.method) return new Response(JSON.stringify([conversation]))
      if (url.endsWith(conversation.id) && !init?.method) return new Response(JSON.stringify(conversation))
      if (url.endsWith('/turns')) return pendingTurn
      return new Response(JSON.stringify([]))
    })
    const { result, rerender } = renderHook(
      ({ sandboxMode }) => useCortex(false, { devModeActive: true, sandboxMode }),
      { initialProps: { sandboxMode: false } },
    )
    await waitFor(() => expect(result.current.cortexConversationId).toBe(conversation.id))
    let queryPromise!: Promise<void>
    act(() => { queryPromise = result.current.queryAgent('in flight', 'panthera') })
    await waitFor(() => expect(result.current.isCortexQuerying).toBe(true))

    rerender({ sandboxMode: true })
    await waitFor(() => expect(result.current.isCortexQuerying).toBe(false))
    expect(result.current.activeQueryAgent).toBeNull()

    releaseTurn(new Response(JSON.stringify({ answer: 'late response' })))
    await act(async () => { await queryPromise })
  })
})
