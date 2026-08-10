import { describe, expect, it } from 'vitest'

import type { TelemetryModuleEntry } from '../types/telemetry'
import { resolveCalendarTelemetry } from './calendarTelemetry'

function calendarModule(
  data: Record<string, unknown>,
): TelemetryModuleEntry {
  return {
    name: 'calendar',
    status: 'healthy',
    freshness: 'live',
    reason_code: 'ok',
    observed_at: '2026-07-24T12:00:00Z',
    display_text: '',
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
      /^[A-Za-z]+, [A-Za-z]+ \d{1,2} · All day$/,
    )
    expect(result.totalCount).toBe(2)
  })

})
