import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CalendarTelemetry } from '../lib/calendarTelemetry'
import { CalendarEventList } from './CalendarEventList'

function telemetry(
  overrides: Partial<CalendarTelemetry> = {},
): CalendarTelemetry {
  return {
    windowDays: 7,
    items: [],
    totalCount: 0,
    ...overrides,
  }
}

describe('CalendarEventList', () => {
  it('renders the standard seven-day collection without an overflow line', () => {
    render(
      <CalendarEventList
        hasSnapshot
        telemetry={telemetry({
          items: [
            {
              summary: 'Planning',
              start: 'Fri, 9:00 AM',
              end: null,
              allDay: false,
            },
          ],
          totalCount: 1,
        })}
      />,
    )

    expect(screen.getByText('1 Upcoming')).toBeInTheDocument()
    expect(screen.getByText('Planning')).toBeInTheDocument()
    expect(screen.queryByText(/more events?/i)).not.toBeInTheDocument()
  })

  it('renders every seven-day event in the compact layout', () => {
    render(
      <CalendarEventList
        compact
        hasSnapshot
        telemetry={telemetry({
          items: [
            {
              summary: 'Day one',
              start: 'Fri, 9:00 AM',
              end: null,
              allDay: false,
            },
            {
              summary: 'Day three',
              start: 'Sun, 2:00 PM',
              end: null,
              allDay: false,
            },
            {
              summary: 'Day five',
              start: 'Tue, 11:00 AM',
              end: null,
              allDay: false,
            },
            {
              summary: 'Day seven',
              start: 'Thu, 4:00 PM',
              end: null,
              allDay: false,
            },
          ],
          totalCount: 4,
        })}
      />,
    )

    expect(screen.getByText('4 Upcoming')).toBeInTheDocument()
    expect(screen.getByText('Day one')).toBeInTheDocument()
    expect(screen.getByText('Day three')).toBeInTheDocument()
    expect(screen.getByText('Day five')).toBeInTheDocument()
    expect(screen.getByText('Day seven')).toBeInTheDocument()
    expect(screen.queryByText(/more events?/i)).not.toBeInTheDocument()
  })

  it('shows the empty seven-day state', () => {
    render(
      <CalendarEventList
        hasSnapshot
        telemetry={telemetry()}
      />,
    )

    expect(
      screen.getByText('No events in the next 7 days.'),
    ).toBeInTheDocument()
  })
})
