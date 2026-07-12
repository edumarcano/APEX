import { useEffect, useRef, useState } from 'react'

import type { MarketResponse, MarketResponseStatus, MarketTickerItem } from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'

const MARKET_ENDPOINT = API_ENDPOINTS.market
const MARKET_POLL_INTERVAL_MS = 30_000

const VALID_MARKET_STATUSES: readonly MarketResponseStatus[] = [
  'live',
  'partial',
  'stale',
  'unavailable',
  'not_configured',
  'provider_unavailable',
]

const VALID_TICKER_STATUSES: readonly MarketTickerItem['status'][] = [
  'live',
  'stale',
  'unavailable',
]

export type MarketDataState = {
  data: MarketResponse | null
  isLoading: boolean
}

function parseNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  return null
}

function parseMarketTickerItem(entry: unknown): MarketTickerItem | null {
  if (!entry || typeof entry !== 'object') {
    return null
  }

  const record = entry as Record<string, unknown>
  const symbol = typeof record.symbol === 'string' ? record.symbol.trim() : ''
  if (!symbol) {
    return null
  }

  const status = record.status
  if (typeof status !== 'string' || !VALID_TICKER_STATUSES.includes(status as MarketTickerItem['status'])) {
    return null
  }

  const sparklineRaw = Array.isArray(record.sparkline) ? record.sparkline : []
  const sparkline = sparklineRaw
    .map((value) => parseNumber(value))
    .filter((value): value is number => value !== null)

  return {
    symbol,
    price: parseNumber(record.price),
    change: parseNumber(record.change),
    change_percent: parseNumber(record.change_percent),
    status: status as MarketTickerItem['status'],
    last_updated: typeof record.last_updated === 'string' ? record.last_updated : null,
    sparkline,
  }
}

function parseMarketResponse(body: unknown): MarketResponse | null {
  if (!body || typeof body !== 'object') {
    return null
  }

  const record = body as Record<string, unknown>
  const status = record.status
  if (typeof status !== 'string' || !VALID_MARKET_STATUSES.includes(status as MarketResponseStatus)) {
    return null
  }

  const tickersRaw = Array.isArray(record.tickers) ? record.tickers : []
  const tickers = tickersRaw
    .map((entry) => parseMarketTickerItem(entry))
    .filter((entry): entry is MarketTickerItem => entry !== null)

  const cooldownRemaining = parseNumber(record.cooldown_remaining_seconds)

  return {
    status: status as MarketResponseStatus,
    cooldown_active: record.cooldown_active === true,
    cooldown_remaining_seconds:
      cooldownRemaining !== null ? Math.max(0, Math.floor(cooldownRemaining)) : 0,
    tickers,
  }
}

function toStaleFallback(previous: MarketResponse): MarketResponse {
  return {
    ...previous,
    status: previous.status === 'live' || previous.status === 'partial' ? 'stale' : previous.status,
    tickers: previous.tickers.map((ticker) => ({
      ...ticker,
      status: ticker.status === 'live' ? 'stale' : ticker.status,
    })),
  }
}

export function useMarketData(enabled: boolean): MarketDataState {
  const [data, setData] = useState<MarketResponse | null>(null)
  const [isLoading, setIsLoading] = useState(enabled)
  const dataRef = useRef<MarketResponse | null>(null)
  // eslint-disable-next-line react-hooks/refs -- Poll fallback needs the latest committed market payload without resubscribing the interval.
  dataRef.current = data

  useEffect(() => {
    if (!enabled) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Disabled is an explicit external lifecycle state.
      setData(null)
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    const pollMarket = async (): Promise<void> => {
      try {
        const response = await fetch(MARKET_ENDPOINT)

        if (cancelled) {
          return
        }

        if (!response.ok) {
          if (dataRef.current) {
            setData(toStaleFallback(dataRef.current))
          }
          return
        }

        let body: unknown = null
        try {
          body = await response.json()
        } catch {
          if (!cancelled) {
            if (dataRef.current) {
              setData(toStaleFallback(dataRef.current))
            }
          }
          return
        }

        const parsed = parseMarketResponse(body)
        if (cancelled || !parsed) {
          if (!cancelled) {
            if (dataRef.current) {
              setData(toStaleFallback(dataRef.current))
            }
          }
          return
        }

        setData(parsed)
      } catch {
        if (!cancelled) {
          if (dataRef.current) {
            setData(toStaleFallback(dataRef.current))
          }
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void pollMarket()

    const intervalId = window.setInterval(() => {
      void pollMarket()
    }, MARKET_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [enabled])

  return { data, isLoading }
}
