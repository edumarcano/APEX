import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_WEATHER_INFO } from '../../lib/weatherTelemetry'
import type { HudIdentityProps } from './HudIdentity'
import type { HudTelemetryData } from './HudTelemetry'
import { OverviewView } from './OverviewView'

afterEach(() => {
  vi.unstubAllGlobals()
})

const identity: HudIdentityProps = {
  logoProps: { status: 'idle' },
  glyphProps: { status: 'idle', isSpeaking: false },
}

const telemetry: HudTelemetryData = {
  hasSnapshot: false,
  isRefreshingAll: false,
  isRefreshingAnyConnector: false,
  onRefreshConnector: vi.fn(),
  attentionTiers: { weather: 'pending', events: 'pending', market: 'pending', email: 'pending', news: 'pending', reminders: 'pending' },
  attentionStagger: { weather: 0, events: 0, market: 0, email: 0, news: 0, reminders: 0 },
  weather: { info: DEFAULT_WEATHER_INFO, body: 'Weather unavailable.', ledState: 'loading', statusMessage: null, showAttribution: false },
  events: {
    f1Text: '',
    ledState: 'loading',
    statusMessage: null,
    compactValue: null,
    calendar: { windowDays: 7, items: [], totalCount: 0 },
    football: { fixtures: [], configuredTeamCount: 0 },
    footballModule: undefined,
    calendarRefreshing: false,
    f1Refreshing: false,
    footballRefreshing: false,
  },
  market: { data: null, isLoading: false, enabled: true },
  email: { state: 'unavailable', ledState: 'loading', statusMessage: null, compactValue: null, count: null, items: [], refreshing: false },
  news: { state: 'unavailable', ledState: 'loading', statusMessage: null, compactValue: null, items: [], refreshing: false },
  reminders: {
    loadState: 'loaded',
    ledState: 'loading',
    statusMessage: null,
    compactValue: '',
    items: [],
    sourceState: null,
    actionError: null,
    refreshDisabled: false,
    onRefresh: vi.fn(),
    onOpenCompleted: vi.fn(),
    onSave: vi.fn(async () => 'synced' as const),
    onMarkRead: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onReview: vi.fn(),
  },
}

function setCompactLayout(compact: boolean): void {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: compact,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })))
}

