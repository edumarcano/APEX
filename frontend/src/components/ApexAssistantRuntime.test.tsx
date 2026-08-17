import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApexAssistantRuntime, ApexAssistantThread } from './ApexAssistantRuntime'

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
})
