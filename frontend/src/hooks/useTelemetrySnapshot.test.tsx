import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useTelemetrySnapshot } from './useTelemetrySnapshot'

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

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
    let outcome: Awaited<ReturnType<typeof result.current.refreshAllWithOutcome>> | undefined
    await act(async () => {
      await result.current.refreshAll()
      outcome = await result.current.refreshAllWithOutcome()
    })
    expect(result.current.error).toMatch(/already in progress/i)
    expect(outcome).toMatchObject({ kind: 'conflict', snapshot: null })
  })

  it('returns refresh failures directly instead of relying on queued React state', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'network down' }, false, 503))
    const { result } = renderHook(() => useTelemetrySnapshot())
    let outcome: Awaited<ReturnType<typeof result.current.refreshAllWithOutcome>> | undefined
    await act(async () => {
      outcome = await result.current.refreshAllWithOutcome()
    })
    expect(outcome).toEqual({ kind: 'failure', snapshot: null, error: 'network down' })
  })

  it('reports an aborted refresh as cancellation', async () => {
    vi.mocked(fetch).mockRejectedValue(new DOMException('The operation was aborted', 'AbortError'))
    const { result } = renderHook(() => useTelemetrySnapshot())
    let outcome: Awaited<ReturnType<typeof result.current.refreshAllWithOutcome>> | undefined
    await act(async () => {
      outcome = await result.current.refreshAllWithOutcome()
    })
    expect(outcome).toMatchObject({ kind: 'cancelled', snapshot: null })
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
