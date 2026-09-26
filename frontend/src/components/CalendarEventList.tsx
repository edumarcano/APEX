import type { ReactElement } from 'react'

import type { CalendarTelemetry } from '../lib/calendarTelemetry'

interface CalendarEventListProps {
  telemetry: CalendarTelemetry
  hasSnapshot: boolean
  compact?: boolean
  /** Places each event's time below its title for narrow rails. */
  stacked?: boolean
}

export function CalendarEventList({
  telemetry,
  hasSnapshot,
  compact = false,
  stacked = false,
}: CalendarEventListProps): ReactElement {
  return (
    <div className="shrink-0">
      {telemetry.totalCount > 0 && (
        <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">
          {telemetry.totalCount} Upcoming
        </p>
      )}
      {telemetry.items.length > 0 ? (
        <ul
          className={
            compact ? 'space-y-1.5' : 'space-y-2'
          }
        >
          {telemetry.items.map((item, index) => (
            <li
              key={`${item.summary}-${item.start}-${index}`}
              className={stacked ? 'flex flex-col gap-0.5' : 'flex items-start justify-between gap-3'}
            >
              <span className="flex min-w-0 items-start gap-2">
                <span className="hud-log-index">
                  {String(index).padStart(2, '0')}
                </span>
                <span className="min-w-0 break-words text-sm text-zinc-200">
                  {item.summary}
                  {item.calendarName ? <span className="ml-1.5 text-xs text-zinc-500">· {item.calendarName}</span> : null}
                </span>
              </span>
              <span className={`${stacked ? 'pl-7' : 'shrink-0'} font-mono text-xs text-zinc-500`}>
                {item.start}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-[color:var(--hud-muted-text)]">
          {hasSnapshot
            ? 'No events in the next 7 days.'
            : 'Schedule unavailable.'}
        </p>
      )}
    </div>
  )
}
