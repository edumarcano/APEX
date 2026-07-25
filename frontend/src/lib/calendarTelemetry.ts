import type { TelemetryModuleEntry } from '../types/telemetry'

export interface CalendarDisplayEvent {
  summary: string
  start: string
  end: string | null
  allDay: boolean
}

export interface CalendarTelemetry {
  windowDays: number
  displayWindowHours: number
  items: CalendarDisplayEvent[]
  totalCount: number
  displayCount: number
  overflowCount: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
    ? value
    : null
}

function formatStart(start: string, allDay: boolean): string {
  const parsed = new Date(allDay ? `${start}T00:00:00` : start)
  if (Number.isNaN(parsed.getTime())) {
    return start
  }
  if (allDay) {
    const day = parsed.toLocaleDateString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    })
    return `${day} · All day`
  }
  return parsed.toLocaleString(undefined, {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function parseStructuredEvent(value: unknown): CalendarDisplayEvent | null {
  if (!isRecord(value)) {
    return null
  }
  const summary = typeof value.summary === 'string' ? value.summary.trim() : ''
  const start = typeof value.start === 'string' ? value.start.trim() : ''
  if (!summary || !start) {
    return null
  }
  const allDay = value.all_day === true
  return {
    summary,
    start: formatStart(start, allDay),
    end: typeof value.end === 'string' ? value.end : null,
    allDay,
  }
}

function parseLegacyCalendar(calendarText: string): CalendarTelemetry {
  const empty: CalendarTelemetry = {
    windowDays: 2,
    displayWindowHours: 48,
    items: [],
    totalCount: 0,
    displayCount: 0,
    overflowCount: 0,
  }
  if (!calendarText || calendarText.includes('No upcoming events')) {
    return empty
  }

  const stripped = calendarText
    .replace(/^Calendar Telemetry\s*\(48h\)\s*:\s*/i, '')
    .trim()
  if (!stripped || /no upcoming events/i.test(stripped)) {
    return empty
  }

  const items = [...stripped.matchAll(/'([^']+)'\s+at\s+([^|]+)/g)].map(
    (match) => ({
      summary: match[1],
      start: match[2].trim(),
      end: null,
      allDay: match[2].includes('(All day)'),
    }),
  )
  return {
    ...empty,
    items,
    totalCount: items.length,
    displayCount: items.length,
  }
}

/** Prefer the seven-day structured contract while preserving older snapshots. */
export function resolveCalendarTelemetry(
  module: TelemetryModuleEntry | undefined,
): CalendarTelemetry {
  const data = module?.data
  if (
    isRecord(data) &&
    Array.isArray(data.display_events) &&
    nonNegativeInteger(data.total_count) !== null &&
    nonNegativeInteger(data.display_count) !== null &&
    nonNegativeInteger(data.overflow_count) !== null
  ) {
    const items = data.display_events
      .map(parseStructuredEvent)
      .filter((event): event is CalendarDisplayEvent => event !== null)
    return {
      windowDays: nonNegativeInteger(data.window_days) ?? 7,
      displayWindowHours: nonNegativeInteger(data.display_window_hours) ?? 48,
      items,
      totalCount: nonNegativeInteger(data.total_count) ?? items.length,
      displayCount: nonNegativeInteger(data.display_count) ?? items.length,
      overflowCount: nonNegativeInteger(data.overflow_count) ?? 0,
    }
  }

  return parseLegacyCalendar(module?.display_text ?? '')
}
