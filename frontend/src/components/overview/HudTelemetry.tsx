import { Calendar, CheckSquare, Clock, CloudSun, Mail } from 'lucide-react'
import type { ComponentProps, ReactElement } from 'react'

import type { AttentionTier } from '../../lib/attentionTier'
import type { resolveModuleLedState } from '../../lib/moduleTelemetry'
import type { ResolvedWeatherInfo } from '../../lib/weatherTelemetry'
import type { TelemetryContentState } from '../../lib/emailTelemetry'
import type { ActiveReminder } from '../../types/telemetry'
import { CalendarEventList } from '../CalendarEventList'
import { FootballFixtureList } from '../FootballFixtureList'
import { MarketTickerCard } from '../MarketTickerCard'
import { ReminderListRow } from '../ReminderListRow'
import { ReminderQuickAdd } from '../ReminderQuickAdd'
import { ScrollFadeContainer } from '../ScrollFadeContainer'
import { TelemetryCard } from '../TelemetryCard'

type LedState = ReturnType<typeof resolveModuleLedState>
type Surface = 'weather' | 'events' | 'market' | 'email' | 'reminders'

/** App-derived telemetry view model shared by Overview cards and the Briefing rail. */
export type HudTelemetryData = {
  hasSnapshot: boolean
  isRefreshingAll: boolean
  isRefreshingAnyConnector: boolean
  onRefreshConnector: (name: string) => void
  attentionTiers: Record<Surface, AttentionTier>
  attentionStagger: Record<Surface, number>
  weather: {
    info: ResolvedWeatherInfo
    body: string
    ledState: LedState
    statusMessage: string | null
    showAttribution: boolean
  }
  events: {
    f1Text: string
    ledState: LedState
    statusMessage: string | null
    compactValue: string | null
    calendar: ComponentProps<typeof CalendarEventList>['telemetry']
    football: ComponentProps<typeof FootballFixtureList>['telemetry']
    footballModule: ComponentProps<typeof FootballFixtureList>['module']
    calendarRefreshing: boolean
    f1Refreshing: boolean
    footballRefreshing: boolean
  }
  market: {
    data: ComponentProps<typeof MarketTickerCard>['data']
    isLoading: boolean
    enabled: boolean
  }
  email: {
    ledState: LedState
    statusMessage: string | null
    compactValue: string | null
    state: TelemetryContentState
    count: number | null
    items: Array<{ subject: string; time: string }>
    refreshing: boolean
  }
  reminders: {
    loadState: 'loading' | 'loaded' | 'unavailable'
    ledState: LedState
    statusMessage: string | null
    compactValue: string
    items: ActiveReminder[]
    sourceState: string | null
    actionError: string | null
    refreshDisabled: boolean
    onRefresh: () => void
    onOpenCompleted: () => void
    onSave: ComponentProps<typeof ReminderQuickAdd>['onSave']
    onMarkRead: (id: string) => void
    onEdit: (id: string) => void
    onDelete: (id: string) => void
    onReview: () => void
  }
}

export type HudTelemetryVariant = 'card' | 'section'

type DomainProps = {
  data: HudTelemetryData
  variant: HudTelemetryVariant
  className?: string
}

function layoutClass(variant: HudTelemetryVariant, className?: string): string {
  return [variant === 'card' ? 'min-h-0 h-full' : 'h-auto! flex-none', className].filter(Boolean).join(' ')
}

