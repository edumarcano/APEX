import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CalendarTelemetry } from '../lib/calendarTelemetry'
import { CalendarEventList } from './CalendarEventList'

function telemetry(
  overrides: Partial<CalendarTelemetry> = {},
): CalendarTelemetry {
  return {
    windowDays: 7,
    displayWindowHours: 48,
    items: [],
    totalCount: 0,
    displayCount: 0,
    overflowCount: 0,
    ...overrides,
  }
}

describe('CalendarEventList', () => {
  it('renders the standard layout without an overflow line when none exists', () => {
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
          displayCount: 1,
        })}
      />,
    )

    expect(screen.getByText('1 Upcoming')).toBeInTheDocument()
    expect(screen.getByText('Planning')).toBeInTheDocument()
    expect(screen.queryByText(/more events?/i)).not.toBeInTheDocument()
  })

  it('renders a singular overflow line in the compact layout', () => {
    render(
      <CalendarEventList
        compact
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
          totalCount: 2,
          displayCount: 1,
          overflowCount: 1,
        })}
      />,
    )

    expect(
      screen.getByText('+ 1 more event in the next 7 days'),
    ).toBeInTheDocument()
  })

  it('shows the empty 48-hour state before multiple later events', () => {
    render(
      <CalendarEventList
        hasSnapshot
        telemetry={telemetry({
          totalCount: 3,
          overflowCount: 3,
        })}
      />,
    )

    expect(
      screen.getByText('No events in the next 48 hours.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('+ 3 more events in the next 7 days'),
    ).toBeInTheDocument()
  })
})
