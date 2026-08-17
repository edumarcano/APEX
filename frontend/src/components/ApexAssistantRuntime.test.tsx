import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApexAssistantRuntime, ApexAssistantThread, ApexConversationRail, type ApexAssistantRuntimeHandle } from './ApexAssistantRuntime'

const conversationId = '00000000-0000-4000-8000-000000000001'
const summary = {
  id: conversationId,
  title: 'HUD conversation',
  archived_at: null,
  agent: 'panthera' as const,
  selected_tool_names: [],
  tool_profile_id: null,
  updated_at: '2026-08-17T12:00:00Z',
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ApexAssistantRuntime', () => {
  it('loads the authoritative thread and gates a prompt through the APEX turn endpoint', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: null, messages: [] })
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/turns`)) {
        expect(init?.method).toBe('POST')
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>
        expect(payload.prompt).toBe('List my pending reminders.')
        expect(payload.user_message_id).toMatch(/^[0-9a-f-]{36}$/i)
        expect(payload.agent_message_id).toMatch(/^[0-9a-f-]{36}$/i)
        expect(payload.agent).toBe('panthera')
        return response({ answer: 'There are three active reminders.', tool_trace: [], tool_outputs: [], citations: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const beforeRun = vi.fn(async () => true)
    const user = userEvent.setup()

    render(
      <ApexAssistantRuntime
        config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        beforeRun={beforeRun}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('Reminders')).toBeInTheDocument())
    await user.click(screen.getByText('Reminders'))
    expect(screen.getByPlaceholderText('Ask APEX…')).toHaveValue('List my pending reminders.')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByText('There are three active reminders.')).toBeInTheDocument())
    expect(beforeRun).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('hides the in-flight Agent card and uses one Apex prefix in the working label', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    let resolveTurn: (value: Response) => void = () => undefined
    const turnResponse = new Promise<Response>((resolve) => { resolveTurn = resolve })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([{ ...summary, agent: 'felis' }])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, agent: 'felis', active_leaf_message_id: null, messages: [] })
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/turns`)) {
        expect(init?.method).toBe('POST')
        return turnResponse
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime
        config={{ agent: 'felis', effort: null, selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        beforeRun={async () => true}
      >
        <ApexAssistantThread
          composer={{
            activeAgent: 'felis',
            activeAgentName: 'Apex Felis',
            tools: {
              catalog: null,
              selectedToolNames: [],
              activeToolProfileId: null,
              onSelectionChange: () => undefined,
              onProfileChange: () => undefined,
            },
          }}
        />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'Keep this request running')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getByText('Apex Felis working')).toBeInTheDocument())
    expect(screen.queryByText('Apex Apex Felis working')).not.toBeInTheDocument()
    resolveTurn(response({ answer: 'Finished.', tool_trace: [], tool_outputs: [], citations: [] }))
    await waitFor(() => expect(screen.getByText('Finished.')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalled()
  })

  it('does not reload the remote thread list when host callbacks change identity', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    let regularListCalls = 0
    let archivedListCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) {
        archivedListCalls += 1
        return response([])
      }
      if (url.endsWith('/api/v1/cortex/conversations')) {
        regularListCalls += 1
        return response([summary])
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) {
        return response({ ...summary, active_leaf_message_id: null, messages: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { rerender } = render(
      <ApexAssistantRuntime
        config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        onConversationChange={() => undefined}
        onRunningChange={() => undefined}
        onResponseChange={() => undefined}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    const callsBeforeRerender = { regular: regularListCalls, archived: archivedListCalls }
    rerender(
      <ApexAssistantRuntime
        config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        onConversationChange={() => undefined}
        onRunningChange={() => undefined}
        onResponseChange={() => undefined}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect({ regular: regularListCalls, archived: archivedListCalls }).toEqual(callsBeforeRerender)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('keeps a user edit composer mounted across host rerenders', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const userId = '00000000-0000-4000-8000-000000000010'
    const agentId = '00000000-0000-4000-8000-000000000011'
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) {
        return response({
          ...summary,
          active_leaf_message_id: agentId,
          messages: [
            { id: userId, parent_message_id: null, role: 'user', content: 'Original prompt', status: 'completed', created_at: '2026-08-17T12:00:00Z', response_metadata: null },
            { id: agentId, parent_message_id: userId, role: 'agent', content: 'Original answer', status: 'completed', created_at: '2026-08-17T12:00:01Z', response_metadata: {} },
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { rerender } = render(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('Original prompt')).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.getByPlaceholderText('Edit message…')).toHaveValue('Original prompt')
    rerender(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'high', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    expect(screen.getByPlaceholderText('Edit message…')).toHaveValue('Original prompt')
    expect(fetchMock).toHaveBeenCalled()
  })

  it('keeps branch persistence errors visible after authoritative reload', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const userId = '00000000-0000-4000-8000-000000000040'
    const firstAgentId = '00000000-0000-4000-8000-000000000041'
    const siblingAgentId = '00000000-0000-4000-8000-000000000042'
    let detailLoads = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`) && init?.method === 'PATCH') return response({ detail: 'Branch persistence failed.' }, 500)
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) {
        detailLoads += 1
        return response({
          ...summary,
          active_leaf_message_id: firstAgentId,
          messages: [
            { id: userId, parent_message_id: null, role: 'user', content: 'Branch prompt', status: 'completed', created_at: '2026-08-17T12:00:00Z', response_metadata: null },
            { id: firstAgentId, parent_message_id: userId, role: 'agent', content: `First answer ${detailLoads}`, status: 'completed', created_at: '2026-08-17T12:00:01Z', response_metadata: {} },
            { id: siblingAgentId, parent_message_id: userId, role: 'agent', content: 'Sibling answer', status: 'completed', created_at: '2026-08-17T12:00:02Z', response_metadata: {} },
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('First answer 1')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next branch' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Branch persistence failed.'))
    expect(detailLoads).toBeGreaterThan(1)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('does not persist an empty HUD thread and creates it only when the first turn is accepted', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const createdId = '00000000-0000-4000-8000-000000000020'
    let createCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations') && init?.method === 'POST') {
        createCalls += 1
        return response({ ...summary, id: createdId })
      }
      if (url.endsWith('/api/v1/cortex/conversations')) return response([])
      if (url.endsWith(`/api/v1/cortex/conversations/${createdId}`)) return response({ ...summary, id: createdId, active_leaf_message_id: null, messages: [] })
      if (url.endsWith(`/api/v1/cortex/conversations/${createdId}/turns`)) return response({ answer: 'Created after use.', tool_trace: [], tool_outputs: [], citations: [] })
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    const beforeRun = vi.fn(async () => true)
    render(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }} beforeRun={beforeRun}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    expect(createCalls).toBe(0)
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'Use this thread')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getByText('Created after use.')).toBeInTheDocument())
    expect(createCalls).toBe(1)
    expect(beforeRun).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('returns the updated conversation preferences after a PATCH', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const runtimeRef: { current: ApexAssistantRuntimeHandle | null } = { current: null }
    const updatedSummary = { ...summary, agent: 'felis' as const, selected_tool_names: ['reminders'], tool_profile_id: 'focused' }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`) && init?.method === 'PATCH') return response(updatedSummary)
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: null, messages: [] })
      throw new Error(`Unexpected request: ${url}`)
    })
    render(
      <ApexAssistantRuntime
        config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        runtimeRef={runtimeRef}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    const updated = await runtimeRef.current?.patchPreferences({ agent: 'felis', selectedToolNames: ['reminders'], toolProfileId: 'focused' })
    expect(updated).toEqual({ conversationId, agent: 'felis', selected_tool_names: ['reminders'], tool_profile_id: 'focused' })
    expect(fetchMock).toHaveBeenCalled()
  })

  it('only deletes archived conversations after confirmation', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const archivedId = '00000000-0000-4000-8000-000000000030'
    const archivedSummary = { ...summary, id: archivedId, title: 'Archived HUD', archived_at: '2026-08-17T12:00:00Z' }
    let archivedPresent = true
    let deleteCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response(archivedPresent ? [archivedSummary] : [])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([])
      if (url.endsWith(`/api/v1/cortex/conversations/${archivedId}`) && init?.method === 'DELETE') {
        deleteCalls += 1
        archivedPresent = false
        return new Response(null, { status: 204 })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${archivedId}`)) return response({ ...archivedSummary, active_leaf_message_id: null, messages: [] })
      throw new Error(`Unexpected request: ${url}`)
    })
    const confirmMock = vi.spyOn(globalThis, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
      </ApexAssistantRuntime>,
    )
    await user.click(await screen.findByRole('button', { name: 'Archived' }))
    const deleteButton = await screen.findByRole('button', { name: 'Delete Archived HUD permanently' })
    await user.click(deleteButton)
    expect(deleteCalls).toBe(0)
    confirmMock.mockReturnValue(true)
    await user.click(deleteButton)
    await waitFor(() => expect(deleteCalls).toBe(1))
    expect(fetchMock).toHaveBeenCalled()
  })

  it('does not initialize a transient thread when preflight rejects', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    let createCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations') && init?.method === 'POST') {
        createCalls += 1
        return response(summary)
      }
      if (url.endsWith('/api/v1/cortex/conversations')) return response([])
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }} beforeRun={async () => false}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'Blocked request')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(createCalls).toBe(0)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('coalesces transient list failures until an explicit retry', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    let calls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      calls += 1
      throw new TypeError('offline')
    })
    const user = userEvent.setup()

    render(
      <ApexAssistantRuntime config={{ agent: 'panthera', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument())
    const initialCalls = calls
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls).toBe(initialCalls)

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(calls).toBeGreaterThan(initialCalls))
    expect(calls).toBe(initialCalls + 2)
    expect(fetchMock).toHaveBeenCalled()
  })
})
