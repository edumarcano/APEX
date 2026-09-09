import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMarketData } from './useMarketData'

const RESPONSE = {
  status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: null, collection_revision: 1,
  tickers: [{ symbol: 'SPY', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: null, close_date: '2026-09-08', price: 500, change: 1, change_percent: 0.2, history: [{ date: '2026-09-05', open: 499, high: 501, low: 498, close: 499, volume: 10 }, { date: '2026-09-08', open: 500, high: 502, low: 499, close: 500, volume: 12 }], period_return_percent: 0.2, period_low: 498, period_high: 502, volume_ratio: 1.2 }],
}

function response(body: unknown = RESPONSE, ok = true): Response { return { ok, json: vi.fn().mockResolvedValue(body) } as unknown as Response }

describe('useMarketData', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response())))
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('does not fetch before telemetry supplies a collection revision', () => {
    const { result } = renderHook(() => useMarketData(true, null))
    expect(fetch).not.toHaveBeenCalled()
    expect(result.current).toEqual({ data: null, isLoading: false })
  })

  it('loads once for each telemetry collection revision without polling', async () => {
    const { rerender } = renderHook(({ revision }) => useMarketData(true, revision), { initialProps: { revision: 1 } })
    await act(async () => { await Promise.resolve() })
    expect(fetch).toHaveBeenCalledTimes(1)
    rerender({ revision: 1 })
    await act(async () => { await Promise.resolve() })
    expect(fetch).toHaveBeenCalledTimes(1)
    rerender({ revision: 2 })
    await act(async () => { await Promise.resolve() })
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('marks retained data stale when a later cache read fails', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response()).mockResolvedValueOnce(response({}, false))
    const { result, rerender } = renderHook(({ revision }) => useMarketData(true, revision), { initialProps: { revision: 1 } })
    await act(async () => { await Promise.resolve() })
    rerender({ revision: 2 })
    await act(async () => { await Promise.resolve() })
    expect(result.current.data?.status).toBe('degraded')
    expect(result.current.data?.freshness).toBe('stale')
  })
})
