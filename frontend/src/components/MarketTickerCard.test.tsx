import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarketTickerCard } from './MarketTickerCard'

const ticker = { symbol: 'SPY', status: 'healthy' as const, freshness: 'live' as const, reason_code: 'ok', observed_at: null, close_date: '2026-09-08', price: 500, change: 1, change_percent: 0.2, history: [{ date: '2026-09-05', open: 499, high: 501, low: 498, close: 499, volume: 10 }, { date: '2026-09-08', open: 500, high: 502, low: 499, close: 500, volume: 12 }], period_return_percent: 0.2, period_low: 498, period_high: 502, volume_ratio: 1.2 }

describe('MarketTickerCard', () => {
  it('renders disabled and unconfigured states', () => {
    const { rerender } = render(<MarketTickerCard data={null} enabled={false} />)
    expect(screen.getByText('Market connector disabled in Runtime Settings.')).toBeVisible()
    rerender(<MarketTickerCard enabled data={{ status: 'unavailable', freshness: 'none', reason_code: 'not_configured', observed_at: null, collection_revision: 0, tickers: [] }} />)
    expect(screen.getByText('Add ticker symbols in Runtime Settings and define `ALPHA_VANTAGE_API_KEY` in `.env`.')).toBeVisible()
  })

  it('renders all eight cells and accessible daily-close detail', () => {
    const data = { status: 'healthy' as const, freshness: 'live' as const, reason_code: 'ok', observed_at: null, collection_revision: 1, tickers: Array.from({ length: 8 }, (_, index) => ({ ...ticker, symbol: `S${index}` })) }
    render(<MarketTickerCard data={data} enabled />)
    expect(screen.getAllByRole('button')).toHaveLength(8)
    fireEvent.focus(screen.getByRole('button', { name: /S0/i }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Period return')
    expect(screen.getByRole('tooltip')).toHaveTextContent('Close date')
  })
})
