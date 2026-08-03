import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarketTickerCard } from './MarketTickerCard'

describe('MarketTickerCard', () => {
  it('renders an explicit disabled state', () => {
    render(<MarketTickerCard data={null} enabled={false} />)

    expect(screen.getByText('MARKET MONITOR DISABLED')).toBeVisible()
    expect(
      screen.getByText('Market connector disabled in Runtime Settings.'),
    ).toBeVisible()
  })

  it('lists both required values when market configuration is incomplete', () => {
    render(
      <MarketTickerCard
        enabled
        data={{
          status: 'not_configured',
          cooldown_active: false,
          cooldown_remaining_seconds: 0,
          tickers: [],
        }}
      />,
    )

    expect(screen.getByText('MARKET MONITOR OFFLINE')).toBeVisible()
    expect(
      screen.getByText(
        'Define ALPHA_VANTAGE_API_KEY and MARKET_SYMBOLS in `.env` to initialize market telemetry.',
      ),
    ).toBeVisible()
  })
})
