import type { ReactElement } from 'react'

import type { CalendarTelemetry } from '../lib/calendarTelemetry'

interface CalendarEventListProps {
  telemetry: CalendarTelemetry
  hasSnapshot: boolean
  compact?: boolean
}

export function CalendarEventList({
  telemetry,
  hasSnapshot,
  compact = false,
}: CalendarEventListProps): ReactElement {
  const visibleItems = compact ? telemetry.items.slice(0, 3) : telemetry.items

  return (
    <>
      {telemetry.displayCount > 0 && (
        <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">
          {telemetry.displayCount} Upcoming
        </p>
      )}
      {visibleItems.length > 0 ? (
        <ul
          className={`list-fade-mask min-h-0 overflow-y-auto pr-1 scrollbar-thin ${
            compact ? 'space-y-1.5' : 'space-y-2'
          }`}
        >
          {visibleItems.map((item, index) => (
            <li
              key={`${item.summary}-${item.start}-${index}`}
              className="flex items-start justify-between gap-3"
            >
              <span className="flex min-w-0 items-start gap-2">
                <span className="hud-log-index">
                  {String(index).padStart(2, '0')}
                </span>
                <span className="break-words text-sm text-zinc-200">
                  {item.summary}
                </span>
              </span>
              <span className="shrink-0 font-mono text-xs text-zinc-500">
                {item.start}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-[color:var(--hud-muted-text)]">
          {hasSnapshot
            ? 'No events in the next 48 hours.'
            : 'Schedule unavailable.'}
        </p>
      )}
      {telemetry.overflowCount > 0 && (
        <p className="mt-2 font-mono text-xs text-[color:var(--hud-muted-text)]">
          + {telemetry.overflowCount} more event
          {telemetry.overflowCount === 1 ? '' : 's'} in the next 7 days
        </p>
      )}
    </>
  )
}
