import type { ReactElement } from 'react'

import { useCompactLayout } from '../../hooks/useCompactLayout'
import { HudIdentityMark, type HudIdentityProps } from './HudIdentity'
import {
  EventsTelemetry,
  EmailTelemetry,
  MarketTelemetry,
  NewsTelemetry,
  RemindersTelemetry,
  WeatherTelemetry,
  type HudTelemetryData,
} from './HudTelemetry'

export type OverviewViewProps = {
  identity: HudIdentityProps
  telemetry: HudTelemetryData
}

/** Telemetry-first Overview peer. It never needs a model. */
export function OverviewView({ identity, telemetry }: OverviewViewProps): ReactElement {
  const compact = useCompactLayout()
  const wide = compact ? '' : 'col-span-3'
  const narrow = compact ? '' : 'col-span-2'
  return <section
    aria-label="Overview"
    className={compact
      ? 'grid w-full grid-cols-1 gap-4 md:grid-cols-2'
      : 'grid h-full min-h-0 w-full flex-1 grid-cols-6 grid-rows-[minmax(0,1.15fr)_minmax(0,1.15fr)_minmax(0,1fr)] gap-4'}
  >
    <WeatherTelemetry data={telemetry} variant="card" className={wide} />
    <EventsTelemetry data={telemetry} variant="card" className={wide} />
    <NewsTelemetry data={telemetry} variant="card" className={narrow} />
    <div
      className={`hud-glass flex min-h-0 flex-col items-center justify-center gap-3 rounded-xl border border-white/10 bg-zinc-950/40 p-3 ${narrow} ${compact ? 'order-first md:col-span-2' : ''}`}
      data-slot="overview-identity-card"
    >
      <HudIdentityMark identity={identity} size="overview" />
    </div>
    <RemindersTelemetry data={telemetry} variant="card" className={narrow} />
    <MarketTelemetry data={telemetry} variant="card" className={wide} />
    <EmailTelemetry data={telemetry} variant="card" className={wide} />
  </section>
}
