import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useActions } from './useActions'

const ACTION = {
  action_id: 'action-1',
  proposal: {
    agent_key: 'panthera', capability_name: 'create_microsoft_todo_task',
    arguments: { list_id: 'list-1', title: 'Plan branch six' }, target: 'Create Microsoft To Do Task',
    risk: 'write', summary: 'Approve Create Microsoft To Do Task',
    proposed_at: '2026-08-13T12:00:00Z', expires_at: '2026-08-14T12:00:00Z', proposal_hash: 'a'.repeat(64),
  },
  status: 'proposed', version: 0, updated_at: '2026-08-13T12:00:00Z',
}

const DETAIL = { ...ACTION, events: [{ action_id: 'action-1', sequence: 0, from_status: null, to_status: 'proposed', occurred_at: '2026-08-13T12:00:00Z', actor: 'agent', result_code: 'proposal_created', evidence: {} }] }

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

describe('useActions', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not access action APIs while disabled', () => {
    renderHook(() => useActions(false))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('loads bounded records and sends the current version for resolution', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([ACTION]))
      .mockResolvedValueOnce(response([ACTION]))
      .mockResolvedValueOnce(response(DETAIL))
      .mockResolvedValueOnce(response({ ...ACTION, status: 'verified', version: 3 }))
      .mockResolvedValueOnce(response([{ ...ACTION, status: 'verified', version: 3 }]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response({ ...DETAIL, status: 'verified', version: 3 }))

    const { result } = renderHook(() => useActions(true))
    await act(async () => { await Promise.resolve() })

    expect(fetch).toHaveBeenNthCalledWith(1, expect.stringContaining('/api/v1/actions?limit=50'), expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(2, expect.stringContaining('status=proposed&limit=50'), expect.any(Object))
    expect(result.current.pendingCount).toBe(1)

    act(() => result.current.setSelectedActionId('action-1'))
    await act(async () => { await Promise.resolve() })
    expect(result.current.detail?.action_id).toBe('action-1')

    await act(async () => { await result.current.resolve('approve') })
    expect(fetch).toHaveBeenNthCalledWith(4, expect.stringContaining('/action-1/approve'), expect.objectContaining({
      method: 'POST', body: JSON.stringify({ expected_version: 0 }),
    }))
    expect(result.current.detail?.status).toBe('verified')
  })

  it('keeps stale-version feedback visible after refreshing authority', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([ACTION]))
      .mockResolvedValueOnce(response([ACTION]))
      .mockResolvedValueOnce(response(DETAIL))
      .mockResolvedValueOnce(response({ detail: 'Action version conflict.' }, 409))
      .mockResolvedValueOnce(response([{ ...ACTION, version: 1 }]))
      .mockResolvedValueOnce(response([{ ...ACTION, version: 1 }]))
      .mockResolvedValueOnce(response({ ...DETAIL, version: 1 }))

    const { result } = renderHook(() => useActions(true))
    await act(async () => { await Promise.resolve() })
    act(() => result.current.setSelectedActionId('action-1'))
    await act(async () => { await Promise.resolve() })

    await act(async () => { await result.current.resolve('approve') })

    expect(result.current.detail?.version).toBe(1)
    expect(result.current.error).toBe('This action changed. Its latest state is shown.')
  })
})
