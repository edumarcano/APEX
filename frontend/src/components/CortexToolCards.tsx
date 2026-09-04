import {
  AlertCircle,
  BookOpen,
  Calendar,
  CloudRain,
  Flag,
  History,
  ListTodo,
  Mail,
  Network,
  Search,
} from 'lucide-react'
import type { ReactElement, ReactNode } from 'react'

import type { ActiveReminder, ToolOutputItem } from '../types/telemetry'

interface WeatherCurrentConditions {
  temp_f: number
  apparent_temp_f?: number
  humidity_pct?: number
  wind_speed_mph?: number
  condition: string
  archetype?: string
}

interface WeatherForecastDay {
  date: string
  temp_max: number
  temp_min: number
  condition: string
  precip_probability_max?: number
  precip_sum_in?: number
  wind_speed_max_mph?: number
  uv_index_max?: number
}

interface WeatherForecastPayload {
  location?: string
  current?: WeatherCurrentConditions
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
  end?: string | null
  all_day?: boolean
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

interface DocumentationResult {
  path: string
  heading: string | null
  line_start: number
  line_end: number
  text: string
  score: number
}

interface DocumentationSearchPayload {
  retrieval_mode: string
  trust: string
  results: DocumentationResult[]
}

interface GmailMetadata {
  id: string
  thread_id: string
  sender: string
  subject: string
  date: string
  labels: string[]
  snippet: string
}

interface GmailSearchResult {
  query?: string
  result_count?: number
  messages: GmailMetadata[]
}

interface GmailMessage extends GmailMetadata {
  body: string
  truncated: boolean
}

interface MicrosoftTodoList {
  id: string
  display_name: string
  is_owner: boolean
  is_shared: boolean
}

interface MicrosoftTodoListsPayload {
  lists: MicrosoftTodoList[]
}

interface MicrosoftTodoDateTime {
  date_time: string
  time_zone: string
}

interface MicrosoftTodoTask {
  id: string
  title: string
  status: string
  importance: string
  is_completed: boolean
  due: MicrosoftTodoDateTime | null
}

interface MicrosoftTodoTasksPayload {
  tasks: MicrosoftTodoTask[]
  include_completed: boolean
}

function parseTodoDateTime(value: unknown): MicrosoftTodoDateTime | null {
  if (!isRecord(value) || typeof value.date_time !== 'string') return null
  return {
    date_time: value.date_time,
    time_zone: typeof value.time_zone === 'string' ? value.time_zone : '',
  }
}
interface ToolErrorPayload {

