import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_WEATHER_INFO } from '../../lib/weatherTelemetry'
import type { HudTelemetryData } from './HudTelemetry'
import { HudTelemetryRail } from './HudTelemetryRail'

const surfaces = { weather: 0, events: 0, market: 0, email: 0, news: 0, reminders: 0 }

function telemetry(overrides: Partial<HudTelemetryData> = {}): HudTelemetryData {
  return {
    hasSnapshot: true,
    isRefreshingAll: false,
    isRefreshingAnyConnector: false,
    onRefreshConnector: vi.fn(),
    attentionTiers: { weather: 'complete', events: 'complete', market: 'complete', email: 'complete', news: 'complete', reminders: 'complete' },
    attentionStagger: surfaces,
    weather: { info: { ...DEFAULT_WEATHER_INFO, temperatureF: 72, condition: 'clear_day' }, body: 'Clear', ledState: 'live', statusMessage: null, showAttribution: true },
    events: {
      f1Text: '',
      ledState: 'live',
      statusMessage: null,
      compactValue: null,
      calendar: { windowDays: 7, items: [{ summary: 'Planning', start: 'Fri, 9:00 AM', end: null, allDay: false }], totalCount: 1 },
      football: { fixtures: [], configuredTeamCount: 0 },
      footballModule: undefined,
      calendarRefreshing: false,
      f1Refreshing: false,
      footballRefreshing: false,
    },
    market: { data: null, isLoading: false, enabled: true },
    email: { ledState: 'live', statusMessage: null, compactValue: null, count: 0, items: [], refreshing: false },
    news: { ledState: 'live', statusMessage: null, compactValue: null, items: [], refreshing: false },
    reminders: {
      loadState: 'loaded',
      ledState: 'live',
      statusMessage: null,
      compactValue: '',
      items: [],
      sourceState: 'live',
      actionError: null,
      refreshDisabled: false,
      onRefresh: vi.fn(),
      onOpenCompleted: vi.fn(),
      onSave: vi.fn(async () => {}),
      onMarkRead: vi.fn(),
      onEdit: vi.fn(),
      onDelete: vi.fn(),
      onReview: vi.fn(),
    },
    ...overrides,
  } as HudTelemetryData
}

function domainSections(rail: HTMLElement): Array<HTMLElement | null> {
  return [
    within(rail).getByRole('heading', { name: 'Weather' }),
    within(rail).getByRole('heading', { name: 'Events' }),
    within(rail).getByRole('heading', { name: 'Email' }),
    within(rail).getByRole('heading', { name: 'News Wire' }),
    within(rail).getByRole('heading', { name: 'Reminders' }),
    within(rail).getByRole('region', { name: 'Market ticker' }),
  ].map((element) => element.closest('section'))
}

