import type { ReactElement } from 'react'
import { RefreshCw } from 'lucide-react'

import { useCompactLayout } from '../../hooks/useCompactLayout'
import { HudIdentityMark, type HudIdentityProps } from './HudIdentity'
import { TelemetryCollectionAction } from './TelemetryCollectionAction'
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
  onRefreshAll: () => void
  collectDisabled?: boolean
}

/** Telemetry-first Overview peer. It never needs a model. */
export function OverviewView({ identity, telemetry, state, error, onCollect, onRefreshAll, collectDisabled = false }: OverviewViewProps): ReactElement {
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
      className={`hud-glass relative flex min-h-0 flex-col items-center justify-center gap-3 rounded-xl border border-white/10 bg-zinc-950/40 p-3 ${hasGrid ? (compact ? 'order-first md:col-span-2' : narrow) : compact ? 'w-full max-w-sm px-8 py-6' : 'w-[calc((100%-2rem)/3)] px-8 py-6'}`}
      data-slot="overview-identity-card"
    >
      {hasGrid ? <button
        type="button"
        onClick={onRefreshAll}
        disabled={state === 'collecting' || telemetry.isRefreshingAll || telemetry.isRefreshingAnyConnector}
        aria-label="Refresh All"
        title="Refresh All"
        className="absolute right-3 top-3 inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[color:var(--hud-muted-text)] transition-colors hover:border-white/20 hover:bg-white/10 hover:text-[color:var(--hud-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <RefreshCw className={`size-3.5 motion-reduce:animate-none ${state === 'collecting' || telemetry.isRefreshingAll ? 'animate-spin' : ''}`} strokeWidth={2} aria-hidden />
      </button> : null}
      <HudIdentityMark identity={identity} size={hasGrid ? 'overview' : 'large'} />
      {state === 'error' ? <div className="max-w-sm text-center" role="alert"><p className="font-mono text-sm text-rose-300">{error || 'I couldn’t collect telemetry just now.'}</p></div> : null}
      {state === 'no-data' ? <p className="font-mono text-sm text-zinc-400" role="status">No telemetry sources are available yet.</p> : null}
      {state === 'center' || state === 'error' || state === 'no-data' ? <TelemetryCollectionAction
        onCollect={onCollect}
        disabled={collectDisabled}
        label={state === 'error' || state === 'no-data' ? 'Retry Telemetry' : 'Collect Telemetry'}
      /> : null}
    </div>
    {hasGrid ? <RemindersTelemetry data={telemetry} variant="card" className={narrow} /> : null}
    {hasGrid ? <MarketTelemetry data={telemetry} variant="card" className={wide} /> : null}
    {hasGrid ? <EmailTelemetry data={telemetry} variant="card" className={wide} /> : null}
  </section>
}
