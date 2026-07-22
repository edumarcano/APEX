import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAppActivation } from './useAppActivation'
import { usePreflight } from './usePreflight'
import { useTelemetrySnapshot } from './useTelemetrySnapshot'

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

describe('useAppActivation', () => {
  it('activates and returns to standby', () => {
    const { result } = renderHook(() => useAppActivation())
    expect(result.current.activated).toBe(false)

    act(() => {
      result.current.activate()
    })
    expect(result.current.activated).toBe(true)

    act(() => {
      result.current.deactivate()
    })
    expect(result.current.activated).toBe(false)
  })
})

describe('usePreflight', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
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

  it('passes profile and cloud metadata for assistant preflight', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ warnings: [], blockers: [], can_proceed: true }),
    )
    const { result } = renderHook(() => usePreflight())

    await act(async () => {
      await result.current.requestOperation('assistant_query', {
        synthesis_profile: 'comet',
        involves_cloud: true,
      })
    })

    const body = JSON.parse(String((vi.mocked(fetch).mock.calls[0][1] as RequestInit).body))
    expect(body).toMatchObject({
      operation: 'assistant_query',
      synthesis_profile: 'comet',
      involves_cloud: true,
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
      second = await result.current.requestOperation('activate_with_briefing')
    })
    expect(second).toBe('blocked')
    expect(fetch).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.resolveDialog('cancel')
      await first
    })
  })
})

describe('useTelemetrySnapshot', () => {
  const snapshot = {
    snapshot_id: 'snap-1',
    collected_at: '2026-07-22T12:00:00Z',
    modules: {
      weather: {
        name: 'weather',
        status: 'healthy',
        freshness: 'live',
        reason_code: 'ok',
        observed_at: '2026-07-22T12:00:00Z',
        display_text: 'Current temperature is 72 degrees with clear sky.',
        data: { temp_f: 72 },
      },
    },
    sync_health_score: 100,
    connector_health: [],
    failed_connectors: [],
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('refreshAll stores snapshot', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(snapshot))
    const { result } = renderHook(() => useTelemetrySnapshot())

    await act(async () => {
      await result.current.refreshAll()
    })

    expect(result.current.snapshot?.snapshot_id).toBe('snap-1')
    expect(result.current.isRefreshingAll).toBe(false)
  })

  it('keeps prior snapshot on refresh failure', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(snapshot))
      .mockResolvedValueOnce(jsonResponse({ detail: 'boom' }, false, 500))

    const { result } = renderHook(() => useTelemetrySnapshot())
    await act(async () => {
      await result.current.refreshAll()
    })
    await act(async () => {
      await result.current.refreshAll({ force: true })
    })

    expect(result.current.snapshot?.snapshot_id).toBe('snap-1')
    expect(result.current.error).toMatch(/boom|500/)
  })

  it('maps 409 to refresh-in-progress error', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'busy' }, false, 409))
    const { result } = renderHook(() => useTelemetrySnapshot())
    await act(async () => {
      await result.current.refreshAll()
    })
    expect(result.current.error).toMatch(/already in progress/i)
  })

  it('refreshConnector targets one connector', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(snapshot))
    const { result } = renderHook(() => useTelemetrySnapshot())
    await act(async () => {
      await result.current.refreshConnector('weather')
    })
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({ connectors: ['weather'] })
  })
})