export function WeatherTelemetry({ data, variant, className, narrow = false, dataSlot }: DomainProps & { narrow?: boolean; dataSlot?: string }): ReactElement {
  const { weather } = data
  const attribution = (
    <span
      className={`${variant === 'card' ? 'justify-end' : ''} flex min-w-0 flex-wrap items-center gap-x-1 text-[9px] leading-tight text-[color:var(--hud-muted-text)]`}
      aria-label="Weather by Open-Meteo. Location by GeoNames. Licensed under CC BY 4.0. Adapted by APEX."
    >
      <span>Weather by</span>
      <a href="https://open-meteo.com/" target="_blank" rel="noreferrer" className="hover:text-[color:var(--hud-text)]">Open-Meteo</a>
      <span>· Location by</span>
      <a href="https://www.geonames.org/" target="_blank" rel="noreferrer" className="hover:text-[color:var(--hud-text)]">GeoNames</a>
      <span>·</span>
      <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer" className="hover:text-[color:var(--hud-text)]">CC BY 4.0</a>
      <span>· adapted by APEX</span>
    </span>
  )
  return <TelemetryCard
    title="Weather"
    icon={CloudSun}
    data-slot={dataSlot}
    primaryTemperatureF={weather.info.temperatureF}
    apparentTemperatureF={weather.info.apparentTempF}
    tempMaxF={weather.info.tempMaxF}
    tempMinF={weather.info.tempMinF}
    windSpeedMph={weather.info.windSpeedMph}
    weatherTimeline={weather.info.timeline}
    weatherCondition={weather.info.condition}
    ledState={weather.ledState}
    onRefresh={() => data.onRefreshConnector('weather')}
    refreshDisabled={data.isRefreshingAll}
    statusMessage={weather.statusMessage}
    compactValue={weather.body}
    headerAction={weather.showAttribution ? attribution : undefined}
    headerActionBelow={variant === 'section' || narrow}
    weatherStacked={narrow}
    attentionTier={data.attentionTiers.weather}
    attentionStaggerMs={data.attentionStagger.weather}
    className={layoutClass(variant, className)}
    chrome={variant === 'section' ? 'section' : 'card'}
  >
    {weather.info.temperatureF == null ? (
      <p className="line-clamp-2 break-words text-[13px] leading-relaxed text-[color:var(--hud-text)]">{weather.body}</p>
    ) : null}
  </TelemetryCard>
}

export function EventsTelemetry({ data, variant, className }: DomainProps): ReactElement {
  const { events } = data
  return <TelemetryCard
    title="Events"
    icon={Calendar}
    f1TelemetryText={events.f1Text}
    ledState={events.ledState}
    refreshActions={[
      { label: 'Calendar', onRefresh: () => data.onRefreshConnector('calendar'), disabled: data.isRefreshingAll, loading: events.calendarRefreshing },
      { label: 'F1', onRefresh: () => data.onRefreshConnector('f1'), disabled: data.isRefreshingAll, loading: events.f1Refreshing },
      { label: 'Football', onRefresh: () => data.onRefreshConnector('football'), disabled: data.isRefreshingAll, loading: events.footballRefreshing },
    ]}
    statusMessage={events.statusMessage}
    compactValue={events.compactValue}
    attentionTier={data.attentionTiers.events}
    attentionStaggerMs={data.attentionStagger.events}
    className={layoutClass(variant, className)}
    chrome={variant === 'section' ? 'section' : 'card'}
  >
    {events.calendarRefreshing && !data.hasSnapshot ? (
      <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">Loading schedule…</p>
    ) : (
      <>
        <CalendarEventList telemetry={events.calendar} hasSnapshot={data.hasSnapshot} stacked={variant === 'section'} />
        <FootballFixtureList telemetry={events.football} module={events.footballModule} hasSnapshot={data.hasSnapshot} stacked={variant === 'section'} />
      </>
    )}
  </TelemetryCard>
}

export function MarketTelemetry({ data, variant, className }: DomainProps): ReactElement {
  return <MarketTickerCard
    data={data.market.data}
    isLoading={data.market.isLoading}
    enabled={data.market.enabled}
    attentionTier={data.attentionTiers.market}
    attentionStaggerMs={data.attentionStagger.market}
    className={`w-full ${layoutClass(variant, className)}`}
    chrome={variant === 'section' ? 'section' : 'card'}
  />
}

