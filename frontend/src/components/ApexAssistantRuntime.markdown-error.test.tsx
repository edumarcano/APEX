import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

const markdownImport = vi.hoisted(() => ({ attempts: 0 }))

vi.mock('./AssistantMarkdown', async () => {
  markdownImport.attempts += 1
  if (markdownImport.attempts === 1) throw new Error('Markdown chunk unavailable')
  return {
    default: ({ text }: { text: string }) => <div data-testid="markdown-ready">{text}</div>,
  }
})

import { ApexAssistantRuntime, ApexAssistantThread } from './ApexAssistantRuntime'

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

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.restoreAllMocks())

describe('ApexAssistantRuntime deferred Markdown errors', () => {
  it('keeps plain answer text, history, and draft usable after a chunk rejection, then retries formatting only', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
    const userId = '00000000-0000-4000-8000-000000000040'
    const agentId = '00000000-0000-4000-8000-000000000041'
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([summary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) return response({
        ...summary,
        active_leaf_message_id: agentId,
        messages: [
          { id: userId, parent_message_id: null, role: 'user', content: '**Keep this prompt plain**', status: 'completed', created_at: '2026-09-28T12:00:00Z', response_metadata: null },
          { id: agentId, parent_message_id: userId, role: 'agent', content: '**Saved** <img src="bad" onerror="alert(1)">', status: 'completed', created_at: '2026-09-28T12:00:01Z', response_metadata: { activity_steps: [
            { sequence: 1, timestamp: '2026-09-28T12:00:00Z', type: 'model.started', payload: { turn: 1 } },
          ] } },
        ],
      })
      throw new Error(`Unexpected request: ${url}`)
    })

    render(<ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}><ApexAssistantThread /></ApexAssistantRuntime>)

    expect(await screen.findByRole('button', { name: 'Retry Markdown' })).toBeInTheDocument()
    expect(screen.getByText('**Saved** <img src="bad" onerror="alert(1)">')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('**Keep this prompt plain**')).toBeInTheDocument()

    const user = userEvent.setup()
    const composer = await screen.findByPlaceholderText('Ask Lynx…')
    await user.type(composer, 'Draft after a chunk error')
    await user.click(screen.getByText('Activity'))
    expect(screen.getByText('Thinking')).toBeVisible()
    const requestsBeforeRetry = fetchMock.mock.calls.length

    await user.click(screen.getByRole('button', { name: 'Retry Markdown' }))
    expect(await screen.findByTestId('markdown-ready')).toHaveTextContent('**Saved** <img src="bad" onerror="alert(1)">')
    expect(fetchMock).toHaveBeenCalledTimes(requestsBeforeRetry)
    expect(markdownImport.attempts).toBe(2)
    expect(composer).toHaveValue('Draft after a chunk error')
    expect(screen.getByText('Thinking')).toBeVisible()
  })
})
