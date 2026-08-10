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

/** Read the canonical structured seven-day calendar contract. */
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

  return {
    windowDays: 7,
    items: [],
    totalCount: 0,
  }
}