export function EmailTelemetry({ data, variant, className }: DomainProps): ReactElement {
  const { email } = data
  return <TelemetryCard
    title="Email"
    icon={Mail}
    ledState={email.ledState}
    onRefresh={() => data.onRefreshConnector('email')}
    refreshDisabled={data.isRefreshingAll}
    statusMessage={email.statusMessage}
    compactValue={email.compactValue}
    attentionTier={data.attentionTiers.email}
    attentionStaggerMs={data.attentionStagger.email}
    className={layoutClass(variant, className)}
    chrome={variant === 'section' ? 'section' : 'card'}
  >
    {email.refreshing && email.state === 'unavailable' ? (
      <p className="animate-pulse text-sm text-[color:var(--hud-muted-text)]">Loading email…</p>
    ) : email.state === 'unavailable' ? (
      <p className="text-sm text-[color:var(--hud-muted-text)]">Email unavailable.</p>
    ) : email.state === 'disabled' ? (
      <p className="text-sm text-[color:var(--hud-muted-text)]">Email disabled.</p>
    ) : (
      <>
        {email.count !== null && email.count > 0 && (
          <p className="mb-2 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--hud-accent)]">{email.count} Primary Messages</p>
        )}
        {email.items.length > 0 ? (
          <ScrollFadeContainer as="ul" className="min-h-0 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
            {email.items.map((item, index) => (
              <li key={`${item.subject}-${item.time}-${index}`} className="flex items-start justify-between gap-3">
                <span className="flex min-w-0 items-start gap-2">
                  <span className="hud-log-index">{String(index).padStart(2, '0')}</span>
                  <span className="break-words text-sm text-zinc-200">{item.subject}</span>
                </span>
                <span className="shrink-0 font-mono text-xs text-zinc-500">{item.time}</span>
              </li>
            ))}
          </ScrollFadeContainer>
        ) : email.count === 0 ? (
          <p className="text-sm text-[color:var(--hud-muted-text)]">No unread emails.</p>
        ) : (
          <p className="text-sm text-[color:var(--hud-muted-text)]">Message previews unavailable.</p>
        )}
      </>
    )}
  </TelemetryCard>
}

export function RemindersTelemetry({ data, variant, className }: DomainProps): ReactElement {
  const { reminders } = data
  return <TelemetryCard
    title="Reminders"
    icon={CheckSquare}
    ledState={reminders.ledState}
    onRefresh={reminders.onRefresh}
    refreshDisabled={reminders.refreshDisabled}
    statusMessage={reminders.statusMessage}
    compactValue={reminders.compactValue}
    attentionTier={data.attentionTiers.reminders}
    attentionStaggerMs={data.attentionStagger.reminders}
    className={layoutClass(variant, className)}
    chrome={variant === 'section' ? 'section' : 'card'}
    role="region"
    aria-label="Active reminders"
    data-slot="reminders-card"
    headerAction={(
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={reminders.onOpenCompleted}
          aria-label="Completed reminders"
          title="Completed reminders"
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[color:var(--hud-text)] transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
        >
          <Clock className="size-3.5 text-[color:var(--hud-accent)]" strokeWidth={2} aria-hidden />
        </button>
        <ReminderQuickAdd onSave={reminders.onSave} />
      </div>
    )}
  >
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {reminders.loadState === 'loading' ? (
        <p className="text-sm text-[color:var(--hud-muted-text)]" role="status">Loading reminders…</p>
      ) : reminders.items.length === 0 && (reminders.loadState === 'unavailable' || reminders.sourceState === 'unavailable') ? (
        <div className="flex flex-col items-start gap-2" role="status">
          <p className="text-sm text-[color:var(--hud-muted-text)]">Reminders unavailable.</p>
          <button type="button" onClick={reminders.onRefresh} disabled={reminders.refreshDisabled} className="font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Retry Reminders</button>
        </div>
      ) : reminders.items.length === 0 ? (
        <div className="rounded-md border border-white/[0.06] bg-zinc-950/20 px-3 py-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-500">No pending reminders</p>
        </div>
      ) : (
        <ScrollFadeContainer as="ul" className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
          {reminders.items.map((reminder, index) => (
            <ReminderListRow
              key={reminder.id}
              reminder={reminder}
              index={index}
              onMarkRead={reminders.onMarkRead}
              onEdit={reminders.onEdit}
              onDelete={reminders.onDelete}
            />
          ))}
        </ScrollFadeContainer>
      )}
      {reminders.sourceState && reminders.sourceState !== 'live' ? (
        <p className="mt-2 font-mono text-[9px] uppercase tracking-wide text-amber-200">Reminder source: {reminders.sourceState}</p>
      ) : null}
      {reminders.actionError ? (
        <p className="mt-2 text-xs leading-relaxed text-red-200" role="alert">{reminders.actionError}</p>
      ) : null}
      {reminders.items.some((item) => item.source === 'local') ? (
        <button type="button" onClick={reminders.onReview} className="mt-2 self-start font-mono text-[10px] uppercase tracking-wide text-[#9AC2FF] hover:text-white">
          Review local reminders
        </button>
      ) : null}
    </div>
  </TelemetryCard>
}
