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
  state: 'center' | 'collecting' | 'ready' | 'error' | 'no-data'
  error?: string | null
  onCollect: () => void
  collectDisabled?: boolean
}

/** Telemetry-first Overview peer. It never needs a model. */
export function OverviewView({ identity, telemetry, state, error, onCollect, collectDisabled = false }: OverviewViewProps): ReactElement {
  const compact = useCompactLayout()
  const wide = compact ? '' : 'col-span-3'
  const narrow = compact ? '' : 'col-span-2'
  const hasGrid = state === 'collecting' || state === 'ready'
  return <section
    aria-label="Overview"
    className={`hud-home-layout ${!hasGrid
      ? 'flex h-full min-h-0 w-full flex-1 items-center justify-center'
      : compact
      ? 'grid w-full grid-cols-1 gap-4 md:grid-cols-2'
      : 'grid h-full min-h-0 w-full flex-1 grid-cols-6 grid-rows-[minmax(0,1.15fr)_minmax(0,1.15fr)_minmax(0,1fr)] gap-4'} ${hasGrid ? 'hud-home-layout-enter' : ''}`}
  >
    {hasGrid ? <WeatherTelemetry data={telemetry} variant="card" className={wide} /> : null}
    {hasGrid ? <EventsTelemetry data={telemetry} variant="card" className={wide} /> : null}
    {hasGrid ? <NewsTelemetry data={telemetry} variant="card" className={narrow} /> : null}
    <div
      className={`hud-glass flex min-h-0 flex-col items-center justify-center gap-3 rounded-xl border border-white/10 bg-zinc-950/40 p-3 ${hasGrid ? (compact ? 'order-first md:col-span-2' : narrow) : 'w-auto max-w-full'}`}
      data-slot="overview-identity-card"
    >
      <HudIdentityMark identity={identity} size={hasGrid ? 'overview' : 'large'} />
      {state === 'error' ? <div className="max-w-sm text-center" role="alert"><p className="font-mono text-sm text-rose-300">{error || 'I couldn’t collect telemetry just now.'}</p></div> : null}
      {state === 'no-data' ? <p className="font-mono text-sm text-zinc-400" role="status">No telemetry sources are available yet.</p> : null}
      {state === 'center' || state === 'error' || state === 'no-data' ? <button
        type="button"
        onClick={onCollect}
        disabled={collectDisabled}
        className="hud-command-surface inline-flex items-center gap-2 rounded-lg border border-emerald-700/60 bg-emerald-900/25 px-4 py-2.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-200 transition-colors hover:border-emerald-500/80 hover:bg-emerald-800/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
      >
        {state === 'error' || state === 'no-data' ? 'Retry Telemetry' : 'Collect Telemetry'}
      </button> : null}
    </div>
    {hasGrid ? <RemindersTelemetry data={telemetry} variant="card" className={narrow} /> : null}
    {hasGrid ? <MarketTelemetry data={telemetry} variant="card" className={wide} /> : null}
    {hasGrid ? <EmailTelemetry data={telemetry} variant="card" className={wide} /> : null}
  </section>
}
