import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_WEATHER_INFO } from '../../lib/weatherTelemetry'
import type { HudIdentityProps } from './HudIdentity'
import type { HudTelemetryData } from './HudTelemetry'
import { OverviewView } from './OverviewView'

afterEach(() => vi.unstubAllGlobals())

const identity: HudIdentityProps = {
  logoProps: { status: 'idle' },
  glyphProps: { status: 'idle', isSpeaking: false },
}

const telemetry: HudTelemetryData = {
  hasSnapshot: false,
  isRefreshingAll: false,
  isRefreshingAnyConnector: false,
  onRefreshConnector: vi.fn(),
  attentionTiers: { weather: 'pending', events: 'pending', market: 'pending', email: 'pending', reminders: 'pending' },
  attentionStagger: { weather: 0, events: 0, market: 0, email: 0, reminders: 0 },
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
  it('renders Weather, Events, Email, Market and Reminders with no News panel', () => {
    setCompactLayout(false)
    render(<OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={vi.fn()} onRefreshAll={vi.fn()} onSetUpBriefing={vi.fn()} />)

    for (const title of ['Weather', 'Events', 'Email', 'Market', 'Reminders']) {
      expect(screen.getByRole('heading', { name: title })).toBeVisible()
    }
    expect(screen.queryByRole('heading', { name: /News Wire/ })).not.toBeInTheDocument()
  })

  it('keeps every card available at compact widths', () => {
    setCompactLayout(true)
    render(<OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={vi.fn()} onRefreshAll={vi.fn()} onSetUpBriefing={vi.fn()} />)

    for (const title of ['Weather', 'Events', 'Email', 'Market', 'Reminders']) {
      expect(screen.getByRole('heading', { name: title })).toBeVisible()
    }
  })

  it('disables Refresh All during collection and connector refreshes', () => {
    setCompactLayout(false)
    const onRefreshAll = vi.fn()
    const { rerender } = render(<OverviewView identity={identity} telemetry={telemetry} state="collecting" onCollect={vi.fn()} onRefreshAll={onRefreshAll} onSetUpBriefing={vi.fn()} />)
    const refresh = screen.getByRole('button', { name: 'Refresh All' })
    expect(refresh).toBeDisabled()
    expect(refresh.querySelector('svg')).toHaveClass('animate-spin')

    rerender(<OverviewView identity={identity} telemetry={telemetry} state="ready" onCollect={vi.fn()} onRefreshAll={onRefreshAll} onSetUpBriefing={vi.fn()} />)
    expect(refresh).toBeEnabled()
    fireEvent.click(refresh)
    expect(onRefreshAll).toHaveBeenCalledOnce()

    rerender(<OverviewView identity={identity} telemetry={{ ...telemetry, isRefreshingAnyConnector: true }} state="ready" onCollect={vi.fn()} onRefreshAll={onRefreshAll} onSetUpBriefing={vi.fn()} />)
    expect(refresh).toBeDisabled()
    expect(refresh.querySelector('svg')).toHaveClass('motion-reduce:animate-none')

    rerender(<OverviewView identity={identity} telemetry={{ ...telemetry, isRefreshingAll: true }} state="ready" onCollect={vi.fn()} onRefreshAll={onRefreshAll} onSetUpBriefing={vi.fn()} />)
    expect(refresh).toBeDisabled()
    expect(refresh.querySelector('svg')).toHaveClass('animate-spin')
  })

  it('offers setup only after collection and invokes it without collecting telemetry', () => {
    setCompactLayout(false)
    const onCollect = vi.fn()
    const onSetUpBriefing = vi.fn()
    const { rerender } = render(<OverviewView identity={identity} telemetry={telemetry} state="center" onCollect={onCollect} onRefreshAll={vi.fn()} onSetUpBriefing={onSetUpBriefing} />)

    expect(screen.getByRole('button', { name: 'Collect Telemetry' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Set up briefing' })).not.toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeVisible()
    expect(screen.getByRole('region', { name: 'Overview' }).querySelector('[data-slot="home-identity"]')).toHaveAttribute('data-logo-size', 'overview')

    rerender(<OverviewView identity={{
      ...identity,
      glyphProps: { ...identity.glyphProps, activity: 'synthesizing' },
    }} telemetry={telemetry} state="ready" onCollect={onCollect} onRefreshAll={vi.fn()} onSetUpBriefing={onSetUpBriefing} />)
    const setup = screen.getByRole('button', { name: 'Set up briefing' })
    expect(setup).toBeEnabled()
    fireEvent.click(setup)
    expect(onSetUpBriefing).toHaveBeenCalledOnce()
    expect(onCollect).not.toHaveBeenCalled()
    expect(screen.getByText('Synthesizing')).toBeVisible()
  })

  it('retains the retry message in error and no-data states', () => {
    setCompactLayout(false)
    const props = { identity, telemetry, onCollect: vi.fn(), onRefreshAll: vi.fn(), onSetUpBriefing: vi.fn() }
    const { rerender } = render(<OverviewView {...props} state="error" error="Network down" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Network down')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeVisible()

    rerender(<OverviewView {...props} state="no-data" />)
    expect(screen.getByRole('status')).toHaveTextContent('No telemetry sources are available yet.')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()
  })
})
