import type { TelemetryModuleEntry } from '../types/telemetry'

export interface CalendarDisplayEvent {
  summary: string
  start: string
  end: string | null
  allDay: boolean
}

export interface CalendarTelemetry {
  windowDays: number
  items: CalendarDisplayEvent[]
  totalCount: number
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
  const parsed = new Date(allDay ? `${start}T12:00:00` : start)
  if (Number.isNaN(parsed.getTime())) {
    return start
  }

  const day = parsed.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })
  if (allDay) {
    return `${day} · All day`
  }

  const time = parsed.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return `${day} at ${time}`
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
    windowDays: 7,
    items: [],
    totalCount: 0,
  }
  if (!calendarText || calendarText.includes('No upcoming events')) {
    return empty
  }

  const stripped = calendarText
    .replace(/^Calendar Telemetry\s*\((?:48h|7d)\)\s*:\s*/i, '')
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
  }
}

/** Prefer the seven-day structured contract while preserving older snapshots. */
export function resolveCalendarTelemetry(
  module: TelemetryModuleEntry | undefined,
): CalendarTelemetry {
  const data = module?.data
  if (
    isRecord(data) &&
    Array.isArray(data.events) &&
    nonNegativeInteger(data.total_count) !== null
  ) {
    const items = data.events
      .map(parseStructuredEvent)
      .filter((event): event is CalendarDisplayEvent => event !== null)
    return {
      windowDays: nonNegativeInteger(data.window_days) ?? 7,
      items,
      totalCount: nonNegativeInteger(data.total_count) ?? items.length,
    }
  }

  if (isRecord(data) && Array.isArray(data.display_events)) {
    const items = data.display_events
      .map(parseStructuredEvent)
      .filter((event): event is CalendarDisplayEvent => event !== null)
    return {
      windowDays: nonNegativeInteger(data.window_days) ?? 7,
      items,
      totalCount: nonNegativeInteger(data.display_count) ?? items.length,
    }
  }

  return parseLegacyCalendar(module?.display_text ?? '')
}
