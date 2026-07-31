import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AssistantToolCards } from './AssistantToolCards'
import MicrosoftTodoSettingsSection from './MicrosoftTodoSettingsSection'

describe('Microsoft To Do settings', () => {
  it('shows a bounded device-code authorization prompt', () => {
    const connect = vi.fn(async () => undefined)
    render(
      <MicrosoftTodoSettingsSection
        sectionId="todo-settings"
        runtime={{
          status: { configured: true, state: 'disconnected', permission: 'Tasks.Read' },
          authorization: null,
          loading: false,
          error: null,
          refresh: vi.fn(async () => undefined),
          connect,
          disconnect: vi.fn(async () => undefined),
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
    expect(connect).toHaveBeenCalledOnce()
    expect(screen.getByText(/APEX reminders remain in the local SQLite ledger/i)).toBeInTheDocument()
  })

  it('renders only sanitized authorization instructions', () => {
    render(
      <MicrosoftTodoSettingsSection
        sectionId="todo-settings"
        runtime={{
          status: { configured: true, state: 'authorizing', permission: 'Tasks.Read' },
          authorization: {
            state: 'authorizing',
            verification_uri: 'https://microsoft.com/devicelogin',
            user_code: 'ABCD-EFGH',
            expires_at: '2026-08-01T00:00:00Z',
          },
          loading: false,
          error: null,
          refresh: vi.fn(async () => undefined),
          connect: vi.fn(async () => undefined),
          disconnect: vi.fn(async () => undefined),
        }}
      />,
    )
    expect(screen.getByText('ABCD-EFGH')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open Microsoft sign-in/i })).toHaveAttribute(
      'href',
      'https://microsoft.com/devicelogin',
    )
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument()
  })
})

describe('Microsoft To Do assistant cards', () => {
  it('renders lists separately from local reminders', () => {
    render(
      <AssistantToolCards
        toolOutputs={[{
          name: 'list_microsoft_todo_lists',
          status: 'success',
          duration_ms: 12,
          output: { lists: [{ id: 'list-1', display_name: 'Personal', is_owner: true, is_shared: false }] },
        }]}
      />,
    )
    expect(screen.getByText('Personal')).toBeInTheDocument()
    expect(screen.getByText(/Microsoft To Do · Read only/i)).toBeInTheDocument()
    expect(screen.queryByText('Active Reminders')).not.toBeInTheDocument()
  })

  it('renders due, high-importance, and completed task state', () => {
    render(
      <AssistantToolCards
        toolOutputs={[{
          name: 'list_microsoft_todo_tasks',
          status: 'success',
          duration_ms: 8,
          output: {
            include_completed: true,
            tasks: [{
              id: 'task-1',
              title: 'Ship release',
              status: 'completed',
              importance: 'high',
              is_completed: true,
              due: { date_time: '2026-08-01T13:00:00', time_zone: 'Eastern Standard Time' },
            }],
          },
        }]}
      />,
    )
    expect(screen.getByText('Ship release')).toHaveClass('line-through')
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })
})
