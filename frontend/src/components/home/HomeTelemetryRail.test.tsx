import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_WEATHER_INFO } from '../../lib/weatherTelemetry'
import type { HomeTelemetryData } from './HomeTelemetry'
import { HomeTelemetryRail } from './HomeTelemetryRail'

const surfaces = { weather: 0, events: 0, market: 0, inbox: 0, news: 0, reminders: 0 }

function telemetry(overrides: Partial<HomeTelemetryData> = {}): HomeTelemetryData {
  return {
    hasSnapshot: true,
    isRefreshingAll: false,
    onRefreshConnector: vi.fn(),
    attentionTiers: { weather: 'complete', events: 'complete', market: 'complete', inbox: 'complete', news: 'complete', reminders: 'complete' },
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
    inbox: { ledState: 'live', statusMessage: null, compactValue: null, count: 0, items: [], refreshing: false },
    news: { ledState: 'live', statusMessage: null, compactValue: null, items: [], refreshing: false },
    reminders: {
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
  } as HomeTelemetryData
}

function domainSections(rail: HTMLElement): Array<HTMLElement | null> {
  return [
    within(rail).getByRole('heading', { name: 'Weather' }),
    within(rail).getByRole('heading', { name: 'Events' }),
    within(rail).getByRole('heading', { name: 'Inbox' }),
    within(rail).getByRole('heading', { name: 'News Wire' }),
    within(rail).getByRole('heading', { name: 'Reminders' }),
    within(rail).getByRole('region', { name: 'Market ticker' }),
  ].map((element) => element.closest('section'))
}

describe('HomeTelemetryRail', () => {
  it('renders every domain as a section of one shared panel rather than separate cards', () => {
    render(<HomeTelemetryRail data={telemetry()} />)

    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })
    const sections = domainSections(rail)
    for (const section of sections) expect(section).toHaveAttribute('data-chrome', 'section')
    expect(new Set(sections.map((section) => section?.parentElement)).size).toBe(1)
    expect(within(rail).getByText('Planning')).toBeInTheDocument()
    expect(within(rail).getByRole('link', { name: 'Open-Meteo' })).toHaveAttribute('href', 'https://open-meteo.com/')
  })

  it('keeps per-domain refresh actions and their disabled state inside the panel', async () => {
    const data = telemetry()
    const { rerender } = render(<HomeTelemetryRail data={data} />)
    const rail = screen.getByRole('complementary', { name: 'Current telemetry' })

    await userEvent.click(within(rail).getByRole('button', { name: 'Refresh Inbox' }))
    expect(data.onRefreshConnector).toHaveBeenCalledWith('email')

    rerender(<HomeTelemetryRail data={{ ...data, isRefreshingAll: true }} />)
    expect(within(rail).getByRole('button', { name: 'Refresh Weather' })).toBeDisabled()
    expect(within(rail).getByRole('button', { name: 'Choose Events module to refresh' })).toBeDisabled()
  })
})
