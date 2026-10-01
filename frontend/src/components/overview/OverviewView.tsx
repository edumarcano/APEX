import type { ReactElement } from 'react'
import { RefreshCw } from 'lucide-react'

import { useCompactLayout } from '../../hooks/useCompactLayout'
import { ApexLogo } from '../ApexLogo'
import { VoiceSignalGlyph } from '../VoiceSignalGlyph'
import { TelemetryCollectionAction } from './TelemetryCollectionAction'
import {
  EventsTelemetry,
  EmailTelemetry,
  MarketTelemetry,
  RemindersTelemetry,
  WeatherTelemetry,
  type HudTelemetryData,
} from './HudTelemetry'
import type { HudIdentityProps } from './HudIdentity'

export type OverviewViewProps = {
  identity: HudIdentityProps
  telemetry: HudTelemetryData
  state: 'center' | 'collecting' | 'ready' | 'error' | 'no-data'
  error?: string | null
  onCollect: () => void
  onRefreshAll: () => void
  onSetUpBriefing: () => void
  collectDisabled?: boolean
}

/** Telemetry-first Overview peer. It never needs a model. */
export function OverviewView({
  identity,
  telemetry,
  state,
  error,
  onCollect,
  onRefreshAll,
  onSetUpBriefing,
  collectDisabled = false,
}: OverviewViewProps): ReactElement {
  const compact = useCompactLayout()
  const hasGrid = state === 'collecting' || state === 'ready'
  const desktop = !compact

  return <section
    aria-label="Overview"
    className={`hud-home-layout ${hasGrid
      ? compact
        ? 'grid w-full grid-cols-1 gap-4 md:grid-cols-2'
        : 'grid h-full min-h-0 w-full flex-1 grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)_minmax(0,1.55fr)] grid-rows-[repeat(6,minmax(0,1fr))] gap-4'
      : 'flex h-full min-h-0 w-full flex-1 items-center justify-center'} ${hasGrid ? 'hud-home-layout-enter' : ''}`}
  >
    {hasGrid ? (
      <WeatherTelemetry
        data={telemetry}
        variant="card"
        className={`overview-weather-center ${desktop ? 'col-start-2 row-start-1 row-span-2 min-w-0' : 'order-1 md:col-span-2 min-w-0'}`}
        narrow
        dataSlot="overview-weather"
      />
    ) : null}
    {hasGrid ? <EventsTelemetry data={telemetry} variant="card" className={desktop ? 'col-start-1 row-start-1 row-span-3 min-w-0' : 'order-2 min-w-0'} /> : null}
    {hasGrid ? <EmailTelemetry data={telemetry} variant="card" className={desktop ? 'col-start-3 row-start-1 row-span-3 min-w-0' : 'order-3 min-w-0'} /> : null}
    <div
      className={`hud-glass relative flex min-h-0 min-w-0 flex-col rounded-xl border border-white/10 bg-zinc-950/40 ${hasGrid
        ? desktop
          ? 'col-start-2 row-start-3 row-span-4 p-4'
          : 'order-first md:col-span-2 p-4'
        : compact
          ? 'w-full max-w-sm px-6 py-5'
          : 'h-2/3 w-[24.4%] max-w-[26rem] min-w-64 p-4'}`}
      data-slot="overview-identity-card"
    >
      {hasGrid ? (
        <>
          <header className="flex w-full shrink-0 items-center justify-end">
            <button
              type="button"
              onClick={onRefreshAll}
              disabled={state === 'collecting' || telemetry.isRefreshingAll || telemetry.isRefreshingAnyConnector}
              aria-label="Refresh All"
              title="Refresh All"
              className="inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[color:var(--hud-muted-text)] transition-colors hover:border-white/20 hover:bg-white/10 hover:text-[color:var(--hud-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RefreshCw className={`size-3.5 motion-reduce:animate-none ${state === 'collecting' || telemetry.isRefreshingAll ? 'animate-spin' : ''}`} strokeWidth={2} aria-hidden />
            </button>
          </header>
          <div className={`flex min-h-0 flex-1 flex-col items-center justify-center filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--logo-glow-color),0.6)] ${compact ? 'gap-3' : 'gap-4'}`} data-slot="home-identity" data-logo-size="overview">
            <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center">
              <ApexLogo
                {...identity.logoProps}
                className="hud-logo-mark h-56 w-auto max-h-full max-w-full aspect-[5208/5420] sm:h-64 xl:h-80 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
              />
            </div>
            <VoiceSignalGlyph {...identity.glyphProps} />
            <button
              type="button"
              onClick={onSetUpBriefing}
              aria-haspopup="dialog"
              className="inline-flex min-h-10 w-full max-w-xs shrink-0 items-center justify-center rounded-lg border border-[#1F6FE5]/50 bg-[#0F4DB8]/20 px-3 py-2 text-center font-orbitron text-[9px] font-semibold uppercase leading-snug tracking-[0.12em] text-[#DCEAFF] transition-[background-color,border-color,box-shadow] duration-200 motion-reduce:transition-none enabled:hover:border-[#6EA8FF]/70 enabled:hover:bg-[#0F4DB8]/35 enabled:hover:shadow-[0_0_16px_rgba(31,111,229,0.22)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]"
            >
              Set up briefing
            </button>
          </div>
        </>
      ) : (
        <>
          <header className="min-h-7 shrink-0" aria-hidden="true" />
          <div className={`flex min-h-0 flex-1 flex-col items-center justify-center ${compact ? 'gap-3' : 'gap-4'}`} data-slot="home-identity" data-logo-size="overview">
          <div className="filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] flex min-h-0 min-w-0 flex-1 items-center justify-center">
            <ApexLogo
              {...identity.logoProps}
              className="hud-logo-mark h-56 w-auto max-h-full max-w-full aspect-[5208/5420] sm:h-64 xl:h-80 transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
            />
          </div>
          <VoiceSignalGlyph {...identity.glyphProps} />
          {state === 'error' ? <div className="max-w-sm text-center" role="alert"><p className="font-mono text-sm text-rose-300">{error || 'I couldn’t collect telemetry just now.'}</p></div> : null}
          {state === 'no-data' ? <p className="font-mono text-sm text-zinc-400" role="status">No telemetry sources are available yet.</p> : null}
          {state === 'center' || state === 'error' || state === 'no-data' ? <TelemetryCollectionAction
            onCollect={onCollect}
            disabled={collectDisabled}
            label={state === 'error' || state === 'no-data' ? 'Retry Telemetry' : 'Collect Telemetry'}
          /> : null}
          </div>
        </>
      )}
    </div>
    {hasGrid ? <MarketTelemetry data={telemetry} variant="card" className={desktop ? 'col-start-1 row-start-4 row-span-3 min-w-0' : 'order-4 min-w-0'} /> : null}
    {hasGrid ? <RemindersTelemetry data={telemetry} variant="card" className={desktop ? 'col-start-3 row-start-4 row-span-3 min-w-0' : 'order-5 min-w-0'} /> : null}
  </section>
}