describe('OverviewView layout', () => {
  it('keeps the desktop identity in its final grid slot while telemetry collection resolves', () => {
    setCompactLayout(false)
    const { rerender } = render(
      <OverviewView identity={identity} telemetry={telemetry} state="collecting" onCollect={vi.fn()} onRefreshAll={vi.fn()} />,
    )

    const layout = screen.getByRole('region', { name: 'Overview' })
    const identityCard = layout.querySelector('[data-slot="overview-identity-card"]')
    expect(layout).toHaveClass('grid-cols-6')
    expect(identityCard).toHaveClass('col-span-2')
    expect(identityCard).not.toHaveClass('col-span-6', 'row-start-2')
    expect(screen.getByRole('heading', { name: 'Reminders' }).closest('section')).toHaveClass('col-span-2')

    rerender(<OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={vi.fn()} onRefreshAll={vi.fn()} />)

    expect(layout.querySelector('[data-slot="overview-identity-card"]')).toHaveClass('col-span-2')
    expect(screen.getByRole('heading', { name: 'Reminders' }).closest('section')).toHaveClass('col-span-2')
    expect(screen.getByRole('heading', { name: 'News Wire' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Market' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Email' })).toBeInTheDocument()
  })

  it('keeps the compact identity first during collection and after telemetry arrives', () => {
    setCompactLayout(true)
    const { rerender } = render(
      <OverviewView identity={identity} telemetry={telemetry} state="collecting" onCollect={vi.fn()} onRefreshAll={vi.fn()} />,
    )

    const layout = screen.getByRole('region', { name: 'Overview' })
    const identityCard = layout.querySelector('[data-slot="overview-identity-card"]')
    expect(identityCard).toHaveClass('order-first', 'md:col-span-2')

    rerender(<OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={vi.fn()} onRefreshAll={vi.fn()} />)

    expect(layout.querySelector('[data-slot="overview-identity-card"]')).toHaveClass('order-first', 'md:col-span-2')
    expect(layout).toHaveClass('grid-cols-1', 'md:grid-cols-2')
  })

  it('shows Refresh All only with the telemetry grid and disables it while collection or refresh is active', () => {
    setCompactLayout(false)
    const onRefreshAll = vi.fn()
    const center = render(
      <OverviewView identity={identity} telemetry={telemetry} state="center" onCollect={vi.fn()} onRefreshAll={onRefreshAll} />,
    )
    expect(screen.queryByRole('button', { name: 'Refresh All' })).not.toBeInTheDocument()

    center.rerender(
      <OverviewView identity={identity} telemetry={telemetry} state="collecting" onCollect={vi.fn()} onRefreshAll={onRefreshAll} />,
    )
    const refreshButton = screen.getByRole('button', { name: 'Refresh All' })
    expect(refreshButton).toBeDisabled()
    expect(refreshButton.querySelector('svg')).toHaveClass('animate-spin')

    center.rerender(
      <OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={vi.fn()} onRefreshAll={onRefreshAll} />,
    )
    expect(refreshButton).toBeEnabled()
    expect(refreshButton.querySelector('svg')).not.toHaveClass('animate-spin')
    fireEvent.click(refreshButton)
    expect(onRefreshAll).toHaveBeenCalledOnce()

    center.rerender(
      <OverviewView identity={identity} telemetry={{ ...telemetry, isRefreshingAll: true }} state="ready" onCollect={vi.fn()} onRefreshAll={onRefreshAll} />,
    )
    expect(refreshButton).toBeDisabled()
    expect(refreshButton.querySelector('svg')).toHaveClass('animate-spin')

    center.rerender(
      <OverviewView identity={identity} telemetry={{ ...telemetry, isRefreshingAnyConnector: true }} state="ready" onCollect={vi.fn()} onRefreshAll={onRefreshAll} />,
    )
    expect(refreshButton).toBeDisabled()
    expect(refreshButton.querySelector('svg')).not.toHaveClass('animate-spin')
    expect(refreshButton.querySelector('svg')).toHaveClass('motion-reduce:animate-none')
  })
})

