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
})
