import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { usePreflight } from './usePreflight'

function response(body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('usePreflight', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('blocks a second operation while the first preflight request is in flight', async () => {
    let resolveFetch!: (value: Response) => void
    const pendingFetch = new Promise<Response>((resolve) => {
      resolveFetch = resolve
    })
    const fetchMock = vi.fn(() => pendingFetch)
    vi.stubGlobal('fetch', fetchMock)

    const hook = renderHook(() => usePreflight())
    let firstOperation!: Promise<'proceed' | 'blocked' | 'cancelled'>
    act(() => {
      firstOperation = hook.result.current.requestOperation('cortex_query')
    })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    await act(async () => {
      await expect(hook.result.current.requestOperation('cortex_query')).resolves.toBe('blocked')
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    resolveFetch(response({ warnings: [], blockers: [], can_proceed: true }))
    await act(async () => {
      await expect(firstOperation).resolves.toBe('proceed')
    })
  })

  it('retains a blocker until the operator cancels the operation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(response({
        warnings: [],
        blockers: [{ code: 'blocked', message: 'Runtime unavailable.' }],
        can_proceed: false,
      }))),
    )

    const hook = renderHook(() => usePreflight())
    let operation!: Promise<'proceed' | 'blocked' | 'cancelled'>
    act(() => {
      operation = hook.result.current.requestOperation('cortex_query')
    })
    await waitFor(() => expect(hook.result.current.dialogOpen).toBe(true))

    act(() => {
      hook.result.current.resolveDialog('cancel')
    })
    await expect(operation).resolves.toBe('cancelled')
  })
})
