import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarketTickerCard } from './MarketTickerCard'

const ticker = { symbol: 'SPY', status: 'healthy' as const, freshness: 'live' as const, reason_code: 'ok', observed_at: null, close_date: '2026-09-08', last_successful_fetch_date: '2026-09-09', last_attempt_date: '2026-09-09', next_attempt_date: null, price: 500, change: 1, change_percent: 0.2, history: [{ date: '2026-09-05', open: 499, high: 501, low: 498, close: 499, volume: 10 }, { date: '2026-09-08', open: 500, high: 502, low: 499, close: 500, volume: 12 }], period_return_percent: 0.2, period_low: 498, period_high: 502, volume_ratio: 1.2 }

describe('MarketTickerCard', () => {
  it('renders disabled and unconfigured states', () => {
    const { rerender } = render(<MarketTickerCard data={null} enabled={false} />)
    expect(screen.getByText('Market connector disabled in Runtime Settings.')).toBeVisible()
    rerender(<MarketTickerCard enabled data={{ status: 'unavailable', freshness: 'none', reason_code: 'not_configured', observed_at: null, collection_revision: 0, tickers: [] }} />)
    expect(screen.getByText('Add ticker symbols in Runtime Settings and define `ALPHA_VANTAGE_API_KEY` in `.env`.')).toBeVisible()
  })

  it('shows loading instead of unavailable while telemetry is collecting', () => {
    const { rerender } = render(<MarketTickerCard data={null} enabled isLoading />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading market telemetry…')
    expect(screen.queryByText('Market telemetry is unavailable. Refresh telemetry to retry.')).not.toBeInTheDocument()
    rerender(<MarketTickerCard data={null} enabled isLoading={false} />)
    expect(screen.getByText('Market telemetry is unavailable. Refresh telemetry to retry.')).toBeVisible()
  })

  it('renders all eight cells and accessible daily-close detail', () => {
    const data = { status: 'healthy' as const, freshness: 'live' as const, reason_code: 'ok', observed_at: null, collection_revision: 1, tickers: Array.from({ length: 8 }, (_, index) => ({ ...ticker, symbol: `S${index}` })) }
    render(<MarketTickerCard data={data} enabled />)
    expect(screen.getAllByRole('button')).toHaveLength(8)
    fireEvent.focus(screen.getByRole('button', { name: /S0/i }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Period return')
    expect(screen.getByRole('tooltip')).toHaveTextContent('Close date')
  })

  it('shows sanitized failure and retry details for an unavailable symbol', () => {
    const failed = { ...ticker, symbol: 'SPCX', status: 'unavailable' as const, freshness: 'none' as const, reason_code: 'daily_rate_limit', price: null, history: [], next_attempt_date: '2026-09-11' }
    render(<MarketTickerCard data={{ status: 'degraded', freshness: 'fresh_cache', reason_code: 'daily_rate_limit', observed_at: null, collection_revision: 2, tickers: [ticker, failed] }} enabled />)
    fireEvent.focus(screen.getByRole('button', { name: /SPCX/i }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('daily rate limit')
    expect(screen.getByRole('tooltip')).toHaveTextContent('2026-09-11')
  })

  it.each([
    [5, 'sm:grid-cols-6', 'sm:col-span-3'],
    [7, 'sm:grid-cols-12', 'sm:col-span-4'],
  ])('fills the grid for %i symbols', (count, gridClass, finalRowClass) => {
    const data = { status: 'healthy' as const, freshness: 'live' as const, reason_code: 'ok', observed_at: null, collection_revision: 1, tickers: Array.from({ length: count }, (_, index) => ({ ...ticker, symbol: `S${index}` })) }
    render(<MarketTickerCard data={data} enabled />)
    expect(screen.getByTestId('market-ticker-grid')).toHaveClass(gridClass)
    const cells = screen.getAllByRole('button')
    expect(cells).toHaveLength(count)
    expect(cells[0]).toHaveClass('overflow-hidden', 'py-1')
    expect(cells[0].querySelector('svg')).toHaveClass('h-3.5')
    expect(cells[cells.length - 1]).toHaveClass('col-span-2', finalRowClass)
  })
})
