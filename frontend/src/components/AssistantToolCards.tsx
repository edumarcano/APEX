import { AlertCircle, Calendar, CloudRain, Flag, History, ListTodo } from 'lucide-react'
import type { ReactElement, ReactNode } from 'react'

import type { ActiveReminder, ToolOutputItem } from '../types/telemetry'

interface WeatherForecastDay {
  date: string
  temp_max: number
  temp_min: number
  condition: string
}

interface WeatherForecastPayload {
  location?: string
  forecast?: WeatherForecastDay[]
  error?: string
}

interface F1StandingEntry {
  position: number
  points: number
  wins: number
  driver_name: string
  driver_code: string
  team: string
}

interface F1StandingsPayload {
  season?: string
  round?: string
  standings?: F1StandingEntry[]
  error?: string
}

interface F1CalendarRace {
  round: number
  raceName: string
  circuitName: string
  country: string
  date: string
  time: string
}

interface F1CalendarPayload {
  season?: string
  calendar?: F1CalendarRace[]
  error?: string
}

interface CalendarEventEntry {
  summary: string
  start: string
}

interface CalendarEventsPayload {
  days_queried?: number
  events?: CalendarEventEntry[]
  error?: string
}

interface BriefingHistoryEntry {
  id: number
  timestamp: string
  briefing: string
  insights: string[]
}

interface BriefingHistoryPayload {
  limit_requested?: number
  briefings?: BriefingHistoryEntry[]
  message?: string
  error?: string
}

const CARD_SHELL =
  'w-full max-w-full rounded-xl border border-white/10 bg-white/[0.02] backdrop-blur-sm'
const CARD_HEADER =
  'flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2'
const CARD_BODY = 'px-3 py-2.5'
const LIST_SCROLL =
  'max-h-48 min-h-0 space-y-2 overflow-y-auto pr-1 scrollbar-thin sm:max-h-56'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatToolLabel(name: string): string {
  return name.replace(/^get_/, '').replace(/_/g, ' ')
}

