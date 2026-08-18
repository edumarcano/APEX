import { describe, expect, it } from 'vitest'

import { filterAndSortActions } from './actionFilters'
import type { ActionRecord } from '../types/actions'

const destructiveAction: ActionRecord = {
  action_id: 'delete-1',
  proposal: {
    agent_key: 'panthera', capability_name: 'delete_microsoft_todo_task',
    arguments: { list_id: 'list-1', task_id: 'task-1' }, target: 'Delete Microsoft To Do Task',
    risk: 'destructive' as const, summary: 'Approve Delete Microsoft To Do Task',
    proposed_at: '2026-08-18T12:00:00Z', expires_at: '2026-08-19T12:00:00Z', proposal_hash: 'a'.repeat(64),
  },
  status: 'proposed' as const, version: 0, updated_at: '2026-08-18T12:00:00Z',
}

const verifiedRecentAction: ActionRecord = {
  action_id: 'create-1',
  proposal: {
    agent_key: 'felis', capability_name: 'create_microsoft_todo_task',
    arguments: { title: 'Recent task' }, target: 'Create Microsoft To Do Task',
    risk: 'write' as const, summary: 'Approve Create Microsoft To Do Task',
    proposed_at: '2026-08-18T10:00:00Z', expires_at: '2026-08-19T10:00:00Z', proposal_hash: 'b'.repeat(64),
  },
  status: 'verified' as const, version: 1, updated_at: '2026-08-18T10:05:00Z',
}

const verifiedOldAction: ActionRecord = {
  action_id: 'old-1',
  proposal: {
    agent_key: 'panthera', capability_name: 'create_microsoft_todo_task',
    arguments: { title: 'Old task' }, target: 'Create Microsoft To Do Task',
    risk: 'write' as const, summary: 'Approve Old Microsoft To Do Task',
    proposed_at: '2026-08-10T12:00:00Z', expires_at: '2026-08-11T12:00:00Z', proposal_hash: 'c'.repeat(64),
  },
  status: 'verified' as const, version: 1, updated_at: '2026-08-10T12:05:00Z',
}

describe('filterAndSortActions', () => {
  const nowMs = Date.parse('2026-08-18T18:00:00Z')

  it('keeps all proposed actions and only resolved actions from the last 24 hours', () => {
    const list = [verifiedOldAction, destructiveAction, verifiedRecentAction]
    const result = filterAndSortActions(list, nowMs)

    expect(result.map((a) => a.action_id)).toEqual(['delete-1', 'create-1'])
    expect(result.find((a) => a.action_id === 'old-1')).toBeUndefined()
  })

  it('orders proposed actions first, followed by recent resolved actions (both newest-first)', () => {
    const olderProposed: ActionRecord = {
      ...destructiveAction,
      action_id: 'proposed-older',
      updated_at: '2026-08-18T08:00:00Z',
    }
    const newerProposed: ActionRecord = {
      ...destructiveAction,
      action_id: 'proposed-newer',
      updated_at: '2026-08-18T15:00:00Z',
    }
    const list = [verifiedRecentAction, olderProposed, newerProposed]
    const result = filterAndSortActions(list, nowMs)

    expect(result.map((a) => a.action_id)).toEqual(['proposed-newer', 'proposed-older', 'create-1'])
  })
})