  error: string
}

type GmailSearchPayload = GmailSearchResult | ToolErrorPayload
type GmailMessagePayload = GmailMessage | ToolErrorPayload

const CARD_SHELL =
  'w-full max-w-full rounded-xl border border-white/10 bg-white/[0.02] backdrop-blur-sm'
const CARD_HEADER =
  'flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2'
const CARD_BODY = 'px-3 py-2.5'
const LIST_SCROLL =
  'max-h-48 min-h-0 space-y-2 overflow-y-auto pr-1 scrollbar-thin sm:max-h-56'
const MCP_PROVIDER_LABELS: Record<string, string> = {
  github: 'GitHub',
  brave: 'Brave Search',
  alphavantage: 'Alpha Vantage',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

interface ActionProposalToolOutput {
  action_id: string
  status: 'proposed'
  version: number
  risk: 'write' | 'destructive'
  summary: string
  target: string
}

function parseActionProposalToolOutput(value: unknown): ActionProposalToolOutput | null {
  if (!isRecord(value)) return null
  if (
    typeof value.action_id !== 'string' ||
    value.status !== 'proposed' ||
    typeof value.version !== 'number' ||
    !Number.isInteger(value.version) ||
    (value.risk !== 'write' && value.risk !== 'destructive') ||
    typeof value.summary !== 'string' ||
    typeof value.target !== 'string'
  ) return null
  return {
    action_id: value.action_id,
    status: value.status,
    version: value.version,
    risk: value.risk,
    summary: value.summary,
    target: value.target,
  }
}

function formatToolLabel(name: string): string {
  return name.replace(/^get_/, '').replace(/_/g, ' ')
}

function parseMcpToolName(
  name: string,
): { provider: string; operation: string } | null {
  for (const [prefix, provider] of Object.entries(MCP_PROVIDER_LABELS)) {
    const marker = `${prefix}_`
    if (name.startsWith(marker) && name.length > marker.length) {
      const remoteName = name.slice(marker.length)
      const operationName = remoteName.startsWith(marker)
        ? remoteName.slice(marker.length)
        : remoteName
      return {
        provider,
        operation: operationName.replace(/_/g, ' '),
      }
    }
  }
  return null
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

function formatEventStart(start: string, allDay = false): string {
  if (allDay) {
    return `${formatDisplayDate(start)} · All day`
  }
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

function formatEmailDate(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return truncateText(value, 80)
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

  let current: WeatherCurrentConditions | undefined
  if (isRecord(output.current)) {
    const tempF = typeof output.current.temp_f === 'number' && Number.isFinite(output.current.temp_f) ? output.current.temp_f : null
    const condition = typeof output.current.condition === 'string' ? output.current.condition : null
    if (tempF !== null && condition) {
      current = {
        temp_f: tempF,
        condition,
        apparent_temp_f: typeof output.current.apparent_temp_f === 'number' && Number.isFinite(output.current.apparent_temp_f) ? output.current.apparent_temp_f : undefined,
        humidity_pct: typeof output.current.humidity_pct === 'number' && Number.isFinite(output.current.humidity_pct) ? output.current.humidity_pct : undefined,
        wind_speed_mph: typeof output.current.wind_speed_mph === 'number' && Number.isFinite(output.current.wind_speed_mph) ? output.current.wind_speed_mph : undefined,
        archetype: typeof output.current.archetype === 'string' ? output.current.archetype : undefined,
      }
    }
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
            precip_probability_max: typeof entry.precip_probability_max === 'number' && Number.isFinite(entry.precip_probability_max) ? entry.precip_probability_max : undefined,
            precip_sum_in: typeof entry.precip_sum_in === 'number' && Number.isFinite(entry.precip_sum_in) ? entry.precip_sum_in : undefined,
            wind_speed_max_mph: typeof entry.wind_speed_max_mph === 'number' && Number.isFinite(entry.wind_speed_max_mph) ? entry.wind_speed_max_mph : undefined,
            uv_index_max: typeof entry.uv_index_max === 'number' && Number.isFinite(entry.uv_index_max) ? entry.uv_index_max : undefined,
          }
        })
        .filter((entry): entry is WeatherForecastDay => entry !== null)
    : []

  return {
    location: typeof output.location === 'string' ? output.location : undefined,
    current,
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

          return {
            summary,
            start,
            end: typeof entry.end === 'string' ? entry.end : null,
            all_day: entry.all_day === true,
          }
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

function parseGmailSearchPayload(output: unknown): GmailSearchPayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }

  const messages = Array.isArray(output.messages)
    ? output.messages
        .map(parseGmailMetadata)
        .filter((entry): entry is GmailMetadata => entry !== null)
    : []

  return {
    query: typeof output.query === 'string' ? output.query : undefined,
    result_count:
      typeof output.result_count === 'number' &&
      Number.isFinite(output.result_count)
        ? output.result_count
        : messages.length,
    messages,
  }
}

function parseGmailMessagePayload(output: unknown): GmailMessagePayload | null {
  if (!isRecord(output)) {
    return null
  }
  if (typeof output.error === 'string') {
    return { error: output.error }
  }
  const metadata = parseGmailMetadata(output)
  if (!metadata) {
    return null
  }
  return {
    ...metadata,
    body: typeof output.body === 'string' ? output.body : '',
    truncated: output.truncated === true,
  }
}

function parseGmailMetadata(output: unknown): GmailMetadata | null {
  if (!isRecord(output) || typeof output.id !== 'string' || !output.id) {
    return null
  }
  return {
    id: output.id,
    thread_id:
      typeof output.thread_id === 'string' ? output.thread_id : '',
    sender: typeof output.sender === 'string' ? output.sender : '',
    subject: typeof output.subject === 'string' ? output.subject : '',
    date: typeof output.date === 'string' ? output.date : '',
    labels: Array.isArray(output.labels)
      ? output.labels.filter(
          (label): label is string => typeof label === 'string',
        )
      : [],
    snippet: typeof output.snippet === 'string' ? output.snippet : '',
  }
}

function parseMicrosoftTodoLists(output: unknown): MicrosoftTodoListsPayload | null {
  if (!isRecord(output) || !Array.isArray(output.lists)) return null
  const lists = output.lists
    .map((item): MicrosoftTodoList | null => {
      if (!isRecord(item) || typeof item.id !== 'string' || typeof item.display_name !== 'string') return null
      return {
        id: item.id,
        display_name: item.display_name,
        is_owner: item.is_owner === true,
        is_shared: item.is_shared === true,
      }
    })
    .filter((item): item is MicrosoftTodoList => item !== null)
  return { lists }
}

function parseMicrosoftTodoTasks(output: unknown): MicrosoftTodoTasksPayload | null {
  if (!isRecord(output) || !Array.isArray(output.tasks)) return null
  const tasks = output.tasks
    .map((item): MicrosoftTodoTask | null => {
      if (!isRecord(item) || typeof item.id !== 'string' || typeof item.title !== 'string') return null
      return {
        id: item.id,
        title: item.title,
        status: typeof item.status === 'string' ? item.status : '',
        importance: typeof item.importance === 'string' ? item.importance : '',
        is_completed: item.is_completed === true,
        due: parseTodoDateTime(item.due),
      }
    })
    .filter((item): item is MicrosoftTodoTask => item !== null)
  return { tasks, include_completed: output.include_completed === true }
}

function formatTodoDue(value: MicrosoftTodoDateTime | null): string | null {
  if (!value?.date_time) return null
  const parsed = new Date(value.date_time)
  if (Number.isNaN(parsed.getTime())) return value.date_time
  const hasTime = /T\d{2}:\d{2}/.test(value.date_time)
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    ...(hasTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(parsed)
}

function TodoSourceLabel(): ReactElement {
  return (
    <p className="mb-2 font-mono text-[9px] uppercase tracking-wider text-[#7EB3FF]">
      Microsoft To Do · Read only
    </p>
  )
}

function parseReminderList(output: unknown): ActiveReminder[] {
  const items = isRecord(output) ? output.items : output
  if (!Array.isArray(items)) {
    return []
  }

  return items
    .map((entry): ActiveReminder | null => {
      if (!isRecord(entry)) {
        return null
      }
      const id = typeof entry.id === 'string' ? entry.id : null
      const note = typeof entry.note === 'string' ? entry.note : null
      const source = entry.source === 'todo' || entry.source === 'local' ? entry.source : null
      const syncState = entry.sync_state === 'synced' || entry.sync_state === 'pending' || entry.sync_state === 'unknown'
        ? entry.sync_state
        : null

      if (id === null || !note || source === null || syncState === null) {
        return null
      }

      return { id, note, source, sync_state: syncState }
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

function parseDocumentationSearchPayload(output: unknown): DocumentationSearchPayload | null {
  if (!isRecord(output) || !Array.isArray(output.results) || typeof output.retrieval_mode !== 'string' || typeof output.trust !== 'string') return null
  const results = output.results.flatMap((value): DocumentationResult[] => {
    if (!isRecord(value) || typeof value.path !== 'string' || typeof value.line_start !== 'number' || typeof value.line_end !== 'number' || typeof value.text !== 'string' || typeof value.score !== 'number') return []
    return [{ path: value.path, heading: typeof value.heading === 'string' ? value.heading : null, line_start: value.line_start, line_end: value.line_end, text: value.text, score: value.score }]
  })
  return { retrieval_mode: output.retrieval_mode, trust: output.trust, results }
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
          <h4 className="truncate font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-300">
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

function ActionProposalCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: ActionProposalToolOutput
}): ReactElement {
  return (
    <ToolCardFrame
      title="Action proposed"
      icon={<ListTodo className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass={output.risk === 'destructive' ? 'text-red-300' : 'text-[#C084FC]'}
    >
      <p className="text-sm font-medium text-zinc-100">{output.summary}</p>
      <p className="mt-1 text-xs text-zinc-400">{output.target}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-wide">
        <span className={output.risk === 'destructive' ? 'text-red-200' : 'text-[#C084FC]'}>{output.risk}</span>
        <span className="text-amber-100">Pending approval</span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-zinc-500">Review this action in the Cortex Actions inspector.</p>
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
      {payload.location || payload.current ? (
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2 border-b border-white/5 pb-2">
          {payload.location ? (
            <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-400">
              {payload.location}
            </p>
          ) : null}
          {payload.current ? (
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="font-semibold text-white">
                {payload.current.temp_f}°
              </span>
              <span className="text-[11px] capitalize text-zinc-300">
                {payload.current.condition}
              </span>
              {payload.current.apparent_temp_f != null ? (
                <span className="text-[10px] text-zinc-500">
                  (feels {payload.current.apparent_temp_f}°)
                </span>
              ) : null}
              {payload.current.wind_speed_mph != null ? (
                <span className="text-[10px] text-zinc-400">
                  💨 {payload.current.wind_speed_mph}mph
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
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
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[11px] uppercase tracking-wide text-zinc-400">
                  {formatDisplayDate(day.date)}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex rounded-full border border-[#0F4DB8]/30 bg-[#0F4DB8]/10 px-2 py-0.5 text-[10px] capitalize text-[#7EB3FF]">
                    {day.condition}
                  </span>
                  {day.precip_probability_max != null && day.precip_probability_max > 0 ? (
                    <span className="inline-flex items-center gap-0.5 text-[10px] font-mono text-[#7EB3FF]">
                      <span>💧</span>
                      <span>{day.precip_probability_max}%</span>
                    </span>
                  ) : null}
                  {day.wind_speed_max_mph != null ? (
                    <span className="text-[10px] font-mono text-zinc-500">
                      💨 {day.wind_speed_max_mph}mph
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="shrink-0 text-right font-mono text-xs">
                <p className="text-[#FBBF24]">▲ {Math.round(day.temp_max)}°</p>
                <p className="text-zinc-500">▼ {Math.round(day.temp_min)}°</p>
              </div>
            </li>
          ))
        )}
      </ul>
      <p className="mt-3 text-[10px] leading-relaxed text-zinc-500">
        Weather by{' '}
        <a
          href="https://open-meteo.com/"
          target="_blank"
          rel="noreferrer"
          className="text-[#7EB3FF] hover:underline"
        >
          Open-Meteo
        </a>
        {' · '}Location by{' '}
        <a
          href="https://www.geonames.org/"
          target="_blank"
          rel="noreferrer"
          className="text-[#7EB3FF] hover:underline"
        >
          GeoNames
        </a>
        {' · '}
        <a
          href="https://creativecommons.org/licenses/by/4.0/"
          target="_blank"
          rel="noreferrer"
          className="text-[#7EB3FF] hover:underline"
        >
          CC BY 4.0
        </a>
        {' · adapted by APEX'}
      </p>
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
                {formatEventStart(event.start, event.all_day)}
              </span>
            </li>
          ))
        )}
      </ul>
    </ToolCardFrame>
  )
}

function GmailLabels({ message }: { message: GmailMetadata }): ReactElement | null {
  if (message.labels.length === 0) {
    return null
  }
  return (
    <div className="flex flex-wrap gap-1 pt-0.5">
      {message.labels.slice(0, 4).map((label) => (
        <span
          key={`${message.id}-${label}`}
          className="rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-zinc-500"
        >
          {label}
        </span>
      ))}
    </div>
  )
}

function GmailSearchCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseGmailSearchPayload(output)

  if (!payload || 'error' in payload) {
    return (
      <ErrorFallbackCard
        toolName="search_gmail"
        durationMs={durationMs}
        message={payload?.error ?? 'Gmail search payload is unavailable.'}
      />
    )
  }

  const messages = payload.messages

  return (
    <ToolCardFrame
      title="Gmail Search"
      icon={<Search className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#7EB3FF]"
    >
      <div className="mb-2 flex min-w-0 items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
        <span className="truncate normal-case tracking-normal">
          {payload.query ?? 'Mailbox search'}
        </span>
        <span className="shrink-0">
          {payload.result_count ?? messages.length} result
          {(payload.result_count ?? messages.length) === 1 ? '' : 's'}
        </span>
      </div>
      <ul className={LIST_SCROLL}>
        {messages.length === 0 ? (
          <li className="text-sm text-zinc-500">No matching messages.</li>
        ) : (
          messages.map((message) => (
            <li
              key={message.id}
              className="space-y-1 rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-100">
                  {message.subject || '(No subject)'}
                </p>
                {message.date ? (
                  <span className="shrink-0 font-mono text-[10px] text-zinc-500">
                    {formatEmailDate(message.date)}
                  </span>
                ) : null}
              </div>
              <p className="truncate text-xs text-[#7EB3FF]">
                {message.sender || 'Unknown sender'}
              </p>
              {message.snippet ? (
                <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
                  {message.snippet}
                </p>
              ) : null}
              <GmailLabels message={message} />
            </li>
          ))
        )}
      </ul>
    </ToolCardFrame>
  )
}

function GmailMessageCard({
  durationMs,
  output,
}: {
  durationMs: number
  output: unknown
}): ReactElement {
  const payload = parseGmailMessagePayload(output)

  if (!payload || 'error' in payload) {
    return (
      <ErrorFallbackCard
        toolName="get_gmail_message"
        durationMs={durationMs}
        message={payload?.error ?? 'Gmail message payload is unavailable.'}
      />
    )
  }

  return (
    <ToolCardFrame
      title="Gmail Message"
      icon={<Mail className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#7EB3FF]"
    >
      <div className="space-y-1 border-b border-white/5 pb-2">
        <p className="text-sm font-medium text-zinc-100">
          {payload.subject || '(No subject)'}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <span className="min-w-0 truncate text-xs text-[#7EB3FF]">
            {payload.sender || 'Unknown sender'}
          </span>
          {payload.date ? (
            <span className="shrink-0 font-mono text-[10px] text-zinc-500">
              {formatEmailDate(payload.date)}
            </span>
          ) : null}
        </div>
        <GmailLabels message={payload} />
      </div>
      <div className="mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap break-words pr-1 text-sm leading-relaxed text-zinc-300 scrollbar-thin">
        {payload.body || payload.snippet || 'This message has no readable text body.'}
      </div>
      {payload.truncated ? (
        <p className="mt-2 font-mono text-[10px] uppercase tracking-wide text-[#FBBF24]">
          Message text truncated
        </p>
      ) : null}
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

function MicrosoftTodoListsCard({ durationMs, output }: { durationMs: number; output: unknown }): ReactElement {
  const payload = parseMicrosoftTodoLists(output)
  if (!payload) return <ErrorFallbackCard toolName="list_microsoft_todo_lists" durationMs={durationMs} message="Microsoft To Do list data is unavailable." />
  return (
    <ToolCardFrame
      title="Microsoft To Do Lists"
      icon={<ListTodo className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#7EB3FF]"
    >
      <TodoSourceLabel />
      <ul className={LIST_SCROLL}>
        {payload.lists.length === 0 ? <li className="text-sm text-zinc-500">No task lists found.</li> : payload.lists.map((list) => (
          <li key={list.id} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-zinc-200">{list.display_name}</span>
              <span className="text-[10px] text-zinc-500">{list.is_shared ? 'Shared' : list.is_owner ? 'Owned' : ''}</span>
            </div>
            <p className="mt-1 truncate font-mono text-[9px] text-zinc-600" title={list.id}>{list.id}</p>
          </li>
        ))}
      </ul>
    </ToolCardFrame>
  )
}

function MicrosoftTodoTasksCard({ durationMs, output }: { durationMs: number; output: unknown }): ReactElement {
  const payload = parseMicrosoftTodoTasks(output)
  if (!payload) return <ErrorFallbackCard toolName="list_microsoft_todo_tasks" durationMs={durationMs} message="Microsoft To Do task data is unavailable." />
  return (
    <ToolCardFrame
      title="Microsoft To Do Tasks"
      icon={<ListTodo className="size-3.5" aria-hidden />}
      durationMs={durationMs}
      accentClass="text-[#7EB3FF]"
    >
      <TodoSourceLabel />
      <ul className={LIST_SCROLL}>
        {payload.tasks.length === 0 ? <li className="text-sm text-zinc-500">No tasks found.</li> : payload.tasks.map((task) => {
          const due = formatTodoDue(task.due)
          return (
            <li key={task.id} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2">
              <div className="flex items-start justify-between gap-2">
                <span className={task.is_completed ? 'text-sm text-zinc-500 line-through' : 'text-sm text-zinc-200'}>{task.title}</span>
                {task.importance === 'high' ? <span className="font-mono text-[9px] uppercase text-amber-300">High</span> : null}
              </div>
              <div className="mt-1 flex gap-2 font-mono text-[9px] uppercase tracking-wide text-zinc-500">
                {due ? <span>Due {due}</span> : null}
                {payload.include_completed && task.is_completed ? <span>Completed</span> : null}
              </div>
            </li>
          )
        })}
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

function DocumentationSearchCard({ durationMs, output }: { durationMs: number; output: unknown }): ReactElement {
  const payload = parseDocumentationSearchPayload(output)
  if (!payload) return <ErrorFallbackCard toolName="search_apex_docs" durationMs={durationMs} message="Documentation search data is unavailable." />
  return (
    <ToolCardFrame title="APEX Documentation Search" icon={<BookOpen className="size-3.5" aria-hidden />} durationMs={durationMs} accentClass="text-[#7EB3FF]">
      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[#FBBF24]">Reference material · {payload.retrieval_mode}</p>
      {payload.results.length === 0 ? <p className="text-sm text-zinc-500">No matching documentation excerpts.</p> : <ul className={LIST_SCROLL}>
        {payload.results.map((result) => <li key={`${result.path}:${result.line_start}-${result.line_end}`} className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2">
          <p className="font-mono text-[10px] text-[#7EB3FF]">{result.path}:L{result.line_start}-L{result.line_end}</p>
          {result.heading ? <p className="mt-1 text-xs text-zinc-300">{result.heading}</p> : null}
          <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed text-zinc-400">{truncateText(result.text, 420)}</p>
        </li>)}
      </ul>}
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

function formatMcpResult(output: unknown): string {
  if (typeof output === 'string') {
    return truncateText(output, 2400)
  }
  try {
    return truncateText(JSON.stringify(output, null, 2), 2400)
  } catch {
    return 'Structured result could not be displayed.'
  }
}

function McpResultCard({
  item,
  provider,
  operation,
}: {
  item: ToolOutputItem
  provider: string
  operation: string
}): ReactElement {
  return (
    <ToolCardFrame
      title={operation}
      icon={<Network className="size-3.5" aria-hidden />}
      durationMs={item.duration_ms}
      accentClass="text-[#C084FC]"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-wider">
        <span className="rounded-full border border-[#7E22CE]/35 bg-[#7E22CE]/10 px-2 py-0.5 text-[#D8B4FE]">
          {provider}
        </span>
        <span className="inline-flex items-center gap-1 text-[#6EE7B7]">
          <span
            className="size-1.5 rounded-full bg-[#10B981]"
            aria-hidden
          />
          Success
        </span>
      </div>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/5 bg-black/20 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-zinc-300 scrollbar-thin">
        {formatMcpResult(item.output)}
      </pre>
    </ToolCardFrame>
  )
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

  const actionProposal = parseActionProposalToolOutput(item.output)
  if (actionProposal) {
    return <ActionProposalCard durationMs={item.duration_ms} output={actionProposal} />
  }

  const mcpTool = parseMcpToolName(item.name)
  if (mcpTool) {
    return (
      <McpResultCard
        item={item}
        provider={mcpTool.provider}
        operation={mcpTool.operation}
      />
    )
  }

  switch (item.name) {
    case 'get_weather_forecast':
      return (
        <WeatherForecastCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'search_apex_docs':
      return <DocumentationSearchCard durationMs={item.duration_ms} output={item.output} />
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
    case 'search_gmail':
      return (
        <GmailSearchCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'get_gmail_message':
      return (
        <GmailMessageCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'list_microsoft_todo_lists':
      return (
        <MicrosoftTodoListsCard durationMs={item.duration_ms} output={item.output} />
      )
    case 'list_microsoft_todo_tasks':
      return (
        <MicrosoftTodoTasksCard durationMs={item.duration_ms} output={item.output} />
      )
    default:
      return (
        <ToolCardFrame
          title={formatToolLabel(item.name)}
          icon={<AlertCircle className="size-3.5" aria-hidden />}
          durationMs={item.duration_ms}
          accentClass="text-zinc-400"
        >
          <p className="text-sm text-zinc-400">
            Structured card unavailable for this tool output.
          </p>
        </ToolCardFrame>
      )
  }
}

export function CortexToolCards({
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