describe('OverviewView identity mark sizing', () => {
  function homeIdentity(layout: HTMLElement): HTMLElement {
    const node = layout.querySelector('[data-slot="home-identity"]')
    if (!node) {
      throw new Error('Expected [data-slot="home-identity"]')
    }
    return node as HTMLElement
  }

  it('uses a large identity mark and Collect Telemetry in center, error, and no-data', () => {
    setCompactLayout(false)
    const onCollect = vi.fn()

    const centerView = render(
      <OverviewView identity={identity} telemetry={telemetry} state="center" onCollect={onCollect} onRefreshAll={vi.fn()} />,
    )
    const centerLayout = screen.getByRole('region', { name: 'Overview' })
    expect(homeIdentity(centerLayout)).toHaveAttribute('data-logo-size', 'large')
    expect(centerLayout.querySelector('header span')).toHaveTextContent('Ready')
    expect(centerLayout.querySelector('[data-slot="voice-signal-glyph"] span')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collect Telemetry' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh All' })).not.toBeInTheDocument()
    centerView.unmount()

    const errorView = render(
      <OverviewView
        identity={identity}
        telemetry={telemetry}
        state="error"
        error="Network down"
        onCollect={onCollect}
        onRefreshAll={vi.fn()}
      />,
    )
    const errorLayout = screen.getByRole('region', { name: 'Overview' })
    expect(homeIdentity(errorLayout)).toHaveAttribute('data-logo-size', 'large')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Network down')
    errorView.unmount()

    const noDataView = render(
      <OverviewView identity={identity} telemetry={telemetry} state="no-data" onCollect={onCollect} onRefreshAll={vi.fn()} />,
    )
    const noDataLayout = screen.getByRole('region', { name: 'Overview' })
    expect(homeIdentity(noDataLayout)).toHaveAttribute('data-logo-size', 'large')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()
    noDataView.unmount()
  })

  it('uses an overview identity mark when the telemetry grid is visible', () => {
    setCompactLayout(false)
    const onCollect = vi.fn()

    const { rerender } = render(
      <OverviewView identity={identity} telemetry={telemetry} state="collecting" onCollect={onCollect} onRefreshAll={vi.fn()} />,
    )
    const layout = screen.getByRole('region', { name: 'Overview' })
    expect(homeIdentity(layout)).toHaveAttribute('data-logo-size', 'overview')
    expect(screen.queryByText(/Gathering telemetry/i)).not.toBeInTheDocument()

    rerender(<OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={onCollect} onRefreshAll={vi.fn()} />)
    expect(homeIdentity(layout)).toHaveAttribute('data-logo-size', 'overview')
  })

  it('uses grid-slot width on the identity card before collection but not after on desktop', () => {
    const onCollect = vi.fn()
    const gridSlotWidth = 'w-[calc((100%-2rem)/3)]'

    setCompactLayout(false)
    const centerView = render(
      <OverviewView identity={identity} telemetry={telemetry} state="center" onCollect={onCollect} onRefreshAll={vi.fn()} />,
    )
    const centerLayout = screen.getByRole('region', { name: 'Overview' })
    const centerCard = centerLayout.querySelector('[data-slot="overview-identity-card"]')
    expect(centerCard).toHaveClass(gridSlotWidth)
    expect(centerCard).not.toHaveClass('max-w-sm')
    centerView.unmount()

    const readyView = render(
      <OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={onCollect} onRefreshAll={vi.fn()} />,
    )
    const readyLayout = screen.getByRole('region', { name: 'Overview' })
    const readyCard = readyLayout.querySelector('[data-slot="overview-identity-card"]')
    expect(readyCard).not.toHaveClass('max-w-sm', gridSlotWidth)
    readyView.unmount()

    setCompactLayout(true)
    const compactCenterView = render(
      <OverviewView identity={identity} telemetry={telemetry} state="center" onCollect={onCollect} onRefreshAll={vi.fn()} />,
    )
    const compactLayout = screen.getByRole('region', { name: 'Overview' })
    const compactCenterCard = compactLayout.querySelector('[data-slot="overview-identity-card"]')
    expect(compactCenterCard).toHaveClass('max-w-sm')
    compactCenterView.unmount()
  })

  it('renders the central card redesign with top-left status text, scaled logo, and bottom-docked glyph without duplicate label', () => {
    setCompactLayout(false)
    render(
      <OverviewView
        identity={{
          logoProps: { status: 'idle' },
          glyphProps: { status: 'idle', isSpeaking: false, activity: 'briefing_ready' },
        }}
        telemetry={telemetry}
        state="ready"
        onCollect={vi.fn()}
        onRefreshAll={vi.fn()}
      />,
    )

    const layout = screen.getByRole('region', { name: 'Overview' })
    const identityCard = layout.querySelector('[data-slot="overview-identity-card"]') as HTMLElement
    expect(identityCard).toBeInTheDocument()

    // Header has status text at top-left
    const statusText = identityCard.querySelector('header span') as HTMLElement
    expect(statusText).toHaveTextContent('Briefing ready')
    expect(statusText).toHaveClass('text-[#FBBF24]')

    // Top-right refresh button exists
    expect(identityCard.querySelector('header button')).toBeInTheDocument()

    // Scaled logo has responsive classes constrained to container
    const logo = identityCard.querySelector('div.max-h-full')
    expect(logo).toBeInTheDocument()
    const logoClass = logo?.getAttribute('class') ?? ''
    expect(logoClass).toContain('h-36')
    expect(logoClass).toContain('sm:h-48')
    expect(logoClass).toContain('xl:h-56')
    expect(logoClass).toContain('aspect-[5208/5420]')

    // Bottom docked glyph exists and has hideLabel (no nested span inside glyph container)
    const glyph = identityCard.querySelector('[data-slot="voice-signal-glyph"]') as HTMLElement
    expect(glyph).toBeInTheDocument()
    expect(glyph.querySelector('span')).not.toBeInTheDocument()
  })
})
