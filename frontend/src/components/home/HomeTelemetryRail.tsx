import type { ReactElement } from 'react'

import {
  EventsTelemetry,
  InboxTelemetry,
  MarketTelemetry,
  NewsTelemetry,
  RemindersTelemetry,
  WeatherTelemetry,
  type HomeTelemetryData,
} from './HomeTelemetry'

/** Current telemetry beside a briefing; it is not the briefing's evidence snapshot. */
export function HomeTelemetryRail({
  data,
  id,
  className = '',
}: {
  data: HomeTelemetryData
  id?: string
  className?: string
}): ReactElement {
  return <aside id={id} className={`flex min-h-0 min-w-0 flex-col ${className}`} aria-label="Current telemetry">
    <p className="mb-2 shrink-0 font-mono text-[9px] uppercase tracking-wider text-zinc-500">Current telemetry · live, not the briefing snapshot</p>
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1 scrollbar-thin">
      <WeatherTelemetry data={data} variant="section" />
      <EventsTelemetry data={data} variant="section" />
      <InboxTelemetry data={data} variant="section" />
      <NewsTelemetry data={data} variant="section" />
      <RemindersTelemetry data={data} variant="section" />
      <MarketTelemetry data={data} variant="section" />
    </div>
  </aside>
}
