import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApexAssistantRuntime, ApexAssistantThread, ApexConversationRail, type ApexAssistantRuntimeHandle } from './ApexAssistantRuntime'

const conversationId = '00000000-0000-4000-8000-000000000001'
const summary = {
  id: conversationId,
  title: 'HUD conversation',
  archived_at: null,
  agent: 'apex' as const,
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

function sseResponse(events: Array<{ sequence: number; type: string; payload: Record<string, unknown> }>): Response {
  const encoder = new TextEncoder()
  const body = events
    .map((e) => `id: ${e.sequence}\nevent: ${e.type}\ndata: ${JSON.stringify(e.payload)}\n\n`)
    .join('')
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

function mockRunRecord(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: '00000000-0000-4000-8000-000000000099',
    conversation_id: conversationId,
    partition: 'production',
    user_message_id: '00000000-0000-4000-8000-000000000002',
    agent_message_id: '00000000-0000-4000-8000-000000000003',
    requested_model: 'apex-default',
    resolved_model: 'apex-default',
    provider: 'openai',
    runtime: 'cloud',
    status: 'running',
    stop_reason: null,
    created_at: '2026-08-17T12:00:00Z',
    started_at: '2026-08-17T12:00:01Z',
    completed_at: null,
    updated_at: '2026-08-17T12:00:01Z',
    limit_snapshot: { max_elapsed_seconds: 600, max_total_tokens: 128000, max_retries: 4, max_model_turns: 6, max_tool_calls: 10 },
    turns_count: 1, tool_calls_count: 0, retries_count: 0, total_tokens: 100, elapsed_seconds: 1.0,
    usage_quality: 'reported', runtime_measurements: {}, evidence: { final_message_status: 'completed', answer_persisted: true, tool_outcome_counts: {}, action_ids: [] },
    trace_id: null, error: null,
    ...overrides,
  }
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
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/runs`)) {
        expect(init?.method).toBe('POST')
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>
        expect(payload.prompt).toBe('List my pending reminders.')
        expect(payload.user_message_id).toMatch(/^[0-9a-f-]{36}$/i)
        expect(payload.agent_message_id).toMatch(/^[0-9a-f-]{36}$/i)
        expect(payload.agent).toBe('apex')
        return response(mockRunRecord(), 202)
      }
      if (url.includes('/events')) {
        return sseResponse([
          { sequence: 1, type: 'response.delta', payload: { text: 'There are three active reminders.' } },
          { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
        ])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const beforeRun = vi.fn(async () => true)
    const user = userEvent.setup()

    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
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
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: null, messages: [] })
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/runs`)) {
        expect(init?.method).toBe('POST')
        return response(mockRunRecord(), 202)
      }
      if (url.includes('/events')) {
        return turnResponse
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: null, selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        beforeRun={async () => true}
      >
        <ApexAssistantThread
          composer={{
            activeAgent: 'apex',
            activeAgentName: 'Apex Agent',
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
    await waitFor(() => expect(screen.getByText('Apex Agent working')).toBeInTheDocument())
    expect(screen.queryByText('Apex Apex Agent working')).not.toBeInTheDocument()
    resolveTurn(sseResponse([
      { sequence: 1, type: 'response.delta', payload: { text: 'Finished.' } },
      { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
    ]))
    await waitFor(() => expect(screen.getByText('Finished.')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalled()
  })

  it('batches streaming deltas and flushes on completion while preserving agent streaming metadata', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: null, messages: [] })
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/runs`)) {
        return response(mockRunRecord(), 202)
      }
      if (url.includes('/events')) {
        return sseResponse([
          { sequence: 1, type: 'response.delta', payload: { text: 'High ' } },
          { sequence: 2, type: 'response.delta', payload: { text: 'throughput ' } },
          { sequence: 3, type: 'response.delta', payload: { text: 'token stream.' } },
          { sequence: 4, type: 'run.completed', payload: { status: 'completed' } },
        ])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()

    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        beforeRun={async () => true}
      >
        <ApexAssistantThread
          renderAgent={(text, metadata) => (
            <div data-testid="agent-msg-box">
              <span data-testid="agent-msg-key">{String((metadata?.agent_used as Record<string, unknown> | undefined)?.key ?? '')}</span>
              <span data-testid="agent-msg-text">{text}</span>
            </div>
          )}
        />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByPlaceholderText('Ask APEX…')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'Fast stream test')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByTestId('agent-msg-text')).toHaveTextContent('High throughput token stream.'))
    expect(screen.getByTestId('agent-msg-key')).toHaveTextContent('apex')
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
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
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
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
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
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('Original prompt')).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.getByPlaceholderText('Edit message…')).toHaveValue('Original prompt')
    rerender(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'high', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
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
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
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
      if (url.endsWith(`/api/v1/cortex/conversations/${createdId}/runs`)) return response(mockRunRecord({ conversation_id: createdId }), 202)
      if (url.includes('/events')) return sseResponse([
        { sequence: 1, type: 'response.delta', payload: { text: 'Created after use.' } },
        { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
      ])
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    const beforeRun = vi.fn(async () => true)
    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }} beforeRun={beforeRun}>
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
    const updatedSummary = { ...summary, agent: 'apex' as const, selected_tool_names: ['reminders'], tool_profile_id: 'focused' }
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
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        runtimeRef={runtimeRef}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    const updated = await runtimeRef.current?.patchPreferences({ agent: 'apex', selectedToolNames: ['reminders'], toolProfileId: 'focused' })
    expect(updated).toEqual({ conversationId, agent: 'apex', selected_tool_names: ['reminders'], tool_profile_id: 'focused' })
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
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
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

  it('views an archived conversation without restoring it', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const archivedId = '00000000-0000-4000-8000-000000000031'
    const archivedSummary = { ...summary, id: archivedId, title: 'Archived HUD', archived_at: '2026-08-17T12:00:00Z' }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([archivedSummary])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([])
      if (url.endsWith(`/api/v1/cortex/conversations/${archivedId}`) && init?.method === 'PATCH') throw new Error('Archived view must not restore the conversation.')
      if (url.endsWith(`/api/v1/cortex/conversations/${archivedId}`)) return response({ ...archivedSummary, active_leaf_message_id: null, messages: [] })
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )
    await user.click(await screen.findByRole('button', { name: 'Archived' }))
    await user.click(await screen.findByRole('button', { name: 'Archived HUD' }))
    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalled()
  })

  it('locks message mutation controls while an APEX turn is running', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const userId = '00000000-0000-4000-8000-000000000050'
    const agentId = '00000000-0000-4000-8000-000000000051'
    let resolveTurn: (value: Response) => void = () => undefined
    const turnResponse = new Promise<Response>((resolve) => { resolveTurn = resolve })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: agentId, messages: [
        { id: userId, parent_message_id: null, role: 'user', content: 'Existing prompt', status: 'completed', created_at: '2026-08-17T12:00:00Z', response_metadata: null },
        { id: agentId, parent_message_id: userId, role: 'agent', content: 'Existing answer', status: 'completed', created_at: '2026-08-17T12:00:01Z', response_metadata: {} },
      ] })
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/runs`) && init?.method === 'POST') return response(mockRunRecord(), 202)
      if (url.includes('/events')) return turnResponse
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(<ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}><ApexAssistantThread /></ApexAssistantRuntime>)
    await waitFor(() => expect(screen.getByText('Existing prompt')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'New request')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Edit' }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true))
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled()
    resolveTurn(sseResponse([
      { sequence: 1, type: 'response.delta', payload: { text: 'Completed.' } },
      { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
    ]))
    await waitFor(() => expect(screen.getByText('Completed.')).toBeInTheDocument())
  })

  it('treats a persisted pending turn as globally running after reload', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const userId = '00000000-0000-4000-8000-000000000060'
    const agentId = '00000000-0000-4000-8000-000000000061'
    const onRunningChange = vi.fn()
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: agentId, messages: [
        { id: userId, parent_message_id: null, role: 'user', content: 'Persisted prompt', status: 'completed', created_at: '2026-08-17T12:00:00Z', response_metadata: null },
        { id: agentId, parent_message_id: userId, role: 'agent', content: '', status: 'pending', created_at: '2026-08-17T12:00:01Z', response_metadata: null },
      ] })
      throw new Error(`Unexpected request: ${url}`)
    })
    render(<ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }} onRunningChange={onRunningChange}><ApexAssistantThread /></ApexAssistantRuntime>)
    await waitFor(() => expect(screen.getByText('Agent working')).toBeInTheDocument())
    expect(onRunningChange).toHaveBeenCalledWith(true, 'apex')
    expect(screen.getByPlaceholderText('Ask APEX…')).toBeDisabled()
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
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }} beforeRun={async () => false}>
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
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
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

  it('switches between past conversations and applies active styling to the selected rail item', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const conv1Id = '00000000-0000-4000-8000-000000000001'
    const conv2Id = '00000000-0000-4000-8000-000000000002'
    const conv1 = { ...summary, id: conv1Id, title: 'First Conversation' }
    const conv2 = { ...summary, id: conv2Id, title: 'Second Conversation' }
    const user1Id = '00000000-0000-4000-8000-000000000071'
    const agent1Id = '00000000-0000-4000-8000-000000000072'
    const user2Id = '00000000-0000-4000-8000-000000000081'
    const agent2Id = '00000000-0000-4000-8000-000000000082'

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([conv1, conv2])
      if (url.endsWith(`/api/v1/cortex/conversations/${conv1Id}`)) {
        return response({
          ...conv1,
          active_leaf_message_id: agent1Id,
          messages: [
            { id: user1Id, parent_message_id: null, role: 'user', content: 'Turn 1 in First', status: 'completed', created_at: '2026-08-17T12:00:00Z', response_metadata: null },
            { id: agent1Id, parent_message_id: user1Id, role: 'agent', content: 'Answer 1 in First', status: 'completed', created_at: '2026-08-17T12:00:01Z', response_metadata: {} },
          ],
        })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${conv2Id}`)) {
        return response({
          ...conv2,
          active_leaf_message_id: agent2Id,
          messages: [
            { id: user2Id, parent_message_id: null, role: 'user', content: 'Turn 1 in Second', status: 'completed', created_at: '2026-08-17T12:00:00Z', response_metadata: null },
            { id: agent2Id, parent_message_id: user2Id, role: 'agent', content: 'Answer 1 in Second', status: 'completed', created_at: '2026-08-17T12:00:01Z', response_metadata: {} },
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByRole('button', { name: 'First Conversation' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Second Conversation' })).toBeInTheDocument()

    // Click second conversation
    await user.click(screen.getByRole('button', { name: 'Second Conversation' }))
    await waitFor(() => expect(screen.getByText('Turn 1 in Second')).toBeInTheDocument())
    expect(screen.getByText('Answer 1 in Second')).toBeInTheDocument()

    // Check active styling on the item container
    const secondButton = screen.getByRole('button', { name: 'Second Conversation' })
    const secondItemRoot = secondButton.closest('[data-active]')
    expect(secondItemRoot).toHaveAttribute('data-active', 'true')
  })

  it('auto-titles new conversations derived from prompt text on creation', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const createdId = '00000000-0000-4000-8000-000000000099'
    let sentTitle: string | undefined

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { title?: string }
        sentTitle = body.title
        return response({ ...summary, id: createdId, title: body.title ?? 'New conversation' })
      }
      if (url.endsWith('/api/v1/cortex/conversations')) return response([])
      if (url.endsWith(`/api/v1/cortex/conversations/${createdId}/runs`)) return response(mockRunRecord({ conversation_id: createdId }), 202)
      if (url.includes('/events')) return sseResponse([
        { sequence: 1, type: 'response.delta', payload: { text: 'Title tested.' } },
        { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
      ])
      throw new Error(`Unexpected request: ${url}`)
    })

    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'What is the system diagnostics status?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(sentTitle).toBe('What is the system diagnostics status?'))
  })

  it('preserves conversation messages when active_leaf_message_id is null on load', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const convId = '00000000-0000-4000-8000-000000000088'
    const userMsgId = '00000000-0000-4000-8000-000000000081'
    const agentMsgId = '00000000-0000-4000-8000-000000000082'

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) {
        return response([{ ...summary, id: convId, title: 'Preserved Conversation', active_leaf_message_id: null }])
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${convId}`)) {
        return response({
          ...summary,
          id: convId,
          title: 'Preserved Conversation',
          active_leaf_message_id: null,
          messages: [
            { id: userMsgId, parent_message_id: null, role: 'user', content: 'What was the diagnostic result?', status: 'completed', agent: null, created_at: '2026-08-18T12:00:00Z', updated_at: '2026-08-18T12:00:00Z' },
            { id: agentMsgId, parent_message_id: userMsgId, role: 'agent', content: 'All checks normal.', status: 'completed', agent: 'apex', created_at: '2026-08-18T12:00:01Z', updated_at: '2026-08-18T12:00:01Z' },
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('What was the diagnostic result?')).toBeInTheDocument())
    expect(screen.getByText('All checks normal.')).toBeInTheDocument()
  })

  it('switches back to a conversation and sends follow-up turn with correct parent ID', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const conv1 = '00000000-0000-4000-8000-000000000011'
    const conv2 = '00000000-0000-4000-8000-000000000022'
    const msg1User = '00000000-0000-4000-8000-00000000001a'
    const msg1Agent = '00000000-0000-4000-8000-00000000001b'
    let sentParentId: string | undefined

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) {
        return response([
          { ...summary, id: conv1, title: 'Chat Alpha', active_leaf_message_id: msg1Agent },
          { ...summary, id: conv2, title: 'Chat Beta', active_leaf_message_id: null },
        ])
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${conv1}`)) {
        return response({
          ...summary,
          id: conv1,
          title: 'Chat Alpha',
          active_leaf_message_id: msg1Agent,
          messages: [
            { id: msg1User, parent_message_id: null, role: 'user', content: 'Turn 1 in Alpha', status: 'completed', agent: null, created_at: '2026-08-18T12:00:00Z', updated_at: '2026-08-18T12:00:00Z' },
            { id: msg1Agent, parent_message_id: msg1User, role: 'agent', content: 'Reply 1 in Alpha', status: 'completed', agent: 'apex', created_at: '2026-08-18T12:00:01Z', updated_at: '2026-08-18T12:00:01Z' },
          ],
        })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${conv2}`)) {
        return response({
          ...summary,
          id: conv2,
          title: 'Chat Beta',
          active_leaf_message_id: null,
          messages: [],
        })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${conv1}/runs`) && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { parent_message_id?: string }
        sentParentId = body.parent_message_id
        return response(mockRunRecord({ conversation_id: conv1 }), 202)
      }
      if (url.includes('/events')) {
        return sseResponse([
          { sequence: 1, type: 'response.delta', payload: { text: 'Follow up in Alpha complete.' } },
          { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
        ])
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('Turn 1 in Alpha')).toBeInTheDocument())

    // Switch to Chat Beta
    await user.click(screen.getByRole('button', { name: 'Chat Beta' }))
    await waitFor(() => expect(screen.queryByText('Turn 1 in Alpha')).not.toBeInTheDocument())

    // Switch back to Chat Alpha
    await user.click(screen.getByRole('button', { name: 'Chat Alpha' }))
    await waitFor(() => expect(screen.getByText('Turn 1 in Alpha')).toBeInTheDocument())

    // Send follow-up turn in Chat Alpha
    await user.type(screen.getByPlaceholderText('Ask APEX…'), 'Follow up question')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(sentParentId).toBe(msg1Agent))
  })

  it('topologically sorts messages so child messages appearing first do not fail history load', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const convId = '00000000-0000-4000-8000-000000000077'
    const userMsgId = '00000000-0000-4000-8000-00000000007b'
    const agentMsgId = '00000000-0000-4000-8000-00000000007a' // Lexicographically before userMsgId

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) {
        return response([{ ...summary, id: convId, title: 'Inverted Message Order Conversation', active_leaf_message_id: agentMsgId }])
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${convId}`)) {
        return response({
          ...summary,
          id: convId,
          title: 'Inverted Message Order Conversation',
          active_leaf_message_id: agentMsgId,
          // Intentionally return child agent message BEFORE parent user message to test topological sort
          messages: [
            { id: agentMsgId, parent_message_id: userMsgId, role: 'agent', content: 'Agent reply arrived.', status: 'completed', agent: 'apex', created_at: '2026-08-18T12:00:00Z', updated_at: '2026-08-18T12:00:00Z' },
            { id: userMsgId, parent_message_id: null, role: 'user', content: 'User prompt arrived.', status: 'completed', agent: null, created_at: '2026-08-18T12:00:00Z', updated_at: '2026-08-18T12:00:00Z' },
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('User prompt arrived.')).toBeInTheDocument())
    expect(screen.getByText('Agent reply arrived.')).toBeInTheDocument()
  })

  it('renders transient New conversation draft item in the rail when on a new thread', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const convId = '00000000-0000-4000-8000-000000000066'

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) {
        return response([{ ...summary, id: convId, title: 'Existing Chat', active_leaf_message_id: null }])
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${convId}`)) {
        return response({ ...summary, id: convId, title: 'Existing Chat', active_leaf_message_id: null, messages: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const user = userEvent.setup()
    render(
      <ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
        <ApexConversationRail className="block" />
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByRole('button', { name: 'Existing Chat' })).toBeInTheDocument())

    // Click New conversation button
    await user.click(screen.getByRole('button', { name: 'New conversation' }))

    // Verify transient draft item is rendered at top of rail with active state
    await waitFor(() => {
      const draftItem = screen.getByText('New conversation', { selector: 'span' })
      expect(draftItem).toBeInTheDocument()
      expect(draftItem.closest('[data-active]')).toHaveAttribute('data-active', 'true')
    })
  })

  it('creates a new conversation with overrides when submitPrompt uses startNewThread', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const existingId = '00000000-0000-4000-8000-000000000070'
    const newConvId = '00000000-0000-4000-8000-000000000071'
    const runtimeRef: { current: ApexAssistantRuntimeHandle | null } = { current: null }
    let conversationCreatePayload: Record<string, unknown> | null = null
    let turnPayload: Record<string, unknown> | null = null

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations') && init?.method === 'POST') {
        conversationCreatePayload = JSON.parse(String(init.body))
        return response({
          ...summary,
          id: newConvId,
          agent: conversationCreatePayload?.agent,
          title: 'Home prompt',
          active_leaf_message_id: null,
        })
      }
      if (url.endsWith('/api/v1/cortex/conversations')) {
        return response([{ ...summary, id: existingId, title: 'Existing Chat', active_leaf_message_id: null }])
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${existingId}`)) {
        return response({ ...summary, id: existingId, title: 'Existing Chat', active_leaf_message_id: null, messages: [] })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${newConvId}/runs`) && init?.method === 'POST') {
        turnPayload = JSON.parse(String(init.body))
        return response(mockRunRecord({ conversation_id: newConvId }), 202)
      }
      if (url.includes('/events')) {
        return sseResponse([
          { sequence: 1, type: 'response.delta', payload: { text: 'Local model answer.' } },
          { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
        ])
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
        runtimeRef={runtimeRef}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('APEX is ready. Start a session with a focused question.')).toBeInTheDocument())

    const accepted = await runtimeRef.current?.submitPrompt('Home prompt', {
      agent: 'apex',
      modelId: 'gemma-4-E2B-Q4_K_M.gguf',
      contextWindow: 16384,
      localReasoningMode: 'none',
      selectedToolNames: ['reminders'],
      toolProfileId: null,
    }, { startNewThread: true })

    expect(accepted).toBe(true)
    await waitFor(() => expect(conversationCreatePayload).not.toBeNull())
    expect(conversationCreatePayload).toMatchObject({
      agent: 'apex',
      selected_tool_names: ['reminders'],
    })
    await waitFor(() => expect(turnPayload).not.toBeNull())
    expect(turnPayload).toMatchObject({
      prompt: 'Home prompt',
      agent: 'apex',
      model_id: 'gemma-4-E2B-Q4_K_M.gguf',
      context_window: 16384,
      local_reasoning_mode: 'none',
    })
  })

  it('renders the reactive Apex logo in the thread empty state and after message completion', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({ ...summary, active_leaf_message_id: null, messages: [] })
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}/runs`)) {
        return response(mockRunRecord({ conversation_id: conversationId, id: 'run-logo' }))
      }
      if (url.includes('/events')) {
        return sseResponse([
          { sequence: 1, type: 'response.delta', payload: { text: 'Response with logo below.' } },
          { sequence: 2, type: 'run.completed', payload: { status: 'completed' } },
        ])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()

    const { container } = render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
      >
        <ApexAssistantThread logoProps={{ step: 1, status: 'idle' }} />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('Reminders')).toBeInTheDocument())
    expect(container.querySelector('[data-slot="cortex-chat-logo"]')).toBeInTheDocument()

    await user.click(screen.getByText('Reminders'))
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByText('Response with logo below.')).toBeInTheDocument())
    expect(container.querySelector('[data-slot="cortex-chat-logo"]')).toBeInTheDocument()
  })

  it('streams live text deltas and handles response.reset before completing', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const streamConvId = 'conv-stream'
    const streamSummary = { ...summary, id: streamConvId, title: 'Stream test' }
    let runStarted = false
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([streamSummary])
      if (url.endsWith(`/api/v1/cortex/conversations/${streamConvId}`)) {
        return response({
          ...streamSummary,
          active_leaf_message_id: runStarted ? 'msg-stream-agent' : null,
          messages: runStarted
            ? [
                {
                  id: 'msg-stream-user',
                  parent_message_id: null,
                  role: 'user',
                  content: 'List my pending reminders.',
                  status: 'completed',
                  created_at: new Date().toISOString(),
                },
                {
                  id: 'msg-stream-agent',
                  parent_message_id: 'msg-stream-user',
                  role: 'agent',
                  content: 'Final text after reset.',
                  status: 'completed',
                  created_at: new Date().toISOString(),
                  response_metadata: {},
                },
              ]
            : [],
        })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${streamConvId}/runs`)) {
        runStarted = true
        return response(mockRunRecord({ conversation_id: streamConvId, id: 'run-stream' }))
      }
      if (url.includes('/runs/run-stream/events')) {
        return sseResponse([
          { sequence: 1, type: 'response.delta', payload: { text: 'Drafting...' } },
          { sequence: 2, type: 'response.reset', payload: {} },
          { sequence: 3, type: 'response.delta', payload: { text: 'Final text after reset.' } },
          { sequence: 4, type: 'run.completed', payload: { status: 'completed' } },
        ])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()

    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('Reminders')).toBeInTheDocument())
    await user.click(screen.getByText('Reminders'))
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByText('Final text after reset.')).toBeInTheDocument())
  })

  it('cancels active run on explicit stop', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const cancelConvId = 'conv-cancel'
    const cancelSummary = { ...summary, id: cancelConvId, title: 'Cancel test' }
    let cancelCalled = false
    let resolveStream: () => void = () => {}

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([cancelSummary])
      if (url.endsWith(`/api/v1/cortex/conversations/${cancelConvId}`)) {
        return response({ ...cancelSummary, active_leaf_message_id: null, messages: [] })
      }
      if (url.endsWith(`/api/v1/cortex/conversations/${cancelConvId}/runs`)) {
        return response(mockRunRecord({ conversation_id: cancelConvId, id: 'run-to-cancel' }))
      }
      if (url.endsWith('/api/v1/cortex/runs/run-to-cancel/cancel') && init?.method === 'POST') {
        cancelCalled = true
        resolveStream()
        return response({ status: 'cancelling' })
      }
      if (url.includes('/runs/run-to-cancel/events')) {
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(new TextEncoder().encode('event: response.delta\ndata: {"text":"Generating..."}\n\n'))
            // Keep stream open until cancelled
            resolveStream = () => {
              controller.enqueue(new TextEncoder().encode('event: run.completed\ndata: {"status":"interrupted"}\n\n'))
              controller.close()
            }
          },
        })
        return new Response(stream, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()

    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
      >
        <ApexAssistantThread />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByText('Reminders')).toBeInTheDocument())
    await user.click(screen.getByText('Reminders'))
    await user.click(screen.getByRole('button', { name: 'Send' }))

    const stopButton = await screen.findByRole('button', { name: /stop/i })
    await user.click(stopButton)

    await waitFor(() => expect(cancelCalled).toBe(true))
  })

  it('renders tool selector at left of input and icon button for send in Cortex', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const convId = 'conv-composer-icons'
    const convSummary = { ...summary, id: convId, title: 'Composer icon test' }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([convSummary])
      if (url.endsWith(`/api/v1/cortex/conversations/${convId}`)) {
        return response({ ...convSummary, active_leaf_message_id: null, messages: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const toolCatalog = {
      agent: 'apex' as const,
      groups: [],
      tools: [],
      profiles: [],
      default_profile_id: 'no_tools',
      default_profile_name: 'No APEX Tools',
      default_selected_tool_names: [],
      provider_hosted_tools: [],
      context_window: null,
      reserved_response_tokens: null,
    }

    render(
      <ApexAssistantRuntime
        config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}
      >
        <ApexAssistantThread
          composer={{
            activeAgent: 'apex',
            activeAgentName: 'Apex',
            tools: {
              catalog: toolCatalog,
              selectedToolNames: [],
              activeToolProfileId: null,
              onSelectionChange: vi.fn(),
              onProfileChange: vi.fn(),
            },
          }}
        />
      </ApexAssistantRuntime>,
    )

    await waitFor(() => expect(screen.getByPlaceholderText('Ask APEX…')).toBeInTheDocument())
    const toolsButton = screen.getByRole('button', { name: /Tools:/ })
    const input = screen.getByPlaceholderText('Ask APEX…')
    const sendButton = screen.getByRole('button', { name: 'Send' })

    expect(toolsButton.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(sendButton.textContent).toBe('')
  })
})
