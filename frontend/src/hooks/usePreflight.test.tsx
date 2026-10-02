import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePreflight } from './usePreflight'

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

describe('usePreflight', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('blocks a second operation while the first preflight request is in flight', async () => {
    let resolveFetch!: (value: Response) => void
    const pendingFetch = new Promise<Response>((resolve) => { resolveFetch = resolve })
    const fetchMock = vi.fn(() => pendingFetch)
    vi.stubGlobal('fetch', fetchMock)

    const hook = renderHook(() => usePreflight())
    let firstOperation!: Promise<'proceed' | 'blocked' | 'cancelled'>
    act(() => { firstOperation = hook.result.current.requestOperation('cortex_query') })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    await act(async () => {
      await expect(hook.result.current.requestOperation('cortex_query')).resolves.toBe('blocked')
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    resolveFetch(jsonResponse({ warnings: [], blockers: [], can_proceed: true }))
    await act(async () => { await expect(firstOperation).resolves.toBe('proceed') })
  })

  it('retains a blocker until the operator cancels the operation', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({
      warnings: [], blockers: [{ code: 'blocked', message: 'Runtime unavailable.' }], can_proceed: false,
    }))))

    const hook = renderHook(() => usePreflight())
    let operation!: Promise<'proceed' | 'blocked' | 'cancelled'>
    act(() => { operation = hook.result.current.requestOperation('cortex_query') })
    await waitFor(() => expect(hook.result.current.dialogOpen).toBe(true))
    act(() => { hook.result.current.resolveDialog('cancel') })
    await expect(operation).resolves.toBe('cancelled')
  })

  it('proceeds without dialog when there are no warnings', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ warnings: [], blockers: [], can_proceed: true }),
    )
    const { result } = renderHook(() => usePreflight())

    let resolution: string | undefined
    await act(async () => {
      resolution = await result.current.requestOperation('activate')
    })

    expect(resolution).toBe('proceed')
    expect(result.current.dialogOpen).toBe(false)
  })

  it('opens dialog for warnings and honors continue once vs session', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          warnings: [{ code: 'running_on_battery', message: 'On battery' }],
          blockers: [],
          can_proceed: true,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ warnings: [], blockers: [], can_proceed: true }),
      )

    const { result } = renderHook(() => usePreflight())

    let first: Promise<string>
    act(() => {
      first = result.current.requestOperation('activate')
    })
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.dialogOpen).toBe(true)
    expect(result.current.isChecking).toBe(false)

    await act(async () => {
      result.current.resolveDialog('continue_once')
      await first!
    })

    // Second call without session ack still requests preflight; session set empty
    await act(async () => {
      const second = result.current.requestOperation('activate')
      await Promise.resolve()
      // If warnings returned again they'd open dialog; our mock returns empty
      await second
    })

    const bodies = vi.mocked(fetch).mock.calls.map((call) => {
      const init = call[1] as RequestInit
      return JSON.parse(String(init.body))
    })
    expect(bodies[0].acknowledged_warnings).toEqual([])
    expect(bodies[1].acknowledged_warnings).toEqual([])
  })

  it('stores session acknowledgements after continue for session', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          warnings: [{ code: 'running_on_battery', message: 'On battery' }],
          blockers: [],
          can_proceed: true,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ warnings: [], blockers: [], can_proceed: true }),
      )

    const { result } = renderHook(() => usePreflight())
    let pending!: Promise<string>
    act(() => {
      pending = result.current.requestOperation('activate')
    })
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      result.current.resolveDialog('continue_session')
      await pending
    })

    await act(async () => {
      await result.current.requestOperation('activate')
    })

    const secondBody = JSON.parse(String((vi.mocked(fetch).mock.calls[1][1] as RequestInit).body))
    expect(secondBody.acknowledged_warnings).toContain('running_on_battery')
  })

  it('cancel resolves as cancelled', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        warnings: [{ code: 'running_on_battery', message: 'On battery' }],
        blockers: [],
        can_proceed: true,
      }),
    )
    const { result } = renderHook(() => usePreflight())
    let pending!: Promise<string>
    act(() => {
      pending = result.current.requestOperation('activate')
    })
    await act(async () => {
      await Promise.resolve()
    })
    let resolution = ''
    await act(async () => {
      result.current.resolveDialog('cancel')
      resolution = await pending
    })
    expect(resolution).toBe('cancelled')
  })

  it('passes the selected cloud model for assistant preflight', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ warnings: [], blockers: [], can_proceed: true }),
    )
    const { result } = renderHook(() => usePreflight())

    await act(async () => {
      await result.current.requestOperation('cortex_query', {
        model_id: 'z-ai/glm-5.3-flash',
      })
    })

    const body = JSON.parse(String((vi.mocked(fetch).mock.calls[0][1] as RequestInit).body))
    expect(body).toMatchObject({
      operation: 'cortex_query',
      model_id: 'z-ai/glm-5.3-flash',
    })
  })

  it('blocks a second request while a warning dialog is pending', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        warnings: [{ code: 'running_on_battery', message: 'On battery' }],
        blockers: [],
        can_proceed: true,
      }),
    )
    const { result } = renderHook(() => usePreflight())
    let first!: Promise<string>

    act(() => {
      first = result.current.requestOperation('activate')
    })
    await act(async () => {
      await Promise.resolve()
    })

    let second = ''
    await act(async () => {
      second = await result.current.requestOperation('generate_briefing_session')
    })
    expect(second).toBe('blocked')
    expect(fetch).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.resolveDialog('cancel')
      await first
    })
  })
})
