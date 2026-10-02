import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_WEATHER_INFO } from '../../lib/weatherTelemetry'
import type { HudTelemetryData } from './HudTelemetry'
import { EmailTelemetry } from './HudTelemetry'

function telemetry(state: HudTelemetryData['email']['state']): HudTelemetryData {
  return {
    hasSnapshot: true,
    isRefreshingAll: false,
    isRefreshingAnyConnector: false,
    onRefreshConnector: vi.fn(),
    attentionTiers: { weather: 'complete', events: 'complete', market: 'complete', email: 'complete', reminders: 'complete' },
    attentionStagger: { weather: 0, events: 0, market: 0, email: 0, reminders: 0 },
    weather: { info: DEFAULT_WEATHER_INFO, body: 'Weather unavailable.', ledState: 'none', statusMessage: null, showAttribution: false },
    events: {
      f1Text: '', ledState: 'none', statusMessage: null, compactValue: null,
      calendar: { windowDays: 7, items: [], totalCount: 0 },
      football: { fixtures: [], configuredTeamCount: 0 }, footballModule: undefined,
      calendarRefreshing: false, f1Refreshing: false, footballRefreshing: false,
    },
    market: { data: null, isLoading: false, enabled: false },
    email: { state, ledState: 'none', statusMessage: null, compactValue: null, count: null, items: [], refreshing: false },
    reminders: {
      loadState: 'loaded', ledState: 'none', statusMessage: null, compactValue: '0 pending', items: [],
      sourceState: null, actionError: null, refreshDisabled: false, onRefresh: vi.fn(), onOpenCompleted: vi.fn(),
      onSave: vi.fn(async () => 'synced' as const), onMarkRead: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onReview: vi.fn(),
    },
  }
}

describe('Email telemetry content states', () => {
  it('shows unavailable and disabled states independently of snapshot presence', () => {
    const data = telemetry('unavailable')
    const { rerender } = render(<EmailTelemetry data={data} variant="card" />)

    expect(screen.getByText('Email unavailable.')).toBeInTheDocument()
    data.email.state = 'disabled'
    rerender(<EmailTelemetry data={data} variant="card" />)
    expect(screen.getByText('Email disabled.')).toBeInTheDocument()
  })

  it('distinguishes an empty mailbox from missing previews for a positive count', () => {
    const empty = telemetry('available')
    empty.email.count = 0
    const { rerender } = render(<EmailTelemetry data={empty} variant="card" />)
    expect(screen.getByText('No unread emails.')).toBeInTheDocument()

    const noPreview = telemetry('available')
    noPreview.email.count = 4
    rerender(<EmailTelemetry data={noPreview} variant="card" />)
    expect(screen.getByText('4 Primary Messages')).toBeInTheDocument()
    expect(screen.getByText('Message previews unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('No unread emails.')).not.toBeInTheDocument()
  })

  it('keeps stale content visible beside its status message', () => {
    const data = telemetry('available')
    data.email.count = 1
    data.email.items = [{ subject: "Owner's [meeting] | 東京", time: '' }]
    data.email.statusMessage = 'Stale — provider error'
    render(<EmailTelemetry data={data} variant="card" />)

    expect(screen.getByText("Owner's [meeting] | 東京")).toBeInTheDocument()
    expect(screen.getByText('Stale — provider error')).toBeInTheDocument()
  })

  it('shows module-specific loading and retained content', () => {
    const data = telemetry('unavailable')
    data.email.refreshing = true
    const { rerender } = render(<EmailTelemetry data={data} variant="card" />)
    expect(screen.getByText('Loading email…')).toBeInTheDocument()

    data.email.state = 'available'
    data.email.count = 1
    data.email.items = [{ subject: 'Retained preview', time: '' }]
    rerender(<EmailTelemetry data={data} variant="card" />)
    expect(screen.getByText('Retained preview')).toBeInTheDocument()
  })
})