function formatDisplayDate(isoDate: string): string {
  const parsed = new Date(`${isoDate}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) {
    return isoDate
  }
  return parsed.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

function formatEventStart(start: string): string {
  const parsed = new Date(start)
  if (Number.isNaN(parsed.getTime())) {
    return start
  }
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function truncateText(text: string, maxLength: number): string {
  const trimmed = text.trim()
  if (trimmed.length <= maxLength) {
    return trimmed
  }
  return `${trimmed.slice(0, maxLength - 1).trimEnd()}…`
}

function parseWeatherForecastPayload(output: unknown): WeatherForecastPayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }

  const forecast = Array.isArray(output.forecast)
    ? output.forecast
        .map((entry): WeatherForecastDay | null => {
          if (!isRecord(entry)) {
            return null
          }
          const date = typeof entry.date === 'string' ? entry.date : null
          const tempMax =
            typeof entry.temp_max === 'number' && Number.isFinite(entry.temp_max)
              ? entry.temp_max
              : null
          const tempMin =
            typeof entry.temp_min === 'number' && Number.isFinite(entry.temp_min)
              ? entry.temp_min
              : null
          const condition =
            typeof entry.condition === 'string' ? entry.condition : null

          if (!date || tempMax === null || tempMin === null || !condition) {
            return null
          }

          return {
            date,
            temp_max: tempMax,
            temp_min: tempMin,
            condition,
          }
        })
        .filter((entry): entry is WeatherForecastDay => entry !== null)
    : []

  return {
    location: typeof output.location === 'string' ? output.location : undefined,
    forecast,
  }
}

function parseF1StandingsPayload(output: unknown): F1StandingsPayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }

  const standings = Array.isArray(output.standings)
    ? output.standings
        .map((entry): F1StandingEntry | null => {
          if (!isRecord(entry)) {
            return null
          }
          const position =
            typeof entry.position === 'number' && Number.isFinite(entry.position)
              ? entry.position
              : null
          const points =
            typeof entry.points === 'number' && Number.isFinite(entry.points)
              ? entry.points
              : null
          const wins =
            typeof entry.wins === 'number' && Number.isFinite(entry.wins)
              ? entry.wins
              : null
          const driverName =
            typeof entry.driver_name === 'string' ? entry.driver_name : null
          const driverCode =
            typeof entry.driver_code === 'string' ? entry.driver_code : null
          const team = typeof entry.team === 'string' ? entry.team : null

          if (
            position === null ||
            points === null ||
            wins === null ||
            !driverName ||
            !driverCode ||
            !team
          ) {
            return null
          }

          return {
            position,
            points,
            wins,
            driver_name: driverName,
            driver_code: driverCode,
            team,
          }
        })
        .filter((entry): entry is F1StandingEntry => entry !== null)
    : []

  return {
    season: typeof output.season === 'string' ? output.season : undefined,
    round: typeof output.round === 'string' ? output.round : undefined,
    standings,
  }
}

function parseF1CalendarPayload(output: unknown): F1CalendarPayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }

  const calendar = Array.isArray(output.calendar)
    ? output.calendar
        .map((entry): F1CalendarRace | null => {
          if (!isRecord(entry)) {
            return null
          }
          const round =
            typeof entry.round === 'number' && Number.isFinite(entry.round)
              ? entry.round
              : null
          const raceName =
            typeof entry.raceName === 'string' ? entry.raceName : null
          const circuitName =
            typeof entry.circuitName === 'string' ? entry.circuitName : null
          const country = typeof entry.country === 'string' ? entry.country : null
          const date = typeof entry.date === 'string' ? entry.date : null
          const time = typeof entry.time === 'string' ? entry.time : ''

          if (
            round === null ||
            !raceName ||
            !circuitName ||
            !country ||
            !date
          ) {
            return null
          }

          return {
            round,
            raceName,
            circuitName,
            country,
            date,
            time,
          }
        })
        .filter((entry): entry is F1CalendarRace => entry !== null)
    : []

  return {
    season: typeof output.season === 'string' ? output.season : undefined,
    calendar,
  }
}

function parseCalendarEventsPayload(output: unknown): CalendarEventsPayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }

  const events = Array.isArray(output.events)
    ? output.events
        .map((entry): CalendarEventEntry | null => {
          if (!isRecord(entry)) {
            return null
          }
          const summary =
            typeof entry.summary === 'string' ? entry.summary : null
          const start = typeof entry.start === 'string' ? entry.start : null

          if (!summary || !start) {
            return null
          }

          return { summary, start }
        })
        .filter((entry): entry is CalendarEventEntry => entry !== null)
    : []

  return {
    days_queried:
      typeof output.days_queried === 'number' && Number.isFinite(output.days_queried)
        ? output.days_queried
        : undefined,
    events,
  }
}

function parseReminderList(output: unknown): ActiveReminder[] {
  if (!Array.isArray(output)) {
    return []
  }

  return output
    .map((entry): ActiveReminder | null => {
      if (!isRecord(entry)) {
        return null
      }
      const id =
        typeof entry.id === 'number' && Number.isFinite(entry.id) ? entry.id : null
      const note = typeof entry.note === 'string' ? entry.note : null

      if (id === null || !note) {
        return null
      }

      return { id, note }
    })
    .filter((entry): entry is ActiveReminder => entry !== null)
}

function parseBriefingHistoryPayload(output: unknown): BriefingHistoryPayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }
  if (typeof output.message === 'string') {
    return { message: output.message }
  }

  const briefings = Array.isArray(output.briefings)
    ? output.briefings
        .map((entry): BriefingHistoryEntry | null => {
          if (!isRecord(entry)) {
            return null
          }
          const id =
            typeof entry.id === 'number' && Number.isFinite(entry.id)
              ? entry.id
              : null
          const timestamp =
            typeof entry.timestamp === 'string' ? entry.timestamp : null
          const briefing =
            typeof entry.briefing === 'string' ? entry.briefing : null
          const insights = Array.isArray(entry.insights)
            ? entry.insights.filter(
                (insight): insight is string => typeof insight === 'string',
              )
            : []

          if (id === null || !timestamp || !briefing) {
            return null
          }

          return { id, timestamp, briefing, insights }
        })
        .filter((entry): entry is BriefingHistoryEntry => entry !== null)
    : []

  return {
    limit_requested:
      typeof output.limit_requested === 'number' &&
      Number.isFinite(output.limit_requested)
        ? output.limit_requested
        : undefined,
    briefings,
  }
}

function ToolCardFrame({
  title,
  icon,
  durationMs,
  accentClass,
  children,
}: {
  title: string
  icon: ReactNode
  durationMs: number
  accentClass: string
  children: ReactNode
}): ReactElement {
  return (
    <article className={CARD_SHELL} data-slot="assistant-tool-card">
      <header className={CARD_HEADER}>
        <div className="flex min-w-0 items-center gap-2">
          <span className={`shrink-0 ${accentClass}`}>{icon}</span>
          <h4 className="truncate font-mono text-[10px] uppercase tracking-[0.18em] text-zinc-300">
            {title}
          </h4>
        </div>
        <span className="shrink-0 font-mono text-[10px] text-zinc-500">
          {Math.round(durationMs)}ms
        </span>
      </header>
      <div className={CARD_BODY}>{children}</div>
    </article>
  )
}

export function ErrorFallbackCard({
  toolName,
  durationMs,
  message,
}: {
  toolName: string
  durationMs: number
  message: string
}): ReactElement {
  return (
    <ToolCardFrame
      title={`${formatToolLabel(toolName)} — error`}
      icon={<AlertCircle className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-red-400"
    >
      <p className="max-h-24 overflow-y-auto pr-1 text-sm leading-relaxed text-red-300/90 scrollbar-thin">
        {truncateText(message, 280)}
      </p>
    </ToolCardFrame>
  )
}

function WeatherForecastCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseWeatherForecastPayload(output)

  if (!payload || payload.error) {
    return (
      <ErrorFallbackCard
        toolName="get_weather_forecast"
        durationMs={durationMs}
        message={payload?.error ?? 'Weather forecast payload is unavailable.'}
      />
    )
  }

  const days = payload.forecast ?? []

  return (
    <ToolCardFrame
      title="Weather Forecast"
      icon={<CloudRain className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#7EB3FF]"
    >
      {payload.location ? (
        <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
          {payload.location}
        </p>
      ) : null}
      <ul className={LIST_SCROLL}>
        {days.length === 0 ? (
          <li className="text-sm text-zinc-500">No forecast days returned.</li>
        ) : (
          days.map((day) => (
            <li
              key={day.date}
              className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2"
            >
              <div className="min-w-0">
                <p className="font-mono text-[11px] uppercase tracking-wide text-zinc-400">
                  {formatDisplayDate(day.date)}
                </p>
                <span className="mt-1 inline-flex rounded-full border border-[#0F4DB8]/30 bg-[#0F4DB8]/10 px-2 py-0.5 text-[10px] capitalize text-[#7EB3FF]">
                  {day.condition}
                </span>
              </div>
              <div className="shrink-0 text-right font-mono text-xs">
                <p className="text-[#FBBF24]">{Math.round(day.temp_max)}°</p>
                <p className="text-zinc-500">{Math.round(day.temp_min)}°</p>
              </div>
            </li>
          ))
        )}
      </ul>
    </ToolCardFrame>
  )
}

function F1StandingsCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseF1StandingsPayload(output)

  if (!payload || payload.error) {
    return (
      <ErrorFallbackCard
        toolName="get_f1_driver_standings"
        durationMs={durationMs}
        message={payload?.error ?? 'F1 standings payload is unavailable.'}
      />
    )
  }

  const standings = payload.standings ?? []

  return (
    <ToolCardFrame
      title="F1 Driver Standings"
      icon={<Flag className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#FBBF24]"
    >
      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
        Season {payload.season ?? '—'}
        {payload.round ? ` · Round ${payload.round}` : ''}
      </p>
      <div className={LIST_SCROLL}>
        {standings.length === 0 ? (
          <p className="text-sm text-zinc-500">No standings returned.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[16rem] border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-white/10 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="pb-2 pr-2">Pos</th>
                  <th className="pb-2 pr-2">Driver</th>
                  <th className="pb-2 pr-2">Team</th>
                  <th className="pb-2 text-right">Pts</th>
                </tr>
              </thead>
              <tbody>
                {standings.map((entry) => (
                  <tr
                    key={`${entry.position}-${entry.driver_code}`}
                    className="border-b border-white/5 text-zinc-200 last:border-b-0"
                  >
                    <td className="py-1.5 pr-2 font-mono text-zinc-400">
                      {entry.position}
                    </td>
                    <td className="py-1.5 pr-2">
                      <span className="font-medium text-white">{entry.driver_name}</span>
                      <span className="ml-1 font-mono text-[10px] text-zinc-500">
                        {entry.driver_code}
                      </span>
                    </td>
                    <td className="max-w-[8rem] truncate py-1.5 pr-2 text-zinc-400">
                      {entry.team}
                    </td>
                    <td className="py-1.5 text-right font-mono text-[#FBBF24]">
                      {entry.points}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </ToolCardFrame>
  )
}

function F1CalendarCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseF1CalendarPayload(output)

  if (!payload || payload.error) {
    return (
      <ErrorFallbackCard
        toolName="get_f1_season_calendar"
        durationMs={durationMs}
        message={payload?.error ?? 'F1 calendar payload is unavailable.'}
      />
    )
  }

  const races = [...(payload.calendar ?? [])].sort((left, right) => left.round - right.round)

  return (
    <ToolCardFrame
      title="F1 Season Calendar"
      icon={<Flag className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#FBBF24]"
    >
      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
        Season {payload.season ?? '—'}
      </p>
      <ol className={LIST_SCROLL}>
        {races.length === 0 ? (
          <li className="text-sm text-zinc-500">No races returned.</li>
        ) : (
          races.map((race) => (
            <li
              key={`${race.round}-${race.raceName}`}
              className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-zinc-100">
                    R{race.round} · {race.raceName}
                  </p>
                  <p className="truncate text-xs text-zinc-500">
                    {race.circuitName}, {race.country}
                  </p>
                </div>
                <span className="shrink-0 font-mono text-[10px] text-zinc-400">
                  {formatDisplayDate(race.date)}
                </span>
              </div>
            </li>
          ))
        )}
      </ol>
    </ToolCardFrame>
  )
}

function CalendarEventsCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseCalendarEventsPayload(output)

  if (!payload || payload.error) {
    return (
      <ErrorFallbackCard
        toolName="get_upcoming_calendar_events"
        durationMs={durationMs}
        message={payload?.error ?? 'Calendar events payload is unavailable.'}
      />
    )
  }

  const events = payload.events ?? []

  return (
    <ToolCardFrame
      title="Upcoming Calendar"
      icon={<Calendar className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#7EB3FF]"
    >
      {payload.days_queried ? (
        <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
          Next {payload.days_queried} day{payload.days_queried === 1 ? '' : 's'}
        </p>
      ) : null}
      <ul className={LIST_SCROLL}>
        {events.length === 0 ? (
          <li className="text-sm text-zinc-500">No upcoming events.</li>
        ) : (
          events.map((event, index) => (
            <li
              key={`${event.summary}-${event.start}-${index}`}
              className="flex items-start justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2"
            >
              <p className="min-w-0 flex-1 text-sm text-zinc-200">{event.summary}</p>
              <span className="shrink-0 font-mono text-[10px] text-[#FBBF24]">
                {formatEventStart(event.start)}
              </span>
            </li>
          ))
        )}
      </ul>
    </ToolCardFrame>
  )
}

function ReminderListCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const reminders = parseReminderList(output)

  return (
    <ToolCardFrame
      title="Active Reminders"
      icon={<ListTodo className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#39FF88]"
    >
      <ul className={LIST_SCROLL}>
        {reminders.length === 0 ? (
          <li className="text-sm text-zinc-500">No pending reminders.</li>
        ) : (
          reminders.map((reminder) => (
            <li
              key={reminder.id}
              className="rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2 text-sm leading-relaxed text-zinc-200"
            >
              <span className="mr-2 font-mono text-[10px] text-zinc-500">
                #{reminder.id}
              </span>
              {reminder.note}
            </li>
          ))
        )}
      </ul>
    </ToolCardFrame>
  )
}

function BriefingHistoryCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseBriefingHistoryPayload(output)

  if (!payload || payload.error) {
    return (
      <ErrorFallbackCard
        toolName="get_briefing_history"
        durationMs={durationMs}
        message={payload?.error ?? 'Briefing history payload is unavailable.'}
      />
    )
  }

  if (payload.message) {
    return (
      <ToolCardFrame
        title="Briefing History"
        icon={<History className="size-3.5" aria-hidden />}
        durationMs={durationMs}
        accentClass="text-[#FBBF24]"
      >
        <p className="text-sm text-zinc-400">{payload.message}</p>
      </ToolCardFrame>
    )
  }

  const briefings = payload.briefings ?? []

  return (
    <ToolCardFrame
      title="Briefing History"
      icon={<History className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#FBBF24]"
    >
      <ul className={LIST_SCROLL}>
        {briefings.length === 0 ? (
          <li className="text-sm text-zinc-500">No briefing records returned.</li>
        ) : (
          briefings.map((entry) => (
            <li
              key={entry.id}
              className="space-y-1.5 rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2"
            >
              <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                {formatEventStart(entry.timestamp)}
              </p>
              <p className="text-sm leading-relaxed text-zinc-200">
                {truncateText(entry.briefing, 180)}
              </p>
              {entry.insights.length > 0 ? (
                <ul className="space-y-1 border-t border-white/5 pt-1.5">
                  {entry.insights.slice(0, 3).map((insight, index) => (
                    <li
                      key={`${entry.id}-insight-${index}`}
                      className="text-xs text-[#FBBF24]/90"
                    >
                      {truncateText(insight, 120)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))
        )}
      </ul>
    </ToolCardFrame>
  )
}

function resolveErrorMessage(output: unknown): string {
  if (typeof output === 'string') {
    return output
  }
  if (isRecord(output) && typeof output.error === 'string') {
    return output.error
  }
  return 'Tool execution failed.'
}

function ToolOutputCard({ item }: { item: ToolOutputItem }): ReactElement {
  if (item.status.toLowerCase() === 'error') {
    return (
      <ErrorFallbackCard
        toolName={item.name}
        durationMs={item.duration_ms}
        message={resolveErrorMessage(item.output)}
      />
    )
  }

  switch (item.name) {
    case 'get_weather_forecast':
      return (
        <WeatherForecastCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'get_f1_driver_standings':
      return (
        <F1StandingsCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'get_f1_season_calendar':
      return <F1CalendarCard durationMs={item.duration_ms} output={item.output} />
    case 'get_upcoming_calendar_events':
      return (
        <CalendarEventsCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'get_active_reminders':
      return (
        <ReminderListCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'get_briefing_history':
      return (
        <BriefingHistoryCard durationMs={item.duration_ms} output={item.output} />
      )
    default:
      return (
        <ErrorFallbackCard
          toolName={item.name}
          durationMs={item.duration_ms}
          message="Structured card unavailable for this tool output."
        />
      )
  }
}

export function AssistantToolCards({
  toolOutputs,
}: {
  toolOutputs: ToolOutputItem[]
}): ReactElement | null {
  if (toolOutputs.length === 0) {
    return null
  }

  return (
    <div className="mt-3 grid w-full max-w-full grid-cols-1 gap-3 lg:grid-cols-2">
      {toolOutputs.map((item, index) => (
        <ToolOutputCard
          key={`${item.name}-${item.duration_ms}-${index}`}
          item={item}
        />
      ))}
    </div>
  )
}
