import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_WEATHER_INFO } from '../../lib/weatherTelemetry'
import type { HudTelemetryData } from './HudTelemetry'
import { EmailTelemetry, NewsTelemetry } from './HudTelemetry'

function telemetry(emailState: HudTelemetryData['email']['state'], newsState: HudTelemetryData['news']['state']): HudTelemetryData {
  return {
    hasSnapshot: true,
    isRefreshingAll: false,
    isRefreshingAnyConnector: false,
    onRefreshConnector: vi.fn(),
    attentionTiers: { weather: 'complete', events: 'complete', market: 'complete', email: 'complete', news: 'complete', reminders: 'complete' },
    attentionStagger: { weather: 0, events: 0, market: 0, email: 0, news: 0, reminders: 0 },
    weather: { info: DEFAULT_WEATHER_INFO, body: 'Weather unavailable.', ledState: 'none', statusMessage: null, showAttribution: false },
    events: {
      f1Text: '', ledState: 'none', statusMessage: null, compactValue: null,
      calendar: { windowDays: 7, items: [], totalCount: 0 },
      football: { fixtures: [], configuredTeamCount: 0 }, footballModule: undefined,
      calendarRefreshing: false, f1Refreshing: false, footballRefreshing: false,
    },
    market: { data: null, isLoading: false, enabled: false },
    email: { state: emailState, ledState: 'none', statusMessage: null, compactValue: null, count: null, items: [], refreshing: false },
    news: { state: newsState, ledState: 'none', statusMessage: null, compactValue: null, items: [], refreshing: false },
    reminders: {
      loadState: 'loaded', ledState: 'none', statusMessage: null, compactValue: '0 pending', items: [],
      sourceState: null, actionError: null, refreshDisabled: false, onRefresh: vi.fn(), onOpenCompleted: vi.fn(),
      onSave: vi.fn(async () => 'synced' as const), onMarkRead: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onReview: vi.fn(),
    },
  }
}

describe('shared telemetry content states', () => {
  it('shows unavailable and disabled states independently of snapshot presence', () => {
    const data = telemetry('unavailable', 'disabled')
    render(<><EmailTelemetry data={data} variant="card" /><NewsTelemetry data={data} variant="card" /></>)

    expect(screen.getByText('Email unavailable.')).toBeInTheDocument()
    expect(screen.getByText('News disabled.')).toBeInTheDocument()
  })

  it('distinguishes an empty mailbox from missing previews for a positive count', () => {
    const empty = telemetry('available', 'available')
    empty.email.count = 0
    const { rerender } = render(<EmailTelemetry data={empty} variant="card" />)
    expect(screen.getByText('No unread emails.')).toBeInTheDocument()

    const noPreview = telemetry('available', 'available')
    noPreview.email.count = 4
    rerender(<EmailTelemetry data={noPreview} variant="card" />)
    expect(screen.getByText('4 Primary Messages')).toBeInTheDocument()
    expect(screen.getByText('Message previews unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('No unread emails.')).not.toBeInTheDocument()
  })

  it('keeps stale content visible beside its status message', () => {
    const data = telemetry('available', 'available')
    data.email.count = 1
    data.email.items = [{ subject: "Owner's [meeting] | 東京", time: '' }]
    data.email.statusMessage = 'Stale — provider error'
    data.news.items = [{ topic: 'Local', headline: 'Headline [1] | 東京' }]
    data.news.statusMessage = 'Stale — provider error'
    render(<><EmailTelemetry data={data} variant="card" /><NewsTelemetry data={data} variant="card" /></>)

    expect(screen.getByText("Owner's [meeting] | 東京")).toBeInTheDocument()
    expect(screen.getByText('Headline [1] | 東京')).toBeInTheDocument()
    expect(screen.getAllByText('Stale — provider error')).toHaveLength(2)
  })

  it('shows module-specific loading without hiding retained content or disabled state', () => {
    const data = telemetry('unavailable', 'unavailable')
    data.email.refreshing = true
    data.news.refreshing = true
    const { rerender } = render(<><EmailTelemetry data={data} variant="card" /><NewsTelemetry data={data} variant="card" /></>)
    expect(screen.getByText('Loading email…')).toBeInTheDocument()
    expect(screen.getByText('Loading news…')).toBeInTheDocument()

    data.email.state = 'available'
    data.email.count = 1
    data.email.items = [{ subject: 'Retained preview', time: '' }]
    data.news.state = 'available'
    data.news.items = [{ topic: 'World', headline: 'Retained headline' }]
    rerender(<><EmailTelemetry data={data} variant="card" /><NewsTelemetry data={data} variant="card" /></>)
    expect(screen.getByText('Retained preview')).toBeInTheDocument()
    expect(screen.getByText('Retained headline')).toBeInTheDocument()

    data.email.state = 'disabled'
    data.news.state = 'disabled'
    rerender(<><EmailTelemetry data={data} variant="card" /><NewsTelemetry data={data} variant="card" /></>)
    expect(screen.getByText('Email disabled.')).toBeInTheDocument()
    expect(screen.getByText('News disabled.')).toBeInTheDocument()
  })
})
