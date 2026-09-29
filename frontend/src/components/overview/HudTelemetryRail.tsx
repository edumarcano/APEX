import type { ReactElement } from 'react'
import { Radio } from 'lucide-react'

import {
  EventsTelemetry,
  EmailTelemetry,
  MarketTelemetry,
  NewsTelemetry,
  RemindersTelemetry,
  WeatherTelemetry,
  type HudTelemetryData,
} from './HudTelemetry'
import { TelemetryCollectionAction } from './TelemetryCollectionAction'

export type BriefingTelemetryCollectionState = 'idle' | 'collecting' | 'error' | 'no-data'

/** Current telemetry beside a briefing; it is not the briefing's evidence snapshot. */
export function HudTelemetryRail({
  data,
  id,
  className = '',
  hasUsableSnapshot = data.hasSnapshot,
  collectionState = 'idle',
  collectionError = null,
  collectionDisabled = false,
  onCollect,
}: {
  data: HudTelemetryData
  id?: string
  className?: string
  hasUsableSnapshot?: boolean
  collectionState?: BriefingTelemetryCollectionState
  collectionError?: string | null
  collectionDisabled?: boolean
  onCollect?: () => void
}): ReactElement {
  return <aside id={id} className={`flex min-h-0 min-w-0 flex-col ${className}`} aria-label="Current telemetry">
    <p className="mb-2 shrink-0 font-mono text-[9px] uppercase tracking-wider text-zinc-500">Current telemetry, not the briefing snapshot</p>
    <div className="hud-glass flex min-h-0 flex-1 flex-col divide-y divide-white/[0.06] overflow-y-auto rounded-xl border border-white/10 bg-zinc-950/40 px-3 scrollbar-thin" data-slot="telemetry-rail-panel">
      {hasUsableSnapshot ? <>
        <WeatherTelemetry data={data} variant="section" />
        <EventsTelemetry data={data} variant="section" />
        <EmailTelemetry data={data} variant="section" />
        <NewsTelemetry data={data} variant="section" />
        <RemindersTelemetry data={data} variant="section" />
        <MarketTelemetry data={data} variant="section" />
      </> : <>
        <section className="flex-none py-4" aria-label="Telemetry collection" data-slot="telemetry-collection-empty-state">
          {collectionState === 'collecting' ? (
            <div className="flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-zinc-950/40 px-3 py-5 text-sm text-zinc-300" role="status">
              <Radio className="size-4 animate-pulse text-emerald-400 motion-reduce:animate-none" aria-hidden />
              <span>Collecting telemetry…</span>
            </div>
          ) : (
            <div className="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl border border-white/10 bg-zinc-950/40 px-4 py-5 text-center">
              {collectionState === 'error' ? <p className="max-w-sm font-mono text-xs leading-relaxed text-rose-300" role="alert">{collectionError || 'I couldn’t collect telemetry just now.'}</p> : null}
              {collectionState === 'no-data' ? <p className="max-w-sm font-mono text-xs leading-relaxed text-zinc-400" role="status">No telemetry sources are available yet.</p> : null}
              {collectionState === 'idle' ? <p className="max-w-sm font-mono text-xs leading-relaxed text-zinc-400">Collect current telemetry to populate this panel.</p> : null}
              <TelemetryCollectionAction
                onCollect={onCollect ?? (() => undefined)}
                label={collectionState === 'error' || collectionState === 'no-data' ? 'Retry Telemetry' : 'Collect Telemetry'}
                disabled={collectionDisabled || onCollect === undefined}
              />
            </div>
          )}
        </section>
        <RemindersTelemetry data={data} variant="section" />
      </>}
    </div>
  </aside>
}
