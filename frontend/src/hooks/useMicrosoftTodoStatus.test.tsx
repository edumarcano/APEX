import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useMicrosoftTodoStatus } from './useMicrosoftTodoStatus'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useMicrosoftTodoStatus', () => {
  it('loads list options once per connected Settings session while status continues to refresh', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ configured: true, state: 'connected', permission: 'Tasks.ReadWrite' }))
      .mockResolvedValueOnce(jsonResponse({ lists: [{ id: 'list-1', display_name: 'Personal' }] }))
      .mockResolvedValueOnce(jsonResponse({ configured: true, state: 'connected', permission: 'Tasks.ReadWrite' }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useMicrosoftTodoStatus(false))

    await act(async () => { await result.current.refresh() })
    await act(async () => { await result.current.refresh() })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(result.current.lists).toEqual([{ id: 'list-1', display_name: 'Personal' }])
  })
})
