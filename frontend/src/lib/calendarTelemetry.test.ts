import { describe, expect, it } from 'vitest'

import type { TelemetryModuleEntry } from '../types/telemetry'
import { resolveCalendarTelemetry } from './calendarTelemetry'

function calendarModule(
  data: Record<string, unknown>,
  displayText = 'legacy text should not be parsed',
): TelemetryModuleEntry {
  return {
    name: 'calendar',
    status: 'healthy',
    freshness: 'live',
    reason_code: 'ok',
    observed_at: '2026-07-24T12:00:00Z',
    display_text: displayText,
    data,
  }
}

describe('resolveCalendarTelemetry', () => {
  it('uses the complete structured seven-day event collection', () => {
    const result = resolveCalendarTelemetry(
      calendarModule({
        window_days: 7,
        events: [
          {
            summary: 'Within 48 hours',
            start: '2026-07-25T15:00:00-04:00',
            end: '2026-07-25T15:30:00-04:00',
            all_day: false,
          },
          {
            summary: 'Day six',
            start: '2026-07-30',
            end: '2026-07-31',
            all_day: true,
          },
        ],
        total_count: 2,
      }),
    )

    expect(result.items).toHaveLength(2)
    expect(result.items[0].summary).toBe('Within 48 hours')
    expect(result.items[0].start).toMatch(
      /^[A-Za-z]+, [A-Za-z]+ \d{1,2} at \d{2}:\d{2}$/,
    )
    expect(result.items[1].summary).toBe('Day six')
    expect(result.items[1].start).toMatch(
      /^[A-Za-z]+, [A-Za-z]+ \d{1,2} Â· All day$/,
    )
    expect(result.totalCount).toBe(2)
  })

  it('reads every event from previous split snapshots', () => {
    const result = resolveCalendarTelemetry(
      calendarModule({
        window_days: 7,
        display_window_hours: 48,
        events: [
          {
            summary: 'Soon',
            start: '2026-07-25T15:00:00-04:00',
            end: null,
            all_day: false,
          },
          {
            summary: 'Later',
            start: '2026-07-29T15:00:00-04:00',
            end: null,
            all_day: false,
          },
        ],
        display_events: [
          {
            summary: 'Soon',
            start: '2026-07-25T15:00:00-04:00',
            end: null,
            all_day: false,
          },
        ],
        total_count: 2,
        display_count: 1,
        overflow_count: 1,
      }),
    )

    expect(result.items.map((event) => event.summary)).toEqual(['Soon', 'Later'])
    expect(result.totalCount).toBe(2)
  })

  it('falls back to legacy display text for older snapshots', () => {
    const result = resolveCalendarTelemetry(
      calendarModule(
        {},
        "Calendar Telemetry (48h): 'Planning' at 09:00 AM | 'Review' at 03:30 PM",
      ),
    )

    expect(result.items.map((event) => event.summary)).toEqual([
      'Planning',
      'Review',
    ])
    expect(result.totalCount).toBe(2)
  })
})
