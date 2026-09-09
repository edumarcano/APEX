import { useEffect, useRef, useState } from 'react'

import type {
  ConnectorFreshness,
  ConnectorHealthStatus,
  MarketDailyBar,
  MarketResponse,
  MarketTickerItem,
} from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const MARKET_ENDPOINT = API_ENDPOINTS.market
const VALID_STATUSES: readonly ConnectorHealthStatus[] = ['healthy', 'degraded', 'unavailable', 'disabled']
const VALID_FRESHNESS: readonly ConnectorFreshness[] = ['live', 'fresh_cache', 'stale', 'none']

export type MarketDataState = { data: MarketResponse | null; isLoading: boolean }

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function parseBar(value: unknown): MarketDailyBar | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (typeof row.date !== 'string') return null
  const open = numberOrNull(row.open)
  const high = numberOrNull(row.high)
  const low = numberOrNull(row.low)
  const close = numberOrNull(row.close)
  const volume = numberOrNull(row.volume)
  if (open === null || high === null || low === null || close === null || volume === null) return null
  return { date: row.date, open, high, low, close, volume }
}

function parseTicker(value: unknown): MarketTickerItem | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (typeof row.symbol !== 'string' || !VALID_STATUSES.includes(row.status as ConnectorHealthStatus)) return null
  if (!VALID_FRESHNESS.includes(row.freshness as ConnectorFreshness)) return null
  return {
    symbol: row.symbol,
    status: row.status as ConnectorHealthStatus,
    freshness: row.freshness as ConnectorFreshness,
    reason_code: typeof row.reason_code === 'string' ? row.reason_code : '',
    observed_at: typeof row.observed_at === 'string' ? row.observed_at : null,
    close_date: typeof row.close_date === 'string' ? row.close_date : null,
    price: numberOrNull(row.price),
    change: numberOrNull(row.change),
    change_percent: numberOrNull(row.change_percent),
    history: Array.isArray(row.history) ? row.history.map(parseBar).filter((bar): bar is MarketDailyBar => bar !== null) : [],
    period_return_percent: numberOrNull(row.period_return_percent),
    period_low: numberOrNull(row.period_low),
    period_high: numberOrNull(row.period_high),
    volume_ratio: numberOrNull(row.volume_ratio),
  }
}

function parseResponse(body: unknown): MarketResponse | null {
  if (!body || typeof body !== 'object') return null
  const row = body as Record<string, unknown>
  if (!VALID_STATUSES.includes(row.status as ConnectorHealthStatus) || !VALID_FRESHNESS.includes(row.freshness as ConnectorFreshness)) return null
  if (typeof row.collection_revision !== 'number' || !Number.isInteger(row.collection_revision) || row.collection_revision < 0) return null
  return {
    status: row.status as ConnectorHealthStatus,
    freshness: row.freshness as ConnectorFreshness,
    reason_code: typeof row.reason_code === 'string' ? row.reason_code : '',
    observed_at: typeof row.observed_at === 'string' ? row.observed_at : null,
    collection_revision: row.collection_revision,
    tickers: Array.isArray(row.tickers) ? row.tickers.map(parseTicker).filter((ticker): ticker is MarketTickerItem => ticker !== null) : [],
  }
}

function staleFallback(previous: MarketResponse): MarketResponse {
  return {
    ...previous,
    status: previous.status === 'healthy' ? 'degraded' : previous.status,
    freshness: previous.status === 'disabled' ? 'none' : 'stale',
    reason_code: 'display_request_failed',
    tickers: previous.tickers.map((ticker) => ({
      ...ticker,
      status: ticker.status === 'healthy' ? 'degraded' : ticker.status,
      freshness: ticker.status === 'unavailable' ? 'none' : 'stale',
      reason_code: 'display_request_failed',
    })),
  }
}

/** Load cache-backed market display data when telemetry publishes a new revision. */
export function useMarketData(enabled: boolean, collectionRevision: number | null): MarketDataState {
  const [data, setData] = useState<MarketResponse | null>(null)
  const [isLoading, setIsLoading] = useState(enabled)
  const dataRef = useRef<MarketResponse | null>(null)

  useEffect(() => {
    dataRef.current = data
  }, [data])

  useEffect(() => {
    if (!enabled || collectionRevision === null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Disabled and missing telemetry revision are explicit lifecycle resets.
      setData(null)
      setIsLoading(false)
      return
    }
    const controller = new AbortController()
    setIsLoading(true)
    void (async (): Promise<void> => {
      try {
        const response = await fetch(MARKET_ENDPOINT, { signal: controller.signal })
        const parsed = response.ok ? parseResponse(await response.json()) : null
        if (controller.signal.aborted) return
        if (parsed) setData(parsed)
        else if (dataRef.current) setData(staleFallback(dataRef.current))
      } catch {
        if (!controller.signal.aborted && dataRef.current) setData(staleFallback(dataRef.current))
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    })()
    return () => controller.abort()
  }, [enabled, collectionRevision])

  return { data, isLoading }
}
