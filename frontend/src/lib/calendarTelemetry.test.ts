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
  it('uses structured display events and overflow counts', () => {
    const result = resolveCalendarTelemetry(
      calendarModule({
        window_days: 7,
        display_window_hours: 48,
        events: [],
        display_events: [
          {
            summary: 'Within 48 hours',
            start: '2026-07-25T15:00:00-04:00',
            end: '2026-07-25T15:30:00-04:00',
            all_day: false,
          },
        ],
        total_count: 3,
        display_count: 1,
        overflow_count: 2,
      }),
    )

    expect(result.items).toHaveLength(1)
    expect(result.items[0].summary).toBe('Within 48 hours')
    expect(result.displayCount).toBe(1)
    expect(result.totalCount).toBe(3)
    expect(result.overflowCount).toBe(2)
  })

  it('keeps overflow when the 48-hour window is empty', () => {
    const result = resolveCalendarTelemetry(
      calendarModule({
        window_days: 7,
        display_window_hours: 48,
        events: [],
        display_events: [],
        total_count: 4,
        display_count: 0,
        overflow_count: 4,
      }),
    )

    expect(result.items).toEqual([])
    expect(result.displayCount).toBe(0)
    expect(result.overflowCount).toBe(4)
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
    expect(result.displayCount).toBe(2)
    expect(result.overflowCount).toBe(0)
  })
})
