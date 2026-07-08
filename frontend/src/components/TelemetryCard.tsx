import {
  Cloud,
  CloudLightning,
  CloudRain,
  Moon,
  Sun,
  type LucideIcon,
} from 'lucide-react'
import type * as React from 'react'

import type { WeatherConditionArchetype } from '../types/telemetry'
import {
  useId,
  useMemo,
  type ComponentPropsWithoutRef,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from 'react'

/** Variable Typography Engine — closed interval for ambient temperature (°F). */
export const VTE_TEMP_MIN_F = 40
export const VTE_TEMP_MAX_F = 90

/** Variable Typography Engine — closed interval for primary readout font weight. */
export const VTE_WEIGHT_MIN = 300
export const VTE_WEIGHT_MAX = 800

export type VariableTypographyInput = {
  temperatureFahrenheit: number
}

const F1_DATA_PREFIX = 'F1_DATA:'
const CHECKERED_FALLBACK_FLAG = '🏁'

type F1SchedulePayload = {
  raceName?: unknown
  round?: unknown
  country?: unknown
  raceDateTimeEST?: unknown
  relativeWeek?: unknown
  sprintScheduled?: unknown
  sprintDateTimeEST?: unknown
}

const COUNTRY_FLAG_MAP: Record<string, string> = {
  australia: 'au',
  austria: 'at',
  azerbaijan: 'az',
  bahrain: 'bh',
  belgium: 'be',
  brazil: 'br',
  canada: 'ca',
  china: 'cn',
  hungary: 'hu',
  italy: 'it',
  japan: 'jp',
  mexico: 'mx',
  monaco: 'mc',
  netherlands: 'nl',
  qatar: 'qa',
  'saudi arabia': 'sa',
  singapore: 'sg',
  spain: 'es',
  'united arab emirates': 'ae',
  uae: 'ae',
  'united kingdom': 'gb',
  uk: 'gb',
  'united states': 'us',
  usa: 'us',
}

function extractBalancedJsonObject(source: string, startIndex: number): string | null {
  if (source[startIndex] !== '{') return null

  let depth = 0
  let inString = false
  let isEscaped = false

  for (let index = startIndex; index < source.length; index += 1) {
    const character = source[index]

    if (inString) {
      if (isEscaped) {
        isEscaped = false
        continue
      }
      if (character === '\\') {
        isEscaped = true
        continue
      }
      if (character === '"') {
        inString = false
      }
      continue
    }

    if (character === '"') {
      inString = true
      continue
    }

    if (character === '{') {
      depth += 1
      continue
    }

    if (character === '}') {
      depth -= 1
      if (depth === 0) {
        return source.slice(startIndex, index + 1)
      }
    }
  }

  return null
}

function extractF1DataJson(source: string): string | null {
  const prefixIndex = source.indexOf(F1_DATA_PREFIX)
  if (prefixIndex < 0) return null

  let jsonStartIndex = prefixIndex + F1_DATA_PREFIX.length
  while (jsonStartIndex < source.length && /\s/.test(source[jsonStartIndex])) {
    jsonStartIndex += 1
  }

  return extractBalancedJsonObject(source, jsonStartIndex)
}

function parseF1SchedulePayload(source: string): F1SchedulePayload | null {
  const jsonBlock = extractF1DataJson(source)
  if (!jsonBlock) return null

  try {
    const parsed = JSON.parse(jsonBlock) as unknown
    if (parsed && typeof parsed === 'object') {
      return parsed as F1SchedulePayload
    }
  } catch {
    return null
  }

  return null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false
}

function resolveCountryFlag(country: string): string {
  const normalizedCountry = country.toLowerCase()
  return COUNTRY_FLAG_MAP[normalizedCountry] ?? CHECKERED_FALLBACK_FLAG
}

/**
 * Variable Typography Engine interpolation entry point.
 * Maps temperatureFahrenheit on [VTE_TEMP_MIN_F, VTE_TEMP_MAX_F] to font weight
 * on [VTE_WEIGHT_MIN, VTE_WEIGHT_MAX] for the primary temperature readout.
 */
export function resolveTemperatureFontWeight(
  input: VariableTypographyInput,
): number {
  const temp = input.temperatureFahrenheit

  // 1. Enforce strict boundary clamping
  const clampedTemp = Math.max(VTE_TEMP_MIN_F, Math.min(VTE_TEMP_MAX_F, temp))

  // 2. Compute proportional scalar weight via linear interpolation
  const tempRange = VTE_TEMP_MAX_F - VTE_TEMP_MIN_F
  const weightRange = VTE_WEIGHT_MAX - VTE_WEIGHT_MIN

  const interpolatedWeight = VTE_WEIGHT_MIN + ((clampedTemp - VTE_TEMP_MIN_F) / tempRange) * weightRange

  // 3. Round to avoid partial fractional pixel weights
  return Math.round(interpolatedWeight)
}

const WEATHER_GLOW_BY_CONDITION: Record<
  WeatherConditionArchetype,
  { bgClass: string; opacityClass: string; animateClass: string }
> = {
  clear_day: {
    bgClass: 'bg-[#F4B22A]',
    opacityClass: 'opacity-25',
    animateClass: 'animate-weather-solar',
  },
  clear_night: {
    bgClass: 'bg-[#4F8FFF]',
    opacityClass: 'opacity-24',
    animateClass: 'animate-weather-night',
  },
  clouds: {
    bgClass: 'bg-[#8EA7C7]',
    opacityClass: 'opacity-16',
    animateClass: 'animate-weather-hover',
  },
  rain: {
    bgClass: 'bg-[#37A6FF]',
    opacityClass: 'opacity-30',
    animateClass: 'animate-weather-breath',
  },
  thunderstorm: {
    bgClass: 'bg-[#4F8FFF]',
    opacityClass: 'opacity-20',
    animateClass: 'animate-weather-surge',
  },
}

const WEATHER_ICON_BY_CONDITION: Record<WeatherConditionArchetype, LucideIcon> = {
  clear_day: Sun,
  clear_night: Moon,
  clouds: Cloud,
  rain: CloudRain,
  thunderstorm: CloudLightning,
}

const weatherIconStyles: Record<WeatherConditionArchetype, React.CSSProperties> = {
  clear_day: {
    color: '#FFD166',
    filter: 'drop-shadow(0 0 10px rgba(255, 209, 102, 0.75))',
  },
  clear_night: {
    color: '#A8C8FF',
    filter: 'drop-shadow(0 0 10px rgba(168, 200, 255, 0.75))',
  },
  clouds: {
    color: '#D0D8E8',
    filter: 'drop-shadow(0 0 8px rgba(208, 216, 232, 0.55))',
  },
  rain: {
    color: '#7DD3FC',
    filter: 'drop-shadow(0 0 10px rgba(125, 211, 252, 0.75))',
  },
  thunderstorm: {
    color: '#FFE082',
    filter: 'drop-shadow(0 0 12px rgba(255, 224, 130, 0.85))',
  },
}

function resolveCardHoverClass(title: string): string {
  const normalized = title.trim()
  if (normalized === 'Weather') return 'hover-weather-bright'
  if (normalized === 'Events') return 'hover-blue-medium'
  if (normalized === 'Reminders') return 'hover-blue-strong'
  return 'hover-blue-subtle'
}

export type TelemetryLedState = 'live' | 'stale' | 'loading' | 'error' | 'none'

const LED_STATE_CLASS: Record<TelemetryLedState, string> = {
  live: 'hud-led hud-led--live size-1.5',
  stale: 'hud-led hud-led--stale size-1.5',
  loading: 'hud-led hud-led--loading size-1.5',
  error: 'hud-led hud-led--error size-1.5',
  none: '',
}

const LED_STATE_LABEL: Record<TelemetryLedState, string> = {
  live: 'Live data',
  stale: 'Stale data',
  loading: 'Loading data',
  error: 'Data error',
  none: '',
}

export type TelemetryCardProps = {
  title: string
  icon: LucideIcon
  children?: ReactNode
  /** When set, renders the primary temperature numerical readout with VTE inline weight. */
  primaryTemperatureF?: number | null
  /** Optional F1 telemetry text source used for F1_DATA parsing. */
  f1TelemetryText?: string
  /** Micro-climate archetype for scoped atmospheric background glow. */
  weatherCondition?: WeatherConditionArchetype | null
  /** Module status LED communicating this card's data freshness, mirroring the unified pipeline state. */
  ledState?: TelemetryLedState
  /** When true, renders a single condensed summary row instead of the full card body (e.g. while the console tray is open). */
  isCompact?: boolean
  /** Right-aligned summary content shown only in the compact row. */
  compactValue?: ReactNode
} & Omit<ComponentPropsWithoutRef<'section'>, 'title' | 'children'>

export function TelemetryCard({
  title,
  icon: Icon,
  children,
  primaryTemperatureF,
  f1TelemetryText,
  weatherCondition,
  ledState = 'none',
  isCompact = false,
  compactValue,
  className,
  ...sectionProps
}: TelemetryCardProps): ReactElement {
  const showHeader = title.trim().length > 0

  const headingId = useId()
  const weatherGlow =
    weatherCondition != null ? WEATHER_GLOW_BY_CONDITION[weatherCondition] : null
  const WeatherConditionIcon =
    weatherCondition != null
      ? WEATHER_ICON_BY_CONDITION[weatherCondition]
      : null
  const isWeatherCard = title.trim() === 'Weather'

  const sectionClassName = [
    'hud-corner-brackets hud-interactive-shell relative flex overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] hud-glass transition-all duration-700 ease-in-out',
    isCompact
      ? 'h-auto min-h-[3.75rem] shrink-0 flex-none flex-row items-center px-4 py-3'
      : 'h-full min-h-0 flex-col p-[var(--hud-panel-pad)]',
    resolveCardHoverClass(title),
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const primaryTemperatureStyle: CSSProperties | undefined =
    primaryTemperatureF != null
      ? {
          fontWeight: resolveTemperatureFontWeight({
            temperatureFahrenheit: primaryTemperatureF,
          }),
        }
      : undefined

  const f1Schedule = useMemo(() => {
    const source = f1TelemetryText?.trim() ?? ''
    if (!source) return null

    const payload = parseF1SchedulePayload(source)
    if (!payload) return null

    const raceName = asString(payload.raceName) || 'Upcoming Grand Prix'
    const round = asString(payload.round) || 'TBD'
    const country = asString(payload.country)
    const raceDateTimeEST = asString(payload.raceDateTimeEST)
    const relativeWeek = asString(payload.relativeWeek)
    const sprintScheduled = asBoolean(payload.sprintScheduled)

    return {
      raceName,
      round,
      country,
      raceEtLabel: `${relativeWeek} — ${raceDateTimeEST}`,
      sprintScheduled,
      countryFlag: resolveCountryFlag(country),
    }
  }, [f1TelemetryText])

  return (
    <section
      {...sectionProps}
      className={sectionClassName}
      aria-labelledby={showHeader ? headingId : undefined}
    >
      <span className="hud-corner-bl" aria-hidden />
      <span className="hud-corner-br" aria-hidden />
      {weatherGlow && !isCompact ? (
        <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden rounded-2xl">
          <div
            className={[
              'weather-glow-core absolute inset-0 blur-[64px] transition-opacity duration-500',
              weatherGlow.bgClass,
              weatherGlow.opacityClass,
              weatherGlow.animateClass,
            ].join(' ')}
            aria-hidden
          />
        </div>
      ) : null}
      {isCompact ? (
        <div className="hud-inner-lift relative z-10 flex min-w-0 flex-1 items-center gap-3">
          <span className="hud-icon-badge size-7 shrink-0">
            <Icon
              className="size-4 text-[color:var(--hud-accent)]"
              strokeWidth={1.75}
              aria-hidden
            />
          </span>
          <span
            id={headingId}
            className={[
              'min-w-0 truncate font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--hud-text)]',
              isWeatherCard ? 'flex-[0_1_auto]' : 'flex-1',
            ].join(' ')}
          >
            {title}
          </span>
          {compactValue != null ? (
            <span
              className={[
                'min-w-0 shrink truncate text-right font-mono text-xs uppercase tracking-wide text-zinc-300',
                isWeatherCard ? 'max-w-[72%]' : 'max-w-[56%]',
              ].join(' ')}
            >
              {compactValue}
            </span>
          ) : null}
          {ledState !== 'none' ? (
            <span
              className={LED_STATE_CLASS[ledState]}
              role="status"
              aria-label={LED_STATE_LABEL[ledState]}
              title={LED_STATE_LABEL[ledState]}
            />
          ) : null}
        </div>
      ) : (
      <div className="hud-inner-lift relative z-10 flex h-full min-h-0 flex-col">
      {showHeader ? (
        <header className="mb-3 shrink-0">
          <div className="flex min-h-9 items-center gap-2.5">
            <span className="hud-icon-badge size-7 shrink-0">
              <Icon
                className="size-4 text-[color:var(--hud-accent)]"
                strokeWidth={1.75}
                aria-hidden
              />
            </span>
            <h2
              id={headingId}
              className="min-w-0 flex-1 truncate font-orbitron text-sm font-semibold leading-none tracking-[0.12em] text-[color:var(--hud-text)]"
            >
              {title}
            </h2>
            {ledState !== 'none' ? (
              <span
                className={LED_STATE_CLASS[ledState]}
                role="status"
                aria-label={LED_STATE_LABEL[ledState]}
                title={LED_STATE_LABEL[ledState]}
              />
            ) : null}
          </div>
          <div className="hud-header-divider mt-3" aria-hidden />
        </header>
      ) : null}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {primaryTemperatureF != null ? (
          <div className="mb-3 flex shrink-0 items-center gap-4">
            <p
              className="tabular-nums text-4xl leading-none tracking-tight text-white"
              style={primaryTemperatureStyle}
              data-vte="primary-temperature-readout"
              aria-label="Current temperature"
            >
              {primaryTemperatureF}°
            </p>
            {weatherCondition != null && WeatherConditionIcon != null ? (
              <WeatherConditionIcon
                className="size-8 shrink-0 transition-all duration-1000 ease-in-out"
                style={weatherIconStyles[weatherCondition]}
                strokeWidth={1.75}
                aria-hidden="true"
              />
            ) : null}
            {isWeatherCard && compactValue != null ? (
              <p className="min-w-0 flex-1 line-clamp-2 break-words text-sm leading-snug text-zinc-200">
                {compactValue}
              </p>
            ) : null}
          </div>
        ) : null}
        {f1Schedule ? (
          <div className="mb-3 shrink-0 rounded-xl border border-white/5 bg-black/30 p-2.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span
                  aria-label={`Race country flag ${f1Schedule.country || 'unknown'}`}
                  className="shrink-0 text-sm leading-none"
                >
                  {f1Schedule.countryFlag === CHECKERED_FALLBACK_FLAG ? (
                    f1Schedule.countryFlag
                  ) : (
                    <img
                      src={`https://cdnjs.cloudflare.com/ajax/libs/flag-icon-css/3.4.6/flags/4x3/${f1Schedule.countryFlag}.svg`}
                      alt={`${f1Schedule.country || 'Unknown'} flag`}
                      className="h-3 w-4 rounded object-cover shadow-sm"
                      loading="lazy"
                      decoding="async"
                      onError={(event) => {
                        const flagContainer = event.currentTarget.parentElement
                        if (!flagContainer) return
                        flagContainer.textContent = CHECKERED_FALLBACK_FLAG
                      }}
                    />
                  )}
                </span>
                <span className="truncate text-xs font-semibold text-zinc-200">
                  {f1Schedule.raceName}
                </span>
              </div>
              <span className="shrink-0 font-mono text-[10px] text-zinc-500">
                R{f1Schedule.round}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="truncate text-[11px] font-medium text-[#7EB3FF]">
                {f1Schedule.raceEtLabel}
              </span>
              {f1Schedule.sprintScheduled ? (
                <span className="shrink-0 rounded-full border border-[#7EB3FF]/30 bg-[#7EB3FF]/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[#7EB3FF]">
                  Sprint
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden pr-1 scrollbar-thin flex flex-col">
          {children}
        </div>
      </div>
      </div>
      )}
    </section>
  )
}
