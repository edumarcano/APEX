import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMarketData } from './useMarketData'

const LIVE_RESPONSE = {
  status: 'live',
  cooldown_active: false,
  cooldown_remaining_seconds: 0,
  tickers: [
    {
      symbol: 'SPY',
      price: 500,
      change: 1,
      change_percent: 0.2,
      status: 'live',
      last_updated: null,
      sparkline: [499, 500],
    },
  ],
}

function response(body: unknown = LIVE_RESPONSE, ok = true): Response {
  return { ok, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

describe('useMarketData', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response()))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not fetch while disabled', () => {
    const { result } = renderHook(() => useMarketData(false))

    expect(fetch).not.toHaveBeenCalled()
    expect(result.current).toEqual({ data: null, isLoading: false })
  })

  it('fetches immediately, polls, stops, and fetches again when re-enabled', async () => {
    const { rerender } = renderHook(({ enabled }) => useMarketData(enabled), {
      initialProps: { enabled: false },
    })

    rerender({ enabled: true })
    await act(async () => {
      await Promise.resolve()
    })
    expect(fetch).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(fetch).toHaveBeenCalledTimes(2)

    rerender({ enabled: false })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(fetch).toHaveBeenCalledTimes(2)

    rerender({ enabled: true })
    await act(async () => {
      await Promise.resolve()
    })
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('downgrades retained live data when a later poll fails', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(response({}, false))
    const { result } = renderHook(() => useMarketData(true))

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.data?.status).toBe('live')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    expect(result.current.data?.status).toBe('stale')
    expect(result.current.data?.tickers[0]?.status).toBe('stale')
  })
})