describe('HudTelemetryRail', () => {
  it('offers collection before a usable snapshot and keeps database reminders below it', async () => {
    const user = userEvent.setup()
    const data = telemetry({ reminders: { ...telemetry().reminders, loadState: 'loaded', items: [{ id: 'reminder', note: 'Check the briefing', source: 'local', sync_state: 'synced' }] } })
    const onCollect = vi.fn()
    render(<HudTelemetryRail data={data} hasUsableSnapshot={false} onCollect={onCollect} />)

    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    expect(within(rail).getByRole('button', { name: 'Collect Telemetry' })).toBeEnabled()
    expect(within(rail).queryByRole('heading', { name: 'Weather' })).not.toBeInTheDocument()
    expect(within(rail).getByText('Check the briefing')).toBeInTheDocument()
    await user.click(within(rail).getByRole('button', { name: 'Collect Telemetry' }))
    expect(onCollect).toHaveBeenCalledOnce()
  })

  it('does not claim reminders are empty until the independent reminder load completes', () => {
    const data = telemetry({ reminders: { ...telemetry().reminders, loadState: 'loading' } })
    render(<HudTelemetryRail data={data} hasUsableSnapshot={false} onCollect={vi.fn()} />)

    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    expect(within(rail).getByText('Loading reminders…')).toBeInTheDocument()
    expect(within(rail).queryByText('No pending reminders')).not.toBeInTheDocument()
  })

  it('shows a truthful unavailable state with a retry when reminder data is unavailable and empty', async () => {
    const user = userEvent.setup()
    const onRefresh = vi.fn()
    const data = telemetry({ reminders: { ...telemetry().reminders, loadState: 'unavailable', sourceState: 'unavailable', onRefresh } })
    render(<HudTelemetryRail data={data} hasUsableSnapshot={false} onCollect={vi.fn()} />)

    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    const reminders = within(rail).getByRole('region', { name: 'Reminders' })
    expect(within(reminders).getByText('Reminders unavailable.')).toBeInTheDocument()
    expect(within(reminders).queryByText('No pending reminders')).not.toBeInTheDocument()
    await user.click(within(reminders).getByRole('button', { name: 'Retry Reminders' }))
    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('shows collection progress, error retry, and no-data retry states', () => {
    const data = telemetry()
    const onCollect = vi.fn()
    const { rerender } = render(<HudTelemetryRail data={data} hasUsableSnapshot={false} collectionState="collecting" onCollect={onCollect} />)
    expect(screen.getByText('Collecting telemetry…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Collect Telemetry' })).not.toBeInTheDocument()

    rerender(<HudTelemetryRail data={data} hasUsableSnapshot={false} collectionState="error" collectionError="Connector request failed" onCollect={onCollect} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Connector request failed')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()

    rerender(<HudTelemetryRail data={data} hasUsableSnapshot={false} collectionState="no-data" onCollect={onCollect} />)
    expect(screen.getByText('No telemetry sources are available yet.')).toHaveAttribute('role', 'status')
    expect(screen.getByRole('button', { name: 'Retry Telemetry' })).toBeInTheDocument()
  })

  it('renders every domain as a section of one shared panel rather than separate cards', () => {
    render(<HudTelemetryRail data={telemetry()} />)

    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    const sections = domainSections(rail)
    for (const section of sections) expect(section).toHaveAttribute('data-chrome', 'section')
    expect(new Set(sections.map((section) => section?.parentElement)).size).toBe(1)
    expect(within(rail).getByText('Planning')).toBeInTheDocument()
    expect(within(rail).getByRole('link', { name: 'Open-Meteo' })).toHaveAttribute('href', 'https://open-meteo.com/')
  })

  it('keeps per-domain refresh actions and their disabled state inside the panel', async () => {
    const data = telemetry()
    const { rerender } = render(<HudTelemetryRail data={data} />)
    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })

    await userEvent.click(within(rail).getByRole('button', { name: 'Refresh Email' }))
    expect(data.onRefreshConnector).toHaveBeenCalledWith('email')

    rerender(<HudTelemetryRail data={{ ...data, isRefreshingAll: true }} />)
    expect(within(rail).getByRole('button', { name: 'Refresh Weather' })).toBeDisabled()
    expect(within(rail).getByRole('button', { name: 'Choose Events module to refresh' })).toBeDisabled()
  })

  it('lets sections grow with their content so the shared panel is the only height limit', () => {
    const base = telemetry()
    const items = Array.from({ length: 40 }, (_, index) => ({ summary: `Event ${index}`, start: 'Fri, 9:00 AM', end: null, allDay: false }))
    render(<HudTelemetryRail data={{ ...base, events: { ...base.events, calendar: { windowDays: 7, items, totalCount: items.length } } }} />)

    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    expect(within(rail).getByText('Event 39')).toBeInTheDocument()
    for (const section of domainSections(rail)) {
      expect(section).not.toHaveClass('max-h-96')
      expect(section).not.toHaveClass('overflow-hidden')
    }
  })
})
