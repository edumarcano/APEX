import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CortexActions } from './CortexActions'

const destructiveAction = {
  action_id: 'delete-1',
  proposal: {
    agent_key: 'panthera', capability_name: 'delete_microsoft_todo_task',
    arguments: { list_id: 'list-1', task_id: 'task-1' }, target: 'Delete Microsoft To Do Task',
    risk: 'destructive' as const, summary: 'Approve Delete Microsoft To Do Task',
    proposed_at: '2026-08-13T12:00:00Z', expires_at: '2026-08-14T12:00:00Z', proposal_hash: 'a'.repeat(64),
  },
  status: 'proposed' as const, version: 0, updated_at: '2026-08-13T12:00:00Z',
}

function actionState(overrides: Record<string, unknown> = {}) {
  return {
    actions: [destructiveAction], pendingCount: 1, isLoading: false, error: null,
    selectedActionId: 'delete-1', detail: { ...destructiveAction, events: [{ action_id: 'delete-1', sequence: 0, from_status: null, to_status: 'proposed' as const, occurred_at: '2026-08-13T12:00:00Z', actor: 'agent', result_code: 'proposal_created', evidence: {} }] },
    isDetailLoading: false, mutation: null, setSelectedActionId: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), resolve: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('CortexActions', () => {
  it('requires a second confirmation before destructive approval', async () => {
    const user = userEvent.setup()
    const actions = actionState()
    render(<CortexActions actions={actions} demoModeActive={false} />)

    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(actions.resolve).not.toHaveBeenCalled()
    expect(screen.getByText(/Confirm this destructive action/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Confirm approve' }))
    expect(actions.resolve).toHaveBeenCalledWith('approve')
  })

  it('keeps demo mode read-only without rendering action controls', () => {
    render(<CortexActions actions={actionState()} demoModeActive />)
    expect(screen.getByText(/Actions are unavailable in demo mode/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })
})
